"""P0-P3 人机协作能力的端到端集成测试。

用 FakeRunner 预设所有 Agent 的结构化响应，验证：
- 章纲审批环节（run_plan → approve_plan → draft pipeline）
- 迭代修改（revise_draft）
- 局部重生成（locally_revise）
- 审计报告读取（read_audit_reports）
- 阶段查询（read_stage）
- 记忆候选编辑（update_memory_candidate）
"""

from pathlib import Path

import pytest

from app.agents.schemas import (
    ChapterDraft,
    ChapterPlan,
    CommercialDimensionScore,
    CommercialReport,
    ContinuityIssue,
    DraftWriterResult,
    MemoryCandidate,
    MemoryCuration,
    RevisionProposal,
    StyleIssue,
)
from app.domain.commercial import CommercialProfile
from app.domain.errors import WorkflowGateError
from app.domain.task import TaskKind, TaskPurpose
from app.repositories.database import DatabaseRepository
from app.repositories.drafts import DraftRepository
from app.repositories.tasks import TasksRepository
from app.repositories.workspace import WorkspaceRepository
from app.workflows.chapter import ChapterService
from app.workflows.commercial import CommercialService
from app.workflows.new_book import NewBookRequest, NewBookService
from app.workflows.outline import OutlineService
from app.workflows.task_service import TaskService

COMMERCIAL_DIMENSIONS = [
    "opening_urgency",
    "reader_promise",
    "emotional_payoff",
    "conflict_escalation",
    "information_clarity",
    "chapter_hook",
    "differentiation",
]
REFERENCE = [{"path": "canon/outline.md", "location": "paragraph 1", "quote": "大纲"}]


def _commercial_report(score: int = 80) -> CommercialReport:
    return CommercialReport(
        id=f"commercial-{score}",
        chapter_id="0001",
        total_score=score,
        recommendation="pass" if score >= 70 else "revise",
        dimensions=[
            CommercialDimensionScore(dimension=dim, score=score, reason="有正文证据")
            for dim in COMMERCIAL_DIMENSIONS
        ],
        issues=[],
        references=REFERENCE,
    )


def _make_project(tmp_path: Path) -> WorkspaceRepository:
    """创建完整前置条件的项目：设定+商业+大纲+分卷全部已确认。"""
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
        minimum_commercial_score=70,
    )
    commercial_task = CommercialService(workspace).create("night-01", profile)
    CommercialService(workspace).approve("night-01", commercial_task.id)
    outlines = OutlineService(workspace)
    book = outlines.create_book("night-01", "大纲")
    outlines.approve_book("night-01", book.id)
    volume = outlines.create_volume("night-01", "1", "分卷")
    outlines.approve_volume("night-01", volume.id, "1")
    return workspace


def _resume_task(workspace: WorkspaceRepository, project_id: str, task_id: str) -> None:
    """将 AWAITING_APPROVAL 的任务转回 RUNNING，模拟 job executor 入队新阶段。"""
    service = TaskService(TasksRepository(DatabaseRepository(workspace), project_id))
    service.approve(task_id)


def _start_chapter_task(
    workspace: WorkspaceRepository, project_id: str, chapter_id: str, volume_id: str = "1"
) -> str:
    """创建并启动一个 CHAPTER 任务（RUNNING），用于 run_plan_for_task 等入口。"""
    service = TaskService(TasksRepository(DatabaseRepository(workspace), project_id))
    task = service.create(
        TaskKind.WRITE, TaskPurpose.CHAPTER, subject_id=chapter_id,
        volume_id=volume_id, chapter_id=chapter_id,
    )
    service.start(task.id)
    return task.id


