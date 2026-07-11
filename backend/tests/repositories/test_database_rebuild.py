from pathlib import Path

import pytest

from app.domain.errors import SearchQueryError, WorkspacePathViolationError
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
            == "1"
        )
        assert (
            connection.execute(
                "SELECT name FROM sqlite_master WHERE name = 'content_fts'"
            ).fetchone()[0]
            == "content_fts"
        )


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


def test_search_rejects_queries_shorter_than_trigram_contract(tmp_path: Path) -> None:
    _, _, database = setup_project(tmp_path)
    database.rebuild("story-01")

    with pytest.raises(SearchQueryError) as raised:
        database.search("story-01", "落雨")

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
