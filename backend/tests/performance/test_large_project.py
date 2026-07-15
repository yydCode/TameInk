import time
import tracemalloc
from hashlib import sha256
from pathlib import Path

import pytest

from app.domain.project import ConfirmedContent, Project
from app.domain.task import TaskStatus
from app.repositories.canon import CanonRepository
from app.repositories.database import DatabaseRepository
from app.repositories.search import SearchRepository
from app.repositories.workspace import WorkspaceRepository
from app.workflows.import_book import ChapterBoundary, ImportBookService

CHAPTER_COUNT = 1_000
CHINESE_CHARACTERS_PER_CHAPTER = 2_000
MAX_IMPORT_SECONDS = 60
MAX_PERSIST_AND_READ_SECONDS = 45
MAX_REBUILD_AND_SEARCH_SECONDS = 30
MAX_PEAK_MEMORY_BYTES = 512 * 1024 * 1024


def _large_book() -> tuple[str, bytes]:
    body = "长篇性能线索" * 333 + "正文"
    assert len(body) == CHINESE_CHARACTERS_PER_CHAPTER
    text = "".join(f"第{number}章 性能测试\n{body}\n" for number in range(1, CHAPTER_COUNT + 1))
    return text, text.encode("utf-8")


def _confirmed_boundaries(boundaries: list[ChapterBoundary]) -> list[dict[str, object]]:
    return [
        {
            "number": chapter.number,
            "title": chapter.title,
            "start": chapter.start.__dict__,
            "end": chapter.end.__dict__,
        }
        for chapter in boundaries
    ]


@pytest.mark.performance
def test_large_project_import_index_and_chapter_read_stay_bounded(tmp_path: Path) -> None:
    workspace = WorkspaceRepository(tmp_path)
    workspace.create_project("large-01")
    canon = CanonRepository(workspace)
    canon.write_project(Project(id="large-01", title="合成作品", language="zh-CN"))
    database = DatabaseRepository(workspace)
    database.initialize("large-01")
    service = ImportBookService(workspace)
    source_text, payload = _large_book()

    total_started = time.perf_counter()
    tracemalloc.start()
    import_started = time.perf_counter()
    decoded, candidates = service.upload("large-01", "source-01", payload, "utf-8")
    task, confirmed = service.confirm_boundaries(
        "large-01",
        "source-01",
        sha256(payload).hexdigest(),
        len(payload),
        _confirmed_boundaries(candidates),
    )
    import_seconds = time.perf_counter() - import_started

    assert decoded.text == source_text
    assert len(confirmed) == CHAPTER_COUNT
    assert task.status is TaskStatus.AWAITING_APPROVAL

    persist_started = time.perf_counter()
    for chapter in confirmed:
        body = payload[chapter.body_start.byte : chapter.end.byte].decode("utf-8").strip()
        canon.write_markdown(
            "large-01",
            f"canon/chapters/{chapter.number:04d}.md",
            ConfirmedContent(markdown=f"# 第{chapter.number}章 {chapter.title}\n\n{body}\n"),
        )
    for number in range(1, CHAPTER_COUNT + 1):
        content = canon.read_markdown("large-01", f"canon/chapters/{number:04d}.md")
        assert "长篇性能线索" in content.markdown
    persist_and_read_seconds = time.perf_counter() - persist_started

    search_started = time.perf_counter()
    database.rebuild("large-01")
    hits = SearchRepository(workspace, database).search("large-01", "长篇性能线索")
    rebuild_and_search_seconds = time.perf_counter() - search_started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    total_seconds = time.perf_counter() - total_started

    assert len(source_text) >= CHAPTER_COUNT * CHINESE_CHARACTERS_PER_CHAPTER
    assert len(hits) == CHAPTER_COUNT
    assert {hit.path for hit in hits} == {
        f"canon/chapters/{number:04d}.md" for number in range(1, CHAPTER_COUNT + 1)
    }
    assert import_seconds < MAX_IMPORT_SECONDS
    assert persist_and_read_seconds < MAX_PERSIST_AND_READ_SECONDS
    assert rebuild_and_search_seconds < MAX_REBUILD_AND_SEARCH_SECONDS
    assert total_seconds < MAX_IMPORT_SECONDS + MAX_PERSIST_AND_READ_SECONDS
    assert peak < MAX_PEAK_MEMORY_BYTES