class _FullRunner:
    """模拟全流程 Agent 响应。

    Pipeline 顺序：
      ChapterPlanner → DraftWriter(1) → 3 Auditors → DraftWriter(2, revision)
      → RetentionAuditor(2, final) → MemoryCurator
    revised draft = "新句。保留句。" (旧句→新句)
    """

    def __init__(self) -> None:
        self.calls: list[str] = []

    def invoke(self, agent: str, payload: dict[str, object]) -> object:
        self.calls.append(agent)
        if agent == "ChapterPlanner":
            return ChapterPlan(
                id="plan-1",
                chapter_id="0001",
                content="第一章计划",
                context_intent={"keywords": ["密室"]},
                references=REFERENCE,
                chapter_end_hook="章末钩子",
            )
        if agent == "DraftWriter":
            if "local_revision" in payload:
                return DraftWriterResult(
                    id="local-rev-1",
                    chapter_id="0001",
                    markdown="重写的段落",
                    references=REFERENCE,
                )
            if "issues" in payload:
                return [
                    RevisionProposal(
                        id="rev-1",
                        issue_id="continuity-1",
                        target="chars:0-2",
                        replacement="新句",
                        reason="修复冲突",
                        citation={"source": "draft", "location": "chars:0-2", "quote": "旧句"},
                        references=REFERENCE,
                    )
                ]
            return ChapterDraft(
                id="draft-1",
                chapter_id="0001",
                markdown="旧句。保留句。",
                references=REFERENCE,
            )
        if agent == "ContinuityAuditor":
            if "instruction" in payload:
                return []
            return [
                ContinuityIssue(
                    id="continuity-1",
                    severity="error",
                    description="事实冲突",
                    citation={"source": "draft", "location": "chars:0-2", "quote": "旧句"},
                    references=REFERENCE,
                )
            ]
        if agent == "StyleCritic":
            if "instruction" in payload:
                return []
            return [
                StyleIssue(
                    id="style-1",
                    severity="warning",
                    description="表达重复",
                    citation={"source": "draft", "location": "chars:3-6", "quote": "保留句"},
                    references=REFERENCE,
                )
            ]
        if agent == "RetentionAuditor":
            return _commercial_report()
        if agent == "MemoryCurator":
            return MemoryCuration(
                id="memory-1",
                updates=[
                    MemoryCandidate(
                        stable_id="fact-rain",
                        kind="fact",
                        operation="create",
                        content="雨城在第一章处于雨夜",
                        citation={
                            "source": "draft",
                            "location": "chars:0-2",
                            "quote": "新句",
                        },
                    )
                ],
                references=REFERENCE,
            )
        raise AssertionError(f"unexpected agent: {agent}")


# ============================================================================
# P0: 章纲审批环节
# ============================================================================


def test_chapter_plan_only_then_approve_and_continue(tmp_path: Path) -> None:
    """P0: 只跑章纲 → 人审 → 批准后跑正文流水线。"""
    workspace = _make_project(tmp_path)
    runner = _FullRunner()
    chapters = ChapterService(workspace, runner=runner)

    task_id = _start_chapter_task(workspace, "night-01", "0001")
    task = chapters.run_plan_for_task("night-01", task_id, "0001", "写第一章", "1")

    assert task.status.value == "awaiting_approval"
    assert "ChapterPlanner" in runner.calls
    assert "DraftWriter" not in runner.calls
    drafts = DraftRepository(workspace)
    files = drafts.list_files("night-01", task.id)
    assert "plan.md" in files
    assert "plan.json" in files
    assert "chapter.md" not in files
    assert chapters.read_stage("night-01", task.id) == "plan_awaiting_approval"


def test_approve_plan_and_continue_runs_draft_pipeline(tmp_path: Path) -> None:
    """P0: 批准章纲后跑完整正文流水线。"""
    workspace = _make_project(tmp_path)
    runner = _FullRunner()
    chapters = ChapterService(workspace, runner=runner)

    task_id = _start_chapter_task(workspace, "night-01", "0001")
    task = chapters.run_plan_for_task("night-01", task_id, "0001", "写第一章", "1")
    _resume_task(workspace, "night-01", task.id)
    completed = chapters.approve_plan_and_continue("night-01", task.id, "0001", "1")

    assert completed.status.value == "awaiting_approval"
    assert "DraftWriter" in runner.calls
    assert "ContinuityAuditor" in runner.calls
    assert "MemoryCurator" in runner.calls
    assert chapters.read_stage("night-01", task.id) == "draft_awaiting_approval"


def test_chapter_full_run_writes_stage_draft_awaiting(tmp_path: Path) -> None:
    """P0: 全流程跑完后 stage=draft_awaiting_approval。"""
    workspace = _make_project(tmp_path)
    runner = _FullRunner()
    chapters = ChapterService(workspace, runner=runner)

    task = chapters.run("night-01", "0001", "写第一章", "1")

    assert task.status.value == "awaiting_approval"
    assert chapters.read_stage("night-01", task.id) == "draft_awaiting_approval"


# ============================================================================
# P1: 审计报告读取
# ============================================================================


def test_audit_reports_visible_after_full_run(tmp_path: Path) -> None:
    """P1: 全流程跑完后审计报告对人可见。"""
    workspace = _make_project(tmp_path)
    runner = _FullRunner()
    chapters = ChapterService(workspace, runner=runner)

    task = chapters.run("night-01", "0001", "写第一章", "1")
    reports = chapters.read_audit_reports("night-01", task.id)

    assert "continuity" in reports
    assert "style" in reports
    assert len(reports["continuity"]) == 1
    assert reports["continuity"][0]["id"] == "continuity-1"


# ============================================================================
# P2: 记忆候选编辑
# ============================================================================


