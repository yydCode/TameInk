from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.agents.schemas import SkillExecutionContract
from app.domain.creation import AuthorDecision, CreativeBrief
from app.domain.errors import ArtifactDecisionError, WorkflowGateError
from app.domain.project import Project
from app.domain.revision import RevisionWrite
from app.domain.task import TaskKind, TaskPurpose, TaskStatus
from app.repositories.artifacts import ArtifactsRepository
from app.repositories.canon import CanonRepository
from app.repositories.database import DatabaseRepository
from app.repositories.revisions import RevisionRepository
from app.repositories.tasks import TasksRepository
from app.repositories.workspace import WorkspaceRepository
from app.workflows.creative import CreativeService
from app.workflows.task_service import TaskService


def setup(tmp_path) -> tuple[WorkspaceRepository, CreativeService]:
    workspace = WorkspaceRepository(tmp_path)
    workspace.create_project("story-01")
    CanonRepository(workspace).write_project(Project(id="story-01", title="长夜", language="zh-CN"))
    DatabaseRepository(workspace).initialize("story-01")
    CanonRepository(workspace).write_creative_brief("story-01", creative_brief())
    return workspace, CreativeService(workspace)


def creative_brief() -> CreativeBrief:
    now = datetime.now(UTC)
    return CreativeBrief(
        version=1,
        platform="fanqie",
        genre_scope="都市职场成长",
        initial_intent="写一个通过专业选择改变处境的长篇故事。",
        first_story_goal="主角必须拿下第一个项目，并暴露一个无法回避的代价。",
        constraints=["第三人称限知"],
        material_boundaries=["仅使用已获授权素材"],
        created_at=now,
        updated_at=now,
    )


def reader_contract_result() -> SkillExecutionContract:
    return SkillExecutionContract.model_validate(
        {
            "id": "reader-contract-result",
            "skill": "webnovel-design-reader-contract",
            "status": "ready",
            "references": [
                {"path": "project.yaml", "location": "chars:0-1", "quote": "i"}
            ],
            "evidence": [],
            "candidate": {
                "artifact_kind": "reader_contract",
                "summary": "都市成长读者契约",
                "payload": {
                    "id": "reader-contract-1",
                    "platform": "fanqie",
                    "channel": "都市",
                    "genre_scope": "都市职场成长",
                    "target_readers": ["职场成长读者"],
                    "core_experience": "主角通过专业选择赢得空间",
                    "protagonist_promise": "每次压力都要求主动选择",
                    "must_payoffs": ["看见专业能力改变处境"],
                    "forbidden_directions": ["无代价万能成功"],
                    "evidence_refs": [],
                },
            },
            "decision_requests": [],
            "effects": [],
        }
    )


def test_skill_result_stays_candidate_until_author_accepts(tmp_path) -> None:
    workspace, creative = setup(tmp_path)
    task = creative.create_skill_task("story-01", "webnovel-design-reader-contract", {})
    TaskService(TasksRepository(DatabaseRepository(workspace), "story-01")).start(task.id)

    stored = creative.store_skill_result("story-01", task.id, reader_contract_result())
    artifact = ArtifactsRepository(DatabaseRepository(workspace), "story-01").list_all()[0]

    assert stored.status is TaskStatus.AWAITING_APPROVAL
    assert artifact.status == "awaiting_approval"
    assert not (
        workspace.project_path("story-01") / "commitments/reader-contract.yaml"
    ).exists()

    decision = AuthorDecision(
        id=str(uuid4()),
        project_id="story-01",
        artifact_id=artifact.id,
        expected_status="awaiting_approval",
        action="accept",
        effects=[],
        target_layer="commitment",
        formal_path="commitments/reader-contract.yaml",
        created_at=datetime.now(UTC),
    )
    completed = creative.decide("story-01", decision)

    assert completed.status is TaskStatus.COMPLETED
    repository = ArtifactsRepository(DatabaseRepository(workspace), "story-01")
    assert repository.get(artifact.id).status == "accepted"
    assert CanonRepository(workspace).read_reader_contract("story-01").id == "reader-contract-1"


