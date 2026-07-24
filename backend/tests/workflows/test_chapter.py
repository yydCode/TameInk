from pathlib import Path

import pytest

from app.agents.schemas import (
    ChapterDraft,
    ChapterPlan,
    CommercialDimensionScore,
    CommercialIssue,
    CommercialReport,
    ContinuityIssue,
    MemoryCuration,
    RevisionProposal,
    StyleIssue,
)
from app.domain.commercial import CommercialProfile
from app.domain.errors import CommercialGateError, StorageWriteError, WorkflowGateError
from app.repositories.database import DatabaseRepository
from app.repositories.revisions import RevisionRepository
from app.repositories.tasks import TasksRepository
from app.workflows.chapter import ChapterService
from app.workflows.commercial import CommercialService
from app.workflows.new_book import NewBookRequest, NewBookService
from app.workflows.outline import OutlineService

COMMERCIAL_DIMENSIONS = [
    "opening_urgency",
    "reader_promise",
    "emotional_payoff",
    "conflict_escalation",
    "information_clarity",
    "chapter_hook",
    "differentiation",
]


def approve_commercial_profile(workspace, minimum_score: int = 70) -> None:
    profile = CommercialProfile(
        platform="fanqie",
        monetization="free_ad",
        target_reader="悬疑读者",
        core_fantasy="破解不可能犯罪",
        differentiator="线索会反向误导侦探",
        emotional_payoffs=["识破骗局"],
        opening_promise="第一章发生密室命案",
        first_thirty_chapter_promise="破解主案并揭示幕后组织",
        update_cadence="每日两章",
        title_candidates=["长夜密室"],
        synopsis="侦探必须在被陷害前破解密室命案。",
        minimum_commercial_score=minimum_score,
    )
    service = CommercialService(workspace)
    task = service.create("night-01", profile)
    service.approve("night-01", task.id)


def commercial_report(reference: list[dict[str, str]], score: int = 80) -> CommercialReport:
    return CommercialReport(
        id=f"commercial-{score}",
        chapter_id="0001",
        total_score=score,
        recommendation="pass" if score >= 70 else "revise",
        dimensions=[
            CommercialDimensionScore(dimension=dimension, score=score, reason="有正文证据")
            for dimension in COMMERCIAL_DIMENSIONS
        ],
        issues=[],
        references=reference,
    )


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
    approve_commercial_profile(workspace)
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


def test_selected_memory_candidate_is_committed_atomically_with_chapter(
    tmp_path: Path,
) -> None:
    from app.repositories.canon import CanonRepository
    from app.repositories.workspace import WorkspaceRepository

    workspace = WorkspaceRepository(tmp_path)
    books = NewBookService(workspace)
    setting = books.create(
        NewBookRequest(
            project_id="night-01",
            title="长夜",
            genre="悬疑",
            target_words=1000,
            constraints="第三人称",
        ),
        "设定",
    )
    books.approve_setting("night-01", setting.task.id)
    outlines = OutlineService(workspace)
    book = outlines.create_book("night-01", "大纲")
    outlines.approve_book("night-01", book.id)
    volume = outlines.create_volume("night-01", "1", "分卷")
    outlines.approve_volume("night-01", volume.id, "1")
    candidates = MemoryCuration(
        id="memory-curation-1",
        updates=[
            {
                "stable_id": "old-city-rain",
                "kind": "fact",
                "operation": "create",
                "content": "旧城在第一章处于雨夜",
                "citation": {
                    "source": "draft",
                    "location": "chars:2-6",
                    "quote": "旧城落雨",
                },
            }
        ],
        references=[{"path": "canon/outline.md", "location": "full document", "quote": "大纲"}],
    )
    chapters = ChapterService(workspace)
    task = chapters.start(
        "night-01",
        "0001",
        "计划",
        "雨夜旧城落雨。",
        [],
        memory_candidates=candidates,
    )

    completed = chapters.approve("night-01", task.id, "0001", accepted_memory_ids=["old-city-rain"])
    memory = CanonRepository(workspace).read_memory("night-01", "memory/facts/old-city-rain.yaml")

    assert completed.status.value == "completed"
    assert memory.content == "旧城在第一章处于雨夜"
    assert memory.source == "canon/chapters/0001.md"
    assert memory.location == "line 1, column 3, char 2"
    assert memory.quote == "旧城落雨"


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
    approve_commercial_profile(workspace)
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
                    id="plan-1",
                    chapter_id="0001",
                    content="计划",
                    context_intent={"keywords": ["旧句事实"]},
                    references=reference,
                    chapter_end_hook="章末钩子",
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
            if agent == "RetentionAuditor":
                return commercial_report(reference)
            if agent == "MemoryCurator":
                return MemoryCuration(id="memory-1", updates=[], references=reference)
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

    task = ChapterService(workspace, runner=FakeRunner()).run("night-01", "0001", "写下一章")

    assert calls == [
        "ChapterPlanner",
        "DraftWriter",
        "ContinuityAuditor",
        "StyleCritic",
        "RetentionAuditor",
        "DraftWriter",
        "RetentionAuditor",
        "MemoryCurator",
    ]
    assert task.status == "awaiting_approval"
    from app.repositories.drafts import DraftRepository

    assert DraftRepository(workspace).read("night-01", task.id, "chapter.md") == "新句。保留句。"


