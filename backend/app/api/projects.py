from fastapi import APIRouter, Request, status
from pydantic import BaseModel, ConfigDict, Field

from app.domain.project import Project
from app.domain.task import Task
from app.repositories.canon import CanonRepository
from app.repositories.database import DatabaseRepository
from app.repositories.drafts import DraftRepository
from app.repositories.tasks import TasksRepository
from app.repositories.workspace import WorkspaceRepository
from app.workflows.new_book import NewBookRequest, NewBookService

router = APIRouter(prefix="/projects", tags=["projects"])


class CreateProjectRequest(NewBookRequest):
    model_config = ConfigDict(extra="forbid", strict=True)

    setting_draft: str


class DraftContentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    path: str = Field(min_length=1)
    content: str


class DraftContentResponse(DraftContentRequest):
    task_id: str


@router.post("", status_code=status.HTTP_201_CREATED)
def create_project(payload: CreateProjectRequest, request: Request) -> dict[str, object]:
    workspace: WorkspaceRepository = request.app.state.workspace
    result = NewBookService(workspace).create(
        NewBookRequest(**payload.model_dump(exclude={"setting_draft"})), payload.setting_draft
    )
    return {"project": result.project, "task": result.task}


@router.get("/{project_id}", response_model=Project)
def get_project(project_id: str, request: Request) -> Project:
    workspace: WorkspaceRepository = request.app.state.workspace
    return CanonRepository(workspace).read_project(project_id)


@router.get("/{project_id}/drafts/{task_id}", response_model=DraftContentResponse)
def get_draft(
    project_id: str, task_id: str, path: str, request: Request
) -> DraftContentResponse:
    workspace: WorkspaceRepository = request.app.state.workspace
    TasksRepository(DatabaseRepository(workspace), project_id).get(task_id)
    content = DraftRepository(workspace).read(project_id, task_id, path)
    return DraftContentResponse(task_id=task_id, path=path, content=content)


@router.put("/{project_id}/drafts/{task_id}", response_model=DraftContentResponse)
def save_draft(
    project_id: str, task_id: str, payload: DraftContentRequest, request: Request
) -> DraftContentResponse:
    workspace: WorkspaceRepository = request.app.state.workspace
    TasksRepository(DatabaseRepository(workspace), project_id).get(task_id)
    DraftRepository(workspace).write(project_id, task_id, payload.path, payload.content)
    return DraftContentResponse(task_id=task_id, path=payload.path, content=payload.content)


@router.post("/{project_id}/setting/{task_id}/approve", response_model=Task)
def approve_setting(project_id: str, task_id: str, request: Request) -> Task:
    return NewBookService(request.app.state.workspace).approve_setting(project_id, task_id)