def test_start_project_versions_author_brief_before_queuing_research(tmp_path) -> None:
    workspace = WorkspaceRepository(tmp_path)
    creative = CreativeService(workspace)

    created = creative.start_project("new-story", "新故事", creative_brief())

    assert created.task.subject_id == "webnovel-research-genre"
    stored = CanonRepository(workspace).read_creative_brief("new-story")
    assert stored.first_story_goal == "主角必须拿下第一个项目，并暴露一个无法回避的代价。"
    assert RevisionRepository(workspace).current_revision("new-story") is not None


def test_creative_skill_requires_author_brief(tmp_path) -> None:
    workspace = WorkspaceRepository(tmp_path)
    workspace.create_project("without-brief")
    CanonRepository(workspace).write_project(
        Project(id="without-brief", title="未立项", language="zh-CN")
    )
    DatabaseRepository(workspace).initialize("without-brief")

    with pytest.raises(WorkflowGateError):
        CreativeService(workspace).create_skill_task(
            "without-brief", "webnovel-research-genre", {}
        )


def test_hypothesis_conflict_cannot_be_promoted_to_formal_content(tmp_path) -> None:
    workspace, creative = setup(tmp_path)
    task = creative.create_skill_task("story-01", "webnovel-audit", {"audit_kind": "continuity"})
    TaskService(TasksRepository(DatabaseRepository(workspace), "story-01")).start(task.id)
    result = SkillExecutionContract.model_validate(
        {
            "id": "conflict-result",
            "skill": "webnovel-audit",
            "status": "conflict",
            "references": [
                {"path": "project.yaml", "location": "chars:0-1", "quote": "i"}
            ],
            "evidence": [
                {
                    "kind": "conflict",
                    "description": "身份冲突",
                    "reference": {"path": "project.yaml", "location": "chars:0-1", "quote": "i"},
                }
            ],
            "candidate": None,
            "decision_requests": [
                {"id": "identity", "question": "确认身份", "options": ["甲", "乙"]}
            ],
            "effects": [],
        }
    )
    creative.store_skill_result("story-01", task.id, result)
    artifact = ArtifactsRepository(DatabaseRepository(workspace), "story-01").list_all()[0]
    decision = AuthorDecision(
        id=str(uuid4()),
        project_id="story-01",
        artifact_id=artifact.id,
        expected_status="conflict",
        action="accept",
        effects=[],
        target_layer="canon",
        formal_path="canon/chapters/chapter-1.md",
        created_at=datetime.now(UTC),
    )

    with pytest.raises(ArtifactDecisionError):
        creative.decide("story-01", decision)
    assert artifact.status == "conflict"


def test_next_action_prioritizes_author_decision_then_earliest_missing_commitment(tmp_path) -> None:
    workspace, creative = setup(tmp_path)

    assert creative.next_action("story-01").skill == "webnovel-research-genre"
    task = creative.create_skill_task("story-01", "webnovel-research-genre", {})
    TaskService(TasksRepository(DatabaseRepository(workspace), "story-01")).start(task.id)
    research = SkillExecutionContract.model_validate(
        {
            "id": "research-result",
            "skill": "webnovel-research-genre",
            "status": "needs_decision",
            "references": [
                {"path": "project.yaml", "location": "chars:0-1", "quote": "i"}
            ],
            "evidence": [],
            "candidate": None,
            "decision_requests": [
                {"id": "genre", "question": "选择题材", "options": ["都市"]}
            ],
            "effects": [],
        }
    )
    creative.store_skill_result("story-01", task.id, research)

    action = creative.next_action("story-01")
    assert action.kind == "decision"
    assert action.artifact_id is not None


