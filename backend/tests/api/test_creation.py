from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


def test_creation_outline_draft_and_approval(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path)) as client:
        created = client.post(
            "/api/projects",
            json={
                "project_id": "night-01",
                "title": "长夜",
                "genre": "悬疑",
                "target_words": 1,
                "constraints": "x",
                "setting_draft": "draft",
            },
        )
        client.post(f"/api/projects/night-01/setting/{created.json()['task']['id']}/approve")
        task = client.post("/api/projects/night-01/design/outline", json={"content": "全书大纲"})
        approved = client.post(f"/api/projects/night-01/design/outline/{task.json()['id']}/approve")

    assert task.status_code == 201
    assert approved.json()["status"] == "completed"
