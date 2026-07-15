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
        if root.is_symlink():
            raise WorkspacePathViolationError(str(root))
        self.root = root.resolve()

    def project_path(self, project_id: str) -> Path:
        validate_project_id(project_id)
        projects_path = self.root / "projects"
        project_path = projects_path / project_id
        self._reject_symlink_components(projects_path)
        self._reject_symlink_components(project_path)
        projects = projects_path.resolve()
        result = project_path.resolve()
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

    def project_ids(self) -> list[str]:
        projects = self.root / "projects"
        if not projects.exists():
            return []
        if projects.is_symlink():
            raise WorkspacePathViolationError(str(projects))
        result: list[str] = []
        for path in sorted(projects.iterdir()):
            if path.is_symlink():
                raise WorkspacePathViolationError(str(path))
            if path.is_dir() and (path / "project.yaml").is_file():
                result.append(validate_project_id(path.name))
        return result

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

    @staticmethod
    def _reject_symlink_components(path: Path) -> None:
        current = Path(path.anchor)
        for part in path.parts[1:]:
            current /= part
            if current.is_symlink():
                raise WorkspacePathViolationError(str(path))
