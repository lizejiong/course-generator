from uuid import uuid4

from sqlalchemy.orm import sessionmaker

from app.db.models import Run
from app.services.courses import CourseService
from app.services.jobs import JobService
from app.services.reviews import ReviewService
from app.worker import Worker
from app.workflows.runner import WorkflowRunner


def test_worker_persists_stage_artifact_waits_for_human_then_resumes(settings, db_session) -> None:
    course = CourseService(db_session, settings.courses_root).create(
        "worker-course",
        {
            "title": "Worker Course",
            "audience": "learners",
            "learning_goals": ["verify a durable workflow"],
            "expected_chapter_count": 1,
        },
    )
    run = Run(course_id=course.id, thread_id=str(uuid4()))
    db_session.add(run)
    db_session.flush()
    JobService(db_session).enqueue(run, "start")
    db_session.commit()
    factory = sessionmaker(db_session.bind, expire_on_commit=False)
    worker = Worker(factory, "test-worker", WorkflowRunner(settings).execute)

    assert worker.run_once()
    with factory.begin() as session:
        persisted = session.get(Run, run.id)
        assert persisted and persisted.status == "waiting_human"
        assert persisted.current_stage == 1
        assert (settings.courses_root / "worker-course" / "workspace" / "INPUT.json").is_file()
        ReviewService(session).decide(persisted, scope="stage", target="stage-1", action="approve")

    assert worker.run_once()
    with factory.begin() as session:
        persisted = session.get(Run, run.id)
        assert persisted and persisted.status == "waiting_human"
        assert persisted.current_stage == 2
        root = settings.courses_root / "worker-course" / "workspace"
        assert (root / "MISSION.md").is_file()
        assert (root / "SPEC.md").is_file()
