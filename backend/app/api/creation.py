from fastapi import APIRouter, Request, status
from pydantic import BaseModel, ConfigDict

from app.domain.task import Task
from app.workflows.chapter import ChapterService
from app.workflows.outline import OutlineService

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
