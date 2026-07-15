from pathlib import Path

import pytest

from app.domain.errors import WorkflowGateError
from app.repositories.canon import CanonRepository
from app.repositories.revisions import RevisionRepository
from app.repositories.workspace import WorkspaceRepository
from app.workflows.new_book import NewBookRequest, NewBookService
from app.workflows.outline import OutlineService


def test_new_book_keeps_setting_draft_outside_canon_until_explicit_approval(tmp_path: Path) -> None:
    workspace = WorkspaceRepository(tmp_path)
    service = NewBookService(workspace)

    created = service.create(
        NewBookRequest(
            project_id="night-01",
            title="长夜",
            genre="悬疑",
            target_words=200000,
            constraints="第一人称",
        ),
        "# 设定\n雨夜",
    )

    project = workspace.project_path("night-01")
    assert CanonRepository(workspace).read_project("night-01").title == "长夜"
    assert CanonRepository(workspace).read_project("night-01").genre == "悬疑"
    assert CanonRepository(workspace).read_project("night-01").target_words == 200000
    assert not (project / "canon/world/setting.md").exists()
    assert (project / ".tame-ink/drafts" / created.task.id / "setting.md").exists()

    service.approve_setting("night-01", created.task.id)

    assert (project / "canon/world/setting.md").read_text() == "# 设定\n雨夜"
    assert RevisionRepository(workspace).history("night-01")[0].message == "确认：故事设定"


def test_volume_requires_approved_book_outline(tmp_path: Path) -> None:
    workspace = WorkspaceRepository(tmp_path)
    NewBookService(workspace).create(
        NewBookRequest(
            project_id="night-01",
            title="长夜",
            genre="悬疑",
            target_words=200000,
            constraints="第一人称",
        ),
        "设定",
    )
    outlines = OutlineService(workspace)

    with pytest.raises(WorkflowGateError, match="book outline"):
        outlines.create_volume("night-01", "第一卷", "内容")
