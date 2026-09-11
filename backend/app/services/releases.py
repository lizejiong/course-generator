import hashlib
import json
import shutil
from pathlib import Path

from jinja2 import BaseLoader, Environment
from markdown_it import MarkdownIt
from markupsafe import Markup, escape

from app.db.models import Course

_TEMPLATE = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{ title }}</title>
  <link rel="stylesheet" href="assets/site.css">
</head>
<body><main><article class="lesson">{{ body }}</article></main></body>
</html>"""

_SITE_CSS = """*{box-sizing:border-box}body{margin:0;background:#f4f7fb;color:#192b43;font-family:Inter,"Microsoft YaHei",system-ui,sans-serif;line-height:1.85}main{max-width:860px;margin:0 auto;padding:48px 24px}.lesson{background:#fff;border:1px solid #dfe8f2;border-radius:18px;padding:48px;box-shadow:0 14px 38px #1b4d7a12}.lesson>:first-child{margin-top:0}.lesson h1{font-size:2.1rem;line-height:1.25;letter-spacing:-.04em;margin:0 0 1.4rem;color:#123b70}.lesson h2{margin-top:2.6rem;padding-top:1.3rem;border-top:1px solid #e6edf5;font-size:1.45rem;color:#174f8d}.lesson h3{margin-top:2rem;font-size:1.13rem;color:#245f9f}.lesson p,.lesson li{font-size:1rem}.lesson ul,.lesson ol{padding-left:1.5rem}.lesson li+li{margin-top:.45rem}.lesson blockquote{margin:1.4rem 0;padding:.8rem 1rem;border-left:4px solid #5b9ce0;background:#f2f7fd;color:#4c6480}.lesson pre{overflow:auto;margin:1.4rem 0;padding:18px;border-radius:12px;background:#10233b;color:#e8f1fb;font:14px/1.65 ui-monospace,SFMono-Regular,Consolas,monospace}.lesson code{padding:.12em .35em;border-radius:4px;background:#eef3f8;color:#174f8d;font-family:ui-monospace,SFMono-Regular,Consolas,monospace}.lesson pre code{padding:0;background:transparent;color:inherit}.lesson table{width:100%;border-collapse:collapse;margin:1.4rem 0}.lesson th,.lesson td{padding:.7rem;border:1px solid #dce6f0;text-align:left}.lesson th{background:#f2f7fc}@media(max-width:640px){main{padding:0}.lesson{border:0;border-radius:0;padding:28px 20px}.lesson h1{font-size:1.75rem}}"""


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
            raise ValueError("发布目录不可变")
        markdown_dir = release / "markdown"
        site_dir = release / "site"
        quality_dir = release / "quality"
        markdown_dir.mkdir(parents=True)
        site_dir.mkdir()
        quality_dir.mkdir()
        (site_dir / "assets").mkdir()
        (site_dir / "assets" / "site.css").write_text(_SITE_CSS, encoding="utf-8")
        renderer = MarkdownIt("commonmark", {"html": False})
        index_links: list[str] = []
        chapters: list[dict[str, str]] = []
        for lesson in sorted((workspace / "lessons").glob("*.md")):
            shutil.copy2(lesson, markdown_dir / lesson.name)
            markdown = lesson.read_text(encoding="utf-8")
            title = self._lesson_title(markdown) or lesson.stem
            html = (
                Environment(loader=BaseLoader(), autoescape=True)
                .from_string(_TEMPLATE)
                .render(
                    title=title,
                    body=Markup(renderer.render(markdown)),
                )
            )
            (site_dir / f"{lesson.stem}.html").write_text(html, encoding="utf-8")
            index_links.append(
                f'<li><a href="{lesson.stem}.html">{escape(title)}</a></li>'
            )
            chapters.append(
                {
                    "title": title,
                    "markdown_path": f"markdown/{lesson.name}",
                    "html_path": f"site/{lesson.stem}.html",
                }
            )
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
            "chapters": chapters,
            "files": self._hashes(release),
        }
        (release / "release.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return release

    def promote(self, release: Path) -> dict:
        manifest_path = release / "release.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest["status"] != "rc":
            raise ValueError("只有有效的发布候选可以正式发布")
        # A publication decision is an append-only review event in PostgreSQL.
        # The RC directory, including its manifest, must never be modified.
        return manifest

    @staticmethod
    def _lesson_title(markdown: str) -> str | None:
        for line in markdown.splitlines():
            if line.startswith("# "):
                return line.removeprefix("# ").strip() or None
        return None

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
