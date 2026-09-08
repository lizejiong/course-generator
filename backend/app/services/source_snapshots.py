import hashlib
from collections.abc import Callable
from uuid import UUID

from sqlalchemy.orm import Session

from app.db.models import Course
from app.services.artifacts import ArtifactService, ArtifactWrite
from app.services.sources import SourceSnapshot, fetch_source


class SourceSnapshotService:
    def __init__(
        self, session: Session, fetcher: Callable[[str], SourceSnapshot] = fetch_source
    ) -> None:
        self.session = session
        self.fetcher = fetcher
        self.artifacts = ArtifactService(session)

    def capture(
        self,
        course: Course,
        run_id: UUID,
        resources: list[str | dict],
        source_policy: str,
    ) -> list[dict]:
        snapshots: list[dict] = []
        seen_hashes: set[str] = set()
        for index, resource in enumerate(resources, start=1):
            if isinstance(resource, str) and resource.startswith(("http://", "https://")):
                if source_policy == "internal_only":
                    raise ValueError("source policy forbids network retrieval")
                snapshot = self.fetcher(resource)
                origin = snapshot.url
                content = snapshot.content
                digest = snapshot.sha256
            else:
                content = resource["text"] if isinstance(resource, dict) else resource
                origin = (
                    resource.get("name", f"pasted-{index}")
                    if isinstance(resource, dict)
                    else f"pasted-{index}"
                )
                digest = hashlib.sha256(content.encode()).hexdigest()
            if digest in seen_hashes:
                continue
            seen_hashes.add(digest)
            artifact = self.artifacts.write(
                course,
                ArtifactWrite(
                    course_id=course.id,
                    run_id=run_id,
                    node_name="source_snapshot",
                    scope=f"source-{index}:{origin}",
                    round_no=1,
                    input_hash=digest,
                    logical_path=f"workspace/source-snapshots/{digest}.txt",
                    content=content.encode(),
                ),
            )
            snapshots.append({"origin": origin, "sha256": digest, "artifact_id": str(artifact.id)})
        return snapshots
