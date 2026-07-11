from pathlib import Path

import pytest
from pydantic import ValidationError

from app.domain.errors import CanonContentError, WorkspacePathViolationError
from app.domain.project import ConfirmedContent, MemoryRecord, Project
from app.repositories.canon import CanonRepository
from app.repositories.workspace import WorkspaceRepository


def repository(tmp_path: Path) -> CanonRepository:
    workspace = WorkspaceRepository(tmp_path)
    workspace.create_project("story-01")
    return CanonRepository(workspace)


def test_project_yaml_round_trip_is_stable(tmp_path: Path) -> None:
    canon = repository(tmp_path)
    project = Project(id="story-01", title="长夜", language="zh-CN")
    canon.write_project(project)
    first = canon.project_file("story-01").read_bytes()

    assert canon.read_project("story-01") == project
    canon.write_project(canon.read_project("story-01"))
    assert canon.project_file("story-01").read_bytes() == first


def test_strict_models_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        Project.model_validate({"id": "story-01", "title": "书", "language": "zh-CN", "x": 1})


def test_confirmed_markdown_round_trip(tmp_path: Path) -> None:
    canon = repository(tmp_path)
    content = ConfirmedContent(markdown="# 第一章\n\n正文。\n")
    canon.write_markdown("story-01", "canon/chapters/0001.md", content)
    assert canon.read_markdown("story-01", "canon/chapters/0001.md") == content


def test_memory_yaml_round_trip(tmp_path: Path) -> None:
    canon = repository(tmp_path)
    memory = MemoryRecord(
        id="fact-001",
        kind="fact",
        status="active",
        source="canon/chapters/0001.md",
        quote="天在下雨",
    )
    canon.write_memory("story-01", "memory/facts/fact-001.yaml", memory)
    assert canon.read_memory("story-01", "memory/facts/fact-001.yaml") == memory


@pytest.mark.parametrize(
    "path",
    ["canon/chapters/a.txt", "memory/facts/a.md", ".tame-ink/drafts/a.md", "canon/../project.yaml"],
)
def test_rejects_unsupported_formal_paths(tmp_path: Path, path: str) -> None:
    canon = repository(tmp_path)
    with pytest.raises((WorkspacePathViolationError, CanonContentError)):
        canon.write_markdown("story-01", path, ConfirmedContent(markdown="ok\n"))


def test_rejects_empty_markdown() -> None:
    with pytest.raises(ValidationError):
        ConfirmedContent(markdown="   ")
