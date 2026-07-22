import json
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol, cast

from huey import Huey  # type: ignore[import-untyped]
from huey.contrib.sql_huey import SqlHuey  # type: ignore[import-untyped]
from peewee import SqliteDatabase  # type: ignore[import-untyped]

from app.agents.runtime import DeepAgentRunner
from app.agents.schemas import CommercialReport, CommercialStrategy, Outline, StorySetting
from app.domain.diagnostics import TaskLogLevel
from app.domain.errors import TameInkError, WorkflowGateError
from app.domain.task import Task, TaskStatus
from app.infrastructure.secrets import ApiKeyStore, SecretStoreError
from app.infrastructure.settings import SettingsError, SettingsRepository
from app.repositories.commercial import CommercialRepository
from app.repositories.database import DatabaseRepository
from app.repositories.drafts import DraftRepository
from app.repositories.tasks import TasksRepository
from app.repositories.workspace import WorkspaceRepository
from app.workflows.chapter import ChapterService
from app.workflows.commercial import CommercialService
from app.workflows.creative import CreativeService
from app.workflows.task_service import TaskService


class AgentJobKind(StrEnum):
    SETTING = "setting"
    BOOK_OUTLINE = "book_outline"
    VOLUME_OUTLINE = "volume_outline"
    CHAPTER = "chapter"
    COMMERCIAL = "commercial"
    COMMERCIAL_AUDIT = "commercial_audit"
    CREATIVE_SKILL = "creative_skill"


class JobQueue(Protocol):
    def enqueue(
        self,
        project_id: str,
        task_id: str,
        kind: AgentJobKind,
        payload: dict[str, object],
    ) -> None: ...


class AgentCancellationRequested(RuntimeError):
    pass


