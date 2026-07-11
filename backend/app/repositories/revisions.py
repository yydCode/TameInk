import base64
import hashlib
import json
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Any, cast

from dulwich.objects import Blob, Commit, Tree
from dulwich.repo import Repo
from filelock import FileLock, Timeout

from app.domain.errors import (
    CanonVersionConflictError,
    InvalidRevisionError,
    RecoveryIncompleteError,
    RevisionLockError,
    StorageWriteError,
    TameInkError,
    WorkspacePathViolationError,
)
from app.domain.paths import iter_formal_files, resolve_formal_path
from app.domain.revision import Revision, RevisionWrite
from app.repositories.workspace import WorkspaceRepository

REF = b"refs/heads/main"


class RevisionRepository:
    def __init__(self, workspace: WorkspaceRepository, lock_timeout: float = 1.0) -> None:
        self.workspace = workspace
        self.lock_timeout = lock_timeout

    def confirm(
        self, project_id: str, write: RevisionWrite, expected_revision: str | None
    ) -> Revision:
        with self._locked(project_id):
            return self._confirm_locked(project_id, write, expected_revision)

    def _confirm_locked(
        self, project_id: str, write: RevisionWrite, expected_revision: str | None
    ) -> Revision:
        project, repo = self._repo(project_id)
        log = self._log_path(project_id)
        if log.exists():
            raise RecoveryIncompleteError(str(log))
        current = self.current_revision(project_id)
        if current != expected_revision:
            raise CanonVersionConflictError(f"expected {expected_revision}, found {current}")
        self._formal_target(project_id, write.path)
        try:
            commit_id = self._build_commit(repo, project, write, current)
        except TameInkError:
            raise
        except Exception as error:
            raise StorageWriteError(str(error)) from error
        files = self._current_files(project)
        files[write.path] = write.content.encode()
        self._transaction(repo, project, log, current, commit_id, files)
        return Revision(id=commit_id.decode(), message=write.message)

    def _transaction(
        self,
        repo: Repo,
        project: Path,
        log: Path,
        old_ref: str | None,
        new_ref: bytes,
        files: dict[str, bytes],
    ) -> None:
        record = {
            "old_ref": old_ref,
            "new_ref": new_ref.decode(),
            "old_files": {
                path: self._encode(content)
                for path, content in self._current_files(project).items()
            },
        }
        self._write_log(log, record)
        try:
            self._update_ref(repo, old_ref, new_ref)
            self._apply_files(project, files, self._replace_file)
        except CanonVersionConflictError:
            self._remove_log(log)
            raise
        except Exception as error:
            try:
                self._restore(repo, project, record)
                self._remove_log(log)
            except Exception as recovery_error:
                raise RecoveryIncompleteError(str(recovery_error)) from error
            raise StorageWriteError(str(error)) from error
        self._remove_log(log)

    def current_revision(self, project_id: str) -> str | None:
        _, repo = self._repo(project_id)
        try:
            return repo.refs[REF].decode()
        except KeyError:
            return None

    def history(self, project_id: str) -> list[Revision]:
        _, repo = self._repo(project_id)
        current = self.current_revision(project_id)
        if current is None:
            return []
        return [
            Revision(id=entry.commit.id.decode(), message=entry.commit.message.decode())
            for entry in repo.get_walker(include=[current.encode()])
        ]

    def rollback(self, project_id: str, revision_id: str, expected_revision: str) -> Revision:
        with self._locked(project_id):
            return self._rollback_locked(project_id, revision_id, expected_revision)

    def _rollback_locked(
        self, project_id: str, revision_id: str, expected_revision: str
    ) -> Revision:
        project, repo = self._repo(project_id)
        log = self._log_path(project_id)
        if log.exists():
            raise RecoveryIncompleteError(str(log))
        if self.current_revision(project_id) != expected_revision:
            raise CanonVersionConflictError(expected_revision)
        try:
            commit = repo.object_store[revision_id.encode()]
        except (KeyError, ValueError) as error:
            raise InvalidRevisionError(f"revision does not exist: {revision_id}") from error
        if not isinstance(commit, Commit):
            raise InvalidRevisionError(f"revision is not a commit: {revision_id}")
        reachable = {
            entry.commit.id.decode()
            for entry in repo.get_walker(include=[expected_revision.encode()])
        }
        if revision_id not in reachable:
            raise InvalidRevisionError(f"revision is not an ancestor of HEAD: {revision_id}")
        try:
            target_tree = repo.object_store[commit.tree]
            files = self._tree_files(repo, target_tree)
            for relative in files:
                resolve_formal_path(project, relative)
            message = f"回滚：{commit.message.decode()}"
        except WorkspacePathViolationError:
            raise
        except Exception as error:
            raise InvalidRevisionError(f"revision objects are invalid: {revision_id}") from error
        try:
            rollback_id = self._build_commit_from_files(repo, files, expected_revision, message)
        except Exception as error:
            raise StorageWriteError(str(error)) from error
        self._transaction(repo, project, log, expected_revision, rollback_id, files)
        return Revision(id=rollback_id.decode(), message=message)

    def recover(self, project_id: str) -> None:
        with self._locked(project_id):
            project, repo = self._repo(project_id)
            log = self._log_path(project_id)
            if not log.exists():
                return
            try:
                record = self._read_log(log, project, repo)
                self._restore(repo, project, record)
                self._remove_log(log)
            except RecoveryIncompleteError:
                raise
            except Exception as error:
                raise RecoveryIncompleteError(f"cannot recover {project_id}") from error

    @contextmanager
    def _locked(self, project_id: str) -> Iterator[None]:
        lock_path = self._control_path(project_id, "revision.lock")
        try:
            with FileLock(str(lock_path), timeout=self.lock_timeout):
                yield
        except Timeout as error:
            raise RevisionLockError(project_id) from error

    def _repo(self, project_id: str) -> tuple[Path, Repo]:
        project = self.workspace.project_path(project_id)
        git_dir = project / ".git"
        if not git_dir.exists():
            repo = Repo.init(str(project))
            repo.refs.set_symbolic_ref(b"HEAD", REF)
        else:
            repo = Repo(str(project))
        return project, repo

    def _formal_target(self, project_id: str, relative: str) -> Path:
        return resolve_formal_path(self.workspace.project_path(project_id), relative)

    def _build_commit(
        self, repo: Repo, project: Path, write: RevisionWrite, parent: str | None
    ) -> bytes:
        files = self._current_files(project)
        files[write.path] = write.content.encode()
        return self._build_commit_from_files(repo, files, parent, write.message)

    def _build_commit_from_files(
        self, repo: Repo, files: dict[str, bytes], parent: str | None, message: str
    ) -> bytes:
        tree_files = {PurePosixPath(path).parts: content for path, content in files.items()}
        tree_id = self._store_tree(repo, tree_files)
        now = int(time.time())
        commit = Commit()
        commit.tree = tree_id
        commit.parents = [] if parent is None else [parent.encode()]
        commit.author = commit.committer = b"Tame Ink <tame-ink@localhost>"
        commit.author_time = commit.commit_time = now
        commit.author_timezone = commit.commit_timezone = 0
        commit.message = message.encode()
        repo.object_store.add_object(commit)
        return cast(bytes, commit.id)

    def _store_tree(self, repo: Repo, files: dict[tuple[str, ...], bytes]) -> bytes:
        tree = Tree()
        first_names = sorted({parts[0] for parts in files})
        for name in first_names:
            direct = files.get((name,))
            if direct is not None:
                blob = Blob()
                blob.data = direct
                repo.object_store.add_object(blob)
                tree.add(name.encode(), 0o100644, blob.id)
            else:
                nested = {parts[1:]: data for parts, data in files.items() if parts[0] == name}
                tree.add(name.encode(), 0o040000, self._store_tree(repo, nested))
        repo.object_store.add_object(tree)
        return cast(bytes, tree.id)

    def _update_ref(self, repo: Repo, old: str | None, new: bytes) -> None:
        old_bytes = None if old is None else old.encode()
        if not repo.refs.set_if_equals(REF, old_bytes, new):
            raise CanonVersionConflictError(old or "unborn")

    @staticmethod
    def _replace_file(path: Path, payload: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.revision")
        with temporary.open("wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        RevisionRepository._sync_directory(path.parent)

    def _restore(self, repo: Repo, project: Path, record: dict[str, Any]) -> None:
        old_ref = record["old_ref"]
        new_ref = record.get("new_ref")
        if new_ref is not None:
            try:
                current_ref = repo.refs[REF].decode()
            except KeyError:
                current_ref = None
            if current_ref == old_ref:
                restored = True
            elif old_ref is None:
                restored = repo.refs.remove_if_equals(REF, new_ref.encode())
            else:
                restored = repo.refs.set_if_equals(REF, new_ref.encode(), old_ref.encode())
            if not restored:
                raise RecoveryIncompleteError("revision ref changed during recovery")
        old_files = {path: self._decode(content) for path, content in record["old_files"].items()}
        self._apply_files(
            project,
            {path: content for path, content in old_files.items() if content is not None},
            self._replace_file_direct,
        )

    def _tree_files(
        self, repo: Repo, tree: object, prefix: PurePosixPath = PurePosixPath()
    ) -> dict[str, bytes]:
        if not isinstance(tree, Tree):
            raise StorageWriteError("invalid tree")
        files: dict[str, bytes] = {}
        for name, _mode, sha in tree.iteritems():
            relative = prefix / name.decode()
            obj = repo[sha]
            if isinstance(obj, Tree):
                files.update(self._tree_files(repo, obj, relative))
            elif isinstance(obj, Blob):
                files[relative.as_posix()] = obj.data
        return files

    @staticmethod
    def _current_files(project: Path) -> dict[str, bytes]:
        return {
            path.relative_to(project).as_posix(): path.read_bytes()
            for path in iter_formal_files(project)
        }

    def _apply_files(
        self,
        project: Path,
        files: dict[str, bytes],
        writer: Any,
    ) -> None:
        for path in iter_formal_files(project):
            relative = path.relative_to(project).as_posix()
            if relative not in files:
                path.unlink()
                self._sync_directory(path.parent)
        for relative, content in sorted(files.items()):
            writer(resolve_formal_path(project, relative), content)

    def _log_path(self, project_id: str) -> Path:
        return self._control_path(project_id, "recovery.json")

    def _control_path(self, project_id: str, name: str) -> Path:
        if name not in {"revision.lock", "recovery.json", "recovery.tmp"}:
            raise WorkspacePathViolationError(name)
        project = self.workspace.project_path(project_id)
        control = project / ".tame-ink"
        if control.is_symlink() or not control.is_dir():
            raise WorkspacePathViolationError(str(control))
        for control_name in ("revision.lock", "recovery.json", "recovery.tmp"):
            candidate = control / control_name
            if candidate.is_symlink():
                raise WorkspacePathViolationError(str(candidate))
        return control / name

    @staticmethod
    def _write_log(path: Path, record: dict[str, Any]) -> None:
        temporary = path.with_suffix(".tmp")
        RevisionRepository._reject_control_symlink(path, temporary)
        critical = {key: record[key] for key in ("old_ref", "new_ref", "old_files")}
        envelope = {
            "version": 1,
            **critical,
            "checksum": RevisionRepository._checksum(critical),
        }
        with temporary.open("w") as stream:
            json.dump(envelope, stream, sort_keys=True, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    def _read_log(self, path: Path, project: Path, repo: Repo) -> dict[str, Any]:
        try:
            self._reject_control_symlink(path, path.with_suffix(".tmp"))
            record = json.loads(path.read_text())
            if not isinstance(record, dict) or set(record) != {
                "version",
                "checksum",
                "old_ref",
                "new_ref",
                "old_files",
            }:
                raise ValueError("invalid recovery log fields")
            if record["version"] != 1 or not isinstance(record["checksum"], str):
                raise ValueError("invalid recovery log version")
            critical = {key: record[key] for key in ("old_ref", "new_ref", "old_files")}
            if record["checksum"] != self._checksum(critical):
                raise ValueError("invalid recovery log checksum")
            old_ref = record["old_ref"]
            new_ref = record["new_ref"]
            old_files = record["old_files"]
            if old_ref is not None and not isinstance(old_ref, str):
                raise ValueError("invalid old_ref")
            if not isinstance(new_ref, str) or not isinstance(old_files, dict):
                raise ValueError("invalid recovery log types")
            for relative, content in old_files.items():
                if not isinstance(relative, str) or not isinstance(content, str):
                    raise ValueError("invalid recovery file snapshot")
                resolve_formal_path(project, relative)
                base64.b64decode(content, validate=True)
            if old_ref is not None:
                old_commit = repo.object_store[old_ref.encode()]
                if not isinstance(old_commit, Commit):
                    raise ValueError("old_ref is not a commit")
                old_tree = repo.object_store[old_commit.tree]
                expected = {
                    relative: self._encode(content)
                    for relative, content in self._tree_files(repo, old_tree).items()
                }
                if old_files != expected:
                    raise ValueError("recovery snapshot does not match old_ref")
            return record
        except RecoveryIncompleteError:
            raise
        except Exception as error:
            raise RecoveryIncompleteError(f"invalid recovery log: {path}") from error

    def _remove_log(self, path: Path) -> None:
        self._reject_control_symlink(path, path.with_suffix(".tmp"))
        path.unlink()
        self._sync_directory(path.parent)

    @staticmethod
    def _checksum(critical: dict[str, Any]) -> str:
        payload = json.dumps(
            critical, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
        return hashlib.sha256(payload).hexdigest()

    @staticmethod
    def _reject_control_symlink(*paths: Path) -> None:
        for path in paths:
            if path.parent.is_symlink() or path.is_symlink():
                raise WorkspacePathViolationError(str(path))

    @staticmethod
    def _replace_file_direct(path: Path, payload: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.restore")
        with temporary.open("wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        RevisionRepository._sync_directory(path.parent)

    @staticmethod
    def _sync_directory(path: Path) -> None:
        directory = os.open(path, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    @staticmethod
    def _encode(value: bytes | None) -> str | None:
        return None if value is None else base64.b64encode(value).decode()

    @staticmethod
    def _decode(value: str | None) -> bytes | None:
        return None if value is None else base64.b64decode(value)
