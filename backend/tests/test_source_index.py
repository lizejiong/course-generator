from pathlib import Path
from uuid import uuid4

from app.db.models import Course
from app.services.source_index import SourceIndexService


def test_source_index_splits_snapshot_paragraphs_and_assigns_stable_chapter_refs(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "course"
    snapshots_root = workspace / "workspace" / "source-snapshots"
    snapshots_root.mkdir(parents=True)
    digest = "a" * 64
    (snapshots_root / f"{digest}.txt").write_text("第一段\n\n第二段\n\n第三段", encoding="utf-8")
    course = Course(id=uuid4(), slug="index-course", workspace_path=str(workspace))
    index = SourceIndexService().build(
        course,
        [{"origin": "资料", "sha256": digest}],
        [{"id": "chapter-1"}, {"id": "chapter-2"}],
    )
    assert [item["text"] for item in index["fragments"]] == ["第一段", "第二段", "第三段"]
    assert index["chapter_fragment_ids"] == {
        "chapter-1": [f"{digest[:12]}-p001", f"{digest[:12]}-p003"],
        "chapter-2": [f"{digest[:12]}-p002"],
    }
    assert [item["text"] for item in SourceIndexService.fragments_for(index, "chapter-2")] == [
        "第二段"
    ]