def test_next_action_exposes_interrupted_skill_task_for_explicit_recovery(tmp_path) -> None:
    workspace, creative = setup(tmp_path)
    task = creative.create_skill_task("story-01", "webnovel-research-genre", {})
    tasks = TaskService(TasksRepository(DatabaseRepository(workspace), "story-01"))
    tasks.start(task.id)
    tasks.recover_interrupted()

    action = creative.next_action("story-01")

    assert action.kind == "recover"
    assert action.task_id == task.id


def test_export_reads_only_confirmed_chapters(tmp_path) -> None:
    workspace, creative = setup(tmp_path)
    revisions = RevisionRepository(workspace)
    revisions.confirm(
        "story-01",
        RevisionWrite(
            path="canon/chapters/chapter-1.md",
            content="# 第一章\n\n确认正文",
            message="确认：章节",
        ),
        revisions.current_revision("story-01"),
    )

    exported = creative.export_confirmed_chapters("story-01", "book-export")

    assert exported.task.status is TaskStatus.COMPLETED
    assert exported.chapter_count == 1
    output = workspace.resolve_project_path("story-01", exported.path).read_text()
    assert output == "# 第一章\n\n确认正文\n"


def test_author_can_confirm_memory_proposal_but_not_audit_hypothesis(tmp_path) -> None:
    workspace, creative = setup(tmp_path)
    task = creative.create_skill_task("story-01", "webnovel-curate-memory", {})
    TaskService(TasksRepository(DatabaseRepository(workspace), "story-01")).start(task.id)
    result = SkillExecutionContract.model_validate(
        {
            "id": "memory-result",
            "skill": "webnovel-curate-memory",
            "status": "ready",
            "references": [
                {"path": "project.yaml", "location": "chars:0-1", "quote": "i"}
            ],
            "evidence": [],
            "candidate": {
                "artifact_kind": "memory_proposal",
                "summary": "天气事实",
                "payload": {
                    "id": "weather-rain",
                    "kind": "fact",
                    "status": "active",
                    "source": "canon/chapters/chapter-1.md",
                    "location": "chars:0-2",
                    "quote": "下雨",
                    "content": "北城正在下雨",
                },
            },
            "decision_requests": [],
            "effects": [],
        }
    )
    creative.store_skill_result("story-01", task.id, result)
    artifact = ArtifactsRepository(DatabaseRepository(workspace), "story-01").list_all()[0]
    creative.decide(
        "story-01",
        AuthorDecision(
            id=str(uuid4()),
            project_id="story-01",
            artifact_id=artifact.id,
            expected_status="awaiting_approval",
            action="accept",
            effects=[],
            target_layer="canon",
            formal_path="memory/facts/weather-rain.yaml",
            created_at=datetime.now(UTC),
        ),
    )

    record = CanonRepository(workspace).read_memory("story-01", "memory/facts/weather-rain.yaml")
    assert record.content == "北城正在下雨"


def chapter_draft_result() -> SkillExecutionContract:
    return SkillExecutionContract.model_validate(
        {
            "id": "chapter-draft-result",
            "skill": "webnovel-draft",
            "status": "ready",
            "references": [
                {"path": "project.yaml", "location": "chars:0-1", "quote": "i"}
            ],
            "evidence": [],
            "candidate": {
                "artifact_kind": "chapter_draft",
                "summary": "第一章正文候选",
                "payload": {
                    "markdown": "# 第一章\n\n林越盯着投标书，指尖发凉。他必须拿下这个项目。"
                },
            },
            "decision_requests": [],
            "effects": [],
        }
    )


