import os
from pathlib import Path
from typing import Any, TypeVar

import yaml
from pydantic import BaseModel, ValidationError

from app.domain.errors import (
    CanonContentError,
    StorageReadError,
    StorageWriteError,
    WorkspacePathViolationError,
)
from app.domain.paths import resolve_formal_path, validate_formal_path
from app.domain.project import ConfirmedContent, MemoryRecord, Project
from app.repositories.workspace import WorkspaceRepository

ModelT = TypeVar("ModelT", bound=BaseModel)


class CanonRepository:
    def __init__(self, workspace: WorkspaceRepository) -> None:
        self.workspace = workspace

    def project_file(self, project_id: str) -> Path:
        return self.workspace.resolve_project_path(project_id, "project.yaml")

    def write_project(self, project: Project) -> None:
        self._write_yaml(self.project_file(project.id), project.model_dump(mode="json"))

    def read_project(self, project_id: str) -> Project:
        return self._validate(Project, self._read_yaml(self.project_file(project_id)))

    def write_markdown(self, project_id: str, relative: str, content: ConfirmedContent) -> None:
        path = self._formal_path(project_id, relative, ".md")
        self._replace(path, content.markdown.encode())

    def read_markdown(self, project_id: str, relative: str) -> ConfirmedContent:
        path = self._formal_path(project_id, relative, ".md")
        return self._validate(ConfirmedContent, {"markdown": self._read_text(path)})

    def write_memory(self, project_id: str, relative: str, memory: MemoryRecord) -> None:
        path = self._formal_path(project_id, relative, ".yaml")
        self._write_yaml(path, memory.model_dump(mode="json"))

    def read_memory(self, project_id: str, relative: str) -> MemoryRecord:
        path = self._formal_path(project_id, relative, ".yaml")
        return self._validate(MemoryRecord, self._read_yaml(path))

    def _formal_path(self, project_id: str, relative: str, suffix: str) -> Path:
        pure = validate_formal_path(relative)
        if pure.suffix != suffix:
            raise WorkspacePathViolationError(relative)
        return resolve_formal_path(self.workspace.project_path(project_id), relative)

    def _write_yaml(self, path: Path, data: dict[str, Any]) -> None:
        try:
            payload = yaml.safe_dump(data, allow_unicode=True, sort_keys=True).encode()
        except yaml.YAMLError as error:
            raise CanonContentError(str(path)) from error
        self._replace(path, payload)

    def _read_yaml(self, path: Path) -> Any:
        try:
            return yaml.safe_load(self._read_text(path))
        except yaml.YAMLError as error:
            raise CanonContentError(str(path)) from error

    @staticmethod
    def _read_text(path: Path) -> str:
        try:
            return path.read_text()
        except OSError as error:
            raise StorageReadError(str(path)) from error

    @staticmethod
    def _validate(model: type[ModelT], data: Any) -> ModelT:
        try:
            return model.model_validate(data)
        except ValidationError as error:
            raise CanonContentError(model.__name__) from error

    @staticmethod
    def _replace(path: Path, payload: bytes) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(f".{path.name}.tmp")
            with temporary.open("wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        except OSError as error:
            raise StorageWriteError(str(path)) from error
