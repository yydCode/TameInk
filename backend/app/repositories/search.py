from dataclasses import dataclass
from hashlib import sha256

from app.agents.context import RetrievedSnippet
from app.domain.paths import validate_formal_path
from app.repositories.database import DatabaseRepository
from app.repositories.workspace import WorkspaceRepository


@dataclass(frozen=True)
class SearchHit:
    path: str
    sha256: str
    location: str
    quote: str

    def as_context(self) -> RetrievedSnippet:
        return RetrievedSnippet(path=self.path, location=self.location, quote=self.quote)


class SearchRepository:
    def __init__(self, workspace: WorkspaceRepository, database: DatabaseRepository) -> None:
        self.workspace = workspace
        self.database = database

    def search(self, project_id: str, query: str) -> list[SearchHit]:
        hits: list[SearchHit] = []
        for path in self.database.search(project_id, query):
            validate_formal_path(path)
            source = self.workspace.resolve_project_path(project_id, path)
            if not source.is_file():
                continue
            content = source.read_text(encoding="utf-8")
            quote = self._excerpt(content, query)
            hits.append(
                SearchHit(
                    path=path,
                    sha256=sha256(content.encode()).hexdigest(),
                    location="FTS match",
                    quote=quote,
                )
            )
        return hits

    @staticmethod
    def _excerpt(content: str, query: str) -> str:
        offset = content.find(query)
        if offset < 0:
            return content[:1000]
        return content[max(0, offset - 200) : offset + len(query) + 200]
