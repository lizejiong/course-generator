import hashlib
import json
import shutil
from pathlib import Path

from jinja2 import BaseLoader, Environment

from app.db.models import Course

_TEMPLATE = """<!doctype html><html lang=\"zh-CN\"><meta charset=\"utf-8\">
<title>{{ title }}</title><body><main>{{ body }}</main></body></html>"""


class ReleaseService:
    def __init__(self, releases_root: Path) -> None:
        self.releases_root = releases_root

    def build_rc(self, course: Course) -> Path:
        workspace = Path(course.workspace_path)
        target_root = self.releases_root / course.slug
        version = f"r{len(list(target_root.glob('r[0-9][0-9][0-9][0-9]'))) + 1:04d}"
        release = target_root / version
        if release.exists():
            raise ValueError("release directory is immutable")
        markdown_dir = release / "markdown"
        site_dir = release / "site"
        quality_dir = release / "quality"
        markdown_dir.mkdir(parents=True)
        site_dir.mkdir()
        quality_dir.mkdir()
        for lesson in sorted((workspace / "lessons").glob("*.md")):
            shutil.copy2(lesson, markdown_dir / lesson.name)
            html = (
                Environment(loader=BaseLoader(), autoescape=True)
                .from_string(_TEMPLATE)
                .render(title=lesson.stem, body=f"<pre>{lesson.read_text(encoding='utf-8')}</pre>")
            )
            (site_dir / f"{lesson.stem}.html").write_text(html, encoding="utf-8")
        quality = workspace / "quality.json"
        if quality.exists():
            shutil.copy2(quality, quality_dir / quality.name)
        manifest = {
            "version": version,
            "status": "rc",
            "course_id": str(course.id),
            "files": self._hashes(release),
        }
        (release / "release.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return release

    def promote(self, release: Path) -> dict:
        manifest_path = release / "release.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest["status"] != "rc":
            raise ValueError("only a valid release candidate can be published")
        # A publication decision is an append-only review event in PostgreSQL.
        # The RC directory, including its manifest, must never be modified.
        return manifest

    @staticmethod
    def _hashes(root: Path) -> dict[str, str]:
        return {
            str(path.relative_to(root)).replace("\\", "/"): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in root.rglob("*")
            if path.is_file() and path.name != "release.json"
        }
