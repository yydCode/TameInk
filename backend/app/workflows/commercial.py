from typing import Any

import yaml
from pydantic import ValidationError

from app.domain.commercial import CommercialProfile
from app.domain.errors import CanonContentError
from app.domain.revision import RevisionWrite
from app.domain.task import Task, TaskKind
from app.repositories.database import DatabaseRepository
from app.repositories.drafts import DraftRepository
from app.repositories.revisions import RevisionRepository
from app.repositories.tasks import TasksRepository
from app.repositories.workspace import WorkspaceRepository
from app.workflows.task_service import TaskService

COMMERCIAL_PATH = "canon/commercial.yaml"
COMMERCIAL_DRAFT = "commercial.yaml"


class CommercialService:
    def __init__(self, workspace: WorkspaceRepository) -> None:
        self.workspace = workspace

    def read(self, project_id: str) -> CommercialProfile | None:
        path = self.workspace.resolve_project_path(project_id, COMMERCIAL_PATH)
        if not path.is_file():
            return None
        try:
            return CommercialProfile.model_validate(yaml.safe_load(path.read_text()))
        except (OSError, yaml.YAMLError, ValidationError) as error:
            raise CanonContentError(COMMERCIAL_PATH) from error

    def create(self, project_id: str, profile: CommercialProfile) -> Task:
        service = self._tasks(project_id)
        task = service.create(TaskKind.WRITE)
        service.start(task.id)
        self.write_draft(project_id, task.id, profile)
        return service.await_approval(task.id)

    def write_draft(
        self, project_id: str, task_id: str, profile: CommercialProfile
    ) -> CommercialProfile:
        self._tasks(project_id).get(task_id)
        DraftRepository(self.workspace).write(
            project_id, task_id, COMMERCIAL_DRAFT, self.serialize(profile)
        )
        return profile

    def read_draft(self, project_id: str, task_id: str) -> CommercialProfile:
        content = DraftRepository(self.workspace).read(project_id, task_id, COMMERCIAL_DRAFT)
        try:
            data: Any = yaml.safe_load(content)
            return CommercialProfile.model_validate(data)
        except (yaml.YAMLError, ValidationError) as error:
            raise CanonContentError(COMMERCIAL_DRAFT) from error

    def approve(self, project_id: str, task_id: str) -> Task:
        service = self._tasks(project_id)
        service.approve(task_id)
        try:
            profile = self.read_draft(project_id, task_id)
            revisions = RevisionRepository(self.workspace)
            revisions.confirm(
                project_id,
                RevisionWrite(
                    path=COMMERCIAL_PATH,
                    content=self.serialize(profile),
                    message="确认：商业定位",
                ),
                revisions.current_revision(project_id),
            )
            DatabaseRepository(self.workspace).rebuild(project_id)
        except Exception:
            service.fail(task_id)
            raise
        return service.complete(task_id)

    @staticmethod
    def serialize(profile: CommercialProfile) -> str:
        return yaml.safe_dump(
            profile.model_dump(mode="json"), allow_unicode=True, sort_keys=True
        )

    def _tasks(self, project_id: str) -> TaskService:
        return TaskService(
            TasksRepository(DatabaseRepository(self.workspace), project_id)
        )
