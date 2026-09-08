import hashlib
import json
from pathlib import Path

from langgraph.checkpoint.base import empty_checkpoint
from sqlalchemy.orm import Session, object_session

from app.config import Settings
from app.db.checkpoints import postgres_checkpointer
from app.db.models import Course, Job, ReviewEvent, Run
from app.services.artifacts import ArtifactService, ArtifactWrite
from app.services.context_packs import ContextPackInput, ContextPackService
from app.services.courses import CourseService
from app.services.models import ModelGateway, TokenBudgetPause
from app.services.quality import (
    Finding,
    deterministic_gate,
    language_gate,
    route_quality,
    semantic_gate,
)
from app.services.releases import ReleaseService
from app.services.source_snapshots import SourceSnapshotService


class WorkflowRunner:
    """Execute one durable stage command; no workflow cursor is stored in jobs."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def execute(self, job: Job) -> str:
        session = object_session(job)
        if session is None:
            raise RuntimeError("workflow job must be attached to a database session")
        run = session.get(Run, job.run_id)
        course = session.get(Course, run.course_id) if run else None
        if run is None or course is None:
            raise LookupError("run or course not found")
        checkpoint_state = self._restore_checkpoint(run)
        if checkpoint_state:
            run.current_stage = checkpoint_state["stage"]
        if job.job_type == "publish":
            event = session.get(ReviewEvent, job.input_event_id) if job.input_event_id else None
            release = self._release_path(course)
            if event is None or event.target != release.name:
                raise ValueError(
                    "publication review event does not match the current release candidate"
                )
            ReleaseService(self.settings.releases_root).promote(release)
            run.node_summary = "release promoted by an append-only review event"
            return "completed"
        if (
            job.job_type == "resume"
            and job.input_event_id
            and checkpoint_state.get("review_event_id") != str(job.input_event_id)
        ):
            self._apply_review_decision(session, run, job)
        if run.pause_requested:
            return "paused"
        if run.stop_requested:
            return "stopped"
        outcome = self._execute_stage(session, course, run)
        self._save_checkpoint(run, str(job.input_event_id) if job.input_event_id else None)
        return outcome

    def _restore_checkpoint(self, run: Run) -> dict:
        config = {"configurable": {"thread_id": run.thread_id, "checkpoint_ns": "course_generator"}}
        with postgres_checkpointer(self.settings) as checkpointer:
            checkpoint = checkpointer.get_tuple(config)
        if checkpoint is None:
            return {}
        state = checkpoint.checkpoint["channel_values"].get("workflow_state", {})
        return state if isinstance(state, dict) else {}

    def _save_checkpoint(self, run: Run, review_event_id: str | None) -> None:
        state = {
            "course_id": str(run.course_id),
            "run_id": str(run.id),
            "stage": run.current_stage,
            "review_event_id": review_event_id,
            "node_summary": run.node_summary,
        }
        checkpoint = empty_checkpoint()
        checkpoint["channel_values"] = {"workflow_state": state}
        checkpoint["channel_versions"] = {"workflow_state": 1}
        config = {"configurable": {"thread_id": run.thread_id, "checkpoint_ns": "course_generator"}}
        with postgres_checkpointer(self.settings) as checkpointer:
            checkpointer.put(
                config,
                checkpoint,
                {"source": "loop", "step": run.current_stage, "writes": {"workflow_state": state}},
                {"workflow_state": 1},
            )

    def _apply_review_decision(self, session: Session, run: Run, job: Job) -> None:
        event = session.get(ReviewEvent, job.input_event_id) if job.input_event_id else None
        if event is None:
            raise ValueError("resume job requires its immutable review event")
        if event.action == "approve":
            run.current_stage = min(run.current_stage + 1, 7)
        elif event.action == "rework":
            run.node_summary = f"rework requested: {event.comment or 'no comment'}"
        else:
            raise ValueError("only approve or rework can resume a run")

    def _execute_stage(self, session: Session, course: Course, run: Run) -> str:
        stage = run.current_stage
        if stage == 1:
            self._write_json_artifact(
                session,
                course,
                run,
                "requirements",
                "workspace/INPUT.json",
                self._definition(course),
            )
            run.node_summary = "requirements snapshot ready for approval"
        elif stage == 2:
            self._write_task_definition(session, course, run)
            run.node_summary = "MISSION.md and SPEC.md ready for approval"
        elif stage == 3:
            self._write_blueprint(session, course, run)
            run.node_summary = "sources and blueprint ready for approval"
        elif stage == 4:
            self._write_batches(session, course, run)
            run.node_summary = "batch plan ready for approval; no Context Pack was generated"
        elif stage == 5:
            if not self.settings.openai_api_key:
                run.error_code = "model_not_configured"
                run.error_summary = "OPENAI_API_KEY is required before chapter production"
                return "paused"
            try:
                if not self._produce_chapters(session, course, run):
                    return "waiting_human"
            except TokenBudgetPause:
                return "paused"
            run.node_summary = "batch production completed; quality evidence awaits approval"
        elif stage == 6:
            blockers = self._write_course_quality(session, course, run)
            run.node_summary = (
                "course-wide deterministic quality blockers need review"
                if blockers
                else "course-wide quality review ready for approval"
            )
        elif stage == 7:
            ReleaseService(self.settings.releases_root).build_rc(course)
            run.node_summary = "immutable release candidate ready for final approval"
        else:
            raise ValueError(f"unknown stage {stage}")
        return "waiting_human"

    def _definition(self, course: Course) -> dict:
        return CourseService(self._session_for(course), self.settings.courses_root).read_definition(
            course
        )

    @staticmethod
    def _session_for(course: Course) -> Session:
        session = object_session(course)
        if session is None:
            raise RuntimeError("course must be attached to a database session")
        return session

    def _write_task_definition(self, session: Session, course: Course, run: Run) -> None:
        definition = self._definition(course)
        title = definition.get("title", course.slug)
        audience = definition.get("audience", "self-directed learners")
        goals = definition.get("learning_goals", [])
        mission = f"# {title}\n\nAudience: {audience}\n\nGoals:\n" + "\n".join(
            f"- {goal}" for goal in goals
        )
        spec = "# Acceptance criteria\n\n" + "\n".join(f"- {goal}" for goal in goals)
        self._write_artifact(
            session, course, run, "task_definition", "workspace/MISSION.md", mission.encode()
        )
        self._write_artifact(
            session, course, run, "task_definition", "workspace/SPEC.md", spec.encode()
        )

    def _write_blueprint(self, session: Session, course: Course, run: Run) -> None:
        definition = self._definition(course)
        count = int(definition.get("expected_chapter_count", 1))
        chapters = [
            {"id": f"chapter-{number}", "number": number, "title": f"Chapter {number}"}
            for number in range(1, count + 1)
        ]
        snapshots = SourceSnapshotService(session).capture(
            course,
            run.id,
            definition.get("resources", []),
            definition.get("source_policy", "user_and_official"),
        )
        resource_markdown = "# Resources\n\n" + "\n".join(
            f"- {snapshot['origin']} ({snapshot['sha256']})" for snapshot in snapshots
        )
        blueprint_markdown = "# Course Blueprint\n\n" + "\n".join(
            f"## {chapter['title']}\n\n- Chapter ID: {chapter['id']}" for chapter in chapters
        )
        self._write_artifact(
            session, course, run, "sources", "workspace/RESOURCES.md", resource_markdown.encode()
        )
        self._write_artifact(
            session, course, run, "blueprint", "workspace/BLUEPRINT.md", blueprint_markdown.encode()
        )

    def _write_batches(self, session: Session, course: Course, run: Run) -> None:
        definition = self._definition(course)
        chapters = [
            {"id": f"chapter-{number}", "number": number, "title": f"Chapter {number}"}
            for number in range(1, int(definition.get("expected_chapter_count", 1)) + 1)
        ]
        batch = {
            "batch_id": "batch-01",
            "chapters": chapters,
            "context_pack_scope": [
                {
                    "chapter_id": chapter["id"],
                    "blueprint_ref": f"workspace/BLUEPRINT.md#{chapter['id']}",
                    "source_refs": [],
                }
                for chapter in chapters
            ],
            "token_budget": definition.get("token_limit"),
            "execution": "sequential",
        }
        self._write_json_artifact(
            session, course, run, "batch_plan", "workspace/batches/batch-01.json", batch
        )

    def _produce_chapters(self, session: Session, course: Course, run: Run) -> bool:
        batch = self._workspace_json(course, "workspace/batches/batch-01.json")
        gateway = ModelGateway(self.settings)
        for chapter in batch["chapters"]:
            pack = ContextPackInput(
                batch_id=batch["batch_id"],
                chapter_number=chapter["number"],
                chapter_id=chapter["id"],
                chapter_goal=chapter["title"],
                blueprint=chapter,
                source_fragments=[],
                prior_summary=None,
                terms=[],
                writing_constraints=["include a clear explanation, example, and exercise"],
            )
            context = ContextPackService(ArtifactService(session)).build(course, run.id, pack)
            path = f"lessons/{chapter['number']:02d}-{course.slug}.md"
            if not self._chapter_quality_cycle(
                session, course, run, gateway, chapter, context.id, path
            ):
                return False
        return True

    def _chapter_quality_cycle(
        self, session, course, run, gateway, chapter, context_id, path
    ) -> bool:
        minimum = int(self._definition(course).get("min_effective_chars_per_chapter", 1))
        prior_fingerprints: list[str] = []
        evidence: list[str] = []
        for round_no in range(1, 4):
            draft = gateway.complete(
                run,
                node="chapter_write",
                operation="draft_chapter",
                prompt=" ".join(
                    [
                        f"Write a Markdown lesson titled {chapter['title']}.",
                        f"Use Context Pack {context_id}.",
                        "Include a clear explanation, example, and exercise.",
                        "Repair evidence: " + "; ".join(evidence),
                    ]
                ),
                prompt_name="chapter_writer",
                prompt_hash=hashlib.sha256(b"chapter_writer_v1").hexdigest(),
            )
            artifact = self._write_artifact(
                session, course, run, "chapter_write", path, draft.content.encode(), round_no
            )
            precheck = deterministic_gate(draft.content, artifact.revision, minimum)
            if not precheck.passed:
                self._write_quality_evidence(session, course, run, chapter, round_no, [precheck])
                evidence = [finding.message for finding in precheck.findings]
                prior_fingerprints.extend(finding.fingerprint for finding in precheck.findings)
                continue
            humanized = self._humanize(gateway, run, draft.content)
            human_artifact = self._write_artifact(
                session, course, run, "humanizer", path, humanized["markdown"].encode(), round_no
            )
            regression = deterministic_gate(humanized["markdown"], human_artifact.revision, minimum)
            language = language_gate(
                humanized["markdown"],
                human_artifact.revision,
                humanized["scores"],
                humanized["findings"],
            )
            semantic = self._semantic_review(
                gateway, run, humanized["markdown"], human_artifact.revision
            )
            results = [regression, language, semantic]
            self._write_quality_evidence(session, course, run, chapter, round_no, results)
            route = route_quality(results, round_no, prior_fingerprints)
            if route == "pass":
                return True
            evidence = [finding.message for result in results for finding in result.findings]
            prior_fingerprints.extend(
                finding.fingerprint for result in results for finding in result.findings
            )
            if route == "waiting_human":
                run.node_summary = (
                    f"chapter {chapter['id']} needs human review after quality failures"
                )
                return False
        return False

    def _humanize(self, gateway, run, markdown: str) -> dict:
        result = gateway.complete(
            run,
            node="humanizer",
            operation="humanize_chapter",
            prompt=(
                "Return JSON only with markdown, scores (naturalness, clarity, conciseness, "
                "teaching), and findings. Improve this Markdown:\n" + markdown
            ),
            prompt_name="natural_language_editor",
            prompt_hash=hashlib.sha256(b"natural_language_editor_v1").hexdigest(),
        )
        payload = self._model_json(result.content)
        return {
            "markdown": str(payload["markdown"]),
            "scores": {
                name: int(payload["scores"][name])
                for name in ("naturalness", "clarity", "conciseness", "teaching")
            },
            "findings": self._findings(payload.get("findings", [])),
        }

    def _semantic_review(self, gateway, run, markdown: str, revision: int):
        result = gateway.complete(
            run,
            node="semantic_review",
            operation="review_chapter_semantics",
            prompt=(
                "Return JSON only with outcomes for facts_sources, goals_scope, teaching, and "
                "logic_continuity (pass/warning/blocker), plus findings. Review this Markdown:\n"
                + markdown
            ),
            prompt_name="semantic_reviewer",
            prompt_hash=hashlib.sha256(b"semantic_reviewer_v1").hexdigest(),
        )
        payload = self._model_json(result.content)
        outcomes = {
            name: payload["outcomes"][name]
            for name in ("facts_sources", "goals_scope", "teaching", "logic_continuity")
        }
        return semantic_gate(
            markdown, revision, outcomes, self._findings(payload.get("findings", []))
        )

    @staticmethod
    def _model_json(content: str) -> dict:
        raw = content.strip().removeprefix("```json").removesuffix("```").strip()
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("model returned a non-object structured response")
        return payload

    @staticmethod
    def _findings(values: list[dict]) -> list[Finding]:
        return [
            Finding(
                str(value.get("rule", "model_finding")),
                str(value.get("location", "unknown")),
                str(value.get("message", "")),
                str(value.get("excerpt", "")),
                str(value.get("fix", "")),
            )
            for value in values
        ]

    def _write_quality_evidence(self, session, course, run, chapter, round_no, results) -> None:
        self._write_json_artifact(
            session,
            course,
            run,
            "quality_evidence",
            f"workspace/quality/{chapter['id']}-round-{round_no}.json",
            {
                "chapter_id": chapter["id"],
                "round": round_no,
                "gates": [result.as_dict() for result in results],
            },
        )

    def _write_course_quality(self, session: Session, course: Course, run: Run) -> bool:
        batch = self._workspace_json(course, "workspace/batches/batch-01.json")
        minimum = int(self._definition(course).get("min_effective_chars_per_chapter", 1))
        chapter_results: list[dict] = []
        has_blockers = False
        for chapter in batch["chapters"]:
            path = Path(course.workspace_path) / f"lessons/{chapter['number']:02d}-{course.slug}.md"
            if not path.is_file():
                has_blockers = True
                chapter_results.append(
                    {"chapter_id": chapter["id"], "missing_lesson": True, "gates": []}
                )
                continue
            gate = deterministic_gate(path.read_text(encoding="utf-8"), 1, minimum)
            has_blockers = has_blockers or not gate.passed
            chapter_results.append(
                {"chapter_id": chapter["id"], "missing_lesson": False, "gates": [gate.as_dict()]}
            )
        self._write_json_artifact(
            session,
            course,
            run,
            "course_quality",
            "quality.json",
            {"stage": 6, "has_blockers": has_blockers, "chapters": chapter_results},
        )
        return has_blockers

    def _write_json_artifact(
        self, session: Session, course: Course, run: Run, node: str, path: str, value: dict
    ) -> None:
        self._write_artifact(
            session,
            course,
            run,
            node,
            path,
            json.dumps(value, ensure_ascii=False, indent=2).encode(),
        )

    def _write_artifact(
        self,
        session: Session,
        course: Course,
        run: Run,
        node: str,
        path: str,
        content: bytes,
        round_no: int = 1,
    ):
        return ArtifactService(session).write(
            course,
            ArtifactWrite(
                course_id=course.id,
                run_id=run.id,
                node_name=node,
                scope=f"stage-{run.current_stage}:{path}",
                round_no=round_no,
                input_hash=hashlib.sha256(content).hexdigest(),
                logical_path=path,
                content=content,
            ),
        )

    def _workspace_json(self, course: Course, path: str) -> dict:
        return json.loads((Path(course.workspace_path) / path).read_text(encoding="utf-8"))

    def _release_path(self, course: Course) -> Path:
        releases = sorted((self.settings.releases_root / course.slug).glob("r[0-9][0-9][0-9][0-9]"))
        if not releases:
            raise ValueError("there is no release candidate to publish")
        return releases[-1]
