from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.domain.errors import ActiveTaskConflictError, InvalidTaskTransitionError
from app.domain.task import Task, TaskEvent, TaskKind, TaskPurpose, TaskStatus
from app.repositories.database import DatabaseRepository
from app.repositories.tasks import TasksRepository
from app.repositories.workspace import WorkspaceRepository


def repository(tmp_path: Path, project_id: str = "story-01") -> TasksRepository:
    workspace = WorkspaceRepository(tmp_path)
    workspace.create_project(project_id)
    database = DatabaseRepository(workspace)
    database.initialize(project_id)
    return TasksRepository(database, project_id)


def new_task(
    project_id: str = "story-01",
    kind: TaskKind = TaskKind.WRITE,
    purpose: TaskPurpose = TaskPurpose.MANUAL,
) -> Task:
    now = datetime.now(UTC)
    return Task(
        id=str(uuid4()),
        project_id=project_id,
        kind=kind,
        purpose=purpose,
        status=TaskStatus.PENDING,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.parametrize(
    "invalid",
    [
        {"id": "not-a-uuid"},
        {"project_id": ""},
        {"created_at": datetime.now()},
        {"unexpected": "value"},
    ],
)
def test_task_schema_rejects_invalid_or_extra_values(invalid: dict[str, object]) -> None:
    values = new_task().model_dump()
    values.update(invalid)
    with pytest.raises(ValidationError):
        Task.model_validate(values)


def test_event_schema_requires_positive_sequence_and_matching_strict_fields() -> None:
    task = new_task()
    with pytest.raises(ValidationError):
        TaskEvent(
            task_id=task.id,
            project_id=task.project_id,
            sequence=0,
            type="task.created",
            timestamp=datetime.now(UTC),
            data={},
        )


def test_initialize_migrates_schema_and_preserves_rebuild(tmp_path: Path) -> None:
    tasks = repository(tmp_path)
    tasks.database.rebuild("story-01")

    with tasks.database.connect("story-01") as connection:
        version = connection.execute(
            "SELECT value FROM metadata WHERE key = 'schema_version'"
        ).fetchone()[0]
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
            )
        }

    assert version == "5"
    assert {"tasks", "task_events", "content_fts", "commercial_observations"} <= tables


def test_create_persists_task_and_first_event(tmp_path: Path) -> None:
    tasks = repository(tmp_path)
    task = new_task()

    created = tasks.create(task, "task.created")

    assert tasks.get(task.id) == created
    assert [(event.sequence, event.type) for event in tasks.events(task.id)] == [
        (1, "task.created")
    ]


def test_task_metadata_and_lifecycle_timing_are_persisted(tmp_path: Path) -> None:
    tasks = repository(tmp_path)
    task = new_task(purpose=TaskPurpose.CHAPTER).model_copy(
        update={"subject_id": "0001", "volume_id": "1", "chapter_id": "0001"}
    )

    created = tasks.create(task, "task.created")
    running = tasks.transition(created.id, TaskStatus.PENDING, TaskStatus.RUNNING, "task.started")
    completed = tasks.transition(
        running.id, TaskStatus.RUNNING, TaskStatus.COMPLETED, "task.completed"
    )

    assert completed.purpose is TaskPurpose.CHAPTER
    assert (completed.subject_id, completed.volume_id, completed.chapter_id) == (
        "0001",
        "1",
        "0001",
    )
    assert completed.started_at is not None
    assert completed.finished_at is not None
    assert completed.duration_ms is not None and completed.duration_ms >= 0


def test_transition_and_event_append_are_atomic(tmp_path: Path) -> None:
    tasks = repository(tmp_path)
    task = tasks.create(new_task(), "task.created")

    updated = tasks.transition(task.id, TaskStatus.PENDING, TaskStatus.RUNNING, "task.started")

    assert updated.status is TaskStatus.RUNNING
    assert [(event.sequence, event.type) for event in tasks.events(task.id)] == [
        (1, "task.created"),
        (2, "task.started"),
    ]


def test_transition_rejects_stale_expected_status_without_writing_event(tmp_path: Path) -> None:
    tasks = repository(tmp_path)
    task = tasks.create(new_task(kind=TaskKind.READ), "task.created")
    tasks.transition(task.id, TaskStatus.PENDING, TaskStatus.RUNNING, "task.started")

    with pytest.raises(InvalidTaskTransitionError):
        tasks.transition(task.id, TaskStatus.PENDING, TaskStatus.CANCELLED, "task.cancelled")

    assert tasks.get(task.id).status is TaskStatus.RUNNING
    assert [event.type for event in tasks.events(task.id)] == ["task.created", "task.started"]


def test_concurrent_event_appends_allocate_unique_monotonic_sequences(tmp_path: Path) -> None:
    tasks = repository(tmp_path)
    task = tasks.create(new_task(kind=TaskKind.READ), "task.created")

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(
            executor.map(
                lambda index: tasks.append_event(task.id, "task.progress", {"n": index}), range(20)
            )
        )

    assert [event.sequence for event in tasks.events(task.id)] == list(range(1, 22))


def test_database_constraint_allows_only_one_active_write_task_per_project(tmp_path: Path) -> None:
    tasks = repository(tmp_path)
    candidates = [new_task(), new_task()]

    def create(task: Task) -> str:
        try:
            return tasks.create(task, "task.created").id
        except ActiveTaskConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(create, candidates))

    assert outcomes.count("conflict") == 1


def test_interrupted_write_task_releases_mutex_for_explicit_retry(tmp_path: Path) -> None:
    tasks = repository(tmp_path)
    first = tasks.create(new_task(), "task.created")
    tasks.transition(first.id, TaskStatus.PENDING, TaskStatus.RUNNING, "task.started")
    tasks.transition(first.id, TaskStatus.RUNNING, TaskStatus.INTERRUPTED, "task.interrupted")

    assert tasks.create(new_task(), "task.created").status is TaskStatus.PENDING


def test_database_rejects_invalid_status_even_outside_repository(tmp_path: Path) -> None:
    tasks = repository(tmp_path)
    task = tasks.create(new_task(), "task.created")

    with pytest.raises(Exception):
        with tasks.database.connect("story-01") as connection:
            connection.execute("UPDATE tasks SET status = 'unknown' WHERE id = ?", (task.id,))


def test_database_rejects_undeclared_transition_even_outside_repository(tmp_path: Path) -> None:
    tasks = repository(tmp_path)
    task = tasks.create(new_task(kind=TaskKind.READ), "task.created")

    with pytest.raises(Exception):
        with tasks.database.connect("story-01") as connection:
            connection.execute("UPDATE tasks SET status = 'completed' WHERE id = ?", (task.id,))


def test_repository_maps_database_transition_guard_to_domain_error(tmp_path: Path) -> None:
    tasks = repository(tmp_path)
    task = tasks.create(new_task(kind=TaskKind.READ), "task.created")

    with pytest.raises(InvalidTaskTransitionError):
        tasks.transition(task.id, TaskStatus.PENDING, TaskStatus.COMPLETED, "task.completed")
