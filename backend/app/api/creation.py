import asyncio
from collections.abc import Callable

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict

from app.agents.runtime import DeepAgentRunner
from app.agents.schemas import CommercialReport, Outline, StorySetting
from app.domain.errors import TameInkError
from app.domain.task import Task
from app.infrastructure.model import ModelConfigurationError
from app.infrastructure.secrets import SecretStoreError
from app.infrastructure.settings import SettingsError
from app.repositories.database import DatabaseRepository
from app.repositories.drafts import DraftRepository
from app.repositories.tasks import TasksRepository
from app.workflows.chapter import ChapterService
from app.workflows.commercial import CommercialService
from app.workflows.outline import OutlineService

router = APIRouter(prefix="/projects/{project_id}/design", tags=["creation"])

SAFE_AGENT_CONFIGURATION_CODES = {
    "MODEL_API_KEY_MISSING",
    "MODEL_SETTINGS_INVALID",
    "MODEL_SETTINGS_NOT_FOUND",
    "MODEL_SETTINGS_READ_FAILED",
    "SECRET_STORE_READ_FAILED",
}


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


class GeneratedTaskResponse(BaseModel):
    task: Task
    content: str


class GeneratedChapterResponse(GeneratedTaskResponse):
    commercial_report: CommercialReport
    minimum_commercial_score: int
    commercial_gate_passed: bool


class ChapterApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    commercial_override_reason: str | None = None


class CommercialAuditResponse(BaseModel):
    commercial_report: CommercialReport
    minimum_commercial_score: int
    commercial_gate_passed: bool


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


def _runner(project_id: str, request: Request) -> DeepAgentRunner:
    return DeepAgentRunner(
        request.app.state.workspace,
        project_id,
        request.app.state.model_settings,
        request.app.state.api_keys,
    )


async def _run_agent[AgentResponse](operation: Callable[[], AgentResponse]) -> AgentResponse:
    try:
        return await asyncio.to_thread(operation)
    except TameInkError:
        raise
    except (SettingsError, SecretStoreError, ModelConfigurationError) as error:
        candidate = str(error)
        code = (
            candidate
            if candidate in SAFE_AGENT_CONFIGURATION_CODES
            else "AGENT_CONFIGURATION_INVALID"
        )
        raise HTTPException(
            status_code=400,
            detail={"code": code, "message": "agent configuration invalid"},
        ) from error
    except Exception as error:
        code = (
            "AGENT_OUTPUT_INVALID"
            if str(error) == "AGENT_OUTPUT_INVALID"
            else "AGENT_RUN_FAILED"
        )
        raise HTTPException(
            status_code=502,
            detail={"code": code, "message": "agent generation failed"},
        ) from error


@router.post("/agent/setting/{task_id}", response_model=GeneratedTaskResponse)
async def generate_setting(
    project_id: str, task_id: str, payload: GenerateRequest, request: Request
) -> GeneratedTaskResponse:
    def run() -> GeneratedTaskResponse:
        workspace = request.app.state.workspace
        task = TasksRepository(DatabaseRepository(workspace), project_id).get(task_id)
        output = _runner(project_id, request).invoke(
            "StoryArchitect", {"instruction": payload.instruction}
        )
        if not isinstance(output, StorySetting):
            raise RuntimeError("AGENT_OUTPUT_INVALID")
        DraftRepository(workspace).write(project_id, task_id, "setting.md", output.content)
        return GeneratedTaskResponse(task=task, content=output.content)

    return await _run_agent(run)


@router.post(
    "/agent/outline",
    response_model=GeneratedTaskResponse,
    status_code=status.HTTP_201_CREATED,
)
async def generate_outline(
    project_id: str, payload: GenerateRequest, request: Request
) -> GeneratedTaskResponse:
    def run() -> GeneratedTaskResponse:
        workspace = request.app.state.workspace
        output = _runner(project_id, request).invoke(
            "OutlineArchitect", {"kind": "book", "instruction": payload.instruction}
        )
        if not isinstance(output, Outline) or output.kind != "book":
            raise RuntimeError("AGENT_OUTPUT_INVALID")
        task = OutlineService(workspace).create_book(project_id, output.content)
        return GeneratedTaskResponse(task=task, content=output.content)

    return await _run_agent(run)