def test_chapter_draft_accept_writes_markdown_into_canon_chapters(tmp_path) -> None:
    """核心链路守卫：webnovel-draft 候选被作者 accept 后，正文必须落地到 canon/chapters/。"""
    workspace, creative = setup(tmp_path)
    task = creative.create_skill_task(
        "story-01", "webnovel-draft", {"chapter_id": "1", "story_card_ids": []}
    )
    TaskService(TasksRepository(DatabaseRepository(workspace), "story-01")).start(task.id)

    stored = creative.store_skill_result("story-01", task.id, chapter_draft_result())
    artifact = ArtifactsRepository(DatabaseRepository(workspace), "story-01").list_all()[0]

    # accept 之前 canon 里不应有章节文件
    assert stored.status is TaskStatus.AWAITING_APPROVAL
    assert artifact.status == "awaiting_approval"
    chapter_path = workspace.project_path("story-01") / "canon/chapters/chapter-1.md"
    assert not chapter_path.exists()

    decision = AuthorDecision(
        id=str(uuid4()),
        project_id="story-01",
        artifact_id=artifact.id,
        expected_status="awaiting_approval",
        action="accept",
        effects=[],
        target_layer="canon",
        formal_path="canon/chapters/chapter-1.md",
        created_at=datetime.now(UTC),
    )
    completed = creative.decide("story-01", decision)

    # accept 之后：任务完成、artifact 已接受、正文写入 canon
    assert completed.status is TaskStatus.COMPLETED
    repository = ArtifactsRepository(DatabaseRepository(workspace), "story-01")
    assert repository.get(artifact.id).status == "accepted"
    assert chapter_path.exists()
    written = chapter_path.read_text(encoding="utf-8")
    assert "林越盯着投标书" in written


def test_chapter_draft_reject_leaves_canon_untouched(tmp_path) -> None:
    """作者 reject 章节草稿后，canon 不得出现任何章节文件。"""
    workspace, creative = setup(tmp_path)
    task = creative.create_skill_task(
        "story-01", "webnovel-draft", {"chapter_id": "1", "story_card_ids": []}
    )
    TaskService(TasksRepository(DatabaseRepository(workspace), "story-01")).start(task.id)
    creative.store_skill_result("story-01", task.id, chapter_draft_result())
    artifact = ArtifactsRepository(DatabaseRepository(workspace), "story-01").list_all()[0]

    decision = AuthorDecision(
        id=str(uuid4()),
        project_id="story-01",
        artifact_id=artifact.id,
        expected_status="awaiting_approval",
        action="reject",
        effects=[],
        created_at=datetime.now(UTC),
    )
    creative.decide("story-01", decision)

    assert ArtifactsRepository(DatabaseRepository(workspace), "story-01").get(
        artifact.id
    ).status == "rejected"
    assert not (
        workspace.project_path("story-01") / "canon/chapters/chapter-1.md"
    ).exists()


def test_chapter_draft_mix_writes_content_override_into_canon(tmp_path) -> None:
    """段落级审批：作者改写后合并的正文经 content_override 写入 canon，而非原始候选。"""
    workspace, creative = setup(tmp_path)
    task = creative.create_skill_task(
        "story-01", "webnovel-draft", {"chapter_id": "1", "story_card_ids": []}
    )
    TaskService(TasksRepository(DatabaseRepository(workspace), "story-01")).start(task.id)
    creative.store_skill_result("story-01", task.id, chapter_draft_result())
    artifact = ArtifactsRepository(DatabaseRepository(workspace), "story-01").list_all()[0]

    edited = "# 第一章\n\n林越盯着投标书，指尖发凉——这一次他绝不能输。"
    decision = AuthorDecision(
        id=str(uuid4()),
        project_id="story-01",
        artifact_id=artifact.id,
        expected_status="awaiting_approval",
        action="mix",
        effects=[],
        target_layer="canon",
        formal_path="canon/chapters/chapter-1.md",
        content_override=edited,
        created_at=datetime.now(UTC),
    )
    completed = creative.decide("story-01", decision)

    assert completed.status is TaskStatus.COMPLETED
    chapter_path = workspace.project_path("story-01") / "canon/chapters/chapter-1.md"
    written = chapter_path.read_text(encoding="utf-8")
    # 写入的是作者改写后的正文，而非原始候选
    assert "这一次他绝不能输" in written
    assert "他必须拿下这个项目" not in written


