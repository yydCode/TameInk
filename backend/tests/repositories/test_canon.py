from pathlib import Path

import pytest
from pydantic import ValidationError

from app.domain.errors import (
    CanonContentError,
    StorageReadError,
    StorageWriteError,
    WorkspacePathViolationError,
)
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


@pytest.mark.parametrize(
    "path",
    [
        "canon/premise.md",
        "canon/outline.md",
        "canon/volumes/volume-01.md",
        "canon/characters/hero.md",
        "canon/world/city.md",
        "canon/chapters/0001.md",
        "memory/summaries/book.md",
        "memory/summaries/volumes/volume-01.md",
        "memory/summaries/chapters/0001.md",
    ],
)
def test_allows_only_document_paths_from_the_formal_whitelist(tmp_path: Path, path: str) -> None:
    canon = repository(tmp_path)
    content = ConfirmedContent(markdown="内容\n")

    canon.write_markdown("story-01", path, content)

    assert canon.read_markdown("story-01", path) == content


@pytest.mark.parametrize(
    "path",
    [
        "canon/arbitrary.md",
        "canon/chapters/nested/0001.md",
        "canon/chapters/.",
        "memory/summaries/other.md",
        "memory/facts/nested/fact.yaml",
        "memory/facts/fact.md",
    ],
)
def test_rejects_paths_outside_exact_formal_whitelist(tmp_path: Path, path: str) -> None:
    canon = repository(tmp_path)

    with pytest.raises(WorkspacePathViolationError):
        canon.write_markdown("story-01", path, ConfirmedContent(markdown="内容\n"))


@pytest.mark.parametrize(
    "data",
    [
        {"id": "Upper", "title": "书", "language": "zh-CN"},
        {"id": "story-01", "title": "   ", "language": "zh-CN"},
        {"id": "story-01", "title": "书", "language": "   "},
    ],
)
def test_project_schema_rejects_invalid_identity_and_blank_fields(data: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        Project.model_validate(data)


@pytest.mark.parametrize("field", ["id", "source", "quote"])
def test_memory_schema_rejects_blank_required_fields(field: str) -> None:
    data = {
        "id": "fact-001",
        "kind": "fact",
        "status": "active",
        "source": "canon/chapters/0001.md",
        "quote": "原文",
    }
    data[field] = "   "

    with pytest.raises(ValidationError):
        MemoryRecord.model_validate(data)


def test_invalid_yaml_maps_to_canon_content_error_with_cause(tmp_path: Path) -> None:
    canon = repository(tmp_path)
    canon.project_file("story-01").write_text("title: [unterminated")

    with pytest.raises(CanonContentError) as raised:
        canon.read_project("story-01")

    assert raised.value.code == "SCHEMA_VALIDATION_FAILED"
    assert raised.value.__cause__ is not None


def test_invalid_yaml_schema_maps_to_canon_content_error_with_cause(tmp_path: Path) -> None:
    canon = repository(tmp_path)
    canon.project_file("story-01").write_text("id: story-01\ntitle: '   '\nlanguage: zh-CN\n")

    with pytest.raises(CanonContentError) as raised:
        canon.read_project("story-01")

    assert raised.value.code == "SCHEMA_VALIDATION_FAILED"
    assert raised.value.__cause__ is not None


def test_read_io_failure_maps_to_stable_error_with_cause(tmp_path: Path) -> None:
    canon = repository(tmp_path)

    with pytest.raises(StorageReadError) as raised:
        canon.read_project("story-01")

    assert raised.value.code == "STORAGE_READ_FAILED"
    assert isinstance(raised.value.__cause__, FileNotFoundError)


def test_write_io_failure_maps_to_stable_error_with_cause(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    canon = repository(tmp_path)
    monkeypatch.setattr(
        "app.repositories.canon.os.replace", lambda *args: (_ for _ in ()).throw(OSError("replace"))
    )

    with pytest.raises(StorageWriteError) as raised:
        canon.write_project(Project(id="story-01", title="长夜", language="zh-CN"))

    assert raised.value.code == "STORAGE_WRITE_FAILED"
    assert isinstance(raised.value.__cause__, OSError)
