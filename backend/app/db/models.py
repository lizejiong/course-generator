import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Timestamped:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Course(Timestamped, Base):
    __tablename__ = "courses"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    workspace_path: Mapped[str] = mapped_column(Text, unique=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    runs: Mapped[list["Run"]] = relationship(back_populates="course")


class Run(Timestamped, Base):
    __tablename__ = "runs"
    __table_args__ = (
        CheckConstraint(
            "status IN "
            "('queued','running','waiting_human','paused','failed','completed','stopped')",
            name="run_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id", ondelete="RESTRICT"))
    status: Mapped[str] = mapped_column(String(24), default="queued")
    current_stage: Mapped[int] = mapped_column(Integer, default=1)
    node_summary: Mapped[str | None] = mapped_column(Text)
    thread_id: Mapped[str] = mapped_column(String(128), unique=True)
    token_limit: Mapped[int | None] = mapped_column(Integer)
    token_usage: Mapped[int] = mapped_column(Integer, default=0)
    token_ledger: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    pause_requested: Mapped[bool] = mapped_column(default=False)
    stop_requested: Mapped[bool] = mapped_column(default=False)
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_summary: Mapped[str | None] = mapped_column(Text)

    course: Mapped[Course] = relationship(back_populates="runs")
    jobs: Mapped[list["Job"]] = relationship(back_populates="run")


class Job(Timestamped, Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','running','succeeded','failed','cancelled')", name="job_status"
        ),
        Index(
            "one_active_job_per_run",
            "run_id",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    job_type: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="queued")
    input_event_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("review_events.id"))
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_owner: Mapped[str | None] = mapped_column(String(128))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_summary: Mapped[str | None] = mapped_column(Text)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    run: Mapped[Run] = relationship(back_populates="jobs")


class Artifact(Timestamped, Base):
    __tablename__ = "artifacts"
    __table_args__ = (UniqueConstraint("operation_id", name="artifact_operation_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    operation_id: Mapped[str] = mapped_column(String(64))
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id", ondelete="RESTRICT"))
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("runs.id", ondelete="SET NULL"))
    logical_path: Mapped[str] = mapped_column(Text)
    storage_path: Mapped[str] = mapped_column(Text, unique=True)
    revision: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    input_hash: Mapped[str] = mapped_column(String(64))
    producer_node: Mapped[str] = mapped_column(String(100))
    is_valid: Mapped[bool] = mapped_column(default=True)


class ReviewEvent(Base):
    __tablename__ = "review_events"
    __table_args__ = (
        CheckConstraint(
            "action IN ('approve','rework','stop','acknowledge')", name="review_action"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    scope: Mapped[str] = mapped_column(String(32))
    target: Mapped[str] = mapped_column(Text)
    action: Mapped[str] = mapped_column(String(16))
    comment: Mapped[str | None] = mapped_column(Text)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    related_revision: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
