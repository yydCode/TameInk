import re
import sqlite3
from pathlib import Path

from app.domain.errors import DatabaseSchemaError, SearchQueryError
from app.domain.paths import iter_formal_files
from app.repositories.workspace import WorkspaceRepository


class DatabaseRepository:
    def __init__(self, workspace: WorkspaceRepository) -> None:
        self.workspace = workspace

    def path(self, project_id: str) -> Path:
        return self.workspace.resolve_project_path(project_id, ".tame-ink/state.db")

    def connect(self, project_id: str) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path(project_id), timeout=5)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self, project_id: str) -> None:
        schema = Path(__file__).with_name("schema.sql").read_text()
        with self.connect(project_id) as connection:
            metadata = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'metadata'"
            ).fetchone()
            if metadata is None:
                version = None
            else:
                row = connection.execute(
                    "SELECT value FROM metadata WHERE key = 'schema_version'"
                ).fetchone()
                if row is None:
                    raise DatabaseSchemaError("schema version is missing")
                version = str(row[0])
            if version is None or version in {"1", "2"}:
                migration = f"""BEGIN IMMEDIATE;
{schema}
INSERT INTO metadata(key, value) VALUES ('schema_version', '3')
ON CONFLICT(key) DO UPDATE SET value = excluded.value;
COMMIT;
"""
                try:
                    connection.executescript(migration)
                except sqlite3.Error:
                    if connection.in_transaction:
                        connection.rollback()
                    raise
            elif version != "3":
                raise DatabaseSchemaError(f"unsupported schema version: {version}")

    def rebuild(self, project_id: str) -> None:
        self.initialize(project_id)
        project = self.workspace.project_path(project_id)
        formal = list(iter_formal_files(project))
        with self.connect(project_id) as connection:
            connection.execute("DELETE FROM content_fts")
            connection.executemany(
                "INSERT INTO content_fts(path, content) VALUES (?, ?)",
                (
                    (str(path.relative_to(project)), path.read_text())
                    for path in sorted(formal)
                    if path.is_file()
                ),
            )

    def search(self, project_id: str, query: str) -> list[str]:
        return self._search(project_id, query, query)

    def search_literal(self, project_id: str, query: str) -> list[str]:
        escaped = query.replace('"', '""')
        return self._search(project_id, query, f'"{escaped}"')

    def _search(self, project_id: str, display_query: str, match_query: str) -> list[str]:
        if len(display_query.strip()) < 2:
            raise SearchQueryError("FTS query must contain at least two characters")
        try:
            with self.connect(project_id) as connection:
                rows = connection.execute(
                    "SELECT path FROM content_fts WHERE content_fts MATCH ? ORDER BY path",
                    (match_query,),
                ).fetchall()
        except sqlite3.OperationalError as error:
            message = str(error)
            if (
                "fts5: syntax error" in message
                or "unterminated string" in message
                or self._query_references_missing_column(match_query, message)
            ):
                raise SearchQueryError(display_query) from error
            raise
        return [str(row[0]) for row in rows]

    @staticmethod
    def _query_references_missing_column(query: str, message: str) -> bool:
        prefix = "no such column: "
        if not message.startswith(prefix):
            return False
        column = message.removeprefix(prefix)
        return re.search(rf"(?:^|\s){re.escape(column)}\s*:", query) is not None
