import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.domain.task import TaskKind
from app.main import create_app
from app.repositories.database import DatabaseRepository
from app.repositories.drafts import DraftRepository
from app.repositories.tasks import TasksRepository
from app.repositories.workspace import WorkspaceRepository
from app.workflows.task_service import TaskService


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    WorkspaceRepository(tmp_path).create_project("story-01")
    with TestClient(create_app(tmp_path)) as test_client:
        yield test_client


def create_task(client: TestClient, kind: str = "write") -> dict[str, object]:
    response = client.post("/api/projects/story-01/tasks", json={"kind": kind})
    assert response.status_code == 201
    return response.json()


def parse_sse(body: str) -> list[dict[str, object]]:
    messages = []
    for block in body.strip().split("\n\n") if body.strip() else []:
        fields = dict(line.split(": ", 1) for line in block.splitlines())
        messages.append(
            {"id": int(fields["id"]), "event": fields["event"], "data": json.loads(fields["data"])}
        )
    return messages


def test_task_endpoints_create_read_and_transition(client: TestClient) -> None:
    task = create_task(client)
    task_id = task["id"]

    assert client.get(f"/api/projects/story-01/tasks/{task_id}").json()["status"] == "pending"
    assert (
        client.post(f"/api/projects/story-01/tasks/{task_id}/start").json()["status"] == "running"
    )
    assert (
        client.post(f"/api/projects/story-01/tasks/{task_id}/await-approval").json()["status"]
        == "awaiting_approval"
    )
    assert (
        client.post(f"/api/projects/story-01/tasks/{task_id}/approve").json()["status"] == "running"
    )
    assert (
        client.post(f"/api/projects/story-01/tasks/{task_id}/complete").json()["status"]
        == "completed"
    )
    listed = client.get("/api/projects/story-01/tasks").json()
    assert [item["id"] for item in listed] == [task_id]
    history = client.get(f"/api/projects/story-01/tasks/{task_id}/history").json()
    assert [event["type"] for event in history] == [
        "task.created",
        "task.started",
        "task.awaiting_approval",
        "task.approved",
        "task.completed",
    ]


def test_task_run_returns_only_validated_agent_trace_fields(client: TestClient) -> None:
    task = create_task(client, "read")
    task_id = str(task["id"])
    trace = {
        "agent": "ChapterPlanner",
        "skill": "webnovel-chapter-planning",
        "skill_sha256": "a" * 64,
        "stage": "chapter-planning",
        "source_paths": ["canon/outline.md", "memory/summaries/book.md"],
        "queries": ["主角 能力"],
        "total_characters": 2048,
        "duration_ms": 321,
        "status": "success",
        "error_code": None,
    }
    DraftRepository(client.app.state.workspace).write(
        "story-01",
        task_id,
        "run.json",
        json.dumps(
            {
                "project_id": "story-01",
                "prompt": "不得通过 API 暴露的正文",
                "api_key": "不得通过 API 暴露的密钥",
                "agent_runs": [trace],
            }
        ),
    )

    response = client.get(f"/api/projects/story-01/tasks/{task_id}/run")

    assert response.status_code == 200
    assert response.json() == {"agent_runs": [trace]}
    assert "正文" not in response.text
    assert "密钥" not in response.text


def test_task_run_is_empty_without_manifest_and_rejects_invalid_trace(
    client: TestClient,
) -> None:
    task = create_task(client, "read")
    task_id = str(task["id"])
    endpoint = f"/api/projects/story-01/tasks/{task_id}/run"

    assert client.get(endpoint).json() == {"agent_runs": []}

    DraftRepository(client.app.state.workspace).write(
        "story-01",
        task_id,
        "run.json",
        json.dumps({"agent_runs": [{"prompt": "invalid"}]}),
    )
    response = client.get(endpoint)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "WORKFLOW_GATE_BLOCKED"
    assert "invalid" not in response.text


