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


def test_save_and_restore_task_draft(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path)) as client:
        created = client.post(
            "/api/projects",
            json={
                "project_id": "draft-book",
                "title": "草稿书",
                "genre": "悬疑",
                "target_words": 100000,
                "constraints": "第三人称",
                "setting_draft": "# 初始设定",
            },
        ).json()
        task_id = created["task"]["id"]
        saved = client.put(
            f"/api/projects/draft-book/drafts/{task_id}",
            json={"path": "setting.md", "content": "# 修改后的设定"},
        )
        restored = client.get(
            f"/api/projects/draft-book/drafts/{task_id}", params={"path": "setting.md"}
        )

    assert saved.status_code == 200
    assert restored.json() == {
        "task_id": task_id,
        "path": "setting.md",
        "content": "# 修改后的设定",
    }
