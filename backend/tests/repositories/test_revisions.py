from pathlib import Path

import pytest
from dulwich.objects import Blob
from pydantic import ValidationError

from app.domain.errors import (
    CanonVersionConflictError,
    InvalidRevisionError,
    RecoveryIncompleteError,
    RevisionLockError,
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


def test_rollback_fsyncs_directory_after_deleting_file(
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
        RevisionWrite(
            path="canon/chapters/0001.md", content="新增章节\n", message="确认：新增章节"
        ),
        first.id,
    )
    synced: list[Path] = []
    monkeypatch.setattr(revisions, "_sync_directory", synced.append)

    revisions.rollback("story-01", first.id, expected_revision=second.id)

    assert workspace.resolve_project_path("story-01", "canon/chapters") in synced


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


@pytest.mark.parametrize("kind", ["random", "blob", "dangling"])
def test_rollback_maps_invalid_or_unreachable_revision(tmp_path: Path, kind: str) -> None:
    _, revisions = repository(tmp_path)
    current = revisions.confirm(
        "story-01",
        RevisionWrite(path="canon/outline.md", content="当前版本\n", message="确认：当前版本"),
        None,
    )
    project, repo = revisions._repo("story-01")
    if kind == "random":
        target = "f" * 40
    elif kind == "blob":
        blob = Blob()
        blob.data = b"not a commit"
        repo.object_store.add_object(blob)
        target = blob.id.decode()
    else:
        target = revisions._build_commit_from_files(
            repo, {"canon/outline.md": b"dangling\n"}, None, "dangling"
        ).decode()

    with pytest.raises(InvalidRevisionError) as raised:
        revisions.rollback("story-01", target, expected_revision=current.id)

    assert raised.value.code == "INVALID_REVISION"
    assert revisions.current_revision("story-01") == current.id
    assert (project / "canon/outline.md").read_text() == "当前版本\n"


@pytest.mark.parametrize(
    "injected_path",
    ["imports/originals/injected.txt", "../outside.txt", ".git/refs/heads/main"],
)
def test_rollback_rejects_unsafe_paths_in_ancestor_tree(tmp_path: Path, injected_path: str) -> None:
    workspace, revisions = repository(tmp_path)
    project, repo = revisions._repo("story-01")
    ancestor = revisions._build_commit_from_files(
        repo, {injected_path: b"injected"}, None, "malicious ancestor"
    )
    repo.refs[b"refs/heads/main"] = ancestor
    current = revisions.confirm(
        "story-01",
        RevisionWrite(path="canon/outline.md", content="安全内容\n", message="确认：安全内容"),
        ancestor.decode(),
    )
    original_ref = repo.refs[b"refs/heads/main"]

    with pytest.raises(WorkspacePathViolationError):
        revisions.rollback("story-01", ancestor.decode(), expected_revision=current.id)

    assert repo.refs[b"refs/heads/main"] == original_ref
    assert (
        workspace.resolve_project_path("story-01", "canon/outline.md").read_text() == "安全内容\n"
    )
    assert not (tmp_path / "outside.txt").exists()


def prepare_crash_log(
    workspace: WorkspaceRepository, revisions: RevisionRepository
) -> tuple[str, bytes, Path]:
    first = revisions.confirm(
        "story-01",
        RevisionWrite(path="canon/outline.md", content="旧文件\n", message="确认：旧文件"),
        None,
    )
    project, repo = revisions._repo("story-01")
    write = RevisionWrite(path="canon/outline.md", content="新文件\n", message="确认：新文件")
    new_ref = revisions._build_commit(repo, project, write, first.id)
    record = {
        "old_ref": first.id,
        "new_ref": new_ref.decode(),
        "old_files": {"canon/outline.md": revisions._encode("旧文件\n".encode())},
    }
    log = workspace.resolve_project_path("story-01", ".tame-ink/recovery.json")
    revisions._write_log(log, record)
    return first.id, new_ref, log


@pytest.mark.parametrize("state", ["before_ref", "after_ref", "partial_file"])
def test_recover_after_restart_restores_old_ref_and_files(
    tmp_path: Path, state: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, revisions = repository(tmp_path)
    old_ref, new_ref, log = prepare_crash_log(workspace, revisions)
    project, repo = revisions._repo("story-01")
    if state != "before_ref":
        assert repo.refs.set_if_equals(b"refs/heads/main", old_ref.encode(), new_ref)
    if state == "partial_file":
        (project / "canon/outline.md").write_text("新文件\n")
    synced: list[Path] = []
    restarted = RevisionRepository(workspace)
    monkeypatch.setattr(restarted, "_sync_directory", synced.append)

    restarted.recover("story-01")

    assert restarted.current_revision("story-01") == old_ref
    assert (project / "canon/outline.md").read_text() == "旧文件\n"
    assert not log.exists()
    assert log.parent in synced


def test_recover_keeps_log_and_external_ref_on_conflict(tmp_path: Path) -> None:
    workspace, revisions = repository(tmp_path)
    _, _, log = prepare_crash_log(workspace, revisions)
    _, repo = revisions._repo("story-01")
    competing = b"3" * 40
    repo.refs[b"refs/heads/main"] = competing

    with pytest.raises(RecoveryIncompleteError):
        RevisionRepository(workspace).recover("story-01")

    assert repo.refs[b"refs/heads/main"] == competing
    assert log.exists()


def test_recover_maps_corrupt_log_to_stable_error(tmp_path: Path) -> None:
    workspace, _ = repository(tmp_path)
    log = workspace.resolve_project_path("story-01", ".tame-ink/recovery.json")
    log.write_text("{broken")

    with pytest.raises(RecoveryIncompleteError) as raised:
        RevisionRepository(workspace).recover("story-01")

    assert raised.value.code == "RECOVERY_INCOMPLETE"
    assert raised.value.__cause__ is not None
    assert log.exists()


def test_revision_lock_timeout_is_stable_and_preserves_log(tmp_path: Path) -> None:
    workspace, first_writer = repository(tmp_path)
    log = workspace.resolve_project_path("story-01", ".tame-ink/recovery.json")
    with first_writer._locked("story-01"):
        log.write_text("first writer")
        with pytest.raises(RevisionLockError) as raised:
            RevisionRepository(workspace, lock_timeout=0).confirm(
                "story-01",
                RevisionWrite(path="canon/outline.md", content="内容\n", message="确认：内容"),
                None,
            )

    assert raised.value.code == "REVISION_LOCKED"
    assert log.read_text() == "first writer"
