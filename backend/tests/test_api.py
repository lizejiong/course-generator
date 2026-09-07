from fastapi.testclient import TestClient

from app.main import create_app


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
