import logging
from collections.abc import Callable

from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Job, Run
from app.services.jobs import JobService
from app.workflows.runner import ModelOutputInvalid

logger = logging.getLogger(__name__)


class Worker:
    """Synchronous PostgreSQL job worker. Workflow state remains in LangGraph checkpoints."""

    def __init__(
        self, session_factory: sessionmaker[Session], worker_id: str, execute: Callable[[Job], str]
    ) -> None:
        self.session_factory = session_factory
        self.worker_id = worker_id
        self.execute = execute

    def run_once(self) -> bool:
        with self.session_factory.begin() as session:
            jobs = JobService(session)
            job = jobs.claim(self.worker_id)
            if job is None:
                return False
            job_id = job.id
        try:
            with self.session_factory.begin() as session:
                job = session.get(Job, job_id)
                assert job is not None
                outcome = self.execute(job)
                run = session.get(Run, job.run_id)
                assert run is not None
                session.expire(run, ["pause_requested", "stop_requested"])
                jobs = JobService(session)
                if run.stop_requested or outcome == "stopped":
                    run.status = "stopped"
                    jobs.succeed(job)
                elif run.pause_requested or outcome == "paused":
                    run.status = "paused"
                    jobs.succeed(job)
                elif outcome == "waiting_human":
                    run.status = "waiting_human"
                    jobs.succeed(job)
                elif outcome == "completed":
                    run.status = "completed"
                    jobs.succeed(job)
                else:
                    jobs.succeed(job)
            return True
        except ModelOutputInvalid as error:
            logger.warning("model output rejected", extra={"job_id": str(job_id)})
            with self.session_factory.begin() as session:
                failed = session.get(Job, job_id)
                assert failed is not None
                JobService(session).fail_business(failed, "model_output_invalid", str(error))
            return True
        except Exception as error:  # Worker owns infrastructure retries, never business routing.
            logger.exception("job execution failed", extra={"job_id": str(job_id)})
            with self.session_factory.begin() as session:
                failed = session.get(Job, job_id)
                assert failed is not None
                JobService(session).fail_infrastructure(failed, "worker_exception", str(error))
            return True
