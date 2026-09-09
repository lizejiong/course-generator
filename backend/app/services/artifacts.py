import hashlib
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Artifact, Course


@dataclass(frozen=True)
class ArtifactWrite:
    course_id: UUID
    run_id: UUID | None
    node_name: str
    scope: str
    round_no: int
    input_hash: str
    logical_path: str
    content: bytes

    @property
    def operation_id(self) -> str:
        parts = (
            str(self.run_id or "manual"),
            self.node_name,
            self.scope,
            str(self.round_no),
            self.input_hash,
        )
        return hashlib.sha256("\0".join(parts).encode()).hexdigest()


class ArtifactService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def write(self, course: Course, request: ArtifactWrite) -> Artifact:
        operation_id = request.operation_id
        workspace = Path(course.workspace_path)
        storage = self.storage_path(course, request)
        existing = self.find(request)
        if existing is not None:
            if not Path(existing.storage_path).is_file():
                self._atomic_write(storage, request.content)
            self._refresh_view(workspace / existing.logical_path, Path(existing.storage_path))
            return existing

        if storage.is_file():
            content = storage.read_bytes()
        else:
            content = request.content
            self._atomic_write(storage, content)
        sha256 = hashlib.sha256(content).hexdigest()
        revision = (
            self.session.scalar(
                select(Artifact.revision)
                .where(
                    Artifact.course_id == course.id, Artifact.logical_path == request.logical_path
                )
                .order_by(Artifact.revision.desc())
                .limit(1)
            )
            or 0
        ) + 1
        artifact = Artifact(
            operation_id=operation_id,
            course_id=course.id,
            run_id=request.run_id,
            logical_path=request.logical_path,
            storage_path=str(storage),
            revision=revision,
            sha256=sha256,
            input_hash=request.input_hash,
            producer_node=request.node_name,
        )
        self.session.add(artifact)
        self.session.flush()
        self._refresh_view(workspace / request.logical_path, storage)
        return artifact

    def find(self, request: ArtifactWrite) -> Artifact | None:
        return self.session.scalar(
            select(Artifact).where(Artifact.operation_id == request.operation_id)
        )

    @staticmethod
    def storage_path(course: Course, request: ArtifactWrite) -> Path:
        return (
            Path(course.workspace_path)
            / ".artifacts"
            / (f"{request.operation_id}{Path(request.logical_path).suffix}")
        )

    def recover(self, course: Course, request: ArtifactWrite) -> Artifact | None:
        """Return a prior durable result without ever replacing a missing artifact with input."""
        existing = self.find(request)
        if existing is not None:
            storage = Path(existing.storage_path)
            if not storage.is_file():
                raise RuntimeError(f"持久化产物缺失：{existing.operation_id}")
            self._refresh_view(Path(course.workspace_path) / existing.logical_path, storage)
            return existing
        if self.storage_path(course, request).is_file():
            return self.write(course, request)
        return None

    @staticmethod
    def _atomic_write(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_bytes(content)
        temporary.replace(path)

    def _refresh_view(self, view: Path, storage: Path) -> None:
        self._atomic_write(view, storage.read_bytes())
