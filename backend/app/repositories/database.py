import re
import sqlite3
from pathlib import Path

import jieba

from app.domain.errors import DatabaseSchemaError, SearchQueryError
from app.domain.paths import iter_formal_files
from app.repositories.workspace import WorkspaceRepository

# Initialize jieba once at module level to avoid repeated dictionary loading
jieba.initialize()


def _tokenize_for_fts(text: str) -> str:
    """Tokenize Chinese/mixed text with jieba for FTS5 indexing.

    Returns space-separated tokens. FTS5 will use unicode61 tokenizer
    on the pre-tokenized text, so each jieba token becomes a search term.
    """
    tokens = jieba.lcut(text)
    return " ".join(tokens)


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
INSERT INTO metadata(key, value) VALUES ('schema_version', '7')
ON CONFLICT(key) DO UPDATE SET value = excluded.value;
COMMIT;
"""
                try:
                    connection.executescript(migration)
                except sqlite3.Error:
                    if connection.in_transaction:
                        connection.rollback()
                    raise
            elif version == "3":
                self._migrate_v3_to_v4(connection)
                self._migrate_v4_to_v5(connection)
                self._migrate_v5_to_v6(connection)
                self._migrate_v6_to_v7(connection)
            elif version == "4":
                self._migrate_v4_to_v5(connection)
                self._migrate_v5_to_v6(connection)
                self._migrate_v6_to_v7(connection)
            elif version == "5":
                self._migrate_v5_to_v6(connection)
                self._migrate_v6_to_v7(connection)
            elif version == "6":
                self._migrate_v6_to_v7(connection)
            elif version != "7":
                raise DatabaseSchemaError(f"unsupported schema version: {version}")

    @staticmethod
    def _migrate_v3_to_v4(connection: sqlite3.Connection) -> None:
        migration = """BEGIN IMMEDIATE;
ALTER TABLE tasks ADD COLUMN purpose TEXT NOT NULL DEFAULT 'manual' CHECK (
    purpose IN (
        'manual', 'setting', 'commercial', 'book_outline', 'volume_outline',
        'chapter', 'import', 'commercial_audit', 'memory_curation', 'export'
    )
);
ALTER TABLE tasks ADD COLUMN subject_id TEXT;
ALTER TABLE tasks ADD COLUMN volume_id TEXT;
ALTER TABLE tasks ADD COLUMN chapter_id TEXT;
ALTER TABLE tasks ADD COLUMN parent_task_id TEXT;
ALTER TABLE tasks ADD COLUMN retry_of_task_id TEXT;
ALTER TABLE tasks ADD COLUMN cancel_requested_at TEXT;
ALTER TABLE tasks ADD COLUMN error_code TEXT;
ALTER TABLE tasks ADD COLUMN error_message TEXT;
ALTER TABLE tasks ADD COLUMN started_at TEXT;
ALTER TABLE tasks ADD COLUMN finished_at TEXT;
ALTER TABLE tasks ADD COLUMN duration_ms INTEGER CHECK (duration_ms IS NULL OR duration_ms >= 0);
UPDATE metadata SET value = '4' WHERE key = 'schema_version';
COMMIT;
"""
        try:
            connection.executescript(migration)
        except sqlite3.Error:
            if connection.in_transaction:
                connection.rollback()
            raise

    @staticmethod
    def _migrate_v4_to_v5(connection: sqlite3.Connection) -> None:
        migration = """BEGIN IMMEDIATE;
DROP INDEX IF EXISTS one_active_write_task_per_project;
CREATE UNIQUE INDEX one_active_write_task_per_project
ON tasks(project_id)
WHERE kind = 'write'
  AND status IN ('pending', 'running', 'awaiting_approval');
UPDATE metadata SET value = '5' WHERE key = 'schema_version';
COMMIT;
"""
        try:
            connection.executescript(migration)
        except sqlite3.Error:
            if connection.in_transaction:
                connection.rollback()
            raise

    @staticmethod
    def _migrate_v5_to_v6(connection: sqlite3.Connection) -> None:
        migration = """BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS task_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    project_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    level TEXT NOT NULL CHECK (level IN ('info', 'warning', 'error')),
    component TEXT NOT NULL CHECK (length(trim(component)) > 0),
    event TEXT NOT NULL CHECK (length(trim(event)) > 0),
    agent TEXT,
    details TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS task_logs_by_task_id ON task_logs(task_id, id);
UPDATE metadata SET value = '6' WHERE key = 'schema_version';
COMMIT;
"""
        try:
            connection.executescript(migration)
        except sqlite3.Error:
            if connection.in_transaction:
                connection.rollback()
            raise

    @staticmethod
    def _migrate_v6_to_v7(connection: sqlite3.Connection) -> None:
        schema = Path(__file__).with_name("schema.sql").read_text()
        migration = f"""BEGIN IMMEDIATE;
{schema}
UPDATE metadata SET value = '7' WHERE key = 'schema_version';
COMMIT;
"""
        try:
            connection.executescript(migration)
        except sqlite3.Error:
            if connection.in_transaction:
                connection.rollback()
            raise

    def rebuild(self, project_id: str) -> None:
        self.initialize(project_id)
        project = self.workspace.project_path(project_id)
        formal = list(iter_formal_files(project))
        with self.connect(project_id) as connection:
            connection.execute("DELETE FROM content_fts")
            connection.executemany(
                "INSERT INTO content_fts(path, content) VALUES (?, ?)",
                (
                    (
                        str(path.relative_to(project)),
                        _tokenize_for_fts(path.read_text(encoding="utf-8")),
                    )
                    for path in sorted(formal)
                    if path.is_file()
                ),
            )

    def search(self, project_id: str, query: str) -> list[str]:
        tokenized_query = _tokenize_for_fts(query)
        return self._search(project_id, query, tokenized_query)

    def search_literal(self, project_id: str, query: str) -> list[str]:
        tokenized_query = _tokenize_for_fts(query)
        escaped = tokenized_query.replace('"', '""')
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
