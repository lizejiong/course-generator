import json
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Course, ReviewEvent, Run
from app.services.jobs import JobService


class ReviewService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.jobs = JobService(session)

    def events(self, run_id: UUID) -> list[ReviewEvent]:
        return list(self.session.scalars(select(ReviewEvent).where(ReviewEvent.run_id == run_id)))

    def decide(
        self,
        run: Run,
        *,
        scope: str,
        target: str,
        action: str,
        comment: str | None = None,
        evidence: dict | None = None,
        related_revision: int | None = None,
    ) -> ReviewEvent:
        if action not in {"approve", "rework", "stop", "acknowledge"}:
            raise ValueError("unsupported review action")
        if action == "approve" and (evidence or {}).get("unresolved_blocker"):
            raise ValueError("approval cannot waive a real blocker")
        if action == "approve" and scope == "stage" and run.current_stage == 6:
            self._require_course_quality_clear(run)
        if scope == "release" and (
            action != "approve" or run.current_stage != 7 or run.status != "waiting_human"
        ):
            raise ValueError("only the waiting stage-seven release candidate can be published")
        if action in {"approve", "rework"} and run.status != "waiting_human":
            raise ValueError("a run can only be reviewed while waiting for human input")
        event = ReviewEvent(
            run_id=run.id,
            scope=scope,
            target=target,
            action=action,
            comment=comment,
            evidence=evidence or {},
            related_revision=related_revision,
        )
        self.session.add(event)
        self.session.flush()
        if action == "stop":
            run.stop_requested = True
            if run.status == "waiting_human":
                run.status = "stopped"
        elif action in {"approve", "rework"}:
            run.status = "queued"
            self.jobs.enqueue(
                run, "publish" if scope == "release" and action == "approve" else "resume", event.id
            )
        return event

    def _require_course_quality_clear(self, run: Run) -> None:
        course = self.session.get(Course, run.course_id)
        if course is None:
            raise ValueError("course not found for stage-six review")
        quality_path = Path(course.workspace_path) / "quality.json"
        if not quality_path.is_file():
            raise ValueError("stage-six quality report is required before approval")
        report = json.loads(quality_path.read_text(encoding="utf-8"))
        if report.get("has_blockers"):
            raise ValueError("approval cannot waive a real blocker; submit rework instead")