def test_content_override_rejected_on_non_mix_action() -> None:
    """守卫：content_override 只允许配合 mix 使用，accept 等动作必须拒绝。"""
    with pytest.raises(ValidationError):
        AuthorDecision(
            id=str(uuid4()),
            project_id="story-01",
            artifact_id=str(uuid4()),
            expected_status="awaiting_approval",
            action="accept",
            effects=[],
            target_layer="canon",
            formal_path="canon/chapters/chapter-1.md",
            content_override="# 第一章\n\n作者改写正文。",
            created_at=datetime.now(UTC),
        )


# ── chapter-phase next_action helpers ─────────────────────────────────────

def _write_story_card(
    workspace: WorkspaceRepository,
    project_id: str,
    card_id: str,
    status: str = "current",
) -> None:
    """Write a minimal story card YAML to commitments/story-cards/."""
    import yaml as _yaml
    revisions = RevisionRepository(workspace)
    content = _yaml.safe_dump(
        {
            "id": card_id,
            "schema_version": 1,
            "decision_id": "00000000-0000-0000-0000-000000000001",
            "confirmed_by": "author",
            "sequence": 1,
            "status": status,
            "goal": "主角拿下第一个项目",
            "motivation": "证明自己的专业价值",
            "cycle_input": "主角处于低谷",
            "cycle_delta": "主角完成第一个里程碑",
            "next_affordance": "敌对方开始注意主角",
        },
        allow_unicode=True,
    )
    revisions.confirm(
        project_id,
        RevisionWrite(
            path=f"commitments/story-cards/{card_id}.yaml",
            content=content,
            message=f"确认：故事卡 {card_id}",
        ),
        revisions.current_revision(project_id),
    )


def _complete_task(
    workspace: WorkspaceRepository, project_id: str, purpose: TaskPurpose
) -> None:
    """Create and immediately complete a task with the given purpose."""
    svc = TaskService(TasksRepository(DatabaseRepository(workspace), project_id))
    task = svc.create(TaskKind.WRITE, purpose)
    svc.start(task.id)
    svc.complete(task.id)


def _setup_story_cards_milestone(tmp_path) -> tuple["WorkspaceRepository", "CreativeService"]:
    """Set up a project that has completed all commitments up to story-cards.

    next_action's `if not artifacts` guard means a real project always has at
    least one artifact record by the time it reaches the story-cards phase, so
    we drive a real research skill through accept to leave one behind, then
    write the reader-contract and story-engine commitments on disk.
    """
    workspace, creative = setup(tmp_path)

    # Leave one terminal (rejected) artifact so next_action passes the
    # `if not artifacts` guard without leaving a blocking decision open.
    task = creative.create_skill_task("story-01", "webnovel-research-genre", {})
    TaskService(TasksRepository(DatabaseRepository(workspace), "story-01")).start(task.id)
    creative.store_skill_result(
        "story-01",
        task.id,
        SkillExecutionContract.model_validate(
            {
                "id": "research-seed",
                "skill": "webnovel-research-genre",
                "status": "needs_decision",
                "references": [{"path": "project.yaml", "location": "chars:0-1", "quote": "i"}],
                "evidence": [],
                "candidate": None,
                "decision_requests": [{"id": "g", "question": "题材", "options": ["都市"]}],
                "effects": [],
            }
        ),
    )
    seed_artifact = ArtifactsRepository(DatabaseRepository(workspace), "story-01").list_all()[0]
    creative.decide(
        "story-01",
        AuthorDecision(
            id=str(uuid4()),
            project_id="story-01",
            artifact_id=seed_artifact.id,
            expected_status="needs_decision",
            action="reject",
            effects=[],
            created_at=datetime.now(UTC),
        ),
    )

    revisions = RevisionRepository(workspace)
    rev_id: str | None = revisions.current_revision("story-01")
    for path, content in [
        ("commitments/reader-contract.yaml", "id: rc-1\nplatform: fanqie\n"),
        ("commitments/story-engine.yaml", "id: se-1\n"),
    ]:
        revision = revisions.confirm(
            "story-01",
            RevisionWrite(path=path, content=content, message=f"确认：{path}"),
            rev_id,
        )
        rev_id = revision.id  # chain: each confirm takes the previous commit's hash
    return workspace, creative


