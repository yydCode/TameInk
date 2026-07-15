from app.domain.errors import InvalidTaskTransitionError
from app.domain.task import TaskStatus

ALLOWED_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.PENDING: frozenset({TaskStatus.RUNNING, TaskStatus.CANCELLED}),
    TaskStatus.RUNNING: frozenset(
        {
            TaskStatus.AWAITING_APPROVAL,
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
            TaskStatus.INTERRUPTED,
        }
    ),
    TaskStatus.AWAITING_APPROVAL: frozenset({TaskStatus.RUNNING, TaskStatus.CANCELLED}),
    TaskStatus.INTERRUPTED: frozenset(
        {TaskStatus.RUNNING, TaskStatus.CANCELLED, TaskStatus.FAILED}
    ),
    TaskStatus.COMPLETED: frozenset(),
    TaskStatus.FAILED: frozenset(),
    TaskStatus.CANCELLED: frozenset(),
}


def transition_task(current: TaskStatus, target: TaskStatus) -> TaskStatus:
    if target not in ALLOWED_TRANSITIONS[current]:
        raise InvalidTaskTransitionError(f"cannot transition task from {current} to {target}")
    return target
