from typing import cast

from fastapi import APIRouter, Request, status
from pydantic import BaseModel, ConfigDict

from app.domain.task import Task, TaskKind, TaskPurpose
from app.infrastructure.jobs import AgentJobKind, JobQueue
from app.repositories.database import DatabaseRepository
from app.repositories.tasks import TasksRepository
from app.workflows.chapter import ChapterService
from app.workflows.outline import OutlineService
from app.workflows.task_service import TaskService

router = APIRouter(prefix="/projects/{project_id}/design", tags=["creation"])


class ContentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str


class ChapterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan: str
    draft: str
    issues: list[dict[str, str]]
    volume_id: str = "1"


class GenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instruction: str


class ChapterApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    commercial_override_reason: str | None = None


@router.post("/outline", response_model=Task, status_code=status.HTTP_201_CREATED)
def create_outline(project_id: str, payload: ContentRequest, request: Request) -> Task:
    return OutlineService(request.app.state.workspace).create_book(project_id, payload.content)


@router.post("/outline/{task_id}/approve", response_model=Task)
def approve_outline(project_id: str, task_id: str, request: Request) -> Task:
    return OutlineService(request.app.state.workspace).approve_book(project_id, task_id)


@router.post("/volumes/{volume_id}", response_model=Task, status_code=status.HTTP_201_CREATED)
def create_volume(
    project_id: str, volume_id: str, payload: ContentRequest, request: Request
) -> Task:
    return OutlineService(request.app.state.workspace).create_volume(
        project_id, volume_id, payload.content
    )


@router.post("/volumes/{volume_id}/{task_id}/approve", response_model=Task)
def approve_volume(project_id: str, volume_id: str, task_id: str, request: Request) -> Task:
    return OutlineService(request.app.state.workspace).approve_volume(
        project_id, task_id, volume_id
    )


@router.post("/chapters/{chapter_id}", response_model=Task, status_code=status.HTTP_201_CREATED)
def start_chapter(
    project_id: str, chapter_id: str, payload: ChapterRequest, request: Request
) -> Task:
    return ChapterService(request.app.state.workspace).start(
        project_id, chapter_id, payload.plan, payload.draft, payload.issues, payload.volume_id
    )


@router.post("/chapters/{chapter_id}/{task_id}/approve", response_model=Task)
def approve_chapter(
    project_id: str,
    chapter_id: str,
    task_id: str,
    request: Request,
    payload: ChapterApprovalRequest | None = None,
) -> Task:
    return ChapterService(request.app.state.workspace).approve(
        project_id,
        task_id,
        chapter_id,
        commercial_override_reason=(payload.commercial_override_reason if payload else None),
    )


@router.post("/agent/setting/{task_id}", response_model=Task, status_code=status.HTTP_202_ACCEPTED)
def generate_setting(
    project_id: str, task_id: str, payload: GenerateRequest, request: Request
) -> Task:
    workspace = request.app.state.workspace
    task = TasksRepository(DatabaseRepository(workspace), project_id).get(task_id)
    _jobs(request).enqueue(
        project_id, task_id, AgentJobKind.SETTING, {"instruction": payload.instruction}
    )
    return TasksRepository(DatabaseRepository(workspace), project_id).get(task.id)


@router.post(
    "/agent/outline",
    response_model=Task,
    status_code=status.HTTP_202_ACCEPTED,
)
def generate_outline(project_id: str, payload: GenerateRequest, request: Request) -> Task:
    task = _create_agent_task(request, project_id, TaskPurpose.BOOK_OUTLINE, "book")
    _jobs(request).enqueue(
        project_id, task.id, AgentJobKind.BOOK_OUTLINE, {"instruction": payload.instruction}
    )
    return _task(request, project_id, task.id)


@router.post(
    "/agent/volumes/{volume_id}",
    response_model=Task,
    status_code=status.HTTP_202_ACCEPTED,
)
def generate_volume(
    project_id: str,
    volume_id: str,
    payload: GenerateRequest,
    request: Request,
) -> Task:
    task = _create_agent_task(
        request,
        project_id,
        TaskPurpose.VOLUME_OUTLINE,
        volume_id,
        volume_id=volume_id,
    )
    _jobs(request).enqueue(
        project_id,
        task.id,
        AgentJobKind.VOLUME_OUTLINE,
        {"instruction": payload.instruction, "volume_id": volume_id},
    )
    return _task(request, project_id, task.id)


@router.post(
    "/agent/chapters/{chapter_id}",
    response_model=Task,
    status_code=status.HTTP_202_ACCEPTED,
)
def generate_chapter(
    project_id: str,
    chapter_id: str,
    payload: GenerateRequest,
    request: Request,
) -> Task:
    volume_id = "1"
    task = _create_agent_task(
        request,
        project_id,
        TaskPurpose.CHAPTER,
        chapter_id,
        volume_id=volume_id,
        chapter_id=chapter_id,
    )
    _jobs(request).enqueue(
        project_id,
        task.id,
        AgentJobKind.CHAPTER,
        {
            "instruction": payload.instruction,
            "chapter_id": chapter_id,
            "volume_id": volume_id,
        },
    )
    return _task(request, project_id, task.id)


@router.post(
    "/agent/chapters/{chapter_id}/{task_id}/commercial-audit",
    response_model=Task,
    status_code=status.HTTP_202_ACCEPTED,
)
def audit_chapter_commercially(
    project_id: str,
    chapter_id: str,
    task_id: str,
    request: Request,
) -> Task:
    task = _task(request, project_id, task_id)
    _jobs(request).enqueue(
        project_id,
        task_id,
        AgentJobKind.COMMERCIAL_AUDIT,
        {"chapter_id": chapter_id},
    )
    return _task(request, project_id, task.id)


def _jobs(request: Request) -> JobQueue:
    return cast(JobQueue, request.app.state.agent_jobs)


def _task(request: Request, project_id: str, task_id: str) -> Task:
    return TasksRepository(DatabaseRepository(request.app.state.workspace), project_id).get(task_id)


def _create_agent_task(
    request: Request,
    project_id: str,
    purpose: TaskPurpose,
    subject_id: str,
    *,
    volume_id: str | None = None,
    chapter_id: str | None = None,
) -> Task:
    service = TaskService(
        TasksRepository(DatabaseRepository(request.app.state.workspace), project_id)
    )
    return service.create(
        TaskKind.WRITE,
        purpose,
        subject_id=subject_id,
        volume_id=volume_id,
        chapter_id=chapter_id,
    )
