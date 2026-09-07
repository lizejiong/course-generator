from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.checkpoints import postgres_checkpointer
from app.db.models import Course, Job, Run
from app.services.jobs import JobService


def test_active_job_constraint_and_skip_locked_claim_are_enforced_by_postgres(db_session) -> None:
    course = Course(slug="postgres-course", workspace_path="/tmp/postgres-course")
    db_session.add(course)
    db_session.flush()
    run = Run(course_id=course.id, thread_id=str(uuid4()))
    db_session.add(run)
    db_session.flush()
    first = JobService(db_session).enqueue(run, "start")
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(Job(run_id=run.id, job_type="resume"))
            db_session.flush()
    claimed = JobService(db_session).claim("worker-a")
    assert claimed and claimed.id == first.id


def test_official_postgres_checkpointer_initializes_its_own_tables(settings) -> None:
    with postgres_checkpointer(settings) as checkpointer:
        assert checkpointer is not None
