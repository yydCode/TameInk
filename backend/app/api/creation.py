from typing import Literal, cast

from fastapi import APIRouter, Request, status
from pydantic import BaseModel, ConfigDict, Field

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


class ChapterDirectiveRequest(BaseModel):
    """P0: 人给章节的结构化方向指令——人决策、AI 执行。"""

    model_config = ConfigDict(extra="forbid")

    required_characters: list[str] = Field(default_factory=list)
    resolve_foreshadowing_ids: list[str] = Field(default_factory=list)
    plant_foreshadowing: list[str] = Field(default_factory=list)
    emotional_tone: str = ""
    pacing: Literal["slow", "medium", "fast"] = "medium"
    focus_entities: list[str] = Field(default_factory=list)
    key_events: list[str] = Field(default_factory=list)
    target_word_count: int | None = None


class GenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instruction: str
    volume_id: str = "1"
    directive: ChapterDirectiveRequest | None = None


class LocalRevisionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: int = Field(ge=0)
    end: int = Field(gt=0)
    instruction: str = Field(min_length=1)


class ChapterApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    commercial_override_reason: str | None = None
    accepted_memory_ids: list[str] = Field(default_factory=list)


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
        accepted_memory_ids=(payload.accepted_memory_ids if payload else []),
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
    volume_id = payload.volume_id
    task = _create_agent_task(
        request,
        project_id,
        TaskPurpose.CHAPTER,
        chapter_id,
        volume_id=volume_id,
        chapter_id=chapter_id,
    )
    job_payload: dict[str, object] = {
        "instruction": payload.instruction,
        "chapter_id": chapter_id,
        "volume_id": volume_id,
    }
    if payload.directive is not None:
        job_payload["directive"] = payload.directive.model_dump()
    _jobs(request).enqueue(
        project_id,
        task.id,
        AgentJobKind.CHAPTER,
        job_payload,
    )
    return _task(request, project_id, task.id)


@router.post(
    "/agent/chapters/{chapter_id}/plan",
    response_model=Task,
    status_code=status.HTTP_202_ACCEPTED,
)
def generate_chapter_plan(
    project_id: str,
    chapter_id: str,
    payload: GenerateRequest,
    request: Request,
) -> Task:
    """P0: 只生成章纲，等审批——人审章纲环节。"""
    volume_id = payload.volume_id
    task = _create_agent_task(
        request,
        project_id,
        TaskPurpose.CHAPTER,
        chapter_id,
        volume_id=volume_id,
        chapter_id=chapter_id,
    )
    job_payload: dict[str, object] = {
        "instruction": payload.instruction,
        "chapter_id": chapter_id,
        "volume_id": volume_id,
    }
    if payload.directive is not None:
        job_payload["directive"] = payload.directive.model_dump()
    _jobs(request).enqueue(
        project_id,
        task.id,
        AgentJobKind.CHAPTER_PLAN,
        job_payload,
    )
    return _task(request, project_id, task.id)


@router.post(
    "/agent/chapters/{chapter_id}/{task_id}/approve-plan",
    response_model=Task,
    status_code=status.HTTP_202_ACCEPTED,
)
def approve_chapter_plan(
    project_id: str,
    chapter_id: str,
    task_id: str,
    request: Request,
) -> Task:
    """P0: 人批准章纲后，跑后续正文流水线。"""
    task = _task(request, project_id, task_id)
    volume_id = task.volume_id or "1"
    _jobs(request).enqueue(
        project_id,
        task_id,
        AgentJobKind.CHAPTER_DRAFT,
        {"chapter_id": chapter_id, "volume_id": volume_id},
    )
    return _task(request, project_id, task_id)


@router.post(
    "/agent/chapters/{chapter_id}/{task_id}/revise",
    response_model=Task,
    status_code=status.HTTP_202_ACCEPTED,
)
def revise_chapter(
    project_id: str,
    chapter_id: str,
    task_id: str,
    request: Request,
) -> Task:
    """P1: 迭代修改——基于人编辑后的草稿重新审计+局部修订。"""
    task = _task(request, project_id, task_id)
    volume_id = task.volume_id or "1"
    _jobs(request).enqueue(
        project_id,
        task_id,
        AgentJobKind.CHAPTER_REVISE,
        {"chapter_id": chapter_id, "volume_id": volume_id},
    )
    return _task(request, project_id, task_id)


@router.post(
    "/agent/chapters/{chapter_id}/{task_id}/local-revise",
    response_model=Task,
    status_code=status.HTTP_202_ACCEPTED,
)
def local_revise_chapter(
    project_id: str,
    chapter_id: str,
    task_id: str,
    payload: LocalRevisionPayload,
    request: Request,
) -> Task:
    """P3: 局部重生成——人选中一段文字，AI 只重写该段。"""
    task = _task(request, project_id, task_id)
    volume_id = task.volume_id or "1"
    _jobs(request).enqueue(
        project_id,
        task_id,
        AgentJobKind.CHAPTER_LOCAL_REVISE,
        {
            "chapter_id": chapter_id,
            "volume_id": volume_id,
            "start": payload.start,
            "end": payload.end,
            "instruction": payload.instruction,
        },
    )
    return _task(request, project_id, task_id)


@router.get("/agent/chapters/{chapter_id}/{task_id}/audit-reports")
def get_audit_reports(
    project_id: str,
    chapter_id: str,
    task_id: str,
    request: Request,
) -> dict[str, object]:
    """P1: 审计报告对人可见。"""
    return ChapterService(request.app.state.workspace).read_audit_reports(
        project_id, task_id
    )


@router.get("/agent/chapters/{chapter_id}/{task_id}/stage")
def get_chapter_stage(
    project_id: str,
    chapter_id: str,
    task_id: str,
    request: Request,
) -> dict[str, str]:
    """P0: 查询当前章节阶段（plan_awaiting_approval / draft_awaiting_approval）。"""
    stage = ChapterService(request.app.state.workspace).read_stage(project_id, task_id)
    return {"stage": stage}


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
