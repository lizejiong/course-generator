import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import Artifact, Course, ReviewEvent, Run
from app.schemas.api import CourseCreate, CoursePatch, FileWrite, ReviewDecision, RunCreate
from app.services.artifacts import ArtifactService, ArtifactWrite
from app.services.courses import CourseService, validate_course_definition
from app.services.invalidation import InvalidationService
from app.services.jobs import JobService
from app.services.reviews import ReviewService


def build_router(settings: Settings, session_factory) -> APIRouter:
    router = APIRouter(prefix="/api")

    def session() -> Session:
        with session_factory.begin() as db:
            yield db

    def course_or_404(db: Session, course_id: UUID) -> Course:
        course = db.get(Course, course_id)
        if course is None:
            raise HTTPException(status_code=404, detail="course not found")
        return course

    @router.post("/courses", status_code=status.HTTP_201_CREATED)
    def create_course(payload: CourseCreate, db: Session = Depends(session)):
        try:
            validate_course_definition(payload.definition)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        try:
            courses = CourseService(db, settings.courses_root)
            course = courses.create(payload.slug, payload.definition)
            content = json.dumps(payload.definition, ensure_ascii=False, indent=2).encode()
            ArtifactService(db).write(
                course,
                ArtifactWrite(
                    course_id=course.id,
                    run_id=None,
                    node_name="course_create",
                    scope="course.json",
                    round_no=0,
                    input_hash=hashlib.sha256(content).hexdigest(),
                    logical_path="course.json",
                    content=content,
                ),
            )
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return course_view(course, CourseService(db, settings.courses_root).read_definition(course))

    @router.get("/courses")
    def list_courses(db: Session = Depends(session)):
        service = CourseService(db, settings.courses_root)
        return [
            course_view(course, service.read_definition(course))
            for course in db.scalars(select(Course))
        ]

    @router.get("/courses/{course_id}")
    def get_course(course_id: UUID, db: Session = Depends(session)):
        course = course_or_404(db, course_id)
        return course_view(course, CourseService(db, settings.courses_root).read_definition(course))

    @router.patch("/courses/{course_id}")
    def patch_course(course_id: UUID, payload: CoursePatch, db: Session = Depends(session)):
        course = course_or_404(db, course_id)
        try:
            validate_course_definition(payload.definition)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        previous = CourseService(db, settings.courses_root).read_definition(course)
        InvalidationService(db).invalidate(course, "course.json")
        content = json.dumps(payload.definition, ensure_ascii=False, indent=2).encode()
        ArtifactService(db).write(
            course,
            ArtifactWrite(
                course_id=course.id,
                run_id=None,
                node_name="manual_edit",
                scope="course.json",
                round_no=0,
                input_hash=hashlib.sha256(
                    json.dumps(previous, ensure_ascii=False, sort_keys=True).encode()
                    + b"\0"
                    + content
                ).hexdigest(),
                logical_path="course.json",
                content=content,
            ),
        )
        return course_view(course, payload.definition)

    @router.post("/courses/{course_id}/archive")
    def archive_course(course_id: UUID, db: Session = Depends(session)):
        course = course_or_404(db, course_id)
        course.archived_at = datetime.now(UTC)
        return {"id": str(course.id), "archived": True}

    @router.post("/courses/{course_id}/restore")
    def restore_course(course_id: UUID, db: Session = Depends(session)):
        course = course_or_404(db, course_id)
        course.archived_at = None
        return {"id": str(course.id), "archived": False}

    @router.post("/courses/{course_id}/runs", status_code=status.HTTP_202_ACCEPTED)
    def create_run(course_id: UUID, payload: RunCreate, db: Session = Depends(session)):
        course_or_404(db, course_id)
        run = Run(course_id=course_id, thread_id=str(uuid4()), token_limit=payload.token_limit)
        db.add(run)
        db.flush()
        JobService(db).enqueue(run, "start")
        return run_view(run)

    @router.get("/runs/{run_id}")
    def get_run(run_id: UUID, db: Session = Depends(session)):
        run = db.get(Run, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        return run_view(run)

    @router.post("/runs/{run_id}/actions")
    def run_action(run_id: UUID, payload: ReviewDecision, db: Session = Depends(session)):
        run = db.get(Run, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        if payload.action == "pause":
            JobService(db).request_safe_pause(run)
            return run_view(run)
        if payload.action == "stop":
            JobService(db).request_safe_stop(run)
            return run_view(run)
        raise HTTPException(status_code=422, detail="action must be pause or stop")

    @router.get("/runs/{run_id}/review")
    def review_events(run_id: UUID, db: Session = Depends(session)):
        if db.get(Run, run_id) is None:
            raise HTTPException(status_code=404, detail="run not found")
        return [review_view(event) for event in ReviewService(db).events(run_id)]

    @router.post("/runs/{run_id}/review", status_code=status.HTTP_202_ACCEPTED)
    def review_run(run_id: UUID, payload: ReviewDecision, db: Session = Depends(session)):
        run = db.get(Run, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        try:
            event = ReviewService(db).decide(run, **payload.model_dump())
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return review_view(event)

    @router.get("/courses/{course_id}/artifacts")
    def list_artifacts(course_id: UUID, db: Session = Depends(session)):
        course_or_404(db, course_id)
        return [
            artifact_view(item)
            for item in db.scalars(select(Artifact).where(Artifact.course_id == course_id))
        ]

    @router.get("/courses/{course_id}/files")
    def get_file(course_id: UUID, path: str, db: Session = Depends(session)):
        course = course_or_404(db, course_id)
        try:
            target = CourseService(db, settings.courses_root).editable_path(course, path)
            return {"path": path, "content": target.read_text(encoding="utf-8")}
        except (ValueError, FileNotFoundError) as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @router.put("/courses/{course_id}/files")
    def put_file(course_id: UUID, path: str, payload: FileWrite, db: Session = Depends(session)):
        course = course_or_404(db, course_id)
        try:
            target = CourseService(db, settings.courses_root).editable_path(course, path)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        previous = target.read_bytes() if target.exists() else b""
        content = payload.content.encode("utf-8")
        InvalidationService(db).invalidate(course, path)
        artifact = ArtifactService(db).write(
            course,
            ArtifactWrite(
                course_id=course.id,
                run_id=None,
                node_name="manual_edit",
                scope=path,
                round_no=0,
                input_hash=hashlib.sha256(previous + b"\0" + content).hexdigest(),
                logical_path=path,
                content=content,
            ),
        )
        return {"path": path, "saved": True, "revision": artifact.revision}

    @router.get("/courses/{course_id}/releases")
    def list_releases(course_id: UUID, db: Session = Depends(session)):
        course = course_or_404(db, course_id)
        root = settings.releases_root / course.slug
        if not root.exists():
            return []
        published = set(
            db.scalars(
                select(ReviewEvent.target).where(
                    ReviewEvent.action == "approve",
                    ReviewEvent.scope == "release",
                    ReviewEvent.run_id.in_(select(Run.id).where(Run.course_id == course_id)),
                )
            )
        )
        return [
            {"version": item.name, "status": "published" if item.name in published else "rc"}
            for item in sorted(root.glob("r[0-9][0-9][0-9][0-9]"))
        ]

    @router.get("/courses/{course_id}/releases/{version}")
    def get_release(course_id: UUID, version: str, db: Session = Depends(session)):
        course = course_or_404(db, course_id)
        manifest = settings.releases_root / course.slug / version / "release.json"
        if not manifest.is_file():
            raise HTTPException(status_code=404, detail="release not found")
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        published = db.scalar(
            select(ReviewEvent.id).where(
                ReviewEvent.action == "approve",
                ReviewEvent.scope == "release",
                ReviewEvent.target == version,
                ReviewEvent.run_id.in_(select(Run.id).where(Run.course_id == course_id)),
            )
        )
        payload["status"] = "published" if published else "rc"
        return Response(json.dumps(payload), media_type="application/json")

    return router


def course_view(course: Course, definition: dict) -> dict:
    return {
        "id": str(course.id),
        "slug": course.slug,
        "archived_at": course.archived_at,
        "definition": definition,
    }


def run_view(run: Run) -> dict:
    return {
        "id": str(run.id),
        "status": run.status,
        "stage": run.current_stage,
        "thread_id": run.thread_id,
        "node_summary": run.node_summary,
        "token_limit": run.token_limit,
        "token_usage": run.token_usage,
        "token_ledger": run.token_ledger,
        "pause_requested": run.pause_requested,
        "stop_requested": run.stop_requested,
        "error_code": run.error_code,
        "error_summary": run.error_summary,
        "updated_at": run.updated_at,
    }


def artifact_view(artifact: Artifact) -> dict:
    return {
        "id": str(artifact.id),
        "operation_id": artifact.operation_id,
        "path": artifact.logical_path,
        "revision": artifact.revision,
        "sha256": artifact.sha256,
        "valid": artifact.is_valid,
    }


def review_view(event) -> dict:
    return {
        "id": str(event.id),
        "scope": event.scope,
        "target": event.target,
        "action": event.action,
        "comment": event.comment,
        "evidence": event.evidence,
        "created_at": event.created_at,
    }
