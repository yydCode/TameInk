import time
import tracemalloc
from pathlib import Path

import pytest

from app.domain.project import ConfirmedContent, Project
from app.repositories.canon import CanonRepository
from app.repositories.database import DatabaseRepository
from app.repositories.search import SearchRepository
from app.repositories.workspace import WorkspaceRepository


@pytest.mark.performance
def test_large_project_import_index_and_chapter_read_stay_bounded(tmp_path: Path) -> None:
    workspace = WorkspaceRepository(tmp_path)
    workspace.create_project("large-01")
    canon = CanonRepository(workspace)
    canon.write_project(Project(id="large-01", title="合成作品", language="zh-CN"))
    chapter = "# 第{number}章\n\n" + ("合成正文线索。" * 200)
    started = time.perf_counter()
    tracemalloc.start()
    for number in range(1, 1001):
        canon.write_markdown(
            "large-01",
            f"canon/chapters/{number:04d}.md",
            ConfirmedContent(markdown=chapter.format(number=number)),
        )
    database = DatabaseRepository(workspace)
    database.initialize("large-01")
    database.rebuild("large-01")
    hits = SearchRepository(workspace, database).search("large-01", "合成正文线索")
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert len(hits) == 1000
    assert current <= peak < 256 * 1024 * 1024
    assert time.perf_counter() - started < 30
