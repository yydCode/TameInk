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


def test_workflow_status_only_reports_confirmed_content(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path)) as client:
        created = client.post(
            "/api/projects",
            json={
                "project_id": "guided-book",
                "title": "引导书",
                "genre": "悬疑",
                "target_words": 1000,
                "constraints": "第三人称",
                "setting_draft": "设定草稿",
            },
        ).json()
        task_id = created["task"]["id"]

        before = client.get("/api/projects/guided-book/workflow-status")
        client.post(f"/api/projects/guided-book/setting/{task_id}/approve")
        after_setting = client.get("/api/projects/guided-book/workflow-status")

    assert before.json() == {
        "setting_confirmed": False,
        "outline_confirmed": False,
        "volume_one_confirmed": False,
        "commercial_confirmed": False,
    }
    assert after_setting.json() == {
        "setting_confirmed": True,
        "outline_confirmed": False,
        "volume_one_confirmed": False,
        "commercial_confirmed": False,
    }


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


def test_project_snapshot_reports_real_documents_tree_and_stats(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path)) as client:
        created = client.post(
            "/api/projects",
            json={
                "project_id": "snapshot-book",
                "title": "快照书",
                "genre": "悬疑",
                "target_words": 1000,
                "constraints": "第三人称",
                "setting_draft": "# 城市设定\n\n雨夜。",
            },
        ).json()
        client.post(f"/api/projects/snapshot-book/setting/{created['task']['id']}/approve")
        outline = client.post(
            "/api/projects/snapshot-book/design/outline", json={"content": "# 主线大纲"}
        ).json()
        client.post(f"/api/projects/snapshot-book/design/outline/{outline['id']}/approve")
        volume = client.post(
            "/api/projects/snapshot-book/design/volumes/2",
            json={"content": "# 第二卷"},
        ).json()
        client.post(f"/api/projects/snapshot-book/design/volumes/2/{volume['id']}/approve")
        chapter = client.post(
            "/api/projects/snapshot-book/design/chapters/0007",
            json={"plan": "计划", "draft": "# 雨夜\n\n长街落雨。", "issues": [], "volume_id": "2"},
        ).json()
        client.post(f"/api/projects/snapshot-book/design/chapters/0007/{chapter['id']}/approve")
        snapshot = client.get("/api/projects/snapshot-book/snapshot")

    assert snapshot.status_code == 200
    payload = snapshot.json()
    assert payload["stats"] == {
        "total_words": 6,
        "chapter_count": 1,
        "volume_count": 1,
        "active_foreshadow_count": 0,
    }
    assert payload["volumes"][0]["id"] == "2"
    assert payload["volumes"][0]["chapters"][0]["id"] == "0007"
    assert payload["unassigned_chapters"] == []
    assert {document["kind"] for document in payload["documents"]} == {
        "setting",
        "outline",
        "volume",
        "chapter",
    }


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
