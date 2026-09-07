from pathlib import Path
from uuid import uuid4

from test_artifacts import MemorySession

from app.db.models import Course
from app.services.artifacts import ArtifactService
from app.services.context_packs import ContextPackInput, ContextPackService


def test_context_pack_is_deterministic_read_only_artifact(tmp_path: Path) -> None:
    workspace = tmp_path / "course"
    (workspace / ".artifacts").mkdir(parents=True)
    course = Course(id=uuid4(), slug="context-course", workspace_path=str(workspace))
    payload = ContextPackInput(
        batch_id="batch-1",
        chapter_number=1,
        chapter_id="chapter-1",
        chapter_goal="explain the concept",
        blueprint={"title": "Intro"},
        source_fragments=[{"id": "source-1", "text": "evidence"}],
        prior_summary=None,
        terms=["term"],
        writing_constraints=["include an exercise"],
    )
    session = MemorySession()
    service = ContextPackService(ArtifactService(session))  # type: ignore[arg-type]
    first = service.build(course, uuid4(), payload)
    # Same visible facts and run scope resolve to the same artifact operation.
    second = service.build(course, first.run_id, payload)
    assert first is second
    assert "context-packs/batch-1/chapter-01.json" in first.logical_path
