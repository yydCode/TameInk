import base64
import json
import os
import time
from pathlib import Path, PurePosixPath
from typing import Any, cast

from dulwich.objects import Blob, Commit, Tree
from dulwich.repo import Repo

from app.domain.errors import (
    CanonVersionConflictError,
    RecoveryIncompleteError,
    StorageWriteError,
    TameInkError,
)
from app.domain.paths import iter_formal_files, resolve_formal_path
from app.domain.revision import Revision, RevisionWrite
from app.repositories.workspace import WorkspaceRepository

REF = b"refs/heads/main"


class RevisionRepository:
    def __init__(self, workspace: WorkspaceRepository) -> None:
        self.workspace = workspace

    def confirm(
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
            log.unlink()
            raise
        except Exception as error:
            try:
                self._restore(repo, project, record)
                log.unlink()
            except Exception as recovery_error:
                raise RecoveryIncompleteError(str(recovery_error)) from error
            raise StorageWriteError(str(error)) from error
        log.unlink()

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
        project, repo = self._repo(project_id)
        log = self._log_path(project_id)
        if log.exists():
            raise RecoveryIncompleteError(str(log))
        if self.current_revision(project_id) != expected_revision:
            raise CanonVersionConflictError(expected_revision)
        commit = repo[revision_id.encode()]
        if not isinstance(commit, Commit):
            raise StorageWriteError("revision is not a commit")
        target_tree = repo[commit.tree]
        files = self._tree_files(repo, target_tree)
        message = f"回滚：{commit.message.decode()}"
        try:
            rollback_id = self._build_commit_from_files(repo, files, expected_revision, message)
        except Exception as error:
            raise StorageWriteError(str(error)) from error
        self._transaction(repo, project, log, expected_revision, rollback_id, files)
        return Revision(id=rollback_id.decode(), message=message)

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
        for relative, content in sorted(files.items()):
            writer(project / relative, content)

    def _log_path(self, project_id: str) -> Path:
        return self.workspace.resolve_project_path(project_id, ".tame-ink/recovery.json")

    @staticmethod
    def _write_log(path: Path, record: dict[str, Any]) -> None:
        temporary = path.with_suffix(".tmp")
        with temporary.open("w") as stream:
            json.dump(record, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

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
