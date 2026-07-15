import re
from typing import Literal

import yaml

from app.domain.errors import MemoryProvenanceError
from app.domain.project import MemoryRecord
from app.domain.revision import RevisionWrite
from app.repositories.canon import CanonRepository
from app.repositories.database import DatabaseRepository
from app.repositories.revisions import RevisionRepository
from app.repositories.workspace import WorkspaceRepository

_DIRECTORIES = {
    "fact": "facts",
    "event": "events",
    "relationship": "relationships",
    "foreshadowing": "foreshadowing",
}
MemoryKind = Literal["fact", "event", "relationship", "foreshadowing"]
_LOCATION = re.compile(
    r"^line ([1-9][0-9]*), column ([1-9][0-9]*)(?:, char (0|[1-9][0-9]*))?$"
)


class MemoryService:
    def __init__(self, workspace: WorkspaceRepository) -> None:
        self.workspace = workspace

    def create(
        self,
        project_id: str,
        stable_id: str,
        kind: MemoryKind,
        source: str,
        location: str,
        quote: str,
    ) -> MemoryRecord:
        directory = _DIRECTORIES.get(kind)
        if directory is None or not location.strip() or not quote.strip():
            raise MemoryProvenanceError("memory kind, location and quote are required")
        self._validate_provenance(project_id, source, location, quote)
        relative = f"memory/{directory}/{stable_id}.yaml"
        target = self.workspace.resolve_project_path(project_id, relative)
        if target.exists():
            raise MemoryProvenanceError("memory stable id already exists")
        record = MemoryRecord(
            id=stable_id,
            kind=kind,
            status="active",
            source=source,
            location=location,
            quote=quote,
        )
        self._confirm(project_id, relative, record, f"确认：记忆 {stable_id}")
        return record

    def read(self, project_id: str, stable_id: str, kind: MemoryKind) -> MemoryRecord:
        relative = self._relative(stable_id, kind)
        try:
            return CanonRepository(self.workspace).read_memory(project_id, relative)
        except Exception as error:
            raise MemoryProvenanceError("memory record does not exist") from error

    def list_records(self, project_id: str) -> list[MemoryRecord]:
        canon = CanonRepository(self.workspace)
        records: list[MemoryRecord] = []
        for directory in _DIRECTORIES.values():
            root = self.workspace.resolve_project_path(project_id, f"memory/{directory}")
            if not root.exists():
                continue
            for path in sorted(root.glob("*.yaml")):
                if path.is_symlink():
                    raise MemoryProvenanceError("memory record path is invalid")
                records.append(
                    canon.read_memory(
                        project_id,
                        path.relative_to(self.workspace.project_path(project_id)).as_posix(),
                    )
                )
        return records

    def revoke(self, project_id: str, stable_id: str, kind: MemoryKind) -> MemoryRecord:
        relative = self._relative(stable_id, kind)
        existing = self.read(project_id, stable_id, kind)
        record = existing.model_copy(update={"status": "superseded"})
        self._confirm(project_id, relative, record, f"确认：撤销记忆 {stable_id}")
        return record

    def correct(
        self,
        project_id: str,
        stable_id: str,
        kind: MemoryKind,
        source: str,
        location: str,
        quote: str,
    ) -> MemoryRecord:
        self.read(project_id, stable_id, kind)
        self._validate_provenance(project_id, source, location, quote)
        record = MemoryRecord(
            id=stable_id,
            kind=kind,
            status="active",
            source=source,
            location=location,
            quote=quote,
        )
        self._confirm(
            project_id, self._relative(stable_id, kind), record, f"确认：纠正记忆 {stable_id}"
        )
        return record

    def derive_summaries(
        self, project_id: str, chapter_id: str, volume_id: str, chapter_text: str
    ) -> None:
        """Persist deterministic, traceable summaries after a chapter is already confirmed."""
        revisions = RevisionRepository(self.workspace)
        revisions.confirm_batch(
            project_id,
            self.summary_writes(chapter_id, volume_id, chapter_text),
            revisions.current_revision(project_id),
        )
        DatabaseRepository(self.workspace).rebuild(project_id)

    @staticmethod
    def summary_writes(
        chapter_id: str, volume_id: str, chapter_text: str
    ) -> list[RevisionWrite]:
        excerpt = chapter_text.strip()[:1000]
        message = f"确认：章节 {chapter_id}"
        return [
            RevisionWrite(
                path="memory/summaries/book.md",
                content=f"已确认章节 {chapter_id}：{excerpt}\n",
                message=message,
            ),
            RevisionWrite(
                path=f"memory/summaries/volumes/{volume_id}.md",
                content=f"章节 {chapter_id}：{excerpt}\n",
                message=message,
            ),
            RevisionWrite(
                path=f"memory/summaries/chapters/{chapter_id}.md",
                content=excerpt + "\n",
                message=message,
            ),
        ]

    def _confirm(self, project_id: str, relative: str, record: MemoryRecord, message: str) -> None:
        revisions = RevisionRepository(self.workspace)
        content = yaml.safe_dump(record.model_dump(mode="json"), allow_unicode=True, sort_keys=True)
        revisions.confirm(
            project_id,
            RevisionWrite(path=relative, content=content, message=message),
            revisions.current_revision(project_id),
        )
        DatabaseRepository(self.workspace).rebuild(project_id)

    @staticmethod
    def _relative(stable_id: str, kind: MemoryKind) -> str:
        directory = _DIRECTORIES.get(kind)
        if directory is None:
            raise MemoryProvenanceError("memory kind is invalid")
        return f"memory/{directory}/{stable_id}.yaml"

    def _validate_provenance(
        self, project_id: str, source: str, location: str, quote: str
    ) -> None:
        match = _LOCATION.fullmatch(location)
        if match is None:
            raise MemoryProvenanceError("memory location must contain a line and column")
        source_path = self.workspace.resolve_project_path(project_id, source)
        if not source.startswith("canon/chapters/") or not source_path.is_file():
            raise MemoryProvenanceError("memory source must be an approved chapter")
        lines = source_path.read_text(encoding="utf-8").splitlines(keepends=True)
        line, column = (int(value) for value in match.groups()[:2])
        if line > len(lines) or not lines[line - 1].startswith(quote, column - 1):
            raise MemoryProvenanceError("memory location does not point to its quote")
        char = match.group(3)
        offset = sum(len(value) for value in lines[: line - 1]) + column - 1
        if char is not None and int(char) != offset:
            raise MemoryProvenanceError("memory character offset does not point to its quote")
