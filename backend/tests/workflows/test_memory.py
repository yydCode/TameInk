from pathlib import Path

import pytest

from app.domain.errors import MemoryProvenanceError
from app.domain.project import ConfirmedContent, Project
from app.repositories.canon import CanonRepository
from app.repositories.revisions import RevisionRepository
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

    memory.create("story-01", "meeting", "fact", "canon/chapters/0001.md", "line 1", "雨夜相遇")
    memory.revoke("story-01", "meeting", "fact")

    assert canon.read_memory("story-01", "memory/facts/meeting.yaml").status == "superseded"


def test_memory_rejects_missing_source_or_duplicate_stable_id(tmp_path: Path) -> None:
    workspace = WorkspaceRepository(tmp_path)
    workspace.create_project("story-01")
    RevisionRepository(workspace).current_revision("story-01")
    memory = MemoryService(workspace)

    with pytest.raises(MemoryProvenanceError):
        memory.create("story-01", "missing", "fact", "canon/chapters/0001.md", "line 1", "quote")
