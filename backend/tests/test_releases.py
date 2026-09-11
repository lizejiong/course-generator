import json
from pathlib import Path
from uuid import uuid4

from app.db.models import Course
from app.services.releases import ReleaseService


def test_release_candidate_is_hashed_and_promotion_does_not_change_its_bytes(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "course"
    lessons = workspace / "lessons"
    lessons.mkdir(parents=True)
    (lessons / "01-intro.md").write_text("# 第一章：课程导览\n\n正文", encoding="utf-8")
    course = Course(id=uuid4(), slug="release-course", workspace_path=str(workspace))
    service = ReleaseService(tmp_path / "releases")
    release = service.build_rc(course)
    before = (release / "release.json").read_bytes()
    manifest = service.promote(release)
    assert manifest["status"] == "rc"
    assert (release / "release.json").read_bytes() == before
    payload = json.loads(before)
    assert payload["files"]["markdown/01-intro.md"]
    assert payload["chapters"] == [
        {
            "title": "第一章：课程导览",
            "markdown_path": "markdown/01-intro.md",
            "html_path": "site/01-intro.html",
        }
    ]
    assert (release / "site" / "index.html").is_file()
    html = (release / "site" / "01-intro.html").read_text(encoding="utf-8")
    assert '<article class="lesson">' in html
    assert 'href="assets/site.css"' in html
    assert service.build_rc(course) == release
