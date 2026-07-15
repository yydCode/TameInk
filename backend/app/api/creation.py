import asyncio
from collections.abc import Callable

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict

from app.agents.runtime import DeepAgentRunner
from app.agents.schemas import Outline, StorySetting
from app.domain.errors import TameInkError
from app.domain.task import Task
from app.infrastructure.model import ModelConfigurationError
from app.infrastructure.secrets import SecretStoreError
from app.infrastructure.settings import SettingsError
from app.repositories.database import DatabaseRepository
from app.repositories.drafts import DraftRepository
from app.repositories.tasks import TasksRepository
from app.workflows.chapter import ChapterService
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
def approve_chapter(project_id: str, chapter_id: str, task_id: str, request: Request) -> Task:
    return ChapterService(request.app.state.workspace).approve(project_id, task_id, chapter_id)


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
    response_model=GeneratedTaskResponse,
    status_code=status.HTTP_201_CREATED,
)
async def generate_chapter(
    project_id: str,
    chapter_id: str,
    payload: GenerateRequest,
    request: Request,
) -> GeneratedTaskResponse:
    def run() -> GeneratedTaskResponse:
        workspace = request.app.state.workspace
        task = ChapterService(workspace, runner=_runner(project_id, request)).run(
            project_id, chapter_id, payload.instruction
        )
        content = DraftRepository(workspace).read(project_id, task.id, "chapter.md")
        return GeneratedTaskResponse(task=task, content=content)

    return await _run_agent(run)
