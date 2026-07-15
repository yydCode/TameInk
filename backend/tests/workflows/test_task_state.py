import pytest

from app.domain.errors import InvalidTaskTransitionError
from app.domain.task import TaskStatus
from app.workflows.task_state import transition_task


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (TaskStatus.PENDING, TaskStatus.RUNNING),
        (TaskStatus.PENDING, TaskStatus.CANCELLED),
        (TaskStatus.RUNNING, TaskStatus.AWAITING_APPROVAL),
        (TaskStatus.RUNNING, TaskStatus.COMPLETED),
        (TaskStatus.RUNNING, TaskStatus.FAILED),
        (TaskStatus.RUNNING, TaskStatus.CANCELLED),
        (TaskStatus.RUNNING, TaskStatus.INTERRUPTED),
        (TaskStatus.AWAITING_APPROVAL, TaskStatus.RUNNING),
        (TaskStatus.AWAITING_APPROVAL, TaskStatus.CANCELLED),
        (TaskStatus.INTERRUPTED, TaskStatus.RUNNING),
        (TaskStatus.INTERRUPTED, TaskStatus.CANCELLED),
        (TaskStatus.INTERRUPTED, TaskStatus.FAILED),
    ],
)
def test_allows_declared_task_transitions(current: TaskStatus, target: TaskStatus) -> None:
    assert transition_task(current, target) is target


@pytest.mark.parametrize(
    "terminal", [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]
)
@pytest.mark.parametrize("target", list(TaskStatus))
def test_terminal_task_cannot_transition(terminal: TaskStatus, target: TaskStatus) -> None:
    with pytest.raises(InvalidTaskTransitionError) as raised:
        transition_task(terminal, target)

    assert raised.value.code == "TASK_TRANSITION_INVALID"


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (TaskStatus.PENDING, TaskStatus.COMPLETED),
        (TaskStatus.PENDING, TaskStatus.AWAITING_APPROVAL),
        (TaskStatus.AWAITING_APPROVAL, TaskStatus.COMPLETED),
        (TaskStatus.INTERRUPTED, TaskStatus.COMPLETED),
        (TaskStatus.RUNNING, TaskStatus.PENDING),
    ],
)
def test_rejects_undeclared_task_transitions(current: TaskStatus, target: TaskStatus) -> None:
    with pytest.raises(InvalidTaskTransitionError):
        transition_task(current, target)
