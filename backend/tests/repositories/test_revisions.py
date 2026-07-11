from pathlib import Path

import pytest
from pydantic import ValidationError

from app.domain.errors import (
    CanonVersionConflictError,
    RecoveryIncompleteError,
    StorageWriteError,
    WorkspacePathViolationError,
)
from app.domain.revision import RevisionWrite
from app.repositories.revisions import RevisionRepository
from app.repositories.workspace import WorkspaceRepository


def repository(tmp_path: Path) -> tuple[WorkspaceRepository, RevisionRepository]:
    workspace = WorkspaceRepository(tmp_path)
    workspace.create_project("story-01")
    return workspace, RevisionRepository(workspace)


def test_confirm_creates_chinese_commit_and_lists_history(tmp_path: Path) -> None:
    workspace, revisions = repository(tmp_path)
    revision = revisions.confirm(
        "story-01",
        RevisionWrite(
            path="canon/chapters/0001.md", content="# 第一章\n\n初稿。\n", message="确认：第一章"
        ),
        expected_revision=None,
    )

    assert (
        workspace.resolve_project_path("story-01", "canon/chapters/0001.md").read_text()
        == "# 第一章\n\n初稿。\n"
    )
    assert revisions.current_revision("story-01") == revision.id
    assert [(item.id, item.message) for item in revisions.history("story-01")] == [
        (revision.id, "确认：第一章")
    ]


def test_compare_and_swap_rejects_stale_revision(tmp_path: Path) -> None:
    _, revisions = repository(tmp_path)
    revisions.confirm(
        "story-01",
        RevisionWrite(path="canon/outline.md", content="# 大纲\n", message="确认：大纲"),
        None,
    )

    with pytest.raises(CanonVersionConflictError) as raised:
        revisions.confirm(
            "story-01",
            RevisionWrite(path="canon/outline.md", content="# 新大纲\n", message="确认：新大纲"),
            None,
        )

    assert raised.value.code == "CANON_VERSION_CONFLICT"


def test_rollback_restores_file_and_ref(tmp_path: Path) -> None:
    workspace, revisions = repository(tmp_path)
    first = revisions.confirm(
        "story-01",
        RevisionWrite(path="canon/outline.md", content="第一版\n", message="确认：第一版"),
        None,
    )
    second = revisions.confirm(
        "story-01",
        RevisionWrite(path="canon/outline.md", content="第二版\n", message="确认：第二版"),
        first.id,
    )

    rollback = revisions.rollback("story-01", first.id, expected_revision=second.id)

    assert rollback.id not in {first.id, second.id}
    assert rollback.message.startswith("回滚：")
    assert revisions.current_revision("story-01") == rollback.id
    assert workspace.resolve_project_path("story-01", "canon/outline.md").read_text() == "第一版\n"
    assert [item.id for item in revisions.history("story-01")] == [
        rollback.id,
        second.id,
        first.id,
    ]


def test_rollback_removes_files_added_after_target_revision(tmp_path: Path) -> None:
    workspace, revisions = repository(tmp_path)
    first = revisions.confirm(
        "story-01",
        RevisionWrite(path="canon/outline.md", content="第一版\n", message="确认：第一版"),
        None,
    )
    second = revisions.confirm(
        "story-01",
        RevisionWrite(
            path="canon/chapters/0001.md", content="新增章节\n", message="确认：新增章节"
        ),
        first.id,
    )

    revisions.rollback("story-01", first.id, expected_revision=second.id)

    assert not workspace.resolve_project_path("story-01", "canon/chapters/0001.md").exists()


def test_rollback_concurrent_cas_failure_keeps_files_and_external_ref(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, revisions = repository(tmp_path)
    first = revisions.confirm(
        "story-01",
        RevisionWrite(path="canon/outline.md", content="第一版\n", message="确认：第一版"),
        None,
    )
    second = revisions.confirm(
        "story-01",
        RevisionWrite(path="canon/outline.md", content="第二版\n", message="确认：第二版"),
        first.id,
    )
    _, repo = revisions._repo("story-01")
    competing = b"2" * 40

    def competing_update(*args: object) -> None:
        repo.refs[b"refs/heads/main"] = competing
        raise CanonVersionConflictError("concurrent rollback")

    monkeypatch.setattr(revisions, "_update_ref", competing_update)

    with pytest.raises(CanonVersionConflictError):
        revisions.rollback("story-01", first.id, expected_revision=second.id)

    assert workspace.resolve_project_path("story-01", "canon/outline.md").read_text() == "第二版\n"
    assert repo.refs[b"refs/heads/main"] == competing
    assert not workspace.resolve_project_path("story-01", ".tame-ink/recovery.json").exists()


def test_revision_message_must_be_confirmation_in_chinese() -> None:
    with pytest.raises(ValidationError):
        RevisionWrite(path="canon/outline.md", content="大纲\n", message="update outline")


def test_confirm_rejects_path_escape_before_creating_recovery_log(tmp_path: Path) -> None:
    workspace, revisions = repository(tmp_path)

    with pytest.raises(WorkspacePathViolationError):
        revisions.confirm(
            "story-01",
            RevisionWrite(path="canon/../escape.md", content="越界\n", message="确认：越界"),
            None,
        )

    assert not workspace.resolve_project_path("story-01", ".tame-ink/recovery.json").exists()


@pytest.mark.parametrize("path", ["canon/arbitrary.md", "canon/chapters/nested/0001.md"])
def test_confirm_rejects_paths_outside_exact_formal_whitelist(tmp_path: Path, path: str) -> None:
    _, revisions = repository(tmp_path)

    with pytest.raises(WorkspacePathViolationError):
        revisions.confirm(
            "story-01",
            RevisionWrite(path=path, content="内容\n", message="确认：内容"),
            None,
        )


def test_confirm_rejects_formal_directory_symlink_escape(tmp_path: Path) -> None:
    workspace, revisions = repository(tmp_path)
    chapters = workspace.resolve_project_path("story-01", "canon/chapters")
    chapters.rmdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "leak.md").write_text("外部泄漏内容")
    chapters.symlink_to(outside, target_is_directory=True)

    with pytest.raises(WorkspacePathViolationError) as raised:
        revisions.confirm(
            "story-01",
            RevisionWrite(path="canon/outline.md", content="大纲\n", message="确认：大纲"),
            None,
        )

    assert raised.value.code == "WORKSPACE_PATH_VIOLATION"
    assert revisions.history("story-01") == []


