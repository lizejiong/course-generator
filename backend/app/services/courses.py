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
SOURCE_POLICIES = frozenset(
    {"user_plus_official", "internal_only", "official_only", "extended_cross_checked"}
)


def validate_course_definition(definition: dict) -> None:
    required = (
        "title",
        "audience",
        "learning_goals",
        "content_scope",
        "expected_chapter_count",
        "min_effective_chars_per_chapter",
        "source_policy",
    )
    missing = [field for field in required if definition.get(field) in (None, "", [])]
    if missing:
        raise ValueError(f"课程必填字段缺失：{', '.join(missing)}")
    if (
        not isinstance(definition["learning_goals"], list)
        or not 3 <= len(definition["learning_goals"]) <= 7
    ):
        raise ValueError("学习目标必须包含 3 至 7 条可观察目标")
    if int(definition["expected_chapter_count"]) < 1:
        raise ValueError("期望章节数必须为正整数")
    if int(definition["min_effective_chars_per_chapter"]) < 1:
        raise ValueError("单章有效字符下限必须为正整数")
    if definition["source_policy"] not in SOURCE_POLICIES:
        raise ValueError(
            "来源政策必须是以下之一：user_plus_official、internal_only、official_only、"
            "extended_cross_checked"
        )


class CourseService:
    def __init__(self, session: Session, courses_root: Path) -> None:
        self.session = session
        self.courses_root = courses_root.resolve()

    def create(self, slug: str, definition: dict) -> Course:
        if not _SLUG.fullmatch(slug):
            raise ValueError("课程 slug 只能包含小写字母、数字和单个连字符")
        path = self.courses_root / slug
        if self.session.scalar(select(Course).where(Course.slug == slug)) or path.exists():
            raise ValueError("课程 slug 已存在")
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
            raise LookupError("课程不存在")
        return course

    def course_path(self, course: Course) -> Path:
        path = Path(course.workspace_path).resolve()
        if self.courses_root not in path.parents:
            raise ValueError("课程工作区越出了配置的根目录")
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
            raise ValueError("该路径不是可编辑的课程 Markdown/JSON 视图")
        target = (self.course_path(course) / logical_path).resolve()
        if self.course_path(course) not in target.parents:
            raise ValueError("禁止路径穿越")
        return target

    @staticmethod
    def _atomic_write(path: Path, content: bytes) -> None:
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_bytes(content)
        temporary.replace(path)