# ── chapter-phase next_action tests ───────────────────────────────────────

def test_next_action_after_story_cards_with_no_current_card_asks_for_input(tmp_path) -> None:
    """Story cards exist but none is marked 'current' → ask author to activate one."""
    workspace, creative = _setup_story_cards_milestone(tmp_path)
    _write_story_card(workspace, "story-01", "card-alpha", status="planned")

    action = creative.next_action("story-01")

    assert action.kind == "input"
    assert "current" in action.reason


def test_next_action_current_card_no_history_suggests_plan_chapter(tmp_path) -> None:
    """Current card present, no CHAPTER/MEMORY tasks completed → start with plan-chapter."""
    workspace, creative = _setup_story_cards_milestone(tmp_path)
    _write_story_card(workspace, "story-01", "card-beta", status="current")

    action = creative.next_action("story-01")

    assert action.kind == "execute"
    assert action.skill == "webnovel-plan-chapter"


def test_next_action_after_chapter_completed_suggests_curate_memory(tmp_path) -> None:
    """Last completed task is CHAPTER → next step is memory curation."""
    workspace, creative = _setup_story_cards_milestone(tmp_path)
    _write_story_card(workspace, "story-01", "card-gamma", status="current")
    _complete_task(workspace, "story-01", TaskPurpose.CHAPTER)

    action = creative.next_action("story-01")

    assert action.kind == "execute"
    assert action.skill == "webnovel-curate-memory"


def test_next_action_after_memory_curation_suggests_plan_chapter_for_new_cycle(tmp_path) -> None:
    """Last completed task is MEMORY_CURATION → new cycle starts with plan-chapter."""
    workspace, creative = _setup_story_cards_milestone(tmp_path)
    _write_story_card(workspace, "story-01", "card-delta", status="current")
    _complete_task(workspace, "story-01", TaskPurpose.CHAPTER)
    _complete_task(workspace, "story-01", TaskPurpose.MEMORY_CURATION)

    action = creative.next_action("story-01")

    assert action.kind == "execute"
    assert action.skill == "webnovel-plan-chapter"


def test_next_action_ignores_malformed_story_card_yaml(tmp_path) -> None:
    """Malformed YAML in a story card file must not crash next_action."""
    workspace, creative = _setup_story_cards_milestone(tmp_path)
    # Write a card with valid status=current first so there's a real current card
    _write_story_card(workspace, "story-01", "card-good", status="current")
    # Then write a malformed file directly (bypass RevisionRepository to avoid validation)
    bad_path = workspace.project_path("story-01") / "commitments/story-cards/bad.yaml"
    bad_path.write_text("{{not: valid: yaml:", encoding="utf-8")

    action = creative.next_action("story-01")

    # Malformed file is skipped; the valid current card is found
    assert action.kind == "execute"
    assert action.skill == "webnovel-plan-chapter"


# ── actual_event / expectation artifact accept tests ──────────────────────

def _curate_memory_result(
    artifact_kind: str, artifact_id: str, payload: dict
) -> SkillExecutionContract:
    """Build a webnovel-curate-memory result with the given artifact."""
    return SkillExecutionContract.model_validate(
        {
            "id": f"curate-result-{artifact_id}",
            "skill": "webnovel-curate-memory",
            "status": "ready",
            "references": [
                {"path": "project.yaml", "location": "chars:0-1", "quote": "i"}
            ],
            "evidence": [],
            "candidate": {
                "artifact_kind": artifact_kind,
                "summary": f"{artifact_kind} 候选",
                "payload": payload,
            },
            "decision_requests": [],
            "effects": [],
        }
    )


