import json
from collections.abc import Sequence

from app.domain.errors import WorkflowGateError
from app.domain.revision import RevisionWrite
from app.domain.task import Task, TaskKind
from app.repositories.database import DatabaseRepository
from app.repositories.drafts import DraftRepository
from app.repositories.revisions import RevisionRepository
from app.repositories.tasks import TasksRepository
from app.repositories.workspace import WorkspaceRepository
from app.workflows.memory import MemoryService
from app.workflows.task_service import TaskService


class ChapterService:
    def __init__(self, workspace: WorkspaceRepository) -> None:
        self.workspace = workspace

    def start(
        self,
        project_id: str,
        chapter_id: str,
        plan: str,
        draft: str,
        issues: Sequence[dict[str, str]],
        volume_id: str = "1",
    ) -> Task:
        project = self.workspace.project_path(project_id)
        if (
            not (project / "canon/outline.md").is_file()
            or not (project / "canon/volumes" / f"{volume_id}.md").is_file()
        ):
            raise WorkflowGateError("approved book outline and volume are required")
        service = TaskService(TasksRepository(DatabaseRepository(self.workspace), project_id))
        task = service.create(TaskKind.WRITE)
        service.start(task.id)
        drafts = DraftRepository(self.workspace)
        drafts.write(project_id, task.id, "plan.md", plan)
        drafts.write(project_id, task.id, "chapter.md", self._apply_issues(draft, issues))
        drafts.write(
            project_id,
            task.id,
            "run.json",
            json.dumps(
                {"project_id": project_id, "chapter_id": chapter_id, "volume_id": volume_id}
            ),
        )
        return service.await_approval(task.id)

    def approve(self, project_id: str, task_id: str, chapter_id: str, volume_id: str = "1") -> Task:
        service = TaskService(TasksRepository(DatabaseRepository(self.workspace), project_id))
        service.approve(task_id)
        try:
            drafts = DraftRepository(self.workspace)
            manifest = json.loads(drafts.read(project_id, task_id, "run.json"))
            if manifest["project_id"] != project_id or manifest["chapter_id"] != chapter_id:
                raise WorkflowGateError("chapter approval does not match its run manifest")
            stored_volume_id = str(manifest["volume_id"])
            content = drafts.read(project_id, task_id, "chapter.md")
            revisions = RevisionRepository(self.workspace)
            revisions.confirm(
                project_id,
                RevisionWrite(
                    path=f"canon/chapters/{chapter_id}.md",
                    content=content,
                    message=f"确认：章节 {chapter_id}",
                ),
                revisions.current_revision(project_id),
            )
            MemoryService(self.workspace).derive_summaries(
                project_id, chapter_id, stored_volume_id, content
            )
            DatabaseRepository(self.workspace).rebuild(project_id)
        except Exception:
            service.fail(task_id)
            raise
        return service.complete(task_id)

    @staticmethod
    def _apply_issues(draft: str, issues: Sequence[dict[str, str]]) -> str:
        for issue in issues:
            if not issue.get("id") or not issue.get("citation"):
                raise WorkflowGateError("chapter issue requires an id and exact citation")
            target = issue.get("target")
            replacement = issue.get("replacement")
            if not target or replacement is None or draft.count(target) != 1:
                raise WorkflowGateError("revision must target one cited local passage")
            draft = draft.replace(target, replacement, 1)
        return draft
