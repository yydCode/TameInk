from datetime import UTC, datetime
from pathlib import Path

from app.agents.schemas import SkillExecutionContract, StorySetting
from app.domain.creation import CreativeBrief
from app.domain.project import Project
from app.domain.task import TaskKind, TaskPurpose
from app.infrastructure.jobs import AgentJobKind, DurableAgentQueue, _run_job
from app.repositories.canon import CanonRepository
from app.repositories.database import DatabaseRepository
from app.repositories.drafts import DraftRepository
from app.repositories.tasks import TasksRepository
from app.repositories.workspace import WorkspaceRepository
from app.workflows.creative import CreativeService
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
    logs = service.logs(task.id)
    assert (logs[-1].component, logs[-1].event) == ("queue", "queue.enqueued")
    assert logs[-1].details == {"job_kind": "book_outline"}


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
    assert [
        (entry.component, entry.event) for entry in service.logs(created.task.id)[-5:]
    ] == [
        ("agent", "agent.stage.started"),
        ("task", "task.cancel_requested"),
        ("agent", "agent.stage.completed"),
        ("worker", "worker.cancelled"),
        ("task", "task.status_changed"),
    ]


def test_creative_skill_job_uses_skill_runner_and_stores_only_candidate(tmp_path: Path) -> None:
    workspace = WorkspaceRepository(tmp_path)
    workspace.create_project("creative-job")
    CanonRepository(workspace).write_project(
        Project(id="creative-job", title="创作任务", language="zh-CN")
    )
    now = datetime.now(UTC)
    CanonRepository(workspace).write_creative_brief(
        "creative-job",
        CreativeBrief(
            version=1,
            platform="fanqie",
            genre_scope="都市",
            initial_intent="写一个都市成长故事。",
            first_story_goal="完成第一笔交易。",
            constraints=["第三人称"],
            material_boundaries=["仅使用授权素材"],
            created_at=now,
            updated_at=now,
        ),
    )
    DatabaseRepository(workspace).initialize("creative-job")
    service = CreativeService(workspace)
    task = service.create_skill_task("creative-job", "webnovel-design-reader-contract", {})
    TaskService(TasksRepository(DatabaseRepository(workspace), "creative-job")).start(task.id)

    class Runner:
        def execute_skill(self, skill, payload):
            assert skill == "webnovel-design-reader-contract"
            assert payload == {"instruction": "设计读者契约"}
            return SkillExecutionContract.model_validate(
                {
                    "id": "reader-result",
                    "skill": skill,
                    "status": "ready",
                    "references": [
                        {"path": "project.yaml", "location": "chars:0-1", "quote": "i"}
                    ],
                    "evidence": [],
                    "candidate": {
                        "artifact_kind": "reader_contract",
                        "summary": "读者契约",
                        "payload": {"id": "reader-1"},
                    },
                    "decision_requests": [],
                    "effects": [],
                }
            )

    result = _run_job(
        AgentJobKind.CREATIVE_SKILL,
        {"skill": "webnovel-design-reader-contract", "payload": {"instruction": "设计读者契约"}},
        workspace,
        "creative-job",
        task.id,
        Runner(),  # type: ignore[arg-type]
    )

    assert result.status.value == "awaiting_approval"
    contract = workspace.project_path("creative-job") / "commitments/reader-contract.yaml"
    assert not contract.exists()
