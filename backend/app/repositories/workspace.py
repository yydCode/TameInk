from pathlib import Path

from app.domain.errors import WorkspacePathViolationError
from app.domain.paths import validate_project_id

PROJECT_DIRS = (
    "canon/volumes",
    "canon/characters",
    "canon/world",
    "canon/chapters",
    "memory/summaries/volumes",
    "memory/summaries/chapters",
    "memory/facts",
    "memory/events",
    "memory/relationships",
    "memory/foreshadowing",
    "imports/originals",
    ".tame-ink/drafts",
    ".tame-ink/runs",
)


class WorkspaceRepository:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def project_path(self, project_id: str) -> Path:
        validate_project_id(project_id)
        projects = (self.root / "projects").resolve()
        result = (projects / project_id).resolve()
        try:
            result.relative_to(projects)
        except ValueError as error:
            raise WorkspacePathViolationError(project_id) from error
        return result

    def create_project(self, project_id: str) -> Path:
        project = self.project_path(project_id)
        for relative in PROJECT_DIRS:
            (project / relative).mkdir(parents=True, exist_ok=True)
        return project

    def resolve_project_path(self, project_id: str, relative: str | Path) -> Path:
        project = self.project_path(project_id)
        candidate = Path(relative)
        if candidate.is_absolute():
            raise WorkspacePathViolationError(str(relative))
        resolved = (project / candidate).resolve()
        try:
            resolved.relative_to(project)
        except ValueError as error:
            raise WorkspacePathViolationError(str(relative)) from error
        return resolved
