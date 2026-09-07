import hashlib
import json
from pathlib import Path

from sqlalchemy.orm import Session, object_session

from app.config import Settings
from app.db.models import Course, Job, ReviewEvent, Run
from app.services.artifacts import ArtifactService, ArtifactWrite
from app.services.context_packs import ContextPackInput, ContextPackService
from app.services.courses import CourseService
from app.services.models import ModelGateway
from app.services.releases import ReleaseService


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
        if job.job_type == "publish":
            ReleaseService(self.settings.releases_root).promote(self._release_path(course))
            run.node_summary = "release promoted by an append-only review event"
            return "completed"
        if job.job_type == "resume":
            self._apply_review_decision(session, run, job)
        if run.pause_requested:
            return "paused"
        if run.stop_requested:
            return "stopped"
        return self._execute_stage(session, course, run)

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
            self._produce_chapters(session, course, run)
            run.node_summary = "batch production completed; quality evidence awaits approval"
        elif stage == 6:
            self._write_json_artifact(
                session,
                course,
                run,
                "course_quality",
                "quality.json",
                {"status": "pending_semantic_review", "stage": 6},
            )
            run.node_summary = "course-wide quality review ready for approval"
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
        resources = definition.get("resources", [])
        resource_markdown = "# Resources\n\n" + "\n".join(f"- {resource}" for resource in resources)
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
        batch = {"batch_id": "batch-01", "chapters": chapters, "context_pack_scope": []}
        self._write_json_artifact(
            session, course, run, "batch_plan", "workspace/batches/batch-01.json", batch
        )

    def _produce_chapters(self, session: Session, course: Course, run: Run) -> None:
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
            prompt = " ".join(
                [
                    f"Write one Markdown lesson titled {chapter['title']}.",
                    f"Use Context Pack {context.id}.",
                    "Include a clear explanation, example, and exercise.",
                ]
            )
            result = gateway.complete(
                run,
                node="chapter_write",
                operation="draft_chapter",
                prompt=prompt,
                prompt_name="chapter_writer",
                prompt_hash=hashlib.sha256(b"chapter_writer_v1").hexdigest(),
            )
            path = f"lessons/{chapter['number']:02d}-{course.slug}.md"
            self._write_artifact(
                session, course, run, "chapter_write", path, result.content.encode()
            )

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
        self, session: Session, course: Course, run: Run, node: str, path: str, content: bytes
    ) -> None:
        ArtifactService(session).write(
            course,
            ArtifactWrite(
                course_id=course.id,
                run_id=run.id,
                node_name=node,
                scope=f"stage-{run.current_stage}:{path}",
                round_no=1,
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
