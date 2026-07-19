import os
from pathlib import Path, PurePosixPath
from uuid import UUID

from app.domain.errors import StorageReadError, StorageWriteError, WorkspacePathViolationError
from app.repositories.workspace import WorkspaceRepository


class DraftRepository:
    def __init__(self, workspace: WorkspaceRepository) -> None:
        self.workspace = workspace

    def root(self, project_id: str, task_id: str) -> Path:
        try:
            if str(UUID(task_id)) != task_id:
                raise ValueError
        except ValueError as error:
            raise WorkspacePathViolationError(task_id) from error
        return self.workspace.resolve_project_path(project_id, Path(".tame-ink/drafts") / task_id)

    def resolve(self, project_id: str, task_id: str, relative: str) -> Path:
        pure = PurePosixPath(relative)
        parts = relative.split("/")
        if "\\" in relative or pure.is_absolute() or any(part in {"", ".", ".."} for part in parts):
            raise WorkspacePathViolationError(relative)
        root = self.root(project_id, task_id)
        candidate = root.joinpath(*parts)
        current = root
        for part in parts:
            current /= part
            if current.is_symlink():
                raise WorkspacePathViolationError(relative)
        try:
            candidate.resolve().relative_to(root.resolve())
        except ValueError as error:
            raise WorkspacePathViolationError(relative) from error
        return candidate

    def read(self, project_id: str, task_id: str, relative: str) -> str:
        path = self.resolve(project_id, task_id, relative)
        try:
            return path.read_text()
        except OSError as error:
            raise StorageReadError(relative) from error

    def write(
        self, project_id: str, task_id: str, relative: str, content: str, *, overwrite: bool = True
    ) -> None:
        path = self.resolve(project_id, task_id, relative)
        if not overwrite and path.exists():
            raise StorageWriteError(relative)
        temporary = path.with_name(f".{path.name}.tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with temporary.open("w") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except OSError as error:
            raise StorageWriteError(relative) from error

    def list_files(self, project_id: str, task_id: str) -> list[str]:
        root = self.root(project_id, task_id)
        if not root.exists():
            return []
        files: list[str] = []
        for path in sorted(root.rglob("*")):
            if path.is_symlink():
                raise WorkspacePathViolationError(path.relative_to(root).as_posix())
            if path.is_file():
                files.append(path.relative_to(root).as_posix())
        return files

    def discard_candidates(
        self, project_id: str, task_id: str, keep: frozenset[str] = frozenset({"request.json"})
    ) -> None:
        for relative in self.list_files(project_id, task_id):
            if relative in keep:
                continue
            path = self.resolve(project_id, task_id, relative)
            try:
                path.unlink()
            except OSError as error:
                raise StorageWriteError(relative) from error
