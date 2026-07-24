from pathlib import Path
from uuid import uuid4

import pytest

from app.agents.backend import NovelWorkspaceBackend
from app.domain.errors import WorkspacePathViolationError
from app.domain.project import ConfirmedContent
from app.repositories.canon import CanonRepository
from app.repositories.drafts import DraftRepository
from app.repositories.workspace import WorkspaceRepository


def make_backend(
    tmp_path: Path,
) -> tuple[NovelWorkspaceBackend, CanonRepository, DraftRepository, str]:
    workspace = WorkspaceRepository(tmp_path)
    workspace.create_project("story-01")
    task_id = str(uuid4())
    canon = CanonRepository(workspace)
    drafts = DraftRepository(workspace)
    return NovelWorkspaceBackend(canon, drafts, "story-01", task_id), canon, drafts, task_id


def test_backend_reads_canon_through_repository_and_writes_only_current_draft(
    tmp_path: Path,
) -> None:
    backend, canon, drafts, task_id = make_backend(tmp_path)
    canon.write_markdown("story-01", "canon/premise.md", ConfirmedContent(markdown="confirmed"))

    read = backend.read("/canon/premise.md")
    written = backend.write("/drafts/chapter.md", "draft")

    assert read.content == "confirmed"
    assert read.error is None
    assert written.error is None
    assert drafts.read("story-01", task_id, "chapter.md") == "draft"


def test_backend_scopes_formal_reads_but_keeps_builtin_skills_read_only(
    tmp_path: Path,
) -> None:
    backend, canon, drafts, task_id = make_backend(tmp_path)
    canon.write_markdown("story-01", "canon/premise.md", ConfirmedContent(markdown="premise"))
    canon.write_markdown("story-01", "canon/outline.md", ConfirmedContent(markdown="outline"))
    skill_root = tmp_path / "builtin-skills"
    skill = skill_root / "chapter" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("skill instructions", encoding="utf-8")
    scoped = NovelWorkspaceBackend(
        canon,
        drafts,
        "story-01",
        task_id,
        skill_root=skill_root,
        read_allowlist=frozenset({"canon/outline.md"}),
    )

    assert scoped.read("/canon/outline.md").content == "outline"
    assert scoped.read("/canon/premise.md").error == "WORKSPACE_PATH_VIOLATION"
    assert scoped.read("/skills/chapter/SKILL.md").content == "skill instructions"
    assert scoped.write("/skills/chapter/SKILL.md", "changed").error == "WORKSPACE_PATH_VIOLATION"


@pytest.mark.parametrize(
    "path",
    [
        "/canon/premise.md",
        "/memory/facts/fact-1.yaml",
        "/etc/passwd",
        "/drafts/../other.md",
        "drafts/file.md",
        "/drafts\\file.md",
    ],
)
def test_backend_rejects_write_outside_current_drafts(tmp_path: Path, path: str) -> None:
    backend, _, _, _ = make_backend(tmp_path)
    result = backend.write(path, "blocked")
    assert result.error == "WORKSPACE_PATH_VIOLATION"


def test_draft_repository_rejects_task_or_path_escape(tmp_path: Path) -> None:
    workspace = WorkspaceRepository(tmp_path)
    workspace.create_project("story-01")
    drafts = DraftRepository(workspace)
    with pytest.raises(WorkspacePathViolationError):
        drafts.write("story-01", "not-a-task", "chapter.md", "draft")
    with pytest.raises(WorkspacePathViolationError):
        drafts.write("story-01", str(uuid4()), "../chapter.md", "draft")
