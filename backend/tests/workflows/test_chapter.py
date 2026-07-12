from pathlib import Path

import pytest

from app.domain.errors import WorkflowGateError
from app.workflows.chapter import ChapterService
from app.workflows.new_book import NewBookRequest, NewBookService
from app.workflows.outline import OutlineService


def test_chapter_cannot_start_without_approved_outline_and_volume(tmp_path: Path) -> None:
    workspace_service = NewBookService(
        __import__(
            "app.repositories.workspace", fromlist=["WorkspaceRepository"]
        ).WorkspaceRepository(tmp_path)
    )
    workspace_service.create(
        NewBookRequest(
            project_id="night-01",
            title="长夜",
            genre="悬疑",
            target_words=200000,
            constraints="第一人称",
        ),
        "设定",
    )

    with pytest.raises(WorkflowGateError):
        ChapterService(workspace_service.workspace).start("night-01", "0001", "计划", "正文", [])


def test_chapter_approval_commits_only_issue_local_revision_and_derives_summary(
    tmp_path: Path,
) -> None:
    from app.repositories.workspace import WorkspaceRepository

    workspace = WorkspaceRepository(tmp_path)
    books = NewBookService(workspace)
    setting = books.create(
        NewBookRequest(
            project_id="night-01", title="长夜", genre="悬疑", target_words=1, constraints="x"
        ),
        "设定",
    )
    books.approve_setting("night-01", setting.task.id)
    outlines = OutlineService(workspace)
    book = outlines.create_book("night-01", "大纲")
    outlines.approve_book("night-01", book.id)
    volume = outlines.create_volume("night-01", "1", "分卷")
    outlines.approve_volume("night-01", volume.id, "1")

    chapters = ChapterService(workspace)
    task = chapters.start(
        "night-01",
        "0001",
        "计划",
        "旧句。保留句。",
        [{"id": "i-1", "citation": "旧句", "target": "旧句", "replacement": "新句"}],
    )
    completed = chapters.approve("night-01", task.id, "0001")

    assert completed.status == "completed"
    assert (
        workspace.project_path("night-01") / "canon/chapters/0001.md"
    ).read_text() == "新句。保留句。"
    assert (workspace.project_path("night-01") / "memory/summaries/chapters/0001.md").is_file()
