from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


def test_import_upload_preserves_original_and_requires_boundary_confirmation(
    tmp_path: Path,
) -> None:
    with TestClient(create_app(tmp_path)) as client:
        client.post(
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

    assert uploaded.status_code == 201
    assert uploaded.json()["chapters"][0]["number"] == 1
    assert confirmed.status_code == 201
