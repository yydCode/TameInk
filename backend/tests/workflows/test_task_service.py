from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from app.domain.errors import InvalidTaskTransitionError
from app.domain.task import TaskKind, TaskStatus
from app.repositories.database import DatabaseRepository
from app.repositories.tasks import TasksRepository
from app.repositories.workspace import WorkspaceRepository
from app.workflows.task_service import TaskService


def service(tmp_path: Path, project_id: str = "story-01") -> TaskService:
    workspace = WorkspaceRepository(tmp_path)
    workspace.create_project(project_id)
    database = DatabaseRepository(workspace)
    database.initialize(project_id)
    return TaskService(TasksRepository(database, project_id))


def test_full_approval_flow_persists_each_transition_event(tmp_path: Path) -> None:
    tasks = service(tmp_path)
    task = tasks.create(TaskKind.WRITE)
    tasks.start(task.id)
    tasks.await_approval(task.id)
    tasks.approve(task.id)
    completed = tasks.complete(task.id)

    assert completed.status is TaskStatus.COMPLETED
    assert [event.type for event in tasks.events(task.id)] == [
        "task.created",
        "task.started",
        "task.awaiting_approval",
        "task.approved",
        "task.completed",
    ]


def test_approve_requires_awaiting_approval(tmp_path: Path) -> None:
    tasks = service(tmp_path)
    task = tasks.create(TaskKind.READ)
    tasks.start(task.id)

    with pytest.raises(InvalidTaskTransitionError):
        tasks.approve(task.id)


def test_reject_cancels_only_at_approval_gate(tmp_path: Path) -> None:
    tasks = service(tmp_path)
    task = tasks.create(TaskKind.WRITE)
    tasks.start(task.id)
    tasks.await_approval(task.id)

    rejected = tasks.reject(task.id)

    assert rejected.status is TaskStatus.CANCELLED
    assert tasks.events(task.id)[-1].type == "task.rejected"


def test_terminal_task_cannot_be_cancelled(tmp_path: Path) -> None:
    tasks = service(tmp_path)
    task = tasks.create(TaskKind.READ)
    tasks.start(task.id)
    tasks.complete(task.id)

    with pytest.raises(InvalidTaskTransitionError):
        tasks.cancel(task.id)


def test_cancel_releases_write_task_mutex(tmp_path: Path) -> None:
    tasks = service(tmp_path)
    first = tasks.create(TaskKind.WRITE)
    tasks.cancel(first.id)

    assert tasks.create(TaskKind.WRITE).status is TaskStatus.PENDING


def test_different_projects_are_independent(tmp_path: Path) -> None:
    first = service(tmp_path, "story-01")
    second = service(tmp_path, "story-02")

    assert first.create(TaskKind.WRITE).project_id == "story-01"
    assert second.create(TaskKind.WRITE).project_id == "story-02"


def test_startup_recovery_interrupts_only_running_tasks_and_is_idempotent(tmp_path: Path) -> None:
    tasks = service(tmp_path)
    running = tasks.create(TaskKind.READ)
    tasks.start(running.id)
    pending = tasks.create(TaskKind.READ)
    approval = tasks.create(TaskKind.READ)
    tasks.start(approval.id)
    tasks.await_approval(approval.id)

    assert tasks.recover_interrupted() == 1
    assert tasks.recover_interrupted() == 0

    assert tasks.get(running.id).status is TaskStatus.INTERRUPTED
    assert tasks.get(pending.id).status is TaskStatus.PENDING
    assert tasks.get(approval.id).status is TaskStatus.AWAITING_APPROVAL
    assert [event.type for event in tasks.events(running.id)].count("task.recovered") == 1


def test_concurrent_recovery_counts_only_its_own_transition_and_writes_one_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = service(tmp_path)
    running = first.create(TaskKind.READ)
    first.start(running.id)
    second = TaskService(TasksRepository(first.repository.database, "story-01"))
    barrier = Barrier(2)
    real_list = TasksRepository.list_by_status

    def synchronized_list(repository: TasksRepository, status: TaskStatus) -> list[object]:
        result = real_list(repository, status)
        barrier.wait()
        return result

    monkeypatch.setattr(TasksRepository, "list_by_status", synchronized_list)

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda item: item.recover_interrupted(), [first, second]))

    assert sorted(outcomes) == [0, 1]
    assert first.get(running.id).status is TaskStatus.INTERRUPTED
    assert [event.type for event in first.events(running.id)].count("task.recovered") == 1


def test_recovery_does_not_swallow_cas_miss_to_an_unexpected_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tasks = service(tmp_path)
    running = tasks.create(TaskKind.READ)
    tasks.start(running.id)
    real_transition = tasks.repository.transition

    def cancelled_by_other_writer(*_args: object, **_kwargs: object) -> object:
        real_transition(
            running.id,
            TaskStatus.RUNNING,
            TaskStatus.CANCELLED,
            "task.cancelled",
        )
        raise InvalidTaskTransitionError("task status changed concurrently")

    monkeypatch.setattr(tasks.repository, "transition", cancelled_by_other_writer)

    with pytest.raises(InvalidTaskTransitionError):
        tasks.recover_interrupted()
