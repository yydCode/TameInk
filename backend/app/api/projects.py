from fastapi import APIRouter, Request, status
from pydantic import BaseModel, ConfigDict, Field

from app.domain.errors import CanonVersionConflictError
from app.domain.project import Project
from app.domain.task import Task
from app.repositories.canon import CanonRepository
from app.repositories.database import DatabaseRepository
from app.repositories.drafts import DraftRepository
from app.repositories.revisions import RevisionRepository
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
    base_revision: str | None


class DraftContentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    task_id: str
    path: str
    content: str
    revision: str | None


class WorkflowStatus(BaseModel):
    """Confirmed creative milestones required before chapter generation."""

    setting_confirmed: bool
    outline_confirmed: bool
    volume_one_confirmed: bool
    commercial_confirmed: bool


@router.post("", status_code=status.HTTP_201_CREATED)
def create_project(payload: CreateProjectRequest, request: Request) -> dict[str, object]:
    workspace: WorkspaceRepository = request.app.state.workspace
    result = NewBookService(workspace).create(
        NewBookRequest(**payload.model_dump(exclude={"setting_draft"})), payload.setting_draft
    )
    return {"project": result.project, "task": result.task}


@router.get("", response_model=list[Project])
def list_projects(request: Request) -> list[Project]:
    workspace: WorkspaceRepository = request.app.state.workspace
    canon = CanonRepository(workspace)
    return [canon.read_project(project_id) for project_id in workspace.project_ids()]


@router.get("/{project_id}", response_model=Project)
def get_project(project_id: str, request: Request) -> Project:
    workspace: WorkspaceRepository = request.app.state.workspace
    return CanonRepository(workspace).read_project(project_id)


@router.get("/{project_id}/workflow-status", response_model=WorkflowStatus)
def get_workflow_status(project_id: str, request: Request) -> WorkflowStatus:
    workspace: WorkspaceRepository = request.app.state.workspace
    # Resolve through the workspace repository so the endpoint keeps the same path checks as writes.
    return WorkflowStatus(
        setting_confirmed=workspace.resolve_project_path(
            project_id, "canon/world/setting.md"
        ).is_file(),
        outline_confirmed=workspace.resolve_project_path(project_id, "canon/outline.md").is_file(),
        volume_one_confirmed=workspace.resolve_project_path(
            project_id, "canon/volumes/1.md"
        ).is_file(),
        commercial_confirmed=workspace.resolve_project_path(
            project_id, "canon/commercial.yaml"
        ).is_file(),
    )


@router.get("/{project_id}/drafts/{task_id}", response_model=DraftContentResponse)
def get_draft(
    project_id: str, task_id: str, path: str, request: Request
) -> DraftContentResponse:
    workspace: WorkspaceRepository = request.app.state.workspace
    TasksRepository(DatabaseRepository(workspace), project_id).get(task_id)
    content = DraftRepository(workspace).read(project_id, task_id, path)
    revision = RevisionRepository(workspace).current_revision(project_id)
    return DraftContentResponse(task_id=task_id, path=path, content=content, revision=revision)


@router.put("/{project_id}/drafts/{task_id}", response_model=DraftContentResponse)
def save_draft(
    project_id: str, task_id: str, payload: DraftContentRequest, request: Request
) -> DraftContentResponse:
    workspace: WorkspaceRepository = request.app.state.workspace
    TasksRepository(DatabaseRepository(workspace), project_id).get(task_id)
    revision = RevisionRepository(workspace).current_revision(project_id)
    if payload.base_revision != revision:
        raise CanonVersionConflictError("formal content changed while editing")
    DraftRepository(workspace).write(project_id, task_id, payload.path, payload.content)
    return DraftContentResponse(
        task_id=task_id,
        path=payload.path,
        content=payload.content,
        revision=revision,
    )


@router.post("/{project_id}/setting/{task_id}/approve", response_model=Task)
def approve_setting(project_id: str, task_id: str, request: Request) -> Task:
    return NewBookService(request.app.state.workspace).approve_setting(project_id, task_id)
