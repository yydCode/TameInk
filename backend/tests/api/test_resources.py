import io
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from app.repositories.database import DatabaseRepository
from app.repositories.tasks import TasksRepository
from app.repositories.workspace import WorkspaceRepository


def create_confirmed_project(client: TestClient) -> tuple[str, str]:
    created = client.post(
        "/api/projects",
        json={
            "project_id": "resource-book",
            "title": "资源书",
            "genre": "悬疑",
            "target_words": 1000,
            "constraints": "第三人称",
            "setting_draft": "# 城市设定\n\n旧城落雨。",
        },
    ).json()
    baseline = client.get("/api/projects/resource-book/revisions").json()[0]["id"]
    client.post(f"/api/projects/resource-book/setting/{created['task']['id']}/approve")
    current = client.get("/api/projects/resource-book/revisions").json()[0]["id"]
    return baseline, current


def test_document_revision_diff_and_restore_round_trip(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path)) as client:
        baseline, current = create_confirmed_project(client)
        document = client.get(
            "/api/projects/resource-book/documents",
            params={"path": "canon/world/setting.md"},
        )
        diff = client.get(
            "/api/projects/resource-book/revisions/diff",
            params={"base": baseline, "target": current},
        )
        restored = client.post(
            f"/api/projects/resource-book/revisions/{baseline}/restore",
            json={"expected_revision": current},
        )
        snapshot = client.get("/api/projects/resource-book/snapshot").json()

    assert document.json()["content"].startswith("# 城市设定")
    assert diff.json()[0]["path"] == "canon/world/setting.md"
    assert diff.json()[0]["status"] == "added"
    assert "+# 城市设定" in diff.json()[0]["patch"]
    assert restored.status_code == 200
    assert not any(item["kind"] == "setting" for item in snapshot["documents"])


def test_project_zip_excludes_internal_state_and_usage_aggregates_task_events(
    tmp_path: Path,
) -> None:
    application = create_app(tmp_path)
    with TestClient(application) as client:
        create_confirmed_project(client)
        workspace = WorkspaceRepository(tmp_path)
        database = DatabaseRepository(workspace)
        tasks = TasksRepository(database, "resource-book")
        task = tasks.list_all()[0]
        tasks.append_event(
            task.id,
            "agent.stage.completed",
            {
                "agent": "StoryArchitect",
                "input_tokens": 100,
                "output_tokens": 50,
                "total_tokens": 150,
                "total_cost_cny": 0.0123,
            },
        )
        archive = client.get("/api/projects/resource-book/exports/project.zip")
        usage = client.get("/api/projects/resource-book/usage")

    with zipfile.ZipFile(io.BytesIO(archive.content)) as project_zip:
        names = project_zip.namelist()
    assert "project.yaml" in names
    assert "canon/world/setting.md" in names
    assert not any(name.startswith(".tame-ink/") or name.startswith("imports/") for name in names)
    assert usage.json()["request_count"] == 1
    assert usage.json()["total_tokens"] == 150
    assert usage.json()["total_cost_cny"] == 0.0123
