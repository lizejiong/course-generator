from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.db.models import Job, Run


class JobService:
    max_infrastructure_retries = 2

    def __init__(self, session: Session) -> None:
        self.session = session

    def enqueue(self, run: Run, job_type: str, input_event_id: UUID | None = None) -> Job:
        job = Job(run_id=run.id, job_type=job_type, input_event_id=input_event_id)
        self.session.add(job)
        self.session.flush()
        return job

    def claim(self, worker_id: str, lease_seconds: int = 60) -> Job | None:
        now = datetime.now(UTC)
        eligible = or_(
            and_(Job.status == "queued", Job.available_at <= now),
            and_(Job.status == "running", Job.lease_expires_at < now),
        )
        job = self.session.scalar(
            select(Job)
            .where(eligible)
            .order_by(Job.available_at, Job.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if job is None:
            return None
        job.status = "running"
        job.attempts += 1
        job.lease_owner = worker_id
        job.lease_expires_at = now + timedelta(seconds=lease_seconds)
        run = self.session.get(Run, job.run_id)
        if run and run.status == "queued":
            run.status = "running"
        self.session.flush()
        return job

    def renew(self, job: Job, worker_id: str, lease_seconds: int = 60) -> None:
        if job.status != "running" or job.lease_owner != worker_id:
            raise ValueError("只有租约持有者可以续租执行中的任务")
        job.lease_expires_at = datetime.now(UTC) + timedelta(seconds=lease_seconds)

    def succeed(self, job: Job) -> None:
        job.status = "succeeded"
        job.lease_owner = None
        job.lease_expires_at = None
        job.finished_at = datetime.now(UTC)

    def cancel(self, job: Job) -> None:
        job.status = "cancelled"
        job.lease_owner = None
        job.lease_expires_at = None
        job.finished_at = datetime.now(UTC)

    def fail_infrastructure(self, job: Job, code: str, summary: str) -> Job | None:
        job.status = "failed"
        job.error_code = code
        job.error_summary = summary
        job.lease_owner = None
        job.lease_expires_at = None
        job.finished_at = datetime.now(UTC)
        if job.attempts > self.max_infrastructure_retries:
            run = self.session.get(Run, job.run_id)
            if run:
                run.status = "failed"
                run.error_code = code
                run.error_summary = summary
            return None
        retry = Job(
            run_id=job.run_id,
            job_type=job.job_type,
            input_event_id=job.input_event_id,
            available_at=datetime.now(UTC) + timedelta(seconds=2**job.attempts),
        )
        self.session.add(retry)
        self.session.flush()
        return retry

    def request_safe_pause(self, run: Run) -> None:
        run.pause_requested = True

    def request_safe_stop(self, run: Run) -> None:
        run.stop_requested = True
