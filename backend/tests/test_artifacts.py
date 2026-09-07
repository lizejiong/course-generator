from pathlib import Path
from uuid import uuid4

from app.db.models import Course
from app.services.artifacts import ArtifactService, ArtifactWrite


class MemorySession:
    def __init__(self) -> None:
        self.artifacts = []

    def scalar(self, statement):
        text = str(statement)
        if "operation_id" in text:
            return self.artifacts[0] if self.artifacts else None
        return max((item.revision for item in self.artifacts), default=0)

    def add(self, value) -> None:
        self.artifacts.append(value)

    def flush(self) -> None:
        pass


def test_operation_reentry_reuses_immutable_artifact_and_rebuilds_missing_work_view(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "course"
    (workspace / ".artifacts").mkdir(parents=True)
    course = Course(id=uuid4(), slug="demo", workspace_path=str(workspace))
    session = MemorySession()
    request = ArtifactWrite(
        course_id=course.id,
        run_id=uuid4(),
        node_name="draft_chapter",
        scope="chapter-01",
        round_no=1,
        input_hash="a" * 64,
        logical_path="lessons/01-demo.md",
        content=b"# v1",
    )
    service = ArtifactService(session)  # type: ignore[arg-type]
    first = service.write(course, request)
    (workspace / "lessons" / "01-demo.md").unlink()
    second = service.write(course, request)
    assert first is second
    assert len(session.artifacts) == 1
    assert (workspace / "lessons" / "01-demo.md").read_bytes() == b"# v1"
    assert Path(first.storage_path).read_bytes() == b"# v1"


def test_existing_file_without_database_row_is_registered_with_its_existing_bytes(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "course"
    (workspace / ".artifacts").mkdir(parents=True)
    course = Course(id=uuid4(), slug="demo", workspace_path=str(workspace))
    request = ArtifactWrite(
        course_id=course.id,
        run_id=uuid4(),
        node_name="draft_chapter",
        scope="chapter-01",
        round_no=1,
        input_hash="b" * 64,
        logical_path="lessons/01-demo.md",
        content=b"new bytes must not replace a completed artifact",
    )
    storage = workspace / ".artifacts" / f"{request.operation_id}.md"
    storage.write_bytes(b"already durable")
    artifact = ArtifactService(MemorySession()).write(course, request)  # type: ignore[arg-type]
    assert artifact.sha256
    assert (workspace / "lessons" / "01-demo.md").read_bytes() == b"already durable"
