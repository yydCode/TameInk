from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import yaml

from app.domain.errors import TameInkError, WorkspacePathViolationError
from app.domain.paths import iter_formal_files, validate_formal_path
from app.repositories.canon import CanonRepository
from app.repositories.drafts import DraftRepository


@dataclass
class ReadResult:
    content: str | None = None
    error: str | None = None


@dataclass
class WriteResult:
    path: str | None = None
    error: str | None = None


class NovelWorkspaceBackend:
    """虚拟文件系统后端，映射 /canon、/drafts、/memory、/skills 路径到实际文件。

    不再实现 deepagents BackendProtocol，只保留 runtime.py 和 context.py 需要的读取能力。
    """

    def __init__(
        self,
        canon: CanonRepository,
        drafts: DraftRepository,
        project_id: str,
        task_id: str,
        *,
        skill_root: Path | None = None,
        read_allowlist: frozenset[str] | None = None,
    ) -> None:
        self.canon = canon
        self.drafts = drafts
        self.project_id = project_id
        self.task_id = task_id
        self.skill_root = skill_root.resolve() if skill_root is not None else None
        self.read_allowlist = read_allowlist

    @staticmethod
    def _parse(path: str) -> tuple[str, str]:
        if "\\" in path or not path.startswith("/"):
            raise WorkspacePathViolationError(path)
        if path == "/project.yaml":
            return "project", "project.yaml"
        parts = path.split("/")
        if (
            len(parts) < 3
            or parts[0] != ""
            or parts[1]
            not in {
                "canon",
                "memory",
                "drafts",
                "skills",
            }
        ):
            raise WorkspacePathViolationError(path)
        if any(part in {"", ".", ".."} for part in parts[2:]):
            raise WorkspacePathViolationError(path)
        return parts[1], "/".join(parts[2:])

    def _read_text(self, path: str) -> str:
        root, relative = self._parse(path)
        formal = "project.yaml" if root == "project" else f"{root}/{relative}"
        if (
            root != "skills"
            and self.read_allowlist is not None
            and formal not in self.read_allowlist
        ):
            raise WorkspacePathViolationError(path)
        if root == "project":
            return self.canon.project_file(self.project_id).read_text(encoding="utf-8")
        if root == "drafts":
            return self.drafts.read(self.project_id, self.task_id, relative)
        if root == "skills":
            return self._read_skill(relative)
        validate_formal_path(formal)
        if PurePosixPath(formal).suffix == ".md":
            return self.canon.read_markdown(self.project_id, formal).markdown
        if formal == "canon/commercial.yaml":
            return yaml.safe_dump(
                self.canon.read_commercial(self.project_id).model_dump(mode="json"),
                allow_unicode=True,
                sort_keys=True,
            )
        memory = self.canon.read_memory(self.project_id, formal)
        return yaml.safe_dump(memory.model_dump(mode="json"), allow_unicode=True, sort_keys=True)

    def _read_skill(self, relative: str) -> str:
        if self.skill_root is None:
            raise WorkspacePathViolationError(relative)
        candidate = self.skill_root.joinpath(*PurePosixPath(relative).parts)
        current = self.skill_root
        for part in PurePosixPath(relative).parts:
            current /= part
            if current.is_symlink():
                raise WorkspacePathViolationError(relative)
        try:
            candidate.resolve(strict=True).relative_to(self.skill_root)
            return candidate.read_text(encoding="utf-8")
        except (OSError, RuntimeError, ValueError) as error:
            raise WorkspacePathViolationError(relative) from error

    def read(self, file_path: str, offset: int = 0, limit: int = 1_000_000) -> ReadResult:
        """读取虚拟路径对应的文件内容。"""
        try:
            content = self._read_text(file_path)
            return ReadResult(content=content)
        except TameInkError as error:
            return ReadResult(error=error.code)

    def write(self, file_path: str, content: str) -> WriteResult:
        """写入草稿文件（仅限 /drafts/ 路径）。"""
        try:
            root, relative = self._parse(file_path)
            if root != "drafts":
                raise WorkspacePathViolationError(file_path)
            self.drafts.write(self.project_id, self.task_id, relative, content, overwrite=False)
            return WriteResult(path=file_path)
        except TameInkError as error:
            return WriteResult(error=error.code)

    def files(self) -> list[str]:
        """列出所有可用文件路径（受 read_allowlist 过滤）。"""
        project = self.canon.workspace.project_path(self.project_id)
        formal = [f"/{path.relative_to(project).as_posix()}" for path in iter_formal_files(project)]
        drafts = [
            f"/drafts/{path}" for path in self.drafts.list_files(self.project_id, self.task_id)
        ]
        skills: list[str] = []
        if self.skill_root is not None:
            for path in sorted(self.skill_root.rglob("*")):
                if path.is_symlink():
                    raise WorkspacePathViolationError(path.relative_to(self.skill_root).as_posix())
                if path.is_file():
                    skills.append(f"/skills/{path.relative_to(self.skill_root).as_posix()}")
        files = formal + drafts + skills
        if self.read_allowlist is None:
            return files
        return [
            path
            for path in files
            if path.startswith("/skills/") or path.removeprefix("/") in self.read_allowlist
        ]
