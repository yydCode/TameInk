from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, ConfigDict

from app.domain.task import Task, TaskEvent, TaskKind
from app.repositories.database import DatabaseRepository
from app.repositories.drafts import DraftRepository
from app.repositories.tasks import TasksRepository
from app.repositories.workspace import WorkspaceRepository
from app.workflows.task_service import TaskService

router = APIRouter(prefix="/projects/{project_id}/tasks", tags=["tasks"])


class CreateTaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: TaskKind


def task_service(request: Request, project_id: str) -> TaskService:
    workspace: WorkspaceRepository = request.app.state.workspace
    database = DatabaseRepository(workspace)
    return TaskService(TasksRepository(database, project_id))


Service = Annotated[TaskService, Depends(task_service)]


@router.post("", response_model=Task, status_code=status.HTTP_201_CREATED)
def create_task(payload: CreateTaskRequest, service: Service) -> Task:
    return service.create(payload.kind)


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
