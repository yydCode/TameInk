import sqlite3
from pathlib import Path

import pytest

from app.domain.errors import DatabaseSchemaError, SearchQueryError, WorkspacePathViolationError
from app.domain.project import ConfirmedContent, MemoryRecord, Project
from app.repositories.canon import CanonRepository
from app.repositories.database import DatabaseRepository
from app.repositories.workspace import WorkspaceRepository


def setup_project(
    tmp_path: Path,
) -> tuple[WorkspaceRepository, CanonRepository, DatabaseRepository]:
    workspace = WorkspaceRepository(tmp_path)
    workspace.create_project("story-01")
    canon = CanonRepository(workspace)
    canon.write_project(Project(id="story-01", title="长夜", language="zh-CN"))
    canon.write_markdown(
        "story-01", "canon/chapters/0001.md", ConfirmedContent(markdown="# 雨夜\n\n长街落雨。\n")
    )
    canon.write_memory(
        "story-01",
        "memory/facts/weather.yaml",
        MemoryRecord(
            id="weather",
            kind="fact",
            status="active",
            source="canon/chapters/0001.md",
            location="line 3, column 1",
            quote="长街落雨",
        ),
    )
    return workspace, canon, DatabaseRepository(workspace)


def test_initialization_is_repeatable_and_records_schema_version(tmp_path: Path) -> None:
    _, _, database = setup_project(tmp_path)
    database.initialize("story-01")
    database.initialize("story-01")

    with database.connect("story-01") as connection:
        assert (
            connection.execute(
                "SELECT value FROM metadata WHERE key = 'schema_version'"
            ).fetchone()[0]
            == "5"
        )


def test_initialization_migrates_real_v1_database_without_losing_fts_data(tmp_path: Path) -> None:
    _, _, database = setup_project(tmp_path)
    with database.connect("story-01") as connection:
        connection.executescript(
            """
            CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO metadata(key, value) VALUES ('schema_version', '1');
            CREATE VIRTUAL TABLE content_fts USING fts5(
                path UNINDEXED, content, tokenize = 'trigram'
            );
            INSERT INTO content_fts(path, content) VALUES ('canon/outline.md', '保留迁移内容');
            """
        )

    database.initialize("story-01")

    with database.connect("story-01") as connection:
        assert (
            connection.execute(
                "SELECT value FROM metadata WHERE key = 'schema_version'"
            ).fetchone()[0]
            == "5"
        )
        assert (
            connection.execute(
                "SELECT path FROM content_fts WHERE content_fts MATCH '迁移内容'"
            ).fetchone()[0]
            == "canon/outline.md"
        )
        objects = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'index', 'trigger')"
            )
        }
    assert {
        "tasks",
        "task_events",
        "one_active_write_task_per_project",
        "enforce_task_status_transition",
    } <= objects


def test_initialization_migrates_v2_and_adds_commercial_observations(tmp_path: Path) -> None:
    _, _, database = setup_project(tmp_path)
    with database.connect("story-01") as connection:
        connection.executescript(
            """
            CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO metadata(key, value) VALUES ('schema_version', '2');
            CREATE VIRTUAL TABLE content_fts USING fts5(
                path UNINDEXED, content, tokenize = 'trigram'
            );
            INSERT INTO content_fts(path, content) VALUES ('canon/outline.md', '保留版本二内容');
            """
        )

    database.initialize("story-01")

    with database.connect("story-01") as connection:
        assert (
            connection.execute(
                "SELECT value FROM metadata WHERE key = 'schema_version'"
            ).fetchone()[0]
            == "5"
        )
        assert (
            connection.execute(
                "SELECT path FROM content_fts WHERE content_fts MATCH '版本二内容'"
            ).fetchone()[0]
            == "canon/outline.md"
        )
        assert (
            connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name = 'commercial_observations'"
            ).fetchone()[0]
            == "commercial_observations"
        )


def test_initialization_migrates_v3_tasks_without_losing_rows(tmp_path: Path) -> None:
    _, _, database = setup_project(tmp_path)
    with database.connect("story-01") as connection:
        connection.executescript(
            """
            CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO metadata(key, value) VALUES ('schema_version', '3');
            CREATE TABLE tasks (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL, kind TEXT NOT NULL,
                status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            INSERT INTO tasks VALUES (
                '00000000-0000-0000-0000-000000000001', 'story-01', 'read', 'completed',
                '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:01+00:00'
            );
            """
        )

    database.initialize("story-01")

    with database.connect("story-01") as connection:
        row = connection.execute("SELECT purpose, subject_id, duration_ms FROM tasks").fetchone()
        version = connection.execute(
            "SELECT value FROM metadata WHERE key = 'schema_version'"
        ).fetchone()[0]
    assert version == "5"
    assert row == ("manual", None, None)


@pytest.mark.parametrize("version", ["0", "6", "future"])
def test_initialization_rejects_unknown_schema_versions(tmp_path: Path, version: str) -> None:
    _, _, database = setup_project(tmp_path)
    with database.connect("story-01") as connection:
        connection.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute(
            "INSERT INTO metadata(key, value) VALUES ('schema_version', ?)", (version,)
        )

    with pytest.raises(DatabaseSchemaError, match="schema version"):
        database.initialize("story-01")


