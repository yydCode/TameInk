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


def iter_formal_files(project: Path) -> Iterator[Path]:
    for exact in sorted(EXACT_FILES):
        path = project.joinpath(*exact)
        if path.is_file():
            yield path
    for parent, suffix in sorted(LEAF_DIRECTORIES.items()):
        directory = project.joinpath(*parent)
        if directory.is_dir():
            for path in sorted(directory.glob(f"*{suffix}")):
                if path.is_file():
                    validate_formal_path(path.relative_to(project).as_posix())
                    yield path
