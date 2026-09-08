from uuid import uuid4

from fastapi.testclient import TestClient

from app.db.models import Run
from app.main import create_app
from app.services.courses import CourseService
from app.services.releases import ReleaseService
from app.services.reviews import ReviewService


def definition(title: str = "API course") -> dict:
    return {
        "title": title,
        "audience": "learners",
        "learning_goals": ["one", "two", "three"],
        "content_scope": "a bounded topic",
        "expected_chapter_count": 1,
        "min_effective_chars_per_chapter": 100,
        "source_policy": "internal_only",
    }


def test_course_run_and_safe_file_api(settings, db_session) -> None:
    client = TestClient(create_app(settings))
    created = client.post(
        "/api/courses",
        json={
            "slug": "api-course",
            "definition": definition(),
        },
    )
    assert created.status_code == 201
    course_id = created.json()["id"]
    initial_artifacts = client.get(f"/api/courses/{course_id}/artifacts").json()
    assert initial_artifacts[0]["path"] == "course.json"
    patched = client.patch(
        f"/api/courses/{course_id}",
        json={"definition": definition("Updated")},
    )
    assert patched.status_code == 200
    revisions = client.get(f"/api/courses/{course_id}/artifacts").json()
    assert [item["revision"] for item in revisions if item["path"] == "course.json"] == [1, 2]
    run = client.post(f"/api/courses/{course_id}/runs", json={"token_limit": 500})
    assert run.status_code == 202
    assert run.json()["status"] == "queued"
    assert run.json()["token_limit"] == 500
    projection = client.get(f"/api/runs/{run.json()['id']}").json()
    assert {
        "node_summary",
        "token_usage",
        "token_ledger",
        "pause_requested",
        "stop_requested",
        "error_code",
        "error_summary",
    } <= projection.keys()
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
    invalid = client.post("/api/courses", json={"slug": "invalid-course", "definition": {}})
    assert invalid.status_code == 422
    course = client.post(
        "/api/courses", json={"slug": "archive-course", "definition": definition("Archive")}
    ).json()
    archived = client.post(f"/api/courses/{course['id']}/archive")
    restored = client.post(f"/api/courses/{course['id']}/restore")
    assert archived.json()["archived"] is True
    assert restored.json()["archived"] is False


def test_course_create_rejects_unknown_source_policy(settings, db_session) -> None:
    client = TestClient(create_app(settings))
    payload = definition()
    payload["source_policy"] = "anything_goes"
    response = client.post("/api/courses", json={"slug": "bad-policy", "definition": payload})
    assert response.status_code == 422
    assert "来源政策" in response.json()["detail"]


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
