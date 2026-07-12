from typing import Literal

import yaml

from app.domain.errors import MemoryProvenanceError
from app.domain.project import MemoryRecord
from app.domain.revision import RevisionWrite
from app.repositories.canon import CanonRepository
from app.repositories.revisions import RevisionRepository
from app.repositories.workspace import WorkspaceRepository

_DIRECTORIES = {
    "fact": "facts",
    "event": "events",
    "relationship": "relationships",
    "foreshadowing": "foreshadowing",
}
MemoryKind = Literal["fact", "event", "relationship", "foreshadowing"]


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
        source_path = self.workspace.resolve_project_path(project_id, source)
        if not source.startswith("canon/chapters/") or not source_path.is_file():
            raise MemoryProvenanceError("memory source must be an approved chapter")
        if quote not in source_path.read_text(encoding="utf-8"):
            raise MemoryProvenanceError("memory quote is not present in its source chapter")
        relative = f"memory/{directory}/{stable_id}.yaml"
        target = self.workspace.resolve_project_path(project_id, relative)
        if target.exists():
            raise MemoryProvenanceError("memory stable id already exists")
        record = MemoryRecord(
            id=stable_id, kind=kind, status="active", source=source, quote=f"{location}: {quote}"
        )
        self._confirm(project_id, relative, record, f"确认：记忆 {stable_id}")
        return record

    def revoke(self, project_id: str, stable_id: str, kind: MemoryKind) -> MemoryRecord:
        directory = _DIRECTORIES.get(kind)
        if directory is None:
            raise MemoryProvenanceError("memory kind is invalid")
        relative = f"memory/{directory}/{stable_id}.yaml"
        try:
            existing = CanonRepository(self.workspace).read_memory(project_id, relative)
        except Exception as error:
            raise MemoryProvenanceError("memory record does not exist") from error
        record = existing.model_copy(update={"status": "superseded"})
        self._confirm(project_id, relative, record, f"确认：撤销记忆 {stable_id}")
        return record

    def derive_summaries(
        self, project_id: str, chapter_id: str, volume_id: str, chapter_text: str
    ) -> None:
        """Persist deterministic, traceable summaries after a chapter is already confirmed."""
        excerpts = chapter_text.strip()[:1000]
        summaries = (
            ("memory/summaries/book.md", f"已确认章节 {chapter_id}：{excerpts}\n"),
            (f"memory/summaries/volumes/{volume_id}.md", f"章节 {chapter_id}：{excerpts}\n"),
            (f"memory/summaries/chapters/{chapter_id}.md", excerpts + "\n"),
        )
        for relative, content in summaries:
            revisions = RevisionRepository(self.workspace)
            revisions.confirm(
                project_id,
                RevisionWrite(
                    path=relative, content=content, message=f"确认：章节记忆 {chapter_id}"
                ),
                revisions.current_revision(project_id),
            )

    def _confirm(self, project_id: str, relative: str, record: MemoryRecord, message: str) -> None:
        revisions = RevisionRepository(self.workspace)
        content = yaml.safe_dump(record.model_dump(mode="json"), allow_unicode=True, sort_keys=True)
        revisions.confirm(
            project_id,
            RevisionWrite(path=relative, content=content, message=message),
            revisions.current_revision(project_id),
        )
