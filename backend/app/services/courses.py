import json
import re
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Course

_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_EDITABLE = re.compile(
    r"^(course\.json|workspace/(MISSION|SPEC|BLUEPRINT|RESOURCES)\.md|"
    r"workspace/batches/[a-zA-Z0-9_-]+\.json|lessons/[0-9]{2,3}-[a-z0-9-]+\.md)$"
)


class CourseService:
    def __init__(self, session: Session, courses_root: Path) -> None:
        self.session = session
        self.courses_root = courses_root.resolve()

    def create(self, slug: str, definition: dict) -> Course:
        if not _SLUG.fullmatch(slug):
            raise ValueError("slug must contain lowercase letters, numbers, and single hyphens")
        path = self.courses_root / slug
        if self.session.scalar(select(Course).where(Course.slug == slug)) or path.exists():
            raise ValueError("course slug already exists")
        (path / "workspace" / "batches").mkdir(parents=True)
        (path / "workspace" / "context-packs").mkdir(parents=True)
        (path / "lessons").mkdir()
        (path / ".artifacts").mkdir()
        self._atomic_write(
            path / "course.json", json.dumps(definition, ensure_ascii=False, indent=2).encode()
        )
        course = Course(slug=slug, workspace_path=str(path))
        self.session.add(course)
        self.session.flush()
        return course

    def get(self, course_id: UUID) -> Course:
        course = self.session.get(Course, course_id)
        if course is None:
            raise LookupError("course not found")
        return course

    def course_path(self, course: Course) -> Path:
        path = Path(course.workspace_path).resolve()
        if self.courses_root not in path.parents:
            raise ValueError("course workspace escaped configured root")
        return path

    def read_definition(self, course: Course) -> dict:
        return json.loads((self.course_path(course) / "course.json").read_text(encoding="utf-8"))

    def update_definition(self, course: Course, definition: dict) -> None:
        self._atomic_write(
            self.course_path(course) / "course.json",
            json.dumps(definition, ensure_ascii=False, indent=2).encode(),
        )

    def editable_path(self, course: Course, logical_path: str) -> Path:
        if not _EDITABLE.fullmatch(logical_path):
            raise ValueError("path is not an editable course Markdown/JSON view")
        target = (self.course_path(course) / logical_path).resolve()
        if self.course_path(course) not in target.parents:
            raise ValueError("path traversal is forbidden")
        return target

    @staticmethod
    def _atomic_write(path: Path, content: bytes) -> None:
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_bytes(content)
        temporary.replace(path)
