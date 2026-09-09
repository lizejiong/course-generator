import json
from pathlib import Path
from uuid import uuid4

import pytest
from test_artifacts import MemorySession

from app.db.models import Course
from app.services.source_snapshots import SourceSnapshotService
from app.services.sources import SourceSnapshot


class SourceMemorySession(MemorySession):
    """This service test only needs insertion behavior, not artifact re-entry lookup."""

    def scalar(self, statement):
        return None


def test_pasted_sources_become_hashed_artifacts_without_network(tmp_path: Path) -> None:
    workspace = tmp_path / "course"
    (workspace / ".artifacts").mkdir(parents=True)
    course = Course(id=uuid4(), slug="source-course", workspace_path=str(workspace))
    service = SourceSnapshotService(
        SourceMemorySession(), lambda url: SourceSnapshot(url, "web", "a" * 64)
    )  # type: ignore[arg-type]
    snapshots = service.capture(
        course, uuid4(), [{"name": "notes", "text": "evidence"}], "internal_only"
    )
    assert snapshots[0]["origin"] == "notes"
    assert (
        workspace / "workspace" / "source-snapshots" / f"{snapshots[0]['sha256']}.txt"
    ).is_file()
    manifest = json.loads(
        (workspace / "workspace" / "source-snapshots" / f"{snapshots[0]['sha256']}.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["origin"] == "notes"
    assert manifest["source_policy"] == "internal_only"
    assert manifest["captured_at"]
    duplicate = service.capture(
        course,
        uuid4(),
        [{"name": "first", "text": "same"}, {"name": "second", "text": "same"}],
        "internal_only",
    )
    assert len(duplicate) == 1


def test_internal_only_policy_rejects_url_fetching(tmp_path: Path) -> None:
    workspace = tmp_path / "course"
    (workspace / ".artifacts").mkdir(parents=True)
    course = Course(id=uuid4(), slug="source-course", workspace_path=str(workspace))
    service = SourceSnapshotService(SourceMemorySession())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="禁止联网"):
        service.capture(course, uuid4(), ["https://example.com"], "internal_only")
