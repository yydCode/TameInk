import json
from collections.abc import Callable
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from app.domain.errors import WorkflowGateError, WorkspacePathViolationError
from app.domain.paths import validate_formal_path
from app.domain.task import Task, TaskEvent, TaskKind, TaskPurpose
from app.repositories.database import DatabaseRepository
from app.repositories.drafts import DraftRepository
from app.repositories.tasks import TasksRepository
from app.repositories.workspace import WorkspaceRepository
from app.workflows.task_service import TaskService

router = APIRouter(prefix="/projects/{project_id}/tasks", tags=["tasks"])


class CreateTaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: TaskKind
    purpose: TaskPurpose = TaskPurpose.MANUAL
    subject_id: str | None = Field(default=None, max_length=128)
    volume_id: str | None = Field(default=None, max_length=128)
    chapter_id: str | None = Field(default=None, max_length=128)


class AgentRunTrace(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    agent: str = Field(min_length=1, max_length=64)
    skill: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    skill_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    stage: str = Field(min_length=1, max_length=64)
    source_paths: list[str] = Field(min_length=1, max_length=64)
    queries: list[str] = Field(max_length=48)
    total_characters: int = Field(ge=0)
    duration_ms: int = Field(ge=0)
    status: Literal["success", "failed"]
    error_code: str | None = Field(max_length=128)

    @field_validator("source_paths")
    @classmethod
    def validate_source_paths(cls, values: list[str]) -> list[str]:
        if len(set(values)) != len(values):
            raise ValueError("agent run source paths must be unique")
        for value in values:
            try:
                validate_formal_path(value)
            except WorkspacePathViolationError as error:
                raise ValueError("agent run source path is invalid") from error
        return values

    @field_validator("queries")
    @classmethod
    def validate_queries(cls, values: list[str]) -> list[str]:
        if len(set(values)) != len(values):
            raise ValueError("agent run queries must be unique")
        if any(value != value.strip() or not 2 <= len(value) <= 64 for value in values):
            raise ValueError("agent run query is invalid")
        return values

    @model_validator(mode="after")
    def validate_status(self) -> "AgentRunTrace":
        if (self.status == "success") != (self.error_code is None):
            raise ValueError("agent run status and error code disagree")
        return self


class TaskRunManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    agent_runs: list[AgentRunTrace]


def task_service(request: Request, project_id: str) -> TaskService:
    workspace: WorkspaceRepository = request.app.state.workspace
    database = DatabaseRepository(workspace)
    return TaskService(TasksRepository(database, project_id))


Service = Annotated[TaskService, Depends(task_service)]


@router.post("", response_model=Task, status_code=status.HTTP_201_CREATED)
def create_task(payload: CreateTaskRequest, service: Service) -> Task:
    return service.create(
        payload.kind,
        payload.purpose,
        subject_id=payload.subject_id,
        volume_id=payload.volume_id,
        chapter_id=payload.chapter_id,
    )


@router.get("", response_model=list[Task])
def list_tasks(service: Service) -> list[Task]:
    return service.repository.list_all()


@router.get("/{task_id}", response_model=Task)
def read_task(task_id: str, service: Service) -> Task:
    return service.get(task_id)


@router.get("/{task_id}/drafts", response_model=list[str])
def list_task_drafts(
    project_id: str, task_id: str, request: Request, service: Service
) -> list[str]:
    service.get(task_id)
    return DraftRepository(request.app.state.workspace).list_files(project_id, task_id)


@router.get("/{task_id}/run", response_model=TaskRunManifest)
def read_task_run(
    project_id: str, task_id: str, request: Request, service: Service
) -> TaskRunManifest:
    service.get(task_id)
    drafts = DraftRepository(request.app.state.workspace)
    if "run.json" not in drafts.list_files(project_id, task_id):
        return TaskRunManifest(agent_runs=[])
    try:
        stored = json.loads(drafts.read(project_id, task_id, "run.json"))
        if not isinstance(stored, dict) or "agent_runs" not in stored:
            raise ValueError("agent run manifest is missing")
        return TaskRunManifest.model_validate({"agent_runs": stored["agent_runs"]})
    except (json.JSONDecodeError, TypeError, ValueError, ValidationError) as error:
        raise WorkflowGateError("stored agent run manifest is invalid") from error


@router.get("/{task_id}/history", response_model=list[TaskEvent])
def task_history(task_id: str, service: Service) -> list[TaskEvent]:
    return service.events(task_id)


def operation(name: str) -> Callable[[str, TaskService], Task]:
    def run(task_id: str, service: Service) -> Task:
        method: Callable[[str], Task] = getattr(service, name)
        return method(task_id)

    return run


router.post("/{task_id}/start", response_model=Task)(operation("start"))
router.post("/{task_id}/await-approval", response_model=Task)(operation("await_approval"))
router.post("/{task_id}/approve", response_model=Task)(operation("approve"))
router.post("/{task_id}/reject", response_model=Task)(operation("reject"))
router.post("/{task_id}/cancel", response_model=Task)(operation("cancel"))
router.post("/{task_id}/complete", response_model=Task)(operation("complete"))
router.post("/{task_id}/fail", response_model=Task)(operation("fail"))