def test_low_commercial_score_requires_audited_override_reason(tmp_path: Path) -> None:
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
    approve_commercial_profile(workspace, minimum_score=80)
    outlines = OutlineService(workspace)
    book = outlines.create_book("night-01", "大纲")
    outlines.approve_book("night-01", book.id)
    volume = outlines.create_volume("night-01", "1", "分卷")
    outlines.approve_volume("night-01", volume.id, "1")
    report = commercial_report(
        [{"path": "canon/outline.md", "location": "paragraph 1", "quote": "大纲"}],
        score=60,
    )
    task = ChapterService(workspace).start(
        "night-01",
        "0001",
        "计划",
        "正文",
        [],
        commercial_report=report,
        minimum_commercial_score=80,
    )

    with pytest.raises(CommercialGateError):
        ChapterService(workspace).approve("night-01", task.id, "0001")

    completed = ChapterService(workspace).approve(
        "night-01", task.id, "0001", commercial_override_reason="编辑确认该章承担铺垫作用"
    )

    assert completed.status == "completed"
    assert (
        workspace.project_path("night-01")
        / ".tame-ink/drafts"
        / task.id
        / "commercial-override.txt"
    ).read_text() == "编辑确认该章承担铺垫作用"


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


def test_audit_citation_location_is_derived_from_unique_exact_quote() -> None:
    draft = "前句。只改这一句。后句。"
    reference = [{"path": "canon/outline.md", "location": "paragraph 1", "quote": "大纲"}]
    issue = CommercialIssue(
        id="commercial-1",
        severity="error",
        dimension="reader_promise",
        description="承诺未兑现",
        citation={"source": "draft", "location": "chars:0-1", "quote": "只改这一句"},
        references=reference,
    )

    [normalized] = ChapterService.normalize_audit_citations(draft, [issue])

    assert normalized.citation.location == "chars:3-8"
    assert issue.citation.location == "chars:0-1"
    assert ChapterService.validate_audit_issues(draft, [], [], [normalized]) == [normalized]


@pytest.mark.parametrize("draft", ["不存在目标", "重复。重复。"])
def test_audit_citation_normalization_rejects_missing_or_ambiguous_quote(draft: str) -> None:
    reference = [{"path": "canon/outline.md", "location": "paragraph 1", "quote": "大纲"}]
    issue = StyleIssue(
        id="style-1",
        severity="warning",
        description="表达重复",
        citation={"source": "draft", "location": "chars:0-2", "quote": "重复"},
        references=reference,
    )

    with pytest.raises(WorkflowGateError, match="uniquely"):
        ChapterService.normalize_audit_citations(draft, [issue])


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
