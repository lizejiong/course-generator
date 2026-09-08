import hashlib
import json
import shutil
from pathlib import Path

from jinja2 import BaseLoader, Environment
from markdown_it import MarkdownIt
from markupsafe import Markup

from app.db.models import Course

_TEMPLATE = """<!doctype html><html lang=\"zh-CN\"><meta charset=\"utf-8\">
<title>{{ title }}</title><body><main>{{ body }}</main></body></html>"""


class ReleaseService:
    def __init__(self, releases_root: Path) -> None:
        self.releases_root = releases_root

    def build_rc(self, course: Course) -> Path:
        workspace = Path(course.workspace_path)
        target_root = self.releases_root / course.slug
        source_hash = self._source_hash(workspace)
        for candidate in target_root.glob("r[0-9][0-9][0-9][0-9]"):
            manifest_path = candidate / "release.json"
            if manifest_path.is_file():
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                if manifest.get("source_hash") == source_hash:
                    return candidate
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
        (site_dir / "assets").mkdir()
        (site_dir / "assets" / "site.css").write_text(
            "body{font-family:system-ui,sans-serif;max-width:760px;"
            "margin:2rem auto;line-height:1.7}",
            encoding="utf-8",
        )
        renderer = MarkdownIt("commonmark", {"html": False})
        index_links: list[str] = []
        for lesson in sorted((workspace / "lessons").glob("*.md")):
            shutil.copy2(lesson, markdown_dir / lesson.name)
            html = (
                Environment(loader=BaseLoader(), autoescape=True)
                .from_string(_TEMPLATE)
                .render(
                    title=lesson.stem,
                    body=Markup(renderer.render(lesson.read_text(encoding="utf-8"))),
                )
            )
            (site_dir / f"{lesson.stem}.html").write_text(html, encoding="utf-8")
            index_links.append(f'<li><a href="{lesson.stem}.html">{lesson.stem}</a></li>')
        index = (
            Environment(loader=BaseLoader(), autoescape=True)
            .from_string(_TEMPLATE)
            .render(
                title=course.slug,
                body=Markup("<h1>课程目录</h1><ul>" + "".join(index_links) + "</ul>"),
            )
        )
        (site_dir / "index.html").write_text(index, encoding="utf-8")
        quality = workspace / "quality.json"
        if quality.exists():
            shutil.copy2(quality, quality_dir / quality.name)
        manifest = {
            "version": version,
            "status": "rc",
            "course_id": str(course.id),
            "source_hash": source_hash,
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

    @staticmethod
    def _source_hash(workspace: Path) -> str:
        visible = [workspace / "course.json", workspace / "quality.json"]
        visible.extend((workspace / "lessons").glob("*.md"))
        visible.extend((workspace / "workspace" / "source-snapshots").glob("*.txt"))
        digest = hashlib.sha256()
        for path in sorted(path for path in visible if path.is_file()):
            digest.update(str(path.relative_to(workspace)).replace("\\", "/").encode())
            digest.update(b"\0")
            digest.update(hashlib.sha256(path.read_bytes()).digest())
        return digest.hexdigest()
