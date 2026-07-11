from pathlib import Path

import pytest

from app.domain.errors import InvalidProjectIdError, WorkspacePathViolationError
from app.repositories.workspace import WorkspaceRepository


@pytest.mark.parametrize(
    "project_id", ["../escape", "/absolute", "bad/id", "Upper", "a" * 65, "-bad"]
)
def test_rejects_invalid_project_ids(tmp_path: Path, project_id: str) -> None:
    workspace = WorkspaceRepository(tmp_path)

    with pytest.raises(InvalidProjectIdError):
        workspace.project_path(project_id)


def test_creates_the_confirmed_project_layout(tmp_path: Path) -> None:
    workspace = WorkspaceRepository(tmp_path)

    project = workspace.create_project("story-01")

    assert project == (tmp_path / "projects" / "story-01").resolve()
    for relative in (
        "canon/volumes",
        "canon/characters",
        "canon/world",
        "canon/chapters",
        "memory/summaries/volumes",
        "memory/summaries/chapters",
        "memory/facts",
        "memory/events",
        "memory/relationships",
        "memory/foreshadowing",
        "imports/originals",
        ".tame-ink/drafts",
        ".tame-ink/runs",
    ):
        assert (project / relative).is_dir()


@pytest.mark.parametrize("relative", ["../other/file.md", "/tmp/file.md"])
def test_rejects_paths_outside_project(tmp_path: Path, relative: str) -> None:
    workspace = WorkspaceRepository(tmp_path)
    workspace.create_project("story-01")

    with pytest.raises(WorkspacePathViolationError):
        workspace.resolve_project_path("story-01", relative)


def test_rejects_symlink_escape(tmp_path: Path) -> None:
    workspace = WorkspaceRepository(tmp_path)
    project = workspace.create_project("story-01")
    outside = tmp_path / "outside"
    outside.mkdir()
    (project / "canon" / "linked").symlink_to(outside, target_is_directory=True)

    with pytest.raises(WorkspacePathViolationError):
        workspace.resolve_project_path("story-01", "canon/linked/file.md")


def test_rejects_workspace_root_symlink(tmp_path: Path) -> None:
    actual = tmp_path / "actual"
    actual.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(actual, target_is_directory=True)

    with pytest.raises(WorkspacePathViolationError):
        WorkspaceRepository(linked)


def test_rejects_projects_directory_symlink(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "projects").symlink_to(outside, target_is_directory=True)
    workspace = WorkspaceRepository(tmp_path)

    with pytest.raises(WorkspacePathViolationError):
        workspace.project_path("story-01")


def test_rejects_project_directory_alias_symlink(tmp_path: Path) -> None:
    projects = tmp_path / "projects"
    projects.mkdir()
    target = projects / "story-02"
    target.mkdir()
    (projects / "story-01").symlink_to(target, target_is_directory=True)
    workspace = WorkspaceRepository(tmp_path)

    with pytest.raises(WorkspacePathViolationError):
        workspace.project_path("story-01")
