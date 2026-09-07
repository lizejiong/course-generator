from typing import Any

from pydantic import BaseModel, Field


class CourseCreate(BaseModel):
    slug: str
    definition: dict[str, Any]


class CoursePatch(BaseModel):
    definition: dict[str, Any]


class RunCreate(BaseModel):
    token_limit: int | None = Field(default=None, ge=1)


class ReviewDecision(BaseModel):
    scope: str
    target: str
    action: str
    comment: str | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)
    related_revision: int | None = None


class FileWrite(BaseModel):
    content: str
