import json
import time
from pathlib import Path

import pytest
from dulwich.objects import Blob, Commit, Tree
from dulwich.repo import Repo
from pydantic import ValidationError

from app.domain.errors import (
    CanonVersionConflictError,
    InvalidRevisionError,
    RecoveryIncompleteError,
    RevisionLockError,
    StorageWriteError,
    WorkspacePathViolationError,
)
from app.domain.revision import Revision, RevisionWrite
from app.repositories.revisions import RevisionRepository
from app.repositories.workspace import WorkspaceRepository


def repository(tmp_path: Path) -> tuple[WorkspaceRepository, RevisionRepository]:
    workspace = WorkspaceRepository(tmp_path)
    workspace.create_project("story-01")
    return workspace, RevisionRepository(workspace)


def baseline(revisions: RevisionRepository) -> str:
    revision = revisions.current_revision("story-01")
    assert revision is not None
    return revision


def test_initialization_creates_reachable_baseline_from_existing_formal_files(
    tmp_path: Path,
) -> None:
    workspace = WorkspaceRepository(tmp_path)
    project = workspace.create_project("story-01")
    (project / "project.yaml").write_text("id: story-01\ntitle: 书\nlanguage: zh-CN\n")
    (project / "canon/outline.md").write_text("已有大纲\n")
    revisions = RevisionRepository(workspace)

    baseline = revisions.current_revision("story-01")

    assert baseline is not None
    assert revisions.history("story-01")[0].message == "初始化：建立作品版本基线"
    _, repo = revisions._repo("story-01")
    commit = repo.object_store[baseline.encode()]
    assert revisions._tree_files(repo, repo.object_store[commit.tree]) == {
        "canon/outline.md": "已有大纲\n".encode(),
        "project.yaml": "id: story-01\ntitle: 书\nlanguage: zh-CN\n".encode(),
    }


@pytest.mark.parametrize("drift", ["add", "modify", "delete"])
def test_confirm_rejects_formal_worktree_drift_without_log(tmp_path: Path, drift: str) -> None:
    workspace = WorkspaceRepository(tmp_path)
    project = workspace.create_project("story-01")
    (project / "canon/outline.md").write_text("基线\n")
    revisions = RevisionRepository(workspace)
    baseline = revisions.current_revision("story-01")
    assert baseline is not None
    if drift == "add":
        (project / "canon/chapters/0001.md").write_text("外部新增\n")
    elif drift == "modify":
        (project / "canon/outline.md").write_text("外部修改\n")
    else:
        (project / "canon/outline.md").unlink()

    with pytest.raises(CanonVersionConflictError):
        revisions.confirm(
            "story-01",
            RevisionWrite(path="canon/premise.md", content="内容\n", message="确认：内容"),
            baseline,
        )

    assert revisions.current_revision("story-01") == baseline
    assert not (project / ".tame-ink/recovery.json").exists()


def test_recover_rejects_legacy_none_old_ref_log(tmp_path: Path) -> None:
    workspace = WorkspaceRepository(tmp_path)
    project = workspace.create_project("story-01")
    repo = Repo.init(str(project))
    repo.refs.set_symbolic_ref(b"HEAD", b"refs/heads/main")
    revisions = RevisionRepository(workspace)
    log = workspace.resolve_project_path("story-01", ".tame-ink/recovery.json")
    revisions._write_log(log, {"old_ref": None, "new_ref": "f" * 40, "old_files": {}})

    with pytest.raises(RecoveryIncompleteError):
        revisions.recover("story-01")

    assert log.exists()
    assert b"refs/heads/main" not in repo.refs