def test_update_memory_candidate_content(tmp_path: Path) -> None:
    """P2: 人编辑 AI 提取的记忆候选内容。"""
    workspace = _make_project(tmp_path)
    runner = _FullRunner()
    chapters = ChapterService(workspace, runner=runner)

    task = chapters.run("night-01", "0001", "写第一章", "1")
    candidates = chapters.read_memory_candidates("night-01", task.id)
    assert len(candidates) == 1
    assert candidates[0].stable_id == "fact-rain"

    updated = chapters.update_memory_candidate(
        "night-01", task.id, "fact-rain", "人修正后的记忆内容"
    )
    assert updated[0].content == "人修正后的记忆内容"

    reloaded = chapters.read_memory_candidates("night-01", task.id)
    assert reloaded[0].content == "人修正后的记忆内容"


def test_update_memory_candidate_rejects_unknown_id(tmp_path: Path) -> None:
    """P2: 编辑不存在的记忆候选应报错。"""
    workspace = _make_project(tmp_path)
    runner = _FullRunner()
    chapters = ChapterService(workspace, runner=runner)

    task = chapters.run("night-01", "0001", "写第一章", "1")
    with pytest.raises(WorkflowGateError, match="memory candidate not found"):
        chapters.update_memory_candidate("night-01", task.id, "nonexistent", "content")


# ============================================================================
# P3: 局部重生成
# ============================================================================


def test_locally_revise_rewrites_segment(tmp_path: Path) -> None:
    """P3: 人选段落，AI 只重写该段。"""
    workspace = _make_project(tmp_path)
    runner = _FullRunner()
    chapters = ChapterService(workspace, runner=runner)

    task = chapters.run("night-01", "0001", "写第一章", "1")
    _resume_task(workspace, "night-01", task.id)
    drafts = DraftRepository(workspace)
    original = drafts.read("night-01", task.id, "chapter.md")
    assert len(original) >= 2
    start, end = 0, 2
    revised_task = chapters.locally_revise(
        "night-01", task.id, "0001", start, end, "改得更紧张", "1"
    )
    assert revised_task.status.value == "awaiting_approval"
    new_draft = drafts.read("night-01", task.id, "chapter.md")
    assert new_draft == "重写的段落" + original[end:]


def test_locally_revise_rejects_empty_range(tmp_path: Path) -> None:
    """P3: 选空段落应报错。"""
    workspace = _make_project(tmp_path)
    runner = _FullRunner()
    chapters = ChapterService(workspace, runner=runner)

    task = chapters.run("night-01", "0001", "写第一章", "1")
    _resume_task(workspace, "night-01", task.id)
    drafts = DraftRepository(workspace)
    drafts.write("night-01", task.id, "chapter.md", "正文。 \n 结尾。")
    original = drafts.read("night-01", task.id, "chapter.md")
    space_index = original.index(" ")
    gap_start = space_index
    gap_end = space_index + 1
    assert original[gap_start:gap_end].strip() == ""
    with pytest.raises(WorkflowGateError, match="target is empty"):
        chapters.locally_revise(
            "night-01", task.id, "0001", gap_start, gap_end, "test", "1"
        )


def test_locally_revise_rejects_out_of_range(tmp_path: Path) -> None:
    """P3: 超出草稿长度应报错。"""
    workspace = _make_project(tmp_path)
    runner = _FullRunner()
    chapters = ChapterService(workspace, runner=runner)

    task = chapters.run("night-01", "0001", "写第一章", "1")
    _resume_task(workspace, "night-01", task.id)
    drafts = DraftRepository(workspace)
    original = drafts.read("night-01", task.id, "chapter.md")
    with pytest.raises(WorkflowGateError, match="exceeds draft length"):
        chapters.locally_revise(
            "night-01", task.id, "0001", 0, len(original) + 100, "test", "1"
        )


# ============================================================================
# P1: 迭代修改（revise_draft）
# ============================================================================


def test_revise_draft_reaudits_and_stores_audit_reports(tmp_path: Path) -> None:
    """P1: 人编辑草稿后重新审计+局部修订，审计报告对人可见。"""
    workspace = _make_project(tmp_path)
    runner = _FullRunner()
    chapters = ChapterService(workspace, runner=runner)

    task = chapters.run("night-01", "0001", "写第一章", "1")
    _resume_task(workspace, "night-01", task.id)
    drafts = DraftRepository(workspace)
    original = drafts.read("night-01", task.id, "chapter.md")
    drafts.write("night-01", task.id, "chapter.md", "人改后的" + original)

    revised_task = chapters.revise_draft("night-01", task.id, "0001", "1")

    assert revised_task.status.value == "awaiting_approval"
    final_draft = drafts.read("night-01", task.id, "chapter.md")
    assert final_draft == "人改后的" + original
    reports = chapters.read_audit_reports("night-01", task.id)
    assert "continuity" in reports
    assert "style" in reports
    assert reports["continuity"] == []
