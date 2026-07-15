from app.domain.errors import WorkflowGateError
from app.domain.revision import RevisionWrite
from app.domain.task import Task, TaskKind
from app.repositories.database import DatabaseRepository
from app.repositories.drafts import DraftRepository
from app.repositories.revisions import RevisionRepository
from app.repositories.tasks import TasksRepository
from app.repositories.workspace import WorkspaceRepository
from app.workflows.task_service import TaskService


class OutlineService:
    def __init__(self, workspace: WorkspaceRepository) -> None:
        self.workspace = workspace

    def create_book(self, project_id: str, content: str) -> Task:
        return self._create(project_id, "book-outline.md", content)

    def approve_book(self, project_id: str, task_id: str) -> Task:
        return self._approve(
            project_id, task_id, "book-outline.md", "canon/outline.md", "确认：全书大纲"
        )

    def create_volume(self, project_id: str, volume_id: str, content: str) -> Task:
        if not self.workspace.resolve_project_path(project_id, "canon/outline.md").is_file():
            raise WorkflowGateError("approved book outline is required")
        return self._create(project_id, f"volume-{volume_id}.md", content)

    def approve_volume(self, project_id: str, task_id: str, volume_id: str) -> Task:
        return self._approve(
            project_id,
            task_id,
            f"volume-{volume_id}.md",
            f"canon/volumes/{volume_id}.md",
            f"确认：分卷大纲 {volume_id}",
        )

    def _create(self, project_id: str, draft_name: str, content: str) -> Task:
        database = DatabaseRepository(self.workspace)
        service = TaskService(TasksRepository(database, project_id))
        task = service.create(TaskKind.WRITE)
        service.start(task.id)
        DraftRepository(self.workspace).write(project_id, task.id, draft_name, content)
        return service.await_approval(task.id)

    def _approve(
        self, project_id: str, task_id: str, draft_name: str, formal_path: str, message: str
    ) -> Task:
        service = TaskService(TasksRepository(DatabaseRepository(self.workspace), project_id))
        service.approve(task_id)
        try:
            content = DraftRepository(self.workspace).read(project_id, task_id, draft_name)
            revisions = RevisionRepository(self.workspace)
            revisions.confirm(
                project_id,
                RevisionWrite(path=formal_path, content=content, message=message),
                revisions.current_revision(project_id),
            )
            DatabaseRepository(self.workspace).rebuild(project_id)
        except Exception:
            service.fail(task_id)
            raise
        return service.complete(task_id)
