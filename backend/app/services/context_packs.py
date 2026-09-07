import hashlib
import json
from dataclasses import dataclass
from uuid import UUID

from app.db.models import Artifact, Course
from app.services.artifacts import ArtifactService, ArtifactWrite


@dataclass(frozen=True)
class ContextPackInput:
    batch_id: str
    chapter_number: int
    chapter_id: str
    chapter_goal: str
    blueprint: dict
    source_fragments: list[dict]
    prior_summary: str | None
    terms: list[str]
    writing_constraints: list[str]

    def content(self) -> bytes:
        return json.dumps(
            {
                "chapter_id": self.chapter_id,
                "chapter_goal": self.chapter_goal,
                "blueprint": self.blueprint,
                "source_fragments": self.source_fragments,
                "prior_summary": self.prior_summary,
                "terms": self.terms,
                "writing_constraints": self.writing_constraints,
            },
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        ).encode()


class ContextPackService:
    """Deterministically assemble the read-only input for one chapter."""

    def __init__(self, artifacts: ArtifactService) -> None:
        self.artifacts = artifacts

    def build(self, course: Course, run_id: UUID, payload: ContextPackInput) -> Artifact:
        content = payload.content()
        input_hash = hashlib.sha256(content).hexdigest()
        return self.artifacts.write(
            course,
            ArtifactWrite(
                course_id=course.id,
                run_id=run_id,
                node_name="context_pack",
                scope=f"{payload.batch_id}:{payload.chapter_id}",
                round_no=1,
                input_hash=input_hash,
                logical_path=(
                    f"workspace/context-packs/{payload.batch_id}/chapter-{payload.chapter_number:02d}.json"
                ),
                content=content,
            ),
        )
