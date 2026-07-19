from pathlib import Path

from app.agents.schemas import StorySetting
from app.domain.task import TaskKind, TaskPurpose
from app.infrastructure.jobs import AgentJobKind, DurableAgentQueue
from app.repositories.database import DatabaseRepository
from app.repositories.drafts import DraftRepository
from app.repositories.tasks import TasksRepository
from app.repositories.workspace import WorkspaceRepository
from app.workflows.new_book import NewBookRequest, NewBookService
from app.workflows.task_service import TaskService


def test_sql_queue_persists_job_and_request_without_running_it(tmp_path: Path) -> None:
    workspace = WorkspaceRepository(tmp_path)
    workspace.create_project("queue-book")
    database = DatabaseRepository(workspace)
    database.initialize("queue-book")
    service = TaskService(TasksRepository(database, "queue-book"))
    task = service.create(TaskKind.WRITE, TaskPurpose.BOOK_OUTLINE, subject_id="book")
    queue = DurableAgentQueue(tmp_path, immediate=False)

    queue.enqueue(
        "queue-book",
        task.id,
        AgentJobKind.BOOK_OUTLINE,
        {"instruction": "生成大纲"},
    )

    assert queue.huey.pending_count() == 1
    request = DraftRepository(workspace).read("queue-book", task.id, "request.json")
    assert "book_outline" in request
    assert "生成大纲" in request


def test_running_job_cancels_after_current_model_boundary_and_discards_candidate(
    tmp_path: Path, monkeypatch
) -> None:
    workspace = WorkspaceRepository(tmp_path)
    created = NewBookService(workspace).create(
        NewBookRequest(
            project_id="cancel-book",
            title="取消书",
            genre="悬疑",
            target_words=1000,
            constraints="第三人称",
        ),
        "旧设定",
    )
    service = TaskService(TasksRepository(DatabaseRepository(workspace), "cancel-book"))

    class CancellingRunner:
        usage_recorder = None

        def __init__(self, before, after) -> None:
            self.before = before
            self.after = after

        def invoke(self, agent: str, payload: dict[str, object]) -> object:
            self.before(agent)
            service.cancel(created.task.id)
            result = StorySetting(
                id="cancelled-setting",
                title="不应保存",
                content="# 不应保存",
                references=[
                    {"path": "project.yaml", "location": "full document", "quote": "project"}
                ],
            )
            self.after(agent, None)
            return result

    monkeypatch.setattr(
        "app.infrastructure.jobs.create_runner",
        lambda *args, **kwargs: CancellingRunner(kwargs["before_invoke"], kwargs["after_invoke"]),
    )
    queue = DurableAgentQueue(tmp_path, immediate=True)

    queue.enqueue(
        "cancel-book",
        created.task.id,
        AgentJobKind.SETTING,
        {"instruction": "重新生成"},
    )

    assert service.get(created.task.id).status.value == "cancelled"
    assert DraftRepository(workspace).list_files("cancel-book", created.task.id) == ["request.json"]
    assert [event.type for event in service.events(created.task.id)][-4:] == [
        "agent.stage.started",
        "task.cancel_requested",
        "agent.stage.completed",
        "task.cancelled",
    ]
