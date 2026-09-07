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
    with pytest.raises(ValueError, match="cannot waive"):
        ReviewService(ReviewSession()).decide(  # type: ignore[arg-type]
            Run(id=uuid4(), course_id=uuid4(), thread_id="thread"),
            scope="stage",
            target="stage-5",
            action="approve",
            evidence={"unresolved_blocker": True},
        )
