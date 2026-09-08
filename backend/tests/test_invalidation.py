from uuid import uuid4

from app.db.models import Artifact, Course, Job, Run
from app.services.invalidation import InvalidationService, earliest_stage_for_path


def test_path_to_earliest_stage_mapping_is_deterministic() -> None:
    assert earliest_stage_for_path("course.json") == 1
    assert earliest_stage_for_path("workspace/BLUEPRINT.md") == 3
    assert earliest_stage_for_path("workspace/batches/batch-1.json") == 4
    assert earliest_stage_for_path("lessons/01-intro.md") == 5


def test_edit_invalidates_downstream_artifacts_and_enqueues_resume(db_session) -> None:
    course = Course(slug="invalidate-course", workspace_path="/tmp/invalidate-course")
    db_session.add(course)
    db_session.flush()
    run = Run(course_id=course.id, thread_id=str(uuid4()), current_stage=6, status="waiting_human")
    db_session.add(run)
    db_session.add_all(
        [
            Artifact(
                operation_id="a" * 64,
                course_id=course.id,
                logical_path="workspace/BLUEPRINT.md",
                storage_path="/tmp/a",
                revision=1,
                sha256="a" * 64,
                input_hash="a" * 64,
                producer_node="blueprint",
            ),
            Artifact(
                operation_id="b" * 64,
                course_id=course.id,
                logical_path="lessons/01-intro.md",
                storage_path="/tmp/b",
                revision=1,
                sha256="b" * 64,
                input_hash="b" * 64,
                producer_node="chapter_write",
            ),
        ]
    )
    db_session.flush()
    affected = InvalidationService(db_session).invalidate(course, "workspace/BLUEPRINT.md")
    assert affected == [run]
    assert run.current_stage == 3
    assert run.status == "queued"
    assert all(not artifact.is_valid for artifact in db_session.query(Artifact).all())
    assert (
        db_session.query(Job).filter_by(run_id=run.id, job_type="resume", status="queued").count()
        == 1
    )
