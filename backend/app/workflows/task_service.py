from datetime import UTC, datetime
from uuid import uuid4

from app.domain.diagnostics import TaskDiagnosticLog, TaskLogLevel
from app.domain.errors import InvalidTaskTransitionError
from app.domain.task import Task, TaskEvent, TaskKind, TaskPurpose, TaskStatus
from app.repositories.tasks import TasksRepository
from app.workflows.task_state import transition_task


class TaskService:
    def __init__(self, repository: TasksRepository) -> None:
        self.repository = repository

    def create(
        self,
        kind: TaskKind,
        purpose: TaskPurpose = TaskPurpose.MANUAL,
        *,
        subject_id: str | None = None,
        volume_id: str | None = None,
        chapter_id: str | None = None,
        parent_task_id: str | None = None,
        retry_of_task_id: str | None = None,
    ) -> Task:
        now = datetime.now(UTC)
        task = Task(
            id=str(uuid4()),
            project_id=self.repository.project_id,
            kind=kind,
            purpose=purpose,
            status=TaskStatus.PENDING,
            subject_id=subject_id,
            volume_id=volume_id,
            chapter_id=chapter_id,
            parent_task_id=parent_task_id,
            retry_of_task_id=retry_of_task_id,
            created_at=now,
            updated_at=now,
        )
        created = self.repository.create(task, "task.created")
        self.repository.append_log(
            created.id,
            TaskLogLevel.INFO,
            "task",
            "task.created",
            details={"status": created.status.value},
        )
        return created

    def get(self, task_id: str) -> Task:
        return self.repository.get(task_id)

    def events(self, task_id: str, after: int = 0) -> list[TaskEvent]:
        self.get(task_id)
        return self.repository.events(task_id, after)

    def logs(
        self,
        task_id: str,
        *,
        after_id: int = 0,
        limit: int = 100,
        level: TaskLogLevel | None = None,
    ) -> list[TaskDiagnosticLog]:
        self.get(task_id)
        return self.repository.logs(task_id, after_id=after_id, limit=limit, level=level)

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
        task = self.get(task_id)
        if task.status is TaskStatus.RUNNING:
            requested = self.repository.request_cancel(task_id)
            self.repository.append_log(
                task_id,
                TaskLogLevel.WARNING,
                "task",
                "task.cancel_requested",
                details={"status": requested.status.value, "cancel_requested": True},
            )
            return requested
        return self._transition(task_id, TaskStatus.CANCELLED, "task.cancelled")

    def cancellation_requested(self, task_id: str) -> bool:
        return self.get(task_id).cancel_requested_at is not None

    def cancel_requested_task(self, task_id: str) -> Task:
        task = self.get(task_id)
        if task.status is not TaskStatus.RUNNING or task.cancel_requested_at is None:
            raise InvalidTaskTransitionError("running task has no cancellation request")
        return self._transition(task_id, TaskStatus.CANCELLED, "task.cancelled")

    def complete(self, task_id: str) -> Task:
        return self._transition(task_id, TaskStatus.COMPLETED, "task.completed")

    def fail(
        self, task_id: str, error_code: str | None = None, error_message: str | None = None
    ) -> Task:
        if error_code is not None:
            self.repository.record_error(task_id, error_code, error_message or "task failed")
            self.repository.append_log(
                task_id,
                TaskLogLevel.ERROR,
                "task",
                "task.error_recorded",
                details={"error_code": error_code},
            )
        return self._transition(task_id, TaskStatus.FAILED, "task.failed")

    def retry(self, task_id: str) -> Task:
        original = self.get(task_id)
        if original.status not in {
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
            TaskStatus.INTERRUPTED,
        }:
            raise InvalidTaskTransitionError(
                "only failed, cancelled or interrupted tasks can retry"
            )
        return self.create(
            original.kind,
            original.purpose,
            subject_id=original.subject_id,
            volume_id=original.volume_id,
            chapter_id=original.chapter_id,
            parent_task_id=original.parent_task_id or original.id,
            retry_of_task_id=original.id,
        )

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
        updated = self.repository.transition(task_id, current.status, target, event_type)
        level = (
            TaskLogLevel.ERROR
            if target is TaskStatus.FAILED
            else TaskLogLevel.WARNING
            if target in {TaskStatus.CANCELLED, TaskStatus.INTERRUPTED}
            else TaskLogLevel.INFO
        )
        self.repository.append_log(
            task_id,
            level,
            "task",
            "task.status_changed",
            details={"status": target.value},
        )
        return updated
