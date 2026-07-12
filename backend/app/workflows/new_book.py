from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from app.domain.project import Project
from app.domain.revision import RevisionWrite
from app.domain.task import Task, TaskKind
from app.repositories.canon import CanonRepository
from app.repositories.database import DatabaseRepository
from app.repositories.drafts import DraftRepository
from app.repositories.revisions import RevisionRepository
from app.repositories.tasks import TasksRepository
from app.repositories.workspace import WorkspaceRepository
from app.workflows.task_service import TaskService


class NewBookRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    project_id: str
    title: str = Field(min_length=1)
    genre: str = Field(min_length=1)
    target_words: int = Field(gt=0)
    constraints: str = Field(min_length=1)


@dataclass(frozen=True)
class NewBookCreated:
    project: Project
    task: Task


class NewBookService:
    def __init__(self, workspace: WorkspaceRepository) -> None:
        self.workspace = workspace

    def create(self, request: NewBookRequest, setting_draft: str) -> NewBookCreated:
        self.workspace.create_project(request.project_id)
        canon = CanonRepository(self.workspace)
        project = Project(
            id=request.project_id,
            title=request.title,
            language="zh-CN",
            genre=request.genre,
            target_words=request.target_words,
            constraints=request.constraints,
        )
        canon.write_project(project)
        database = DatabaseRepository(self.workspace)
        database.initialize(request.project_id)
        RevisionRepository(self.workspace).current_revision(request.project_id)
        tasks = TaskService(TasksRepository(database, request.project_id))
        task = tasks.create(TaskKind.WRITE)
        tasks.start(task.id)
        DraftRepository(self.workspace).write(
            request.project_id, task.id, "setting.md", setting_draft
        )
        task = tasks.await_approval(task.id)
        return NewBookCreated(project, task)

    def approve_setting(self, project_id: str, task_id: str) -> Task:
        database = DatabaseRepository(self.workspace)
        service = TaskService(TasksRepository(database, project_id))
        service.approve(task_id)
        try:
            content = DraftRepository(self.workspace).read(project_id, task_id, "setting.md")
            revisions = RevisionRepository(self.workspace)
            revisions.confirm(
                project_id,
                RevisionWrite(
                    path="canon/world/setting.md", content=content, message="确认：故事设定"
                ),
                revisions.current_revision(project_id),
            )
            DatabaseRepository(self.workspace).rebuild(project_id)
        except Exception:
            service.fail(task_id)
            raise
        return service.complete(task_id)