def test_first_transaction_recovery_log_has_baseline_old_ref(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, revisions = repository(tmp_path)
    baseline = revisions.current_revision("story-01")
    captured: list[dict[str, object]] = []
    real_write_log = revisions._write_log

    def capture(path: Path, record: dict[str, object]) -> None:
        captured.append(record.copy())
        real_write_log(path, record)

    monkeypatch.setattr(revisions, "_write_log", capture)
    revisions.confirm(
        "story-01",
        RevisionWrite(path="canon/outline.md", content="内容\n", message="确认：内容"),
        baseline,
    )

    assert baseline is not None
    assert captured[0]["old_ref"] == baseline


def test_confirm_creates_chinese_commit_and_lists_history(tmp_path: Path) -> None:
    workspace, revisions = repository(tmp_path)
    revision = revisions.confirm(
        "story-01",
        RevisionWrite(
            path="canon/chapters/0001.md", content="# 第一章\n\n初稿。\n", message="确认：第一章"
        ),
        expected_revision=baseline(revisions),
    )

    assert (
        workspace.resolve_project_path("story-01", "canon/chapters/0001.md").read_text()
        == "# 第一章\n\n初稿。\n"
    )
    assert revisions.current_revision("story-01") == revision.id
    history = revisions.history("story-01")
    assert (history[0].id, history[0].message) == (revision.id, "确认：第一章")
    assert history[1].message == "初始化：建立作品版本基线"


def test_compare_and_swap_rejects_stale_revision(tmp_path: Path) -> None:
    _, revisions = repository(tmp_path)
    revisions.confirm(
        "story-01",
        RevisionWrite(path="canon/outline.md", content="# 大纲\n", message="确认：大纲"),
        baseline(revisions),
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
        baseline(revisions),
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
    history = revisions.history("story-01")
    assert [item.id for item in history[:3]] == [
        rollback.id,
        second.id,
        first.id,
    ]
    assert history[3].message == "初始化：建立作品版本基线"


def test_rollback_removes_files_added_after_target_revision(tmp_path: Path) -> None:
    workspace, revisions = repository(tmp_path)
    first = revisions.confirm(
        "story-01",
        RevisionWrite(path="canon/outline.md", content="第一版\n", message="确认：第一版"),
        baseline(revisions),
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
        baseline(revisions),
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
        baseline(revisions),
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
            baseline(revisions),
        )

    assert not workspace.resolve_project_path("story-01", ".tame-ink/recovery.json").exists()


@pytest.mark.parametrize("path", ["canon/arbitrary.md", "canon/chapters/nested/0001.md"])
def test_confirm_rejects_paths_outside_exact_formal_whitelist(tmp_path: Path, path: str) -> None:
    _, revisions = repository(tmp_path)

    with pytest.raises(WorkspacePathViolationError):
        revisions.confirm(
            "story-01",
            RevisionWrite(path=path, content="内容\n", message="确认：内容"),
            baseline(revisions),
        )


def test_confirm_rejects_formal_directory_symlink_escape(tmp_path: Path) -> None:
    workspace, revisions = repository(tmp_path)
    current = baseline(revisions)
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
            current,
        )

    assert raised.value.code == "WORKSPACE_PATH_VIOLATION"
    assert [item.id for item in revisions.history("story-01")] == [current]


def test_git_ref_failure_restores_original_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, revisions = repository(tmp_path)
    first = revisions.confirm(
        "story-01",
        RevisionWrite(path="canon/outline.md", content="旧版\n", message="确认：旧版"),
        baseline(revisions),
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
        baseline(revisions),
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
        baseline(revisions),
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
        baseline(revisions),
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
        baseline(revisions),
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
        baseline(revisions),
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
        baseline(revisions),
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
    current_id = revisions._build_commit_from_files(
        repo, {"canon/outline.md": "安全内容\n".encode()}, ancestor.decode(), "current"
    )
    repo.refs[b"refs/heads/main"] = current_id
    (project / "canon/outline.md").write_text("安全内容\n")
    current = Revision(id=current_id.decode(), message="current")
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
        baseline(revisions),
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
    current = baseline(first_writer)
    log = workspace.resolve_project_path("story-01", ".tame-ink/recovery.json")
    with first_writer._locked("story-01"):
        log.write_text("first writer")
        with pytest.raises(RevisionLockError) as raised:
            RevisionRepository(workspace, lock_timeout=0).confirm(
                "story-01",
                RevisionWrite(path="canon/outline.md", content="内容\n", message="确认：内容"),
                current,
            )

    assert raised.value.code == "REVISION_LOCKED"
    assert log.read_text() == "first writer"


@pytest.mark.parametrize("control", ["revision.lock", "recovery.json", "recovery.tmp"])
def test_control_file_symlink_is_rejected_without_changing_target(
    tmp_path: Path, control: str
) -> None:
    workspace, revisions = repository(tmp_path)
    current = baseline(revisions)
    project = workspace.project_path("story-01")
    target = project / "project.yaml"
    target.write_text("protected")
    control_path = project / ".tame-ink" / control
    control_path.symlink_to(target)

    with pytest.raises(WorkspacePathViolationError):
        if control == "recovery.json":
            revisions.recover("story-01")
        else:
            revisions.confirm(
                "story-01",
                RevisionWrite(path="canon/outline.md", content="内容\n", message="确认：内容"),
                current,
            )

    assert target.read_text() == "protected"


@pytest.mark.parametrize("damage", ["checksum", "base64", "snapshot", "old_ref"])
def test_recover_rejects_tampered_snapshot_without_applying_files(
    tmp_path: Path, damage: str
) -> None:
    workspace, revisions = repository(tmp_path)
    _, _, log = prepare_crash_log(workspace, revisions)
    project = workspace.project_path("story-01")
    record = json.loads(log.read_text())
    if damage == "checksum":
        record["checksum"] = "0" * 64
    elif damage == "base64":
        record["old_files"]["canon/outline.md"] = "***"
    elif damage == "snapshot":
        record["old_files"]["canon/outline.md"] = revisions._encode("篡改内容\n".encode())
    else:
        record["old_ref"] = "f" * 40
    if damage != "checksum":
        critical = {key: record[key] for key in ("old_ref", "new_ref", "old_files")}
        record["checksum"] = revisions._checksum(critical)
    log.write_text(json.dumps(record, sort_keys=True))

    with pytest.raises(RecoveryIncompleteError):
        RevisionRepository(workspace).recover("story-01")

    assert (project / "canon/outline.md").read_text() == "旧文件\n"
    assert log.exists()


def test_lock_symlink_switch_after_initial_validation_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, revisions = repository(tmp_path)
    current = baseline(revisions)
    project = workspace.project_path("story-01")
    target = project / "project.yaml"
    target.write_text("protected")

    class SwitchingLock:
        def __init__(self, path: str, timeout: float) -> None:
            self.path = Path(path)

        def __enter__(self) -> None:
            self.path.unlink(missing_ok=True)
            self.path.symlink_to(target)

        def __exit__(self, *args: object) -> None:
            self.path.unlink(missing_ok=True)

    monkeypatch.setattr("app.repositories.revisions.FileLock", SwitchingLock)

    with pytest.raises(WorkspacePathViolationError):
        revisions.confirm(
            "story-01",
            RevisionWrite(path="canon/outline.md", content="内容\n", message="确认：内容"),
            current,
        )

    assert target.read_text() == "protected"


def malformed_commit(repo: object, tree_id: bytes, message: bytes, parent: bytes | None) -> bytes:
    commit = Commit()
    commit.tree = tree_id
    commit.parents = [] if parent is None else [parent]
    commit.author = commit.committer = b"Tame Ink <tame-ink@localhost>"
    commit.author_time = commit.commit_time = int(time.time())
    commit.author_timezone = commit.commit_timezone = 0
    commit.message = message
    repo.object_store.add_object(commit)  # type: ignore[attr-defined]
    return commit.id


@pytest.mark.parametrize("damage", ["tree_name", "message", "missing_tree"])
def test_rollback_maps_reachable_malformed_revision(tmp_path: Path, damage: str) -> None:
    _, revisions = repository(tmp_path)
    project, repo = revisions._repo("story-01")
    if damage == "tree_name":
        blob = Blob()
        blob.data = b"bad"
        repo.object_store.add_object(blob)
        tree = Tree()
        tree.add(b"\xff", 0o100644, blob.id)
        repo.object_store.add_object(tree)
        ancestor = malformed_commit(repo, tree.id, b"bad tree", None)
    elif damage == "message":
        tree = Tree()
        repo.object_store.add_object(tree)
        ancestor = malformed_commit(repo, tree.id, b"\xff", None)
    else:
        ancestor = malformed_commit(repo, b"f" * 40, b"missing tree", None)
    repo.refs[b"refs/heads/main"] = ancestor
    current = revisions._build_commit_from_files(
        repo, {"canon/outline.md": b"safe\n"}, ancestor.decode(), "current"
    )
    repo.refs[b"refs/heads/main"] = current
    (project / "canon/outline.md").write_text("safe\n")

    with pytest.raises(InvalidRevisionError) as raised:
        revisions.rollback("story-01", ancestor.decode(), expected_revision=current.decode())

    assert raised.value.code == "INVALID_REVISION"
    assert raised.value.__cause__ is not None
    assert repo.refs[b"refs/heads/main"] == current
