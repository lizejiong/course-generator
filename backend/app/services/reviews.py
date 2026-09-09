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
            raise ValueError("不支持的审核动作")
        if action == "approve" and (evidence or {}).get("unresolved_blocker"):
            raise ValueError("批准不能豁免真实 blocker")
        if action == "approve" and scope == "stage" and run.current_stage == 6:
            self._require_course_quality_clear(run)
        if scope == "release" and (
            action != "approve" or run.current_stage != 7 or run.status != "waiting_human"
        ):
            raise ValueError("只有等待审核的阶段七发布候选可以正式发布")
        if action in {"approve", "rework"} and run.status != "waiting_human":
            raise ValueError("只能审核等待人工输入的运行")
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
            raise ValueError("阶段六审核对应的课程不存在")
        quality_path = Path(course.workspace_path) / "quality.json"
        if not quality_path.is_file():
            raise ValueError("批准前必须存在阶段六质量报告")
        report = json.loads(quality_path.read_text(encoding="utf-8"))
        if report.get("has_blockers"):
            raise ValueError("批准不能豁免真实 blocker；请提交返工")
        warnings = report.get("unresolved_warnings", [])
        required = {warning["fingerprint"] for warning in warnings}
        if not required:
            return
        acknowledgements = self.session.scalars(
            select(ReviewEvent).where(
                ReviewEvent.run_id == run.id,
                ReviewEvent.scope == "stage",
                ReviewEvent.target == "stage-6",
                ReviewEvent.action == "acknowledge",
            )
        )
        acknowledged = {
            fingerprint
            for event in acknowledgements
            for fingerprint in event.evidence.get("warning_fingerprints", [])
        }
        missing = required - acknowledged
        if missing:
            raise ValueError("进入阶段七前必须确认所有未解决的 warning")
