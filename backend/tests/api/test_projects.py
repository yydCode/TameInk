from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


def test_projects_create_and_read(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path)) as client:
        created = client.post(
            "/api/projects",
            json={
                "project_id": "night-01",
                "title": "长夜",
                "genre": "悬疑",
                "target_words": 200000,
                "constraints": "第一人称",
                "setting_draft": "设定候选",
            },
        )
        fetched = client.get("/api/projects/night-01")

    assert created.status_code == 201
    assert created.json()["project"]["title"] == "长夜"
    assert fetched.json()["id"] == "night-01"
