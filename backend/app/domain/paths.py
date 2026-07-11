import os
import re
from collections.abc import Iterator
from pathlib import Path, PurePosixPath

from app.domain.errors import InvalidProjectIdError, WorkspacePathViolationError

PROJECT_ID_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")
LEAF_DIRECTORIES = {
    ("canon", "volumes"): ".md",
    ("canon", "characters"): ".md",
    ("canon", "world"): ".md",
    ("canon", "chapters"): ".md",
    ("memory", "summaries", "volumes"): ".md",
    ("memory", "summaries", "chapters"): ".md",
    ("memory", "facts"): ".yaml",
    ("memory", "events"): ".yaml",
    ("memory", "relationships"): ".yaml",
    ("memory", "foreshadowing"): ".yaml",
}
EXACT_FILES = {
    ("project.yaml",),
    ("canon", "premise.md"),
    ("canon", "outline.md"),
    ("memory", "summaries", "book.md"),
}


def validate_project_id(value: str) -> str:
    if PROJECT_ID_PATTERN.fullmatch(value) is None:
        raise InvalidProjectIdError(value)
    return value


def validate_formal_path(value: str) -> PurePosixPath:
    raw_parts = value.split("/")
    pure = PurePosixPath(value)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in raw_parts):
        raise WorkspacePathViolationError(value)
    parts = tuple(raw_parts)
    if parts in EXACT_FILES:
        return pure
    parent = parts[:-1]
    suffix = PurePosixPath(parts[-1]).suffix
    if parent not in LEAF_DIRECTORIES or LEAF_DIRECTORIES[parent] != suffix:
        raise WorkspacePathViolationError(value)
    if len(parts[-1]) <= len(suffix):
        raise WorkspacePathViolationError(value)
    return pure


def resolve_formal_path(project: Path, value: str) -> Path:
    pure = validate_formal_path(value)
    return _resolve_within_project(project, pure.parts, value)


def _resolve_within_project(project: Path, parts: tuple[str, ...], display: str) -> Path:
    try:
        root = project.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise WorkspacePathViolationError(display) from error
    candidate = project
    for part in parts:
        candidate /= part
        if candidate.is_symlink():
            raise WorkspacePathViolationError(display)
        try:
            candidate.resolve(strict=False).relative_to(root)
        except (OSError, RuntimeError, ValueError) as error:
            raise WorkspacePathViolationError(display) from error
    return candidate


def iter_formal_files(project: Path) -> Iterator[Path]:
    _reject_formal_tree_symlinks(project)
    for exact in sorted(EXACT_FILES):
        relative = "/".join(exact)
        path = resolve_formal_path(project, relative)
        if path.is_file():
            yield path
    for parent, suffix in sorted(LEAF_DIRECTORIES.items()):
        display = "/".join(parent)
        directory = _resolve_within_project(project, parent, display)
        if directory.is_dir():
            for path in sorted(directory.glob(f"*{suffix}")):
                if path.is_file():
                    relative = path.relative_to(project).as_posix()
                    yield resolve_formal_path(project, relative)


def _reject_formal_tree_symlinks(project: Path) -> None:
    for root_name in ("canon", "memory"):
        root = project / root_name
        if root.is_symlink():
            raise WorkspacePathViolationError(root_name)
        if not root.exists():
            continue
        for current, directories, files in os.walk(root, followlinks=False):
            current_path = Path(current)
            for name in directories + files:
                candidate = current_path / name
                if candidate.is_symlink():
                    raise WorkspacePathViolationError(candidate.relative_to(project).as_posix())
