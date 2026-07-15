from pathlib import Path

import pytest

from app.agents.schemas import (
    ChapterDraft,
    ChapterPlan,
    ContinuityIssue,
    RevisionProposal,
    StyleIssue,
)
from app.domain.errors import StorageWriteError, WorkflowGateError
from app.repositories.database import DatabaseRepository
from app.repositories.revisions import RevisionRepository
from app.repositories.tasks import TasksRepository
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
    history_before = len(RevisionRepository(workspace).history("night-01"))
    completed = chapters.approve("night-01", task.id, "0001")

    assert completed.status == "completed"
    assert (
        workspace.project_path("night-01") / "canon/chapters/0001.md"
    ).read_text() == "新句。保留句。"
    assert (workspace.project_path("night-01") / "memory/summaries/chapters/0001.md").is_file()
    assert RevisionRepository(workspace).history("night-01")[0].message == "确认：章节 0001"
    assert len(RevisionRepository(workspace).history("night-01")) == history_before + 1


def test_chapter_approval_storage_failure_is_atomic_and_marks_task_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
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
    task = chapters.start("night-01", "0001", "计划", "正文", [])
    current = RevisionRepository(workspace).current_revision("night-01")
    calls = 0
    replace = RevisionRepository._replace_file

    def fail_second(path: Path, payload: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("disk full")
        replace(path, payload)

    monkeypatch.setattr(RevisionRepository, "_replace_file", staticmethod(fail_second))

    with pytest.raises(StorageWriteError) as raised:
        chapters.approve("night-01", task.id, "0001")

    project = workspace.project_path("night-01")
    assert raised.value.code == "STORAGE_WRITE_FAILED"
    assert RevisionRepository(workspace).current_revision("night-01") == current
    assert not (project / "canon/chapters/0001.md").exists()
    assert not (project / "memory/summaries/chapters/0001.md").exists()
    stored = TasksRepository(DatabaseRepository(workspace), "night-01").get(task.id)
    assert stored.status == "failed"


def test_chapter_pipeline_runs_planner_writer_independent_auditors_and_local_revision(
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
    reference = [{"path": "canon/outline.md", "location": "paragraph 1", "quote": "大纲"}]
    calls: list[str] = []

    class FakeRunner:
        def invoke(self, agent: str, payload: dict[str, object]) -> object:
            calls.append(agent)
            if agent == "ChapterPlanner":
                return ChapterPlan(
                    id="plan-1", chapter_id="0001", content="计划", references=reference
                )
            if agent == "DraftWriter" and calls.count("DraftWriter") == 1:
                return ChapterDraft(
                    id="draft-1", chapter_id="0001", markdown="旧句。保留句。", references=reference
                )
            if agent == "ContinuityAuditor":
                return [
                    ContinuityIssue(
                        id="continuity-1",
                        severity="error",
                        description="事实冲突",
                        citation={"source": "draft", "location": "chars:0-2", "quote": "旧句"},
                        references=reference,
                    )
                ]
            if agent == "StyleCritic":
                return [
                    StyleIssue(
                        id="style-1",
                        severity="warning",
                        description="表达重复",
                        citation={"source": "draft", "location": "chars:3-6", "quote": "保留句"},
                        references=reference,
                    )
                ]
            assert agent == "DraftWriter"
            return [
                RevisionProposal(
                    id="revision-1",
                    issue_id="continuity-1",
                    target="chars:0-2",
                    replacement="新句",
                    reason="修复冲突",
                    citation={"source": "draft", "location": "chars:0-2", "quote": "旧句"},
                    references=reference,
                )
            ]

    task = ChapterService(workspace, runner=FakeRunner()).run(
        "night-01", "0001", "写下一章"
    )

    assert calls == [
        "ChapterPlanner",
        "DraftWriter",
        "ContinuityAuditor",
        "StyleCritic",
        "DraftWriter",
    ]
    assert task.status == "awaiting_approval"
    from app.repositories.drafts import DraftRepository

    assert DraftRepository(workspace).read("night-01", task.id, "chapter.md") == "新句。保留句。"


def test_chapter_pipeline_rejects_duplicate_issue_ids_across_independent_auditors() -> None:
    draft = "旧句。"
    citation = {"source": "draft", "location": "chars:0-2", "quote": "旧句"}
    reference = [{"path": "canon/outline.md", "location": "paragraph 1", "quote": "大纲"}]
    continuity = ContinuityIssue(
        id="same", severity="error", description="冲突", citation=citation, references=reference
    )
    style = StyleIssue(
        id="same", severity="warning", description="重复", citation=citation, references=reference
    )
    with pytest.raises(WorkflowGateError, match="unique"):
        ChapterService.validate_audit_issues(draft, [continuity], [style])


def test_local_revision_rejects_unreported_issue_fabricated_citation_and_whole_chapter() -> None:
    draft = "旧句。保留句。"
    reference = [{"path": "canon/outline.md", "location": "paragraph 1", "quote": "大纲"}]
    issue = ContinuityIssue(
        id="i-1",
        severity="error",
        description="冲突",
        citation={"source": "draft", "location": "chars:0-2", "quote": "旧句"},
        references=reference,
    )

    def revision(issue_id: str, target: str, quote: str, replacement: str) -> RevisionProposal:
        return RevisionProposal(
            id="r-1",
            issue_id=issue_id,
            target=target,
            replacement=replacement,
            reason="修复",
            citation={"source": "draft", "location": target, "quote": quote},
            references=reference,
        )

    for proposal in (
        revision("unknown", "chars:0-2", "旧句", "新句"),
        revision("i-1", "chars:0-2", "伪造", "新句"),
        revision("i-1", "chars:0-8", draft, "整章重写"),
    ):
        with pytest.raises(WorkflowGateError):
            ChapterService.apply_revisions(draft, [issue], [proposal])


def test_local_revision_rejects_whole_chapter_even_when_issue_cites_it() -> None:
    draft = "旧句。保留句。"
    reference = [{"path": "canon/outline.md", "location": "paragraph 1", "quote": "大纲"}]
    citation = {"source": "draft", "location": f"chars:0-{len(draft)}", "quote": draft}
    issue = ContinuityIssue(
        id="i-1", severity="error", description="整章问题", citation=citation, references=reference
    )
    proposal = RevisionProposal(
        id="r-1",
        issue_id="i-1",
        target=f"chars:0-{len(draft)}",
        replacement="整章重写",
        reason="修复",
        citation=citation,
        references=reference,
    )

    with pytest.raises(WorkflowGateError, match="whole chapter"):
        ChapterService.apply_revisions(draft, [issue], [proposal])
