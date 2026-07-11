import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.repositories.workspace import WorkspaceRepository


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    WorkspaceRepository(tmp_path).create_project("story-01")
    return TestClient(create_app(tmp_path))


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


@pytest.mark.parametrize("value", ["-1", "abc", "1.5"])
def test_sse_rejects_invalid_last_event_id(client: TestClient, value: str) -> None:
    task = create_task(client, "read")
    response = client.get(
        f"/api/projects/story-01/tasks/{task['id']}/events?follow=false",
        headers={"Last-Event-ID": value},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "LAST_EVENT_ID_INVALID"


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
