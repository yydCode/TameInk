from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


def test_import_upload_preserves_original_and_requires_boundary_confirmation(
    tmp_path: Path,
) -> None:
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
        ).json()
        client.post(f"/api/projects/night-01/setting/{created['task']['id']}/approve")
        uploaded = client.post(
            "/api/projects/night-01/imports/source-01?encoding=utf-8",
            content="# 第一章\n\n正文".encode(),
        )
        body = uploaded.json()
        confirmed = client.post(
            "/api/projects/night-01/imports/source-01/boundaries",
            json={
                "source_sha256": body["sha256"],
                "source_size": body["size"],
                "boundaries": body["chapters"],
            },
        )
        task_id = confirmed.json()["task"]["id"]
        formal_before = client.get("/api/projects/night-01/snapshot").json()["stats"]
        approved = client.post(f"/api/projects/night-01/imports/source-01/{task_id}/approve")
        snapshot = client.get("/api/projects/night-01/snapshot").json()

    assert uploaded.status_code == 201
    assert uploaded.json()["chapters"][0]["number"] == 1
    assert confirmed.status_code == 201
    assert formal_before["chapter_count"] == 0
    assert approved.json()["status"] == "completed"
    assert snapshot["stats"]["chapter_count"] == 1
    assert snapshot["unassigned_chapters"][0]["id"] == "0001"