class DurableAgentQueue:
    def __init__(self, workspace_root: Path, *, immediate: bool = False) -> None:
        self.workspace_root = workspace_root.resolve()
        queue_path = self.workspace_root / ".tame-ink" / "jobs.db"
        queue_path.parent.mkdir(parents=True, exist_ok=True)
        database = SqliteDatabase(queue_path, timeout=5, pragmas={"journal_mode": "wal"})
        self.huey: Huey = SqlHuey(
            name="tame-ink",
            database=database,
            immediate=immediate,
            immediate_use_memory=True,
            results=False,
        )
        self._execute = self.huey.task(retries=0, name="tame_ink.execute_agent_job")(
            execute_agent_job
        )

    def enqueue(
        self,
        project_id: str,
        task_id: str,
        kind: AgentJobKind,
        payload: dict[str, object],
    ) -> None:
        workspace = WorkspaceRepository(self.workspace_root)
        DraftRepository(workspace).write(
            project_id,
            task_id,
            "request.json",
            json.dumps(
                {"kind": kind.value, "payload": payload},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            overwrite=False,
        )
        TasksRepository(DatabaseRepository(workspace), project_id).append_log(
            task_id,
            TaskLogLevel.INFO,
            "queue",
            "queue.enqueued",
            details={"job_kind": kind.value},
        )
        self._execute(str(self.workspace_root), project_id, task_id, kind.value, payload)


def execute_agent_job(
    workspace_root: str,
    project_id: str,
    task_id: str,
    kind_value: str,
    payload: dict[str, object],
) -> None:
    workspace = WorkspaceRepository(Path(workspace_root))
    database = DatabaseRepository(workspace)
    database.initialize(project_id)
    service = TaskService(TasksRepository(database, project_id))
    drafts = DraftRepository(workspace)
    kind = AgentJobKind(kind_value)
    task = service.get(task_id)
    service.repository.append_log(
        task_id,
        TaskLogLevel.INFO,
        "worker",
        "worker.claimed",
        details={"job_kind": kind.value, "status": task.status.value},
    )
    if task.status is TaskStatus.PENDING:
        service.start(task_id)
    elif task.status is TaskStatus.AWAITING_APPROVAL:
        service.repository.transition(
            task_id,
            TaskStatus.AWAITING_APPROVAL,
            TaskStatus.RUNNING,
            "task.generation_started",
        )
    else:
        raise WorkflowGateError("agent job task is not ready")

    holder: dict[str, DeepAgentRunner] = {}

    def before(agent: str, diagnostics: dict[str, object] | None = None) -> None:
        if service.cancellation_requested(task_id):
            raise AgentCancellationRequested
        service.repository.append_event(task_id, "agent.stage.started", {"agent": agent})
        service.repository.append_log(
            task_id,
            TaskLogLevel.INFO,
            "agent",
            "agent.stage.started",
            agent=agent,
            details=diagnostics,
        )

    def after(
        agent: str,
        error_code: str | None,
        diagnostics: dict[str, object] | None = None,
    ) -> None:
        data: dict[str, object] = {"agent": agent, **(diagnostics or {})}
        event_type = "agent.stage.completed"
        if error_code is not None:
            data["error_code"] = error_code
            event_type = "agent.stage.failed"
        else:
            runner = holder.get("runner")
            recorder = runner.usage_recorder if runner is not None else None
            if recorder is not None:
                events = recorder.events()
                if events:
                    latest = events[-1]
                    for key in (
                        "input_tokens",
                        "output_tokens",
                        "total_tokens",
                        "input_cost_cny",
                        "output_cost_cny",
                        "total_cost_cny",
                    ):
                        data[key] = latest.get(key)
        service.repository.append_event(task_id, event_type, data)
        service.repository.append_log(
            task_id,
            TaskLogLevel.ERROR if error_code is not None else TaskLogLevel.INFO,
            "agent",
            event_type,
            agent=agent,
            details=data,
        )
        if error_code is None and service.cancellation_requested(task_id):
            raise AgentCancellationRequested

    try:
        runner = create_runner(
            workspace,
            project_id,
            SettingsRepository(workspace.root / "settings.json"),
            ApiKeyStore(),
            before_invoke=before,
            after_invoke=after,
        )
        holder["runner"] = runner
        _run_job(kind, payload, workspace, project_id, task_id, runner)
        if service.cancellation_requested(task_id):
            raise AgentCancellationRequested
        service.repository.append_log(
            task_id,
            TaskLogLevel.INFO,
            "worker",
            "worker.completed",
            details={"job_kind": kind.value},
        )
    except AgentCancellationRequested:
        drafts.discard_candidates(project_id, task_id)
        service.repository.append_log(
            task_id,
            TaskLogLevel.WARNING,
            "worker",
            "worker.cancelled",
            details={"job_kind": kind.value, "cancel_requested": True},
        )
        if service.get(task_id).status is TaskStatus.RUNNING:
            service.cancel_requested_task(task_id)
    except Exception as error:
        if isinstance(error, TameInkError):
            code = error.code
        elif isinstance(error, (SettingsError, SecretStoreError)):
            code = str(error)
        else:
            candidate = str(error)
            code = candidate if candidate.startswith("MODEL_") else type(error).__name__
        service.repository.append_log(
            task_id,
            TaskLogLevel.ERROR,
            "worker",
            "worker.failed",
            details={
                "job_kind": kind.value,
                "error_code": code,
                "error_type": type(error).__name__,
            },
        )
        if service.get(task_id).status is TaskStatus.RUNNING:
            service.fail(task_id, code, "agent job failed")


def create_runner(
    workspace: WorkspaceRepository,
    project_id: str,
    settings: SettingsRepository,
    secrets: ApiKeyStore,
    before_invoke: Any,
    after_invoke: Any,
) -> DeepAgentRunner:
    return DeepAgentRunner(
        workspace,
        project_id,
        settings,
        secrets,
        before_invoke=before_invoke,
        after_invoke=after_invoke,
    )


def _run_job(
    kind: AgentJobKind,
    payload: dict[str, object],
    workspace: WorkspaceRepository,
    project_id: str,
    task_id: str,
    runner: DeepAgentRunner,
) -> Task:
    if kind is AgentJobKind.CREATIVE_SKILL:
        skill = _text(payload, "skill")
        skill_payload = payload.get("payload")
        if not isinstance(skill_payload, dict):
            raise WorkflowGateError("creative skill payload is invalid")
        return CreativeService(workspace, runner=runner).execute_skill_task(
            project_id,
            task_id,
            cast(Any, skill),
            skill_payload,
        )
    if kind is AgentJobKind.SETTING:
        output = runner.invoke("StoryArchitect", {"instruction": _text(payload, "instruction")})
        if not isinstance(output, StorySetting):
            raise WorkflowGateError("StoryArchitect returned invalid output")
        DraftRepository(workspace).write(project_id, task_id, "setting.md", output.content)
        _log_artifact(workspace, project_id, task_id, "setting.md", output.content)
        return _tasks(workspace, project_id).await_approval(task_id)
    if kind in {AgentJobKind.BOOK_OUTLINE, AgentJobKind.VOLUME_OUTLINE}:
        outline_kind = "book" if kind is AgentJobKind.BOOK_OUTLINE else "volume"
        request: dict[str, object] = {
            "kind": outline_kind,
            "instruction": _text(payload, "instruction"),
        }
        if outline_kind == "volume":
            request["volume_id"] = _text(payload, "volume_id")
        output = runner.invoke("OutlineArchitect", request)
        if not isinstance(output, Outline) or output.kind != outline_kind:
            raise WorkflowGateError("OutlineArchitect returned invalid output")
        name = (
            "book-outline.md"
            if outline_kind == "book"
            else f"volume-{_text(payload, 'volume_id')}.md"
        )
        DraftRepository(workspace).write(project_id, task_id, name, output.content)
        _log_artifact(workspace, project_id, task_id, name, output.content)
        return _tasks(workspace, project_id).await_approval(task_id)
    if kind is AgentJobKind.CHAPTER:
        return ChapterService(workspace, runner=runner).run_for_task(
            project_id,
            task_id,
            _text(payload, "chapter_id"),
            _text(payload, "instruction"),
            _text(payload, "volume_id"),
        )
    if kind is AgentJobKind.COMMERCIAL:
        database = DatabaseRepository(workspace)
        metrics = CommercialRepository(database).metrics(project_id)
        brief = payload.get("brief")
        if not isinstance(brief, dict):
            raise WorkflowGateError("commercial brief is invalid")
        output = runner.invoke(
            "MarketStrategist",
            {
                "brief": brief,
                "observed_metrics": metrics.model_dump(mode="json"),
                "instruction": _text(brief, "instruction"),
            },
        )
        if not isinstance(output, CommercialStrategy):
            raise WorkflowGateError("MarketStrategist returned invalid output")
        if output.profile.platform != brief.get(
            "platform"
        ) or output.profile.monetization != brief.get("monetization"):
            raise WorkflowGateError("MarketStrategist changed fixed commercial fields")
        CommercialService(workspace).write_draft(project_id, task_id, output.profile)
        _tasks(workspace, project_id).repository.append_log(
            task_id,
            TaskLogLevel.INFO,
            "workflow",
            "workflow.candidate_written",
            details={"artifact": "commercial-profile", "artifact_count": 1},
        )
        return _tasks(workspace, project_id).await_approval(task_id)
    if kind is AgentJobKind.COMMERCIAL_AUDIT:
        profile = CommercialService(workspace).read(project_id)
        if profile is None:
            raise WorkflowGateError("commercial profile is required")
        chapter_id = _text(payload, "chapter_id")
        draft = DraftRepository(workspace).read(project_id, task_id, "chapter.md")
        output = runner.invoke(
            "RetentionAuditor",
            {
                "project_id": project_id,
                "chapter_id": chapter_id,
                "draft": draft,
                "instruction": "re-audit the current user-edited chapter candidate",
            },
        )
        if not isinstance(output, CommercialReport) or output.chapter_id != chapter_id:
            raise WorkflowGateError("RetentionAuditor returned invalid output")
        output = ChapterService.normalize_commercial_report(draft, output)
        ChapterService.validate_audit_issues(draft, [], [], output.issues)
        ChapterService(workspace).store_commercial_report(
            project_id, task_id, chapter_id, output, profile.minimum_commercial_score
        )
        return _tasks(workspace, project_id).await_approval(task_id)
    raise WorkflowGateError("agent job kind is unsupported")


def _tasks(workspace: WorkspaceRepository, project_id: str) -> TaskService:
    return TaskService(TasksRepository(DatabaseRepository(workspace), project_id))


def _log_artifact(
    workspace: WorkspaceRepository,
    project_id: str,
    task_id: str,
    artifact: str,
    content: str,
) -> None:
    _tasks(workspace, project_id).repository.append_log(
        task_id,
        TaskLogLevel.INFO,
        "workflow",
        "workflow.candidate_written",
        details={
            "artifact": artifact,
            "artifact_count": 1,
            "bytes_written": len(content.encode("utf-8")),
        },
    )


def _text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise WorkflowGateError(f"{key} is required")
    return value
