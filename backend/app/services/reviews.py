from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ReviewEvent, Run
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
            run.status = "stopped"
        elif action in {"approve", "rework"}:
            run.status = "queued"
            self.jobs.enqueue(
                run, "publish" if scope == "release" and action == "approve" else "resume", event.id
            )
        return event
