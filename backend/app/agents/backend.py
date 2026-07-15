from fnmatch import fnmatch
from pathlib import PurePosixPath

import yaml
from deepagents.backends.protocol import (
    BackendProtocol,
    EditResult,
    FileDownloadResponse,
    FileInfo,
    FileUploadResponse,
    GlobResult,
    GrepMatch,
    GrepResult,
    LsResult,
    ReadResult,
    WriteResult,
)

from app.domain.errors import TameInkError, WorkspacePathViolationError
from app.domain.paths import iter_formal_files, validate_formal_path
from app.repositories.canon import CanonRepository
from app.repositories.drafts import DraftRepository


class NovelWorkspaceBackend(BackendProtocol):
    def __init__(
        self, canon: CanonRepository, drafts: DraftRepository, project_id: str, task_id: str
    ) -> None:
        self.canon = canon
        self.drafts = drafts
        self.project_id = project_id
        self.task_id = task_id

    @staticmethod
    def _parse(path: str) -> tuple[str, str]:
        if "\\" in path or not path.startswith("/"):
            raise WorkspacePathViolationError(path)
        if path == "/project.yaml":
            return "project", "project.yaml"
        parts = path.split("/")
        if len(parts) < 3 or parts[0] != "" or parts[1] not in {"canon", "memory", "drafts"}:
            raise WorkspacePathViolationError(path)
        if any(part in {"", ".", ".."} for part in parts[2:]):
            raise WorkspacePathViolationError(path)
        return parts[1], "/".join(parts[2:])

    def _read_text(self, path: str) -> str:
        root, relative = self._parse(path)
        if root == "project":
            return self.canon.project_file(self.project_id).read_text(encoding="utf-8")
        if root == "drafts":
            return self.drafts.read(self.project_id, self.task_id, relative)
        formal = f"{root}/{relative}"
        validate_formal_path(formal)
        if PurePosixPath(formal).suffix == ".md":
            return self.canon.read_markdown(self.project_id, formal).markdown
        memory = self.canon.read_memory(self.project_id, formal)
        return yaml.safe_dump(memory.model_dump(mode="json"), allow_unicode=True, sort_keys=True)

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> ReadResult:
        try:
            lines = self._read_text(file_path).splitlines(keepends=True)
            return ReadResult(
                file_data={"content": "".join(lines[offset : offset + limit]), "encoding": "utf-8"}
            )
        except TameInkError as error:
            return ReadResult(error=error.code)

    def write(self, file_path: str, content: str) -> WriteResult:
        try:
            root, relative = self._parse(file_path)
            if root != "drafts":
                raise WorkspacePathViolationError(file_path)
            self.drafts.write(self.project_id, self.task_id, relative, content, overwrite=False)
            return WriteResult(path=file_path)
        except TameInkError as error:
            return WriteResult(error=error.code)

    def edit(
        self, file_path: str, old_string: str, new_string: str, replace_all: bool = False
    ) -> EditResult:
        try:
            root, relative = self._parse(file_path)
            if root != "drafts":
                raise WorkspacePathViolationError(file_path)
            content = self.drafts.read(self.project_id, self.task_id, relative)
            if old_string == "":
                return EditResult(error="EDIT_TARGET_INVALID")
            occurrences = content.count(old_string)
            if (
                occurrences == 0
                or (occurrences > 1 and not replace_all)
                or old_string == new_string
            ):
                return EditResult(error="EDIT_TARGET_INVALID")
            updated = content.replace(old_string, new_string, -1 if replace_all else 1)
            self.drafts.write(self.project_id, self.task_id, relative, updated)
            return EditResult(path=file_path, occurrences=occurrences if replace_all else 1)
        except TameInkError as error:
            return EditResult(error=error.code)

    def _files(self) -> list[str]:
        project = self.canon.workspace.project_path(self.project_id)
        formal = [f"/{path.relative_to(project).as_posix()}" for path in iter_formal_files(project)]
        drafts = [
            f"/drafts/{path}" for path in self.drafts.list_files(self.project_id, self.task_id)
        ]
        return formal + drafts

    def ls(self, path: str) -> LsResult:
        try:
            if path == "/":
                return LsResult(
                    entries=[
                        {"path": f"/{name}", "is_dir": True}
                        for name in ("canon", "drafts", "memory")
                    ]
                )
            if "\\" in path or not path.startswith("/") or path.endswith("/"):
                raise WorkspacePathViolationError(path)
            parts = path.split("/")[1:]
            if not parts or parts[0] not in {"canon", "memory", "drafts"}:
                raise WorkspacePathViolationError(path)
            if any(part in {"", ".", ".."} for part in parts):
                raise WorkspacePathViolationError(path)
            prefix = path + "/"
            children: dict[str, FileInfo] = {}
            for item in self._files():
                if not item.startswith(prefix):
                    continue
                remainder = item[len(prefix) :]
                child_name, separator, _ = remainder.partition("/")
                child_path = prefix + child_name
                children[child_path] = {
                    "path": child_path,
                    "is_dir": bool(separator),
                }
            return LsResult(entries=[children[key] for key in sorted(children)])
        except TameInkError as error:
            return LsResult(error=error.code)

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        responses: list[FileUploadResponse] = []
        for path, payload in files:
            try:
                root, relative = self._parse(path)
                if root != "drafts":
                    raise WorkspacePathViolationError(path)
                content = payload.decode("utf-8")
                self.drafts.write(self.project_id, self.task_id, relative, content)
                responses.append(FileUploadResponse(path=path))
            except UnicodeDecodeError:
                responses.append(FileUploadResponse(path=path, error="DRAFT_ENCODING_INVALID"))
            except TameInkError as error:
                responses.append(FileUploadResponse(path=path, error=error.code))
        return responses

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        responses: list[FileDownloadResponse] = []
        for path in paths:
            try:
                content = self._read_text(path).encode("utf-8")
                responses.append(FileDownloadResponse(path=path, content=content))
            except TameInkError as error:
                responses.append(FileDownloadResponse(path=path, error=error.code))
        return responses

    def glob(self, pattern: str, path: str | None = None) -> GlobResult:
        base = path or "/"
        try:
            if base != "/":
                self._parse(base + "/placeholder" if base.count("/") == 1 else base)
            matches: list[FileInfo] = [
                {"path": item, "is_dir": False}
                for item in self._files()
                if item.startswith(base.rstrip("/") + "/")
                and fnmatch(
                    item, pattern if pattern.startswith("/") else f"{base.rstrip('/')}/{pattern}"
                )
            ]
            return GlobResult(matches=matches)
        except TameInkError as error:
            return GlobResult(error=error.code)

    def grep(self, pattern: str, path: str | None = None, glob: str | None = None) -> GrepResult:
        matches: list[GrepMatch] = []
        glob_result = self.glob(glob or "**", path)
        if glob_result.error is not None:
            return GrepResult(error=glob_result.error)
        for file_path in glob_result.matches or []:
            virtual = file_path["path"]
            read = self.read(virtual, 0, 1_000_000)
            if read.file_data is None:
                continue
            for number, line in enumerate(read.file_data["content"].splitlines(), 1):
                if pattern in line:
                    matches.append({"path": virtual, "line": number, "text": line})
        return GrepResult(matches=matches)
