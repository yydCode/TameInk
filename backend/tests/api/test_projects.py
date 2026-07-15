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


def test_projects_list_returns_saved_projects(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path)) as client:
        for project_id, title in [("book-a", "甲书"), ("book-b", "乙书")]:
            client.post(
                "/api/projects",
                json={
                    "project_id": project_id,
                    "title": title,
                    "genre": "悬疑",
                    "target_words": 1000,
                    "constraints": "第三人称",
                    "setting_draft": "设定",
                },
            )
        projects = client.get("/api/projects")

    assert [project["id"] for project in projects.json()] == ["book-a", "book-b"]


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
        initial = client.get(
            f"/api/projects/draft-book/drafts/{task_id}", params={"path": "setting.md"}
        ).json()
        saved = client.put(
            f"/api/projects/draft-book/drafts/{task_id}",
            json={
                "path": "setting.md",
                "content": "# 修改后的设定",
                "base_revision": initial["revision"],
            },
        )
        restored = client.get(
            f"/api/projects/draft-book/drafts/{task_id}", params={"path": "setting.md"}
        )

    assert saved.status_code == 200
    assert restored.json() == {
        "task_id": task_id,
        "path": "setting.md",
        "content": "# 修改后的设定",
        "revision": initial["revision"],
    }


def test_draft_save_rejects_changed_formal_revision(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path)) as client:
        created = client.post(
            "/api/projects",
            json={
                "project_id": "conflict-book",
                "title": "冲突书",
                "genre": "悬疑",
                "target_words": 1000,
                "constraints": "第三人称",
                "setting_draft": "设定",
            },
        ).json()
        task_id = created["task"]["id"]
        opened = client.get(
            f"/api/projects/conflict-book/drafts/{task_id}", params={"path": "setting.md"}
        ).json()
        client.post(f"/api/projects/conflict-book/setting/{task_id}/approve")
        conflict = client.put(
            f"/api/projects/conflict-book/drafts/{task_id}",
            json={
                "path": "setting.md",
                "content": "过期草稿",
                "base_revision": opened["revision"],
            },
        )

    assert conflict.status_code == 400
    assert conflict.json()["error"]["code"] == "CANON_VERSION_CONFLICT"
