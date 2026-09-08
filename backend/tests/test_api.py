from uuid import uuid4

from fastapi.testclient import TestClient

from app.db.models import Run
from app.main import create_app
from app.services.courses import CourseService
from app.services.releases import ReleaseService
from app.services.reviews import ReviewService


def test_course_run_and_safe_file_api(settings, db_session) -> None:
    client = TestClient(create_app(settings))
    created = client.post(
        "/api/courses",
        json={
            "slug": "api-course",
            "definition": {
                "title": "API course",
                "audience": "learners",
                "learning_goals": ["test"],
            },
        },
    )
    assert created.status_code == 201
    course_id = created.json()["id"]
    run = client.post(f"/api/courses/{course_id}/runs", json={"token_limit": 500})
    assert run.status_code == 202
    assert run.json()["status"] == "queued"
    saved = client.put(
        f"/api/courses/{course_id}/files",
        params={"path": "workspace/MISSION.md"},
        json={"content": "# Mission"},
    )
    assert saved.json()["revision"] == 1
    rejected = client.get(f"/api/courses/{course_id}/files", params={"path": "../course.json"})
    assert rejected.status_code == 404


def test_course_archive_and_restore_are_non_destructive(settings, db_session) -> None:
    client = TestClient(create_app(settings))
    course = client.post("/api/courses", json={"slug": "archive-course", "definition": {}}).json()
    archived = client.post(f"/api/courses/{course['id']}/archive")
    restored = client.post(f"/api/courses/{course['id']}/restore")
    assert archived.json()["archived"] is True
    assert restored.json()["archived"] is False


def test_release_api_projects_published_state_from_immutable_review_event(
    settings, db_session
) -> None:
    course = CourseService(db_session, settings.courses_root).create("published-course", {})
    lessons = settings.courses_root / "published-course" / "lessons"
    (lessons / "01-intro.md").write_text("# Intro\n\nBody", encoding="utf-8")
    run = Run(
        course_id=course.id,
        thread_id=str(uuid4()),
        current_stage=7,
        status="waiting_human",
    )
    db_session.add(run)
    db_session.flush()
    release = ReleaseService(settings.releases_root).build_rc(course)
    ReviewService(db_session).decide(run, scope="release", target=release.name, action="approve")
    db_session.commit()
    client = TestClient(create_app(settings))
    listing = client.get(f"/api/courses/{course.id}/releases")
    assert listing.json() == [{"version": "r0001", "status": "published"}]
    manifest = client.get(f"/api/courses/{course.id}/releases/r0001").json()
    assert manifest["status"] == "published"
