from uuid import uuid4

import pytest

from app.db.models import Run
from app.services.reviews import ReviewService


class ReviewSession:
    def __init__(self) -> None:
        self.added = []

    def add(self, value) -> None:
        self.added.append(value)

    def flush(self) -> None:
        pass

    def scalars(self, statement):
        return []


def test_review_is_append_only_and_approve_enqueues_resume_job() -> None:
    session = ReviewSession()
    run = Run(id=uuid4(), course_id=uuid4(), thread_id="thread", status="waiting_human")
    event = ReviewService(session).decide(  # type: ignore[arg-type]
        run, scope="stage", target="stage-3", action="approve", evidence={}
    )
    assert event in session.added
    assert any(getattr(item, "job_type", None) == "resume" for item in session.added)
    assert run.status == "queued"


def test_approval_cannot_waive_a_real_blocker() -> None:
    with pytest.raises(ValueError, match="不能豁免"):
        ReviewService(ReviewSession()).decide(  # type: ignore[arg-type]
            Run(id=uuid4(), course_id=uuid4(), thread_id="thread"),
            scope="stage",
            target="stage-5",
            action="approve",
            evidence={"unresolved_blocker": True},
        )


def test_stage_six_approval_requires_a_quality_report_without_blockers(tmp_path) -> None:
    class StageSixSession(ReviewSession):
        def __init__(self) -> None:
            super().__init__()
            self.course = type("Course", (), {"workspace_path": str(tmp_path)})()

        def get(self, model, identifier):
            return self.course

    (tmp_path / "quality.json").write_text('{"has_blockers": true}', encoding="utf-8")
    run = Run(
        id=uuid4(),
        course_id=uuid4(),
        thread_id="stage-six",
        status="waiting_human",
        current_stage=6,
    )
    with pytest.raises(ValueError, match="不能豁免"):
        ReviewService(StageSixSession()).decide(  # type: ignore[arg-type]
            run, scope="stage", target="stage-6", action="approve"
        )


def test_release_approval_requires_waiting_stage_seven_candidate() -> None:
    session = ReviewSession()
    with pytest.raises(ValueError, match="阶段七"):
        ReviewService(session).decide(  # type: ignore[arg-type]
            Run(id=uuid4(), course_id=uuid4(), thread_id="thread", current_stage=6),
            scope="release",
            target="r0001",
            action="approve",
        )
    run = Run(
        id=uuid4(),
        course_id=uuid4(),
        thread_id="thread-2",
        current_stage=7,
        status="waiting_human",
    )
    ReviewService(session).decide(  # type: ignore[arg-type]
        run, scope="release", target="r0001", action="approve"
    )
    assert any(getattr(item, "job_type", None) == "publish" for item in session.added)
