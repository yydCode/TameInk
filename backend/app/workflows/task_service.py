from datetime import UTC, datetime
from uuid import uuid4

from app.domain.errors import InvalidTaskTransitionError
from app.domain.task import Task, TaskEvent, TaskKind, TaskStatus
from app.repositories.tasks import TasksRepository
from app.workflows.task_state import transition_task


class TaskService:
    def __init__(self, repository: TasksRepository) -> None:
        self.repository = repository

    def create(self, kind: TaskKind) -> Task:
        now = datetime.now(UTC)
        task = Task(
            id=str(uuid4()),
            project_id=self.repository.project_id,
            kind=kind,
            status=TaskStatus.PENDING,
            created_at=now,
            updated_at=now,
        )
        return self.repository.create(task, "task.created")

    def get(self, task_id: str) -> Task:
        return self.repository.get(task_id)

    def events(self, task_id: str, after: int = 0) -> list[TaskEvent]:
        self.get(task_id)
        return self.repository.events(task_id, after)

    def start(self, task_id: str) -> Task:
        return self._transition(task_id, TaskStatus.RUNNING, "task.started")

    def await_approval(self, task_id: str) -> Task:
        return self._transition(task_id, TaskStatus.AWAITING_APPROVAL, "task.awaiting_approval")

    def approve(self, task_id: str) -> Task:
        task = self.get(task_id)
        if task.status is not TaskStatus.AWAITING_APPROVAL:
            raise InvalidTaskTransitionError("task is not awaiting approval")
        return self._transition(task_id, TaskStatus.RUNNING, "task.approved")

    def reject(self, task_id: str) -> Task:
        task = self.get(task_id)
        if task.status is not TaskStatus.AWAITING_APPROVAL:
            raise InvalidTaskTransitionError("task is not awaiting approval")
        return self._transition(task_id, TaskStatus.CANCELLED, "task.rejected")

    def cancel(self, task_id: str) -> Task:
        return self._transition(task_id, TaskStatus.CANCELLED, "task.cancelled")

    def complete(self, task_id: str) -> Task:
        return self._transition(task_id, TaskStatus.COMPLETED, "task.completed")

    def fail(self, task_id: str) -> Task:
        return self._transition(task_id, TaskStatus.FAILED, "task.failed")

    def recover_interrupted(self) -> int:
        running = self.repository.list_by_status(TaskStatus.RUNNING)
        recovered = 0
        for task in running:
            try:
                self._transition(task.id, TaskStatus.INTERRUPTED, "task.recovered")
                recovered += 1
            except InvalidTaskTransitionError:
                if self.get(task.id).status is not TaskStatus.INTERRUPTED:
                    raise
        return recovered

    def _transition(self, task_id: str, target: TaskStatus, event_type: str) -> Task:
        current = self.get(task_id)
        transition_task(current.status, target)
        return self.repository.transition(task_id, current.status, target, event_type)
