from pathlib import Path

import pytest

from app.domain.errors import SearchQueryError
from app.domain.project import ConfirmedContent, Project
from app.repositories.canon import CanonRepository
from app.repositories.database import DatabaseRepository
from app.repositories.search import SearchRepository
from app.repositories.workspace import WorkspaceRepository


def test_search_returns_only_formal_sources_with_actual_hash_and_excerpt(tmp_path: Path) -> None:
    workspace = WorkspaceRepository(tmp_path)
    workspace.create_project("story-01")
    canon = CanonRepository(workspace)
    canon.write_project(Project(id="story-01", title="长夜", language="zh-CN"))
    canon.write_markdown("story-01", "canon/outline.md", ConfirmedContent(markdown="雨夜线索出现"))
    database = DatabaseRepository(workspace)
    database.initialize("story-01")
    database.rebuild("story-01")

    result = SearchRepository(workspace, database).search("story-01", "雨夜线索")

    assert result[0].path == "canon/outline.md"
    assert len(result[0].sha256) == 64
    assert result[0].quote == "雨夜线索出现"


def test_search_rejects_short_fts_query_stably(tmp_path: Path) -> None:
    workspace = WorkspaceRepository(tmp_path)
    workspace.create_project("story-01")
    database = DatabaseRepository(workspace)
    database.initialize("story-01")

    with pytest.raises(SearchQueryError):
        SearchRepository(workspace, database).search("story-01", "雨夜")