def test_actual_event_accept_writes_yaml_to_canon_actual_events(tmp_path) -> None:
    """actual_event accept → canon/actual-events/{id}.yaml must be written."""
    workspace, creative = setup(tmp_path)
    task = creative.create_skill_task("story-01", "webnovel-curate-memory", {})
    TaskService(TasksRepository(DatabaseRepository(workspace), "story-01")).start(task.id)

    payload = {
        "id": "event-first-win",
        "summary": "林越在会议上说服了客户",
        "source": {
            "path": "canon/chapters/chapter-1.md",
            "location": "chars:0-50",
            "quote": "林越站起来，声音稳定。",
        },
        "state_changes": ["客户态度从怀疑转为认可"],
    }
    creative.store_skill_result(
        "story-01", task.id,
        _curate_memory_result("actual_event", "event-first-win", payload),
    )
    artifact = ArtifactsRepository(DatabaseRepository(workspace), "story-01").list_all()[0]

    expected_path = workspace.project_path("story-01") / "canon/actual-events/event-first-win.yaml"
    assert not expected_path.exists()

    decision = AuthorDecision(
        id=str(uuid4()),
        project_id="story-01",
        artifact_id=artifact.id,
        expected_status="awaiting_approval",
        action="accept",
        effects=[],
        target_layer="canon",
        formal_path="canon/actual-events/event-first-win.yaml",
        created_at=datetime.now(UTC),
    )
    completed = creative.decide("story-01", decision)

    assert completed.status is TaskStatus.COMPLETED
    assert ArtifactsRepository(DatabaseRepository(workspace), "story-01").get(
        artifact.id
    ).status == "accepted"
    assert expected_path.exists()
    content = expected_path.read_text(encoding="utf-8")
    assert "林越在会议上说服了客户" in content


def test_expectation_accept_writes_yaml_to_commitments_expectations(tmp_path) -> None:
    """expectation accept → commitments/expectations/{id}.yaml must be written."""
    workspace, creative = setup(tmp_path)
    task = creative.create_skill_task("story-01", "webnovel-curate-memory", {})
    TaskService(TasksRepository(DatabaseRepository(workspace), "story-01")).start(task.id)

    payload = {
        "id": "exp-career-rise",
        "reader_question": "林越能否在公司站稳脚跟？",
        "contract_link": "rc-1",
        "opened_by": {
            "path": "canon/chapters/chapter-1.md",
            "location": "chars:0-30",
            "quote": "第一章",
        },
        "payoff_semantics": "主角通过专业能力证明价值并被认可",
        "scope": "long_term",
        "status": "opened",
    }
    creative.store_skill_result(
        "story-01", task.id,
        _curate_memory_result("expectation", "exp-career-rise", payload),
    )
    artifact = ArtifactsRepository(DatabaseRepository(workspace), "story-01").list_all()[0]

    expected_path = (
        workspace.project_path("story-01") / "commitments/expectations/exp-career-rise.yaml"
    )
    assert not expected_path.exists()

    decision = AuthorDecision(
        id=str(uuid4()),
        project_id="story-01",
        artifact_id=artifact.id,
        expected_status="awaiting_approval",
        action="accept",
        effects=[],
        target_layer="commitment",
        formal_path="commitments/expectations/exp-career-rise.yaml",
        created_at=datetime.now(UTC),
    )
    completed = creative.decide("story-01", decision)

    assert completed.status is TaskStatus.COMPLETED
    assert ArtifactsRepository(DatabaseRepository(workspace), "story-01").get(
        artifact.id
    ).status == "accepted"
    assert expected_path.exists()
    content = expected_path.read_text(encoding="utf-8")
    assert "林越能否在公司站稳脚跟" in content
