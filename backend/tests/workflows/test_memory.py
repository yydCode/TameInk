from pathlib import Path

import pytest

from app.domain.errors import MemoryProvenanceError
from app.domain.project import ConfirmedContent, Project
from app.repositories.canon import CanonRepository
from app.repositories.database import DatabaseRepository
from app.repositories.revisions import RevisionRepository
from app.repositories.search import SearchRepository
from app.repositories.workspace import WorkspaceRepository
from app.workflows.memory import MemoryService


def test_memory_record_requires_approved_chapter_and_can_be_revoked(tmp_path: Path) -> None:
    workspace = WorkspaceRepository(tmp_path)
    workspace.create_project("story-01")
    canon = CanonRepository(workspace)
    canon.write_project(Project(id="story-01", title="长夜", language="zh-CN"))
    canon.write_markdown(
        "story-01", "canon/chapters/0001.md", ConfirmedContent(markdown="雨夜相遇")
    )
    revisions = RevisionRepository(workspace)
    revisions.current_revision("story-01")
    memory = MemoryService(workspace)

    created = memory.create(
        "story-01", "meeting", "fact", "canon/chapters/0001.md", "line 1, column 1", "雨夜相遇"
    )
    memory.revoke("story-01", "meeting", "fact")

    assert created.location == "line 1, column 1"
    assert created.quote == "雨夜相遇"
    assert canon.read_memory("story-01", "memory/facts/meeting.yaml").status == "superseded"


def test_memory_rejects_missing_source_or_duplicate_stable_id(tmp_path: Path) -> None:
    workspace = WorkspaceRepository(tmp_path)
    workspace.create_project("story-01")
    RevisionRepository(workspace).current_revision("story-01")
    memory = MemoryService(workspace)

    with pytest.raises(MemoryProvenanceError):
        memory.create("story-01", "missing", "fact", "canon/chapters/0001.md", "line 1", "quote")


def test_memory_rejects_quote_not_present_in_source_chapter(tmp_path: Path) -> None:
    workspace = WorkspaceRepository(tmp_path)
    workspace.create_project("story-01")
    canon = CanonRepository(workspace)
    canon.write_project(Project(id="story-01", title="长夜", language="zh-CN"))
    canon.write_markdown(
        "story-01", "canon/chapters/0001.md", ConfirmedContent(markdown="雨夜相遇")
    )
    RevisionRepository(workspace).current_revision("story-01")

    with pytest.raises(MemoryProvenanceError):
        MemoryService(workspace).create(
            "story-01", "bad", "fact", "canon/chapters/0001.md", "line 1, column 1", "不存在"
        )


def test_memory_rejects_location_that_does_not_point_to_quote(tmp_path: Path) -> None:
    workspace = WorkspaceRepository(tmp_path)
    workspace.create_project("story-01")
    canon = CanonRepository(workspace)
    canon.write_markdown(
        "story-01", "canon/chapters/0001.md", ConfirmedContent(markdown="甲句\n雨夜相遇")
    )
    RevisionRepository(workspace).current_revision("story-01")

    with pytest.raises(MemoryProvenanceError):
        MemoryService(workspace).create(
            "story-01",
            "bad-location",
            "fact",
            "canon/chapters/0001.md",
            "line 1, column 1",
            "雨夜相遇",
        )


def test_memory_can_be_read_corrected_and_is_immediately_searchable(tmp_path: Path) -> None:
    workspace = WorkspaceRepository(tmp_path)
    workspace.create_project("story-01")
    canon = CanonRepository(workspace)
    canon.write_markdown(
        "story-01", "canon/chapters/0001.md", ConfirmedContent(markdown="雨夜相遇\n长街重逢")
    )
    RevisionRepository(workspace).current_revision("story-01")
    memory = MemoryService(workspace)
    memory.create(
        "story-01", "meeting", "fact", "canon/chapters/0001.md", "line 1, column 1", "雨夜相遇"
    )

    corrected = memory.correct(
        "story-01",
        "meeting",
        "fact",
        "canon/chapters/0001.md",
        "line 2, column 1, char 5",
        "长街重逢",
    )

    assert memory.read("story-01", "meeting", "fact") == corrected
    assert corrected.status == "active"
    assert corrected.location == "line 2, column 1, char 5"
    assert [
        hit.path
        for hit in SearchRepository(workspace, DatabaseRepository(workspace)).search(
            "story-01", "长街重逢"
        )
    ] == ["canon/chapters/0001.md", "memory/facts/meeting.yaml"]


def test_rolling_summaries_keep_recent_chapters_and_immutable_chapter_files(
    tmp_path: Path,
) -> None:
    workspace = WorkspaceRepository(tmp_path)
    workspace.create_project("story-01")
    canon = CanonRepository(workspace)
    memory = MemoryService(workspace)
    first = memory.summary_writes_for_project("story-01", "1", "1", "第一章状态")
    for write in first:
        canon.write_markdown("story-01", write.path, ConfirmedContent(markdown=write.content))
    second = memory.summary_writes_for_project("story-01", "2", "1", "第二章状态")
    for write in second:
        canon.write_markdown("story-01", write.path, ConfirmedContent(markdown=write.content))

    book = canon.read_markdown("story-01", "memory/summaries/book.md").markdown
    volume = canon.read_markdown("story-01", "memory/summaries/volumes/1.md").markdown
    assert book.startswith("## 章节 2\n第二章状态")
    assert "## 章节 1\n第一章状态" in book
    assert "## 章节 1\n第一章状态" in volume
    assert (
        canon.read_markdown("story-01", "memory/summaries/chapters/1.md").markdown == "第一章状态\n"
    )
