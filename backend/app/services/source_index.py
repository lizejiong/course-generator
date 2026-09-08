"""Lightweight, deterministic source fragmentation without a vector database."""

import re
from pathlib import Path

from app.db.models import Course


class SourceIndexService:
    def build(self, course: Course, snapshots: list[dict], chapters: list[dict]) -> dict:
        fragments: list[dict] = []
        assignments = {chapter["id"]: [] for chapter in chapters}
        workspace = Path(course.workspace_path)
        for snapshot in snapshots:
            digest = snapshot["sha256"]
            text = (workspace / "workspace" / "source-snapshots" / f"{digest}.txt").read_text(
                encoding="utf-8"
            )
            for paragraph_number, paragraph in enumerate(self._paragraphs(text), start=1):
                fragment_id = f"{digest[:12]}-p{paragraph_number:03d}"
                fragment = {
                    "id": fragment_id,
                    "source_sha256": digest,
                    "origin": snapshot["origin"],
                    "paragraph": paragraph_number,
                    "text": paragraph,
                }
                fragments.append(fragment)
                if chapters:
                    assignments[chapters[(len(fragments) - 1) % len(chapters)]["id"]].append(
                        fragment_id
                    )
        return {
            "fragments": fragments,
            "chapter_fragment_ids": assignments,
        }

    @staticmethod
    def fragments_for(index: dict, chapter_id: str) -> list[dict]:
        wanted = set(index.get("chapter_fragment_ids", {}).get(chapter_id, []))
        return [fragment for fragment in index.get("fragments", []) if fragment["id"] in wanted]

    @staticmethod
    def _paragraphs(text: str) -> list[str]:
        return [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
