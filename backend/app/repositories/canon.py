import os
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from app.domain.errors import CanonContentError
from app.domain.project import ConfirmedContent, MemoryRecord, Project
from app.repositories.workspace import WorkspaceRepository


class CanonRepository:
    def __init__(self, workspace: WorkspaceRepository) -> None:
        self.workspace = workspace

    def project_file(self, project_id: str) -> Path:
        return self.workspace.resolve_project_path(project_id, "project.yaml")

    def write_project(self, project: Project) -> None:
        self._write_yaml(self.project_file(project.id), project.model_dump(mode="json"))

    def read_project(self, project_id: str) -> Project:
        return Project.model_validate(self._read_yaml(self.project_file(project_id)))

    def write_markdown(self, project_id: str, relative: str, content: ConfirmedContent) -> None:
        path = self._formal_path(project_id, relative, "canon", ".md")
        self._replace(path, content.markdown.encode())

    def read_markdown(self, project_id: str, relative: str) -> ConfirmedContent:
        path = self._formal_path(project_id, relative, "canon", ".md")
        return ConfirmedContent(markdown=path.read_text())

    def write_memory(self, project_id: str, relative: str, memory: MemoryRecord) -> None:
        path = self._formal_path(project_id, relative, "memory", ".yaml")
        self._write_yaml(path, memory.model_dump(mode="json"))

    def read_memory(self, project_id: str, relative: str) -> MemoryRecord:
        path = self._formal_path(project_id, relative, "memory", ".yaml")
        return MemoryRecord.model_validate(self._read_yaml(path))

    def _formal_path(self, project_id: str, relative: str, root: str, suffix: str) -> Path:
        pure = PurePosixPath(relative)
        if (
            pure.is_absolute()
            or ".." in pure.parts
            or pure.parts[:1] != (root,)
            or pure.suffix != suffix
        ):
            raise CanonContentError(relative)
        return self.workspace.resolve_project_path(project_id, relative)

    def _write_yaml(self, path: Path, data: dict[str, Any]) -> None:
        payload = yaml.safe_dump(data, allow_unicode=True, sort_keys=True).encode()
        self._replace(path, payload)

    @staticmethod
    def _read_yaml(path: Path) -> Any:
        return yaml.safe_load(path.read_text())

    @staticmethod
    def _replace(path: Path, payload: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        with temporary.open("wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