def test_git_ref_failure_restores_original_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, revisions = repository(tmp_path)
    first = revisions.confirm(
        "story-01",
        RevisionWrite(path="canon/outline.md", content="旧版\n", message="确认：旧版"),
        None,
    )
    monkeypatch.setattr(
        revisions, "_update_ref", lambda *args: (_ for _ in ()).throw(OSError("ref failed"))
    )

    with pytest.raises(StorageWriteError):
        revisions.confirm(
            "story-01",
            RevisionWrite(path="canon/outline.md", content="新版\n", message="确认：新版"),
            first.id,
        )

    assert revisions.current_revision("story-01") == first.id
    assert workspace.resolve_project_path("story-01", "canon/outline.md").read_text() == "旧版\n"


def test_concurrent_ref_change_remains_version_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, revisions = repository(tmp_path)
    first = revisions.confirm(
        "story-01",
        RevisionWrite(path="canon/outline.md", content="旧版\n", message="确认：旧版"),
        None,
    )
    monkeypatch.setattr(
        revisions,
        "_update_ref",
        lambda *args: (_ for _ in ()).throw(CanonVersionConflictError("concurrent")),
    )

    with pytest.raises(CanonVersionConflictError):
        revisions.confirm(
            "story-01",
            RevisionWrite(path="canon/outline.md", content="新版\n", message="确认：新版"),
            first.id,
        )


def test_commit_construction_failure_clears_recovery_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, revisions = repository(tmp_path)
    first = revisions.confirm(
        "story-01",
        RevisionWrite(path="canon/outline.md", content="旧版\n", message="确认：旧版"),
        None,
    )
    monkeypatch.setattr(
        revisions, "_build_commit", lambda *args: (_ for _ in ()).throw(OSError("commit failed"))
    )

    with pytest.raises(StorageWriteError):
        revisions.confirm(
            "story-01",
            RevisionWrite(path="canon/outline.md", content="新版\n", message="确认：新版"),
            first.id,
        )

    assert revisions.current_revision("story-01") == first.id
    assert not workspace.resolve_project_path("story-01", ".tame-ink/recovery.json").exists()


def test_file_replace_failure_restores_git_ref(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, revisions = repository(tmp_path)
    first = revisions.confirm(
        "story-01",
        RevisionWrite(path="canon/outline.md", content="旧版\n", message="确认：旧版"),
        None,
    )
    monkeypatch.setattr(
        revisions, "_replace_file", lambda *args: (_ for _ in ()).throw(OSError("replace failed"))
    )

    with pytest.raises(StorageWriteError):
        revisions.confirm(
            "story-01",
            RevisionWrite(path="canon/outline.md", content="新版\n", message="确认：新版"),
            first.id,
        )

    assert revisions.current_revision("story-01") == first.id
    assert workspace.resolve_project_path("story-01", "canon/outline.md").read_text() == "旧版\n"


def test_incomplete_recovery_blocks_later_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, revisions = repository(tmp_path)
    first = revisions.confirm(
        "story-01",
        RevisionWrite(path="canon/outline.md", content="旧版\n", message="确认：旧版"),
        None,
    )
    monkeypatch.setattr(
        revisions, "_replace_file", lambda *args: (_ for _ in ()).throw(OSError("replace failed"))
    )
    monkeypatch.setattr(
        revisions, "_restore", lambda *args: (_ for _ in ()).throw(OSError("restore failed"))
    )

    with pytest.raises(RecoveryIncompleteError):
        revisions.confirm(
            "story-01",
            RevisionWrite(path="canon/outline.md", content="新版\n", message="确认：新版"),
            first.id,
        )
    with pytest.raises(RecoveryIncompleteError):
        revisions.confirm(
            "story-01",
            RevisionWrite(path="canon/outline.md", content="再版\n", message="确认：再版"),
            first.id,
        )


def test_recovery_does_not_overwrite_an_unexpected_ref(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, revisions = repository(tmp_path)
    first = revisions.confirm(
        "story-01",
        RevisionWrite(path="canon/outline.md", content="旧版\n", message="确认：旧版"),
        None,
    )
    _, repo = revisions._repo("story-01")
    competing = b"1" * 40

    def change_ref_then_fail(*args: object) -> None:
        repo.refs[b"refs/heads/main"] = competing
        raise OSError("replace failed")

    monkeypatch.setattr(revisions, "_replace_file", change_ref_then_fail)

    with pytest.raises(RecoveryIncompleteError):
        revisions.confirm(
            "story-01",
            RevisionWrite(path="canon/outline.md", content="新版\n", message="确认：新版"),
            first.id,
        )

    assert repo.refs[b"refs/heads/main"] == competing
    assert workspace.resolve_project_path("story-01", ".tame-ink/recovery.json").exists()