def test_api_maps_domain_errors_without_sqlite_details(client: TestClient) -> None:
    first = create_task(client)
    conflict = client.post("/api/projects/story-01/tasks", json={"kind": "write"})
    invalid = client.post(f"/api/projects/story-01/tasks/{first['id']}/approve")
    missing = client.get("/api/projects/story-01/tasks/00000000-0000-4000-8000-000000000000")

    assert (conflict.status_code, conflict.json()) == (
        409,
        {"error": {"code": "ACTIVE_TASK_CONFLICT", "message": "active write task exists"}},
    )
    assert invalid.status_code == 409
    assert invalid.json()["error"]["code"] == "TASK_TRANSITION_INVALID"
    assert missing.status_code == 404
    assert "sqlite" not in conflict.text.lower()


def test_sse_replays_only_events_after_last_event_id_header(client: TestClient) -> None:
    task = create_task(client, "read")
    task_id = task["id"]
    client.post(f"/api/projects/story-01/tasks/{task_id}/start")
    client.post(f"/api/projects/story-01/tasks/{task_id}/cancel")

    response = client.get(
        f"/api/projects/story-01/tasks/{task_id}/events?follow=false",
        headers={"Last-Event-ID": "1"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert [(item["id"], item["event"]) for item in parse_sse(response.text)] == [
        (2, "task.started"),
        (3, "task.cancelled"),
    ]
    assert client.get(f"/api/projects/story-01/tasks/{task_id}").json()["status"] == "cancelled"


@pytest.mark.parametrize("value", ["+1", " 1 ", "01", "", "-1", "abc", "1.5"])
def test_sse_rejects_invalid_last_event_id(client: TestClient, value: str) -> None:
    task = create_task(client, "read")
    response = client.get(
        f"/api/projects/story-01/tasks/{task['id']}/events?follow=false",
        headers={"Last-Event-ID": value},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "LAST_EVENT_ID_INVALID"


@pytest.mark.parametrize("value", [None, "0", "1"])
def test_sse_accepts_canonical_last_event_id(client: TestClient, value: str | None) -> None:
    task = create_task(client, "read")
    headers = {} if value is None else {"Last-Event-ID": value}

    response = client.get(
        f"/api/projects/story-01/tasks/{task['id']}/events?follow=false",
        headers=headers,
    )

    assert response.status_code == 200


def test_sse_rejects_last_event_id_beyond_current_sequence(client: TestClient) -> None:
    task = create_task(client, "read")
    response = client.get(
        f"/api/projects/story-01/tasks/{task['id']}/events?follow=false",
        headers={"Last-Event-ID": "2"},
    )

    assert response.status_code == 416
    assert response.json()["error"]["code"] == "LAST_EVENT_ID_OUT_OF_RANGE"


def test_sse_with_current_id_returns_an_empty_backlog(client: TestClient) -> None:
    task = create_task(client, "read")
    response = client.get(
        f"/api/projects/story-01/tasks/{task['id']}/events?follow=false",
        headers={"Last-Event-ID": "1"},
    )

    assert response.status_code == 200
    assert response.text == ""


def test_lifespan_initializes_once_and_get_dependencies_do_not_write_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = WorkspaceRepository(tmp_path)
    workspace.create_project("story-01")
    database = DatabaseRepository(workspace)
    database.initialize("story-01")
    task = TaskService(TasksRepository(database, "story-01")).create(TaskKind.READ)
    calls: list[str] = []
    real_initialize = DatabaseRepository.initialize

    def record_initialize(self: DatabaseRepository, project_id: str) -> None:
        calls.append(project_id)
        real_initialize(self, project_id)

    monkeypatch.setattr(DatabaseRepository, "initialize", record_initialize)

    with TestClient(create_app(tmp_path)) as lifespan_client:
        for _ in range(2):
            assert lifespan_client.get(f"/api/projects/story-01/tasks/{task.id}").status_code == 200
            assert (
                lifespan_client.get(
                    f"/api/projects/story-01/tasks/{task.id}/events?follow=false"
                ).status_code
                == 200
            )

    assert calls == ["story-01"]


def test_lifespan_surfaces_initialization_failure_before_serving_requests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    WorkspaceRepository(tmp_path).create_project("story-01")
    monkeypatch.setattr(
        DatabaseRepository,
        "initialize",
        lambda _self, _project_id: (_ for _ in ()).throw(RuntimeError("migration failed")),
    )

    with pytest.raises(RuntimeError, match="migration failed"):
        with TestClient(create_app(tmp_path)):
            pass