@router.post(
    "/agent/volumes/{volume_id}",
    response_model=GeneratedTaskResponse,
    status_code=status.HTTP_201_CREATED,
)
async def generate_volume(
    project_id: str,
    volume_id: str,
    payload: GenerateRequest,
    request: Request,
) -> GeneratedTaskResponse:
    def run() -> GeneratedTaskResponse:
        workspace = request.app.state.workspace
        output = _runner(project_id, request).invoke(
            "OutlineArchitect",
            {"kind": "volume", "volume_id": volume_id, "instruction": payload.instruction},
        )
        if not isinstance(output, Outline) or output.kind != "volume":
            raise RuntimeError("AGENT_OUTPUT_INVALID")
        task = OutlineService(workspace).create_volume(project_id, volume_id, output.content)
        return GeneratedTaskResponse(task=task, content=output.content)

    return await _run_agent(run)


@router.post(
    "/agent/chapters/{chapter_id}",
    response_model=GeneratedChapterResponse,
    status_code=status.HTTP_201_CREATED,
)
async def generate_chapter(
    project_id: str,
    chapter_id: str,
    payload: GenerateRequest,
    request: Request,
) -> GeneratedChapterResponse:
    def run() -> GeneratedChapterResponse:
        workspace = request.app.state.workspace
        service = ChapterService(workspace, runner=_runner(project_id, request))
        task = service.run(project_id, chapter_id, payload.instruction)
        content = DraftRepository(workspace).read(project_id, task.id, "chapter.md")
        report = service.read_commercial_report(project_id, task.id)
        profile = CommercialService(workspace).read(project_id)
        if report is None or profile is None:
            raise RuntimeError("AGENT_OUTPUT_INVALID")
        return GeneratedChapterResponse(
            task=task,
            content=content,
            commercial_report=report,
            minimum_commercial_score=profile.minimum_commercial_score,
            commercial_gate_passed=service.commercial_gate_passed(
                report, profile.minimum_commercial_score
            ),
        )

    return await _run_agent(run)


@router.post(
    "/agent/chapters/{chapter_id}/{task_id}/commercial-audit",
    response_model=CommercialAuditResponse,
)
async def audit_chapter_commercially(
    project_id: str,
    chapter_id: str,
    task_id: str,
    request: Request,
) -> CommercialAuditResponse:
    def run() -> CommercialAuditResponse:
        workspace = request.app.state.workspace
        task = TasksRepository(DatabaseRepository(workspace), project_id).get(task_id)
        if task.status != "awaiting_approval":
            raise RuntimeError("COMMERCIAL_AUDIT_TASK_INVALID")
        profile = CommercialService(workspace).read(project_id)
        if profile is None:
            raise RuntimeError("COMMERCIAL_PROFILE_MISSING")
        draft = DraftRepository(workspace).read(project_id, task_id, "chapter.md")
        output = _runner(project_id, request).invoke(
            "RetentionAuditor",
            {
                "project_id": project_id,
                "chapter_id": chapter_id,
                "draft": draft,
                "instruction": "re-audit the current user-edited chapter candidate",
            },
        )
        if not isinstance(output, CommercialReport) or output.chapter_id != chapter_id:
            raise RuntimeError("AGENT_OUTPUT_INVALID")
        output = ChapterService.normalize_commercial_report(draft, output)
        ChapterService.validate_audit_issues(draft, [], [], output.issues)
        service = ChapterService(workspace)
        passed = service.store_commercial_report(
            project_id,
            task_id,
            chapter_id,
            output,
            profile.minimum_commercial_score,
        )
        return CommercialAuditResponse(
            commercial_report=output,
            minimum_commercial_score=profile.minimum_commercial_score,
            commercial_gate_passed=passed,
        )

    return await _run_agent(run)
