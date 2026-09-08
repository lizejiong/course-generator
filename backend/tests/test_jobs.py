from datetime import UTC, datetime
from uuid import uuid4

from app.db.models import Job, Run
from app.services.jobs import JobService
from app.worker import Worker


class ClaimingSession:
    def __init__(self, job: Job | None, run: Run) -> None:
        self.job = job
        self.run = run
        self.statement = None

    def scalar(self, statement):
        self.statement = statement
        return self.job

    def get(self, model, value):
        return self.run if model is Run else None

    def add(self, value) -> None:
        self.enqueued = value

    def flush(self) -> None:
        pass


def test_claim_uses_skip_locked_and_assigns_lease() -> None:
    run = Run(id=uuid4(), course_id=uuid4(), thread_id="thread", status="queued")
    job = Job(
        id=uuid4(), run_id=run.id, job_type="start", attempts=0, available_at=datetime.now(UTC)
    )
    session = ClaimingSession(job, run)
    claimed = JobService(session).claim("worker-a", lease_seconds=30)  # type: ignore[arg-type]
    assert claimed is job
    assert job.status == "running"
    assert job.lease_owner == "worker-a"
    assert job.lease_expires_at > datetime.now(UTC)
    assert run.status == "running"
    assert session.statement._for_update_arg.skip_locked


def test_infrastructure_failure_enqueues_at_most_two_checkpoint_retries() -> None:
    run = Run(id=uuid4(), course_id=uuid4(), thread_id="thread")
    job = Job(id=uuid4(), run_id=run.id, job_type="resume", attempts=2)
    session = ClaimingSession(job, run)
    retry = JobService(session).fail_infrastructure(job, "network", "temporary")  # type: ignore[arg-type]
    assert retry is not None
    assert retry.run_id == run.id
    final = Job(id=uuid4(), run_id=run.id, job_type="resume", attempts=3)
    session.job = final
    assert JobService(session).fail_infrastructure(final, "network", "permanent") is None  # type: ignore[arg-type]
    assert run.status == "failed"


def test_worker_stop_request_wins_over_waiting_human_outcome() -> None:
    run = Run(id=uuid4(), course_id=uuid4(), thread_id="thread", stop_requested=True)
    job = Job(id=uuid4(), run_id=run.id, job_type="start", status="running", attempts=0)

    class Transaction:
        def __init__(self, session):
            self.session = session

        def __enter__(self):
            return self.session

        def __exit__(self, *args):
            return None

    class WorkerSession(ClaimingSession):
        def __init__(self):
            super().__init__(job, run)
            self.calls = 0

        def begin(self):
            return Transaction(self)

        def get(self, model, value):
            return job if model is Job else run

    class Factory:
        def __init__(self, session):
            self.session = session

        def begin(self):
            return Transaction(self.session)

    session = WorkerSession()
    worker = Worker(Factory(session), "worker", lambda _: "waiting_human")  # type: ignore[arg-type]
    assert worker.run_once()
    assert run.status == "stopped"
    assert job.status == "succeeded"
