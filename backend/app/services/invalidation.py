from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Artifact, Course, Job, Run
from app.services.jobs import JobService


def earliest_stage_for_path(path: str) -> int:
    if path == "course.json":
        return 1
    if path in {"workspace/MISSION.md", "workspace/SPEC.md"}:
        return 2
    if path in {"workspace/BLUEPRINT.md", "workspace/RESOURCES.md"}:
        return 3
    if path.startswith("workspace/batches/"):
        return 4
    if path.startswith("lessons/"):
        return 5
    return 1


class InvalidationService:
    """Apply deterministic source-of-truth invalidation before creating a new revision."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def invalidate(self, course: Course, path: str) -> list[Run]:
        earliest_stage = earliest_stage_for_path(path)
        node_stages = {
            "requirements": 1,
            "task_definition": 2,
            "sources": 3,
            "source_snapshot": 3,
            "source_snapshot_manifest": 3,
            "source_index": 3,
            "blueprint": 3,
            "batch_plan": 4,
            "context_pack": 5,
            "chapter_write": 5,
            "humanizer": 5,
            "semantic_review": 5,
            "quality_evidence": 5,
            "course_quality": 6,
            "course_repair_plan": 6,
            "release": 7,
        }
        artifacts = self.session.scalars(
            select(Artifact).where(Artifact.course_id == course.id, Artifact.is_valid.is_(True))
        )
        for artifact in artifacts:
            if node_stages.get(artifact.producer_node, 1) >= earliest_stage:
                artifact.is_valid = False
        affected: list[Run] = []
        for run in self.session.scalars(select(Run).where(Run.course_id == course.id)):
            if run.status in {"completed", "stopped"}:
                continue
            run.current_stage = min(run.current_stage, earliest_stage)
            run.status = "queued"
            affected.append(run)
            has_active = self.session.scalar(
                select(Job.id).where(Job.run_id == run.id, Job.status.in_(("queued", "running")))
            )
            if has_active is None:
                JobService(self.session).enqueue(run, "resume")
        return affected
