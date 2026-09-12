import hashlib
import json
from dataclasses import replace
from pathlib import Path

from sqlalchemy.orm import Session, object_session

from app.config import Settings
from app.db.checkpoints import postgres_checkpointer
from app.db.models import Course, Job, ReviewEvent, Run
from app.prompts import RenderedPrompt, render_prompt
from app.services.artifacts import ArtifactService, ArtifactWrite
from app.services.context_packs import ContextPackInput, ContextPackService
from app.services.courses import CourseService
from app.services.discovery import TavilyDiscovery
from app.services.models import ModelGateway, TokenBudgetPause
from app.services.quality import (
    Finding,
    deterministic_gate,
    language_gate,
    route_quality,
    semantic_gate,
)
from app.services.releases import ReleaseService
from app.services.source_index import SourceIndexService
from app.services.source_snapshots import SourceSnapshotService
from app.workflows.graph import build_stage_graph


class ModelOutputInvalid(ValueError):
    """A model response remained invalid after one schema repair attempt."""


class WorkflowRunner:
    """Execute one durable stage command; no workflow cursor is stored in jobs."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def execute(self, job: Job) -> str:
        session = object_session(job)
        if session is None:
            raise RuntimeError("工作流任务必须关联数据库会话")
        run = session.get(Run, job.run_id)
        course = session.get(Course, run.course_id) if run else None
        if run is None or course is None:
            raise LookupError("运行或课程不存在")
        config = {"configurable": {"thread_id": run.thread_id, "checkpoint_ns": ""}}
        with postgres_checkpointer(self.settings) as checkpointer:
            graph = build_stage_graph(self._stage_nodes(session, course, run, job), checkpointer)
            checkpoint_state = dict(graph.get_state(config).values)
        if checkpoint_state:
            run.current_stage = checkpoint_state.get("stage", run.current_stage)
        if job.job_type == "publish":
            event = session.get(ReviewEvent, job.input_event_id) if job.input_event_id else None
            release = self._release_path(course)
            if event is None or event.target != release.name:
                raise ValueError("发布审核事件与当前发布候选不匹配")
            ReleaseService(self.settings.releases_root).promote(release)
            run.node_summary = "release promoted by an append-only review event"
            return "completed"
        if (
            job.job_type == "resume"
            and job.input_event_id
            and checkpoint_state.get("pending_review_event_id") != str(job.input_event_id)
        ):
            self._apply_review_decision(session, run, job)
        if run.pause_requested:
            return "paused"
        if run.stop_requested:
            return "stopped"
        outcome: list[str] = []

        def execute_stage(state: dict) -> dict:
            outcome.append(self._execute_stage(session, course, run))
            return {
                **state,
                "course_id": str(course.id),
                "run_id": str(run.id),
                "stage": run.current_stage,
                "pending_review_event_id": str(job.input_event_id) if job.input_event_id else None,
                "last_error_code": run.error_code,
            }

        with postgres_checkpointer(self.settings) as checkpointer:
            graph = build_stage_graph({stage: execute_stage for stage in range(1, 8)}, checkpointer)
            graph.invoke(
                {
                    "course_id": str(course.id),
                    "run_id": str(run.id),
                    "stage": run.current_stage,
                    "batch_id": checkpoint_state.get("batch_id"),
                    "chapter_id": checkpoint_state.get("chapter_id"),
                    "round_no": checkpoint_state.get("round_no", 0),
                    "artifact_refs": checkpoint_state.get("artifact_refs", {}),
                    "gate_result_refs": checkpoint_state.get("gate_result_refs", []),
                    "pending_review_event_id": str(job.input_event_id)
                    if job.input_event_id
                    else None,
                    "last_error_code": run.error_code,
                },
                config,
            )
        return outcome[0]

    @staticmethod
    def _stage_nodes(session: Session, course: Course, run: Run, job: Job) -> dict[int, callable]:
        # Nodes are replaced by the per-command closure immediately before invoke;
        # this first compilation is only used to restore durable graph state.
        return {stage: lambda state: state for stage in range(1, 8)}

    def _apply_review_decision(self, session: Session, run: Run, job: Job) -> None:
        event = session.get(ReviewEvent, job.input_event_id) if job.input_event_id else None
        if event is None:
            raise ValueError("恢复任务必须关联不可变审核事件")
        if event.action == "approve":
            run.current_stage = min(run.current_stage + 1, 7)
        elif event.action == "rework":
            run.node_summary = f"rework requested: {event.comment or 'no comment'}"
        else:
            raise ValueError("只有批准或返工可以恢复运行")

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
            run.node_summary = "课程需求快照已生成，等待人工审核"
        elif stage == 2:
            self._write_task_definition(session, course, run)
            run.node_summary = "MISSION.md 与 SPEC.md 已生成，等待人工审核"
        elif stage == 3:
            self._write_blueprint(session, course, run)
            run.node_summary = "来源登记与课程蓝图已生成，等待人工审核"
        elif stage == 4:
            self._write_batches(session, course, run)
            run.node_summary = "批次计划已生成，尚未创建 Context Pack，等待人工审核"
        elif stage == 5:
            if not self.settings.openai_api_key:
                run.error_code = "model_not_configured"
                run.error_summary = "开始章节生成前必须配置 OPENAI_API_KEY"
                return "paused"
            try:
                if not self._produce_chapters(session, course, run):
                    return "waiting_human"
            except TokenBudgetPause:
                return "paused"
            run.node_summary = "批次章节已生成，质量证据等待人工审核"
        elif stage == 6:
            blockers = self._write_course_quality(session, course, run)
            run.node_summary = (
                "整课确定性质量门发现 blocker，等待人工处理"
                if blockers
                else "整课质量审查已完成，等待人工审核"
            )
        elif stage == 7:
            ReleaseService(self.settings.releases_root).build_rc(course)
            run.node_summary = "不可变发布候选已生成，等待最终人工批准"
        else:
            raise ValueError(f"未知阶段：{stage}")
        return "waiting_human"

    def _definition(self, course: Course) -> dict:
        return CourseService(self._session_for(course), self.settings.courses_root).read_definition(
            course
        )

    def _chapter_plan(self, course: Course) -> list[dict]:
        definition = self._definition(course)
        course_title = str(definition.get("title") or course.slug).strip()
        goals = [
            str(goal).strip()
            for goal in definition.get("learning_goals", [])
            if str(goal).strip()
        ]
        count = int(definition.get("expected_chapter_count", 1))
        return [
            {
                "id": f"chapter-{number}",
                "number": number,
                "title": self._chapter_title(course_title, goals, number),
                "lesson_path": f"lessons/{number:02d}-chapter-{number}.md",
            }
            for number in range(1, count + 1)
        ]

    @staticmethod
    def _chapter_title(course_title: str, goals: list[str], number: int) -> str:
        focus = goals[(number - 1) % len(goals)] if goals else course_title
        if focus == course_title:
            return f"第{number}章：{course_title}"
        return f"第{number}章：{course_title} — {focus}"

    @staticmethod
    def _chapter_lesson_path(course: Course, chapter: dict) -> str:
        return str(
            chapter.get("lesson_path")
            or f"lessons/{int(chapter['number']):02d}-{course.slug}.md"
        )

    @staticmethod
    def _session_for(course: Course) -> Session:
        session = object_session(course)
        if session is None:
            raise RuntimeError("课程必须关联数据库会话")
        return session

    def _write_task_definition(self, session: Session, course: Course, run: Run) -> None:
        definition = self._definition(course)
        title = definition.get("title", course.slug)
        audience = definition.get("audience", "self-directed learners")
        goals = definition.get("learning_goals", [])
        mission = f"# {title}\n\n## 目标受众\n\n{audience}\n\n## 学习目标\n" + "\n".join(
            f"- {goal}" for goal in goals
        )
        spec = "# 课程验收标准\n\n" + "\n".join(f"- {goal}" for goal in goals)
        self._write_artifact(
            session, course, run, "task_definition", "workspace/MISSION.md", mission.encode()
        )
        self._write_artifact(
            session, course, run, "task_definition", "workspace/SPEC.md", spec.encode()
        )

    def _write_blueprint(self, session: Session, course: Course, run: Run) -> None:
        definition = self._definition(course)
        chapters = self._chapter_plan(course)
        resources = list(definition.get("resources", []))
        source_policy = definition.get("source_policy", "internal_only")
        if source_policy != "internal_only":
            resources.extend(
                TavilyDiscovery(self.settings.tavily_api_key).discover(
                    f"{definition['title']} {definition['content_scope']}"
                )
            )
        snapshots = SourceSnapshotService(session).capture(
            course,
            run.id,
            resources,
            source_policy,
        )
        source_index = SourceIndexService().build(course, snapshots, chapters)
        self._write_json_artifact(
            session,
            course,
            run,
            "source_index",
            "workspace/source-index.json",
            source_index,
        )
        resource_markdown = "# 来源登记\n\n" + "\n".join(
            f"- {snapshot['origin']} ({snapshot['sha256']})" for snapshot in snapshots
        )
        blueprint_markdown = "# 课程蓝图\n\n" + "\n".join(
            "\n".join(
                [
                    f"## {chapter['title']}",
                    f"\n- 章节 ID：{chapter['id']}",
                    "- 来源片段：" + ", ".join(source_index["chapter_fragment_ids"][chapter["id"]]),
                ]
            )
            for chapter in chapters
        )
        self._write_artifact(
            session, course, run, "sources", "workspace/RESOURCES.md", resource_markdown.encode()
        )
        self._write_artifact(
            session, course, run, "blueprint", "workspace/BLUEPRINT.md", blueprint_markdown.encode()
        )

    def _write_batches(self, session: Session, course: Course, run: Run) -> None:
        definition = self._definition(course)
        chapters = self._chapter_plan(course)
        index_path = Path(course.workspace_path) / "workspace/source-index.json"
        source_index = (
            json.loads(index_path.read_text(encoding="utf-8")) if index_path.is_file() else {}
        )
        batch = {
            "batch_id": "batch-01",
            "chapters": chapters,
            "context_pack_scope": [
                {
                    "chapter_id": chapter["id"],
                    "blueprint_ref": f"workspace/BLUEPRINT.md#{chapter['id']}",
                    "source_refs": source_index.get("chapter_fragment_ids", {}).get(
                        chapter["id"], []
                    ),
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
        source_index = self._workspace_json(course, "workspace/source-index.json")
        gateway = ModelGateway(self.settings)
        for chapter in batch["chapters"]:
            pack = ContextPackInput(
                batch_id=batch["batch_id"],
                chapter_number=chapter["number"],
                chapter_id=chapter["id"],
                chapter_goal=chapter["title"],
                blueprint=chapter,
                source_fragments=SourceIndexService.fragments_for(source_index, chapter["id"]),
                prior_summary=None,
                terms=[],
                writing_constraints=["include a clear explanation, example, and exercise"],
            )
            context = ContextPackService(ArtifactService(session)).build(course, run.id, pack)
            path = self._chapter_lesson_path(course, chapter)
            context_content = Path(context.storage_path).read_text(encoding="utf-8")
            if not self._chapter_quality_cycle(
                session, course, run, gateway, chapter, context_content, path
            ):
                return False
        return True

    def _chapter_quality_cycle(
        self, session, course, run, gateway, chapter, context_content, path
    ) -> bool:
        minimum = int(self._definition(course).get("min_effective_chars_per_chapter", 1))
        prior_fingerprints: list[str] = []
        evidence: list[str] = []
        for round_no in range(1, 4):
            prompt = render_prompt(
                "chapter_writer",
                skill="instructional-writer",
                title=chapter["title"],
                context_content=context_content,
                repair_evidence="; ".join(evidence),
            )
            draft_content, artifact = self._cached_model_output(
                session,
                course,
                run,
                gateway,
                node="chapter_write",
                operation="draft_chapter",
                prompt=prompt,
                logical_path=path,
                round_no=round_no,
            )
            precheck = deterministic_gate(draft_content, artifact.revision, minimum)
            if not precheck.passed:
                self._write_quality_evidence(session, course, run, chapter, round_no, [precheck])
                evidence = [finding.message for finding in precheck.findings]
                prior_fingerprints.extend(finding.fingerprint for finding in precheck.findings)
                continue
            humanized, human_artifact = self._humanize(
                session, course, run, gateway, draft_content, path, round_no
            )
            regression = deterministic_gate(humanized["markdown"], human_artifact.revision, minimum)
            language = language_gate(
                humanized["markdown"],
                human_artifact.revision,
                humanized["scores"],
                humanized["findings"],
            )
            semantic = self._semantic_review(
                session,
                course,
                run,
                gateway,
                chapter["id"],
                round_no,
                humanized["markdown"],
                human_artifact.revision,
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

    def _humanize(self, session, course, run, gateway, markdown: str, path: str, round_no: int):
        prompt = render_prompt(
            "natural_language_editor", skill="natural-language-editor", markdown=markdown
        )
        content, _ = self._cached_model_output(
            session,
            course,
            run,
            gateway,
            node="humanizer",
            operation="humanize_chapter",
            prompt=prompt,
            logical_path=path,
            round_no=round_no,
        )
        try:
            return self._persist_humanized_markdown(
                session, course, run, path, round_no, self._humanizer_payload(content)
            )
        except (KeyError, TypeError, ValueError):
            content, _ = self._cached_model_output(
                session,
                course,
                run,
                gateway,
                node="humanizer",
                operation="repair_humanizer_schema",
                prompt=self._schema_repair_prompt(prompt),
                logical_path=path,
                round_no=round_no,
            )
            try:
                return self._persist_humanized_markdown(
                    session, course, run, path, round_no, self._humanizer_payload(content)
                )
            except (KeyError, TypeError, ValueError) as error:
                raise ModelOutputInvalid("humanizer returned invalid structured output") from error

    def _persist_humanized_markdown(
        self, session, course, run, path: str, round_no: int, payload: dict
    ):
        """Make the chapter view Markdown while preserving raw model JSON as an artifact."""
        markdown = payload["markdown"]
        artifact = self._write_artifact(
            session,
            course,
            run,
            "humanized_markdown",
            path,
            markdown.encode("utf-8"),
            round_no,
        )
        return payload, artifact

    def _semantic_review(
        self,
        session,
        course,
        run,
        gateway,
        chapter_id: str,
        round_no: int,
        markdown: str,
        revision: int,
    ):
        prompt = render_prompt("semantic_reviewer", markdown=markdown)
        content, _ = self._cached_model_output(
            session,
            course,
            run,
            gateway,
            node="semantic_review",
            operation="review_chapter_semantics",
            prompt=prompt,
            logical_path=f"workspace/quality/{chapter_id}-round-{round_no}-semantic.json",
            round_no=round_no,
        )
        try:
            payload = self._semantic_payload(content)
        except (KeyError, TypeError, ValueError):
            content, _ = self._cached_model_output(
                session,
                course,
                run,
                gateway,
                node="semantic_review",
                operation="repair_semantic_schema",
                prompt=self._schema_repair_prompt(prompt),
                logical_path=f"workspace/quality/{chapter_id}-round-{round_no}-semantic.json",
                round_no=round_no,
            )
            try:
                payload = self._semantic_payload(content)
            except (KeyError, TypeError, ValueError) as error:
                raise ModelOutputInvalid("semantic reviewer returned invalid structured output") from error
        outcomes = {
            name: payload["outcomes"][name]
            for name in ("facts_sources", "goals_scope", "teaching", "logic_continuity")
        }
        return semantic_gate(
            markdown, revision, outcomes, self._findings(payload.get("findings", []))
        )

    def _schema_repair_prompt(self, original: RenderedPrompt) -> RenderedPrompt:
        repair = render_prompt("schema_repair", original=original.content)
        return replace(repair, skill_name=original.skill_name, skill_hash=original.skill_hash)

    def _humanizer_payload(self, content: str) -> dict:
        payload = self._model_json(content)
        scores = {}
        for name in ("naturalness", "clarity", "conciseness", "teaching"):
            score = int(payload["scores"][name])
            if not 0 <= score <= 100 or 1 <= score <= 5:
                raise ValueError(
                    f"humanizer score {name} must use the 0-to-100 scale, not 1-to-5"
                )
            scores[name] = score
        return {
            "markdown": str(payload["markdown"]),
            "scores": scores,
            "findings": self._findings(payload.get("findings", [])),
        }

    def _semantic_payload(self, content: str) -> dict:
        payload = self._model_json(content)
        required = ("facts_sources", "goals_scope", "teaching", "logic_continuity")
        if "outcomes" not in payload and all(name in payload for name in required):
            payload = {
                "outcomes": {name: payload[name] for name in required},
                "findings": payload.get("findings", []),
            }
        outcomes = payload.get("outcomes")
        if not isinstance(outcomes, dict) or any(name not in outcomes for name in required):
            raise ValueError("语义审校没有返回全部必需结果")
        if any(outcomes[name] not in {"pass", "warning", "blocker"} for name in required):
            raise ValueError("语义审校返回了不支持的结果状态")
        return payload

    def _cached_model_output(
        self,
        session: Session,
        course: Course,
        run: Run,
        gateway,
        *,
        node: str,
        operation: str,
        prompt: RenderedPrompt,
        logical_path: str,
        round_no: int,
    ):
        request = ArtifactWrite(
            course_id=course.id,
            run_id=run.id,
            node_name=node,
            scope=f"stage-{run.current_stage}:{logical_path}",
            round_no=round_no,
            input_hash=hashlib.sha256(prompt.content.encode()).hexdigest(),
            logical_path=logical_path,
            content=b"",
        )
        artifacts = ArtifactService(session)
        existing = artifacts.recover(course, request)
        if existing is not None:
            return Path(existing.storage_path).read_text(encoding="utf-8"), existing
        result = gateway.complete(
            run,
            node=node,
            operation=operation,
            prompt=prompt.content,
            prompt_name=prompt.name,
            prompt_hash=prompt.content_hash,
            skill_name=prompt.skill_name,
            skill_hash=prompt.skill_hash,
        )
        return result.content, artifacts.write(
            course,
            ArtifactWrite(
                course_id=request.course_id,
                run_id=request.run_id,
                node_name=request.node_name,
                scope=request.scope,
                round_no=request.round_no,
                input_hash=request.input_hash,
                logical_path=request.logical_path,
                content=result.content.encode(),
            ),
        )

    @staticmethod
    def _model_json(content: str) -> dict:
        raw = content.strip().removeprefix("```json").removesuffix("```").strip()
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("模型没有返回对象形式的结构化结果")
        return payload

    @staticmethod
    def _findings(values: list[dict]) -> list[Finding]:
        findings: list[Finding] = []
        for value in values:
            message = str(value.get("message", "")).strip()
            fix = str(value.get("fix", "")).strip()
            if not message and not fix:
                continue
            findings.append(
                Finding(
                    str(value.get("rule", "model_finding")),
                    str(value.get("location", "unknown")),
                    message,
                    str(value.get("excerpt", "")),
                    fix,
                )
            )
        return findings

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
        repair_targets: list[str] = []
        titles: dict[str, list[str]] = {}
        for chapter in batch["chapters"]:
            path = Path(course.workspace_path) / self._chapter_lesson_path(course, chapter)
            if not path.is_file():
                has_blockers = True
                repair_targets.append(chapter["id"])
                chapter_results.append(
                    {"chapter_id": chapter["id"], "missing_lesson": True, "gates": []}
                )
                continue
            markdown = path.read_text(encoding="utf-8")
            gate = deterministic_gate(markdown, 1, minimum)
            title = self._lesson_title(markdown)
            if title:
                titles.setdefault(title, []).append(chapter["id"])
            has_blockers = has_blockers or not gate.passed
            chapter_results.append(
                {"chapter_id": chapter["id"], "missing_lesson": False, "gates": [gate.as_dict()]}
            )
            if not gate.passed:
                repair_targets.append(chapter["id"])
        warnings = [
            {
                "fingerprint": hashlib.sha256(
                    f"duplicate_chapter_title\0{title}".encode()
                ).hexdigest(),
                "rule": "duplicate_chapter_title",
                "message": f"章节标题“{title}”重复出现",
                "chapters": chapter_ids,
            }
            for title, chapter_ids in titles.items()
            if len(chapter_ids) > 1
        ]
        repair_plan = None
        if repair_targets:
            repair_plan = {
                "stage": 6,
                "status": "needs_human_confirmation",
                "root_cause": "course-wide audit found missing or invalid chapter content",
                "target_chapters": repair_targets,
                "execution_order": repair_targets,
                "propagation_scope": "single_chapter",
                "rerun_gates": ["deterministic", "language", "semantic"],
                "closure": ["verified_pass", "human_evidence_invalidates_finding"],
            }
            self._write_json_artifact(
                session,
                course,
                run,
                "course_repair_plan",
                "workspace/course-repair-plan.json",
                repair_plan,
            )
        self._write_json_artifact(
            session,
            course,
            run,
            "course_quality",
            "quality.json",
            {
                "stage": 6,
                "has_blockers": has_blockers,
                "chapters": chapter_results,
                "repair_plan": repair_plan,
                "unresolved_warnings": warnings,
            },
        )
        return has_blockers

    @staticmethod
    def _lesson_title(markdown: str) -> str | None:
        for line in markdown.splitlines():
            if line.startswith("# "):
                return line.removeprefix("# ").strip()
        return None

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
            raise ValueError("没有可发布的发布候选")
        return releases[-1]