def test_initialization_rejects_metadata_without_schema_version(tmp_path: Path) -> None:
    _, _, database = setup_project(tmp_path)
    with database.connect("story-01") as connection:
        connection.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")

    with pytest.raises(DatabaseSchemaError, match="schema version"):
        database.initialize("story-01")


def test_v1_migration_rolls_back_all_ddl_and_can_retry_after_failure(tmp_path: Path) -> None:
    _, _, database = setup_project(tmp_path)
    with database.connect("story-01") as connection:
        connection.executescript(
            """
            CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO metadata(key, value) VALUES ('schema_version', '1');
            CREATE VIRTUAL TABLE content_fts USING fts5(
                path UNINDEXED, content, tokenize = 'trigram'
            );
            INSERT INTO content_fts(path, content) VALUES ('canon/outline.md', '原子迁移保留');
            CREATE TABLE tasks (id TEXT PRIMARY KEY);
            """
        )

    with pytest.raises(sqlite3.OperationalError):
        database.initialize("story-01")

    with database.connect("story-01") as connection:
        assert (
            connection.execute(
                "SELECT value FROM metadata WHERE key = 'schema_version'"
            ).fetchone()[0]
            == "1"
        )
        objects = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'index', 'trigger')"
            )
        }
        assert {
            "task_events",
            "one_active_write_task_per_project",
            "enforce_task_status_transition",
        }.isdisjoint(objects)
        assert (
            connection.execute(
                "SELECT path FROM content_fts WHERE content_fts MATCH '原子迁移'"
            ).fetchone()[0]
            == "canon/outline.md"
        )
        connection.execute("DROP TABLE tasks")

    database.initialize("story-01")

    with database.connect("story-01") as connection:
        assert (
            connection.execute(
                "SELECT value FROM metadata WHERE key = 'schema_version'"
            ).fetchone()[0]
            == "5"
        )
        objects = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'index', 'trigger')"
            )
        }
    assert {
        "tasks",
        "task_events",
        "one_active_write_task_per_project",
        "enforce_task_status_transition",
    } <= objects


def test_rebuild_restores_core_fts_index_from_formal_files(tmp_path: Path) -> None:
    workspace, _, database = setup_project(tmp_path)
    database.rebuild("story-01")
    assert database.search("story-01", "长街落雨") == [
        "canon/chapters/0001.md",
        "memory/facts/weather.yaml",
    ]

    database.path("story-01").unlink()
    database.rebuild("story-01")

    assert database.search("story-01", "长街落雨") == [
        "canon/chapters/0001.md",
        "memory/facts/weather.yaml",
    ]
    assert workspace.resolve_project_path("story-01", ".tame-ink/state.db").is_file()


def test_search_rejects_single_character_queries(tmp_path: Path) -> None:
    _, _, database = setup_project(tmp_path)
    database.rebuild("story-01")

    with pytest.raises(SearchQueryError) as raised:
        database.search("story-01", "雨")

    assert raised.value.code == "SEARCH_QUERY_INVALID"


def test_rebuild_excludes_files_outside_formal_whitelist(tmp_path: Path) -> None:
    workspace, _, database = setup_project(tmp_path)
    rogue = workspace.resolve_project_path("story-01", "canon/arbitrary.md")
    rogue.write_text("不应索引的秘密内容")

    database.rebuild("story-01")

    assert database.search("story-01", "秘密内容") == []


def test_rebuild_rejects_formal_directory_symlink_escape(tmp_path: Path) -> None:
    workspace, _, database = setup_project(tmp_path)
    chapters = workspace.resolve_project_path("story-01", "canon/world")
    chapters.rmdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "leak.md").write_text("外部泄漏内容")
    chapters.symlink_to(outside, target_is_directory=True)

    with pytest.raises(WorkspacePathViolationError) as raised:
        database.rebuild("story-01")

    assert raised.value.code == "WORKSPACE_PATH_VIOLATION"
    assert database.search("story-01", "泄漏内容") == []


@pytest.mark.parametrize("query", ["abc OR", '"abc', "abc:def"])
def test_search_maps_only_invalid_match_syntax(tmp_path: Path, query: str) -> None:
    _, _, database = setup_project(tmp_path)
    database.rebuild("story-01")

    with pytest.raises(SearchQueryError) as raised:
        database.search("story-01", query)

    assert raised.value.code == "SEARCH_QUERY_INVALID"
    assert raised.value.__cause__ is not None


def test_search_does_not_mask_unrelated_database_errors(tmp_path: Path) -> None:
    _, _, database = setup_project(tmp_path)
    database.initialize("story-01")
    with database.connect("story-01") as connection:
        connection.execute("DROP TABLE content_fts")

    with pytest.raises(Exception) as raised:
        database.search("story-01", "valid query")

    assert not isinstance(raised.value, SearchQueryError)


def test_search_does_not_treat_missing_fixed_path_column_as_query_error(tmp_path: Path) -> None:
    _, _, database = setup_project(tmp_path)
    database.initialize("story-01")
    with database.connect("story-01") as connection:
        connection.execute("DROP TABLE content_fts")
        connection.execute("CREATE VIRTUAL TABLE content_fts USING fts5(content)")

    with pytest.raises(Exception) as raised:
        database.search("story-01", "valid query")

    assert not isinstance(raised.value, SearchQueryError)
