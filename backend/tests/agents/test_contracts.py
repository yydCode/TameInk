import pytest
from pydantic import ValidationError

from app.agents.schemas import (
    ChapterDraft,
    ChapterPlan,
    ContinuityIssue,
    DraftCitation,
    ImportAnalysis,
    MemoryCuration,
    Outline,
    RevisionProposal,
    SkillExecutionContract,
    SourceReference,
    StorySetting,
    StyleIssue,
)

REFERENCE = {"path": "canon/premise.md", "location": "paragraph 2", "quote": "已确认事实"}


@pytest.mark.parametrize(
    ("schema", "payload"),
    [
        (
            StorySetting,
            {"id": "setting-1", "title": "设定", "content": "内容", "references": [REFERENCE]},
        ),
        (
            Outline,
            {
                "id": "outline-1",
                "kind": "book",
                "title": "全书大纲",
                "content": "内容",
                "references": [REFERENCE],
            },
        ),
        (
            ChapterPlan,
            {
                "id": "plan-1",
                "chapter_id": "chapter-1",
                "content": "内容",
                "context_intent": {"keywords": ["已确认事实"]},
                "references": [REFERENCE],
            },
        ),
        (
            ChapterDraft,
            {
                "id": "draft-1",
                "chapter_id": "chapter-1",
                "markdown": "正文",
                "references": [REFERENCE],
            },
        ),
        (
            ContinuityIssue,
            {
                "id": "issue-1",
                "severity": "error",
                "description": "冲突",
                "citation": {"source": "draft", "location": "chars:0-2", "quote": "正文"},
                "references": [REFERENCE],
            },
        ),
        (
            StyleIssue,
            {
                "id": "style-1",
                "severity": "warning",
                "description": "重复",
                "citation": {"source": "draft", "location": "chars:0-2", "quote": "正文"},
                "references": [REFERENCE],
            },
        ),
        (
            RevisionProposal,
            {
                "id": "revision-1",
                "issue_id": "issue-1",
                "target": "chars:0-2",
                "replacement": "替换",
                "reason": "修复",
                "citation": {"source": "draft", "location": "chars:0-2", "quote": "正文"},
                "references": [REFERENCE],
            },
        ),
        (
            MemoryCuration,
            {
                "id": "memory-1",
                "updates": [
                    {
                        "stable_id": "weather-rain",
                        "kind": "fact",
                        "operation": "create",
                        "content": "旧城正在下雨",
                        "citation": {
                            "source": "draft",
                            "location": "chars:0-2",
                            "quote": "正文",
                        },
                    }
                ],
                "references": [REFERENCE],
            },
        ),
        (
            ImportAnalysis,
            {"id": "import-1", "summary": "分析", "content": "结构", "references": [REFERENCE]},
        ),
    ],
)
def test_agent_output_schemas_accept_strict_valid_payload(schema, payload) -> None:
    result = schema.model_validate(payload)
    assert result.id


def test_agent_output_rejects_extra_fields() -> None:
    payload = {
        "id": "setting-1",
        "title": "设定",
        "content": "内容",
        "references": [REFERENCE],
        "guess": "no",
    }
    with pytest.raises(ValidationError):
        StorySetting.model_validate(payload)


@pytest.mark.parametrize("field", ["path", "location", "quote"])
def test_reference_rejects_missing_or_blank_required_parts(field: str) -> None:
    payload = dict(REFERENCE)
    payload[field] = ""
    with pytest.raises(ValidationError):
        SourceReference.model_validate(payload)


@pytest.mark.parametrize(
    "path", ["/etc/passwd", "canon/../memory/facts/a.yaml", "canon\\premise.md", "drafts/a.md"]
)
def test_reference_rejects_non_formal_paths(path: str) -> None:
    with pytest.raises(ValidationError):
        SourceReference.model_validate({**REFERENCE, "path": path})


def test_output_rejects_missing_references_and_blank_ids() -> None:
    with pytest.raises(ValidationError):
        ChapterDraft.model_validate(
            {"id": " ", "chapter_id": "chapter-1", "markdown": "正文", "references": []},
        )


def test_draft_citation_has_parseable_exact_character_range() -> None:
    citation = DraftCitation.model_validate(
        {"source": "draft", "location": "chars:0-2", "quote": "正文"}
    )
    assert citation.character_range() == (0, 2)
    assert DraftCitation.model_json_schema()["properties"]["location"]["pattern"] == (
        r"^chars:\d+-\d+$"
    )


@pytest.mark.parametrize("location", ["line 1", "chars:2-1", "chars:-1-2"])
def test_draft_citation_rejects_unparseable_or_reversed_range(location: str) -> None:
    with pytest.raises(ValidationError):
        DraftCitation.model_validate({"source": "draft", "location": location, "quote": "正文"})


def test_skill_execution_contract_distinguishes_ready_decision_and_conflict() -> None:
    ready = SkillExecutionContract.model_validate(
        {
            "id": "execution-1",
            "skill": "webnovel-plan-rolling-story",
            "status": "ready",
            "references": [REFERENCE],
            "evidence": [],
            "candidate": {
                "artifact_kind": "story_card",
                "summary": "下一单元候选",
                "payload": {"goal": "拿到线索"},
            },
            "decision_requests": [],
            "effects": [],
        }
    )
    needs_decision = SkillExecutionContract.model_validate(
        {
            "id": "execution-2",
            "skill": "webnovel-design-reader-contract",
            "status": "needs_decision",
            "references": [REFERENCE],
            "evidence": [],
            "candidate": None,
            "decision_requests": [
                {"id": "decision-1", "question": "主角是否公开身份？", "options": ["公开"]}
            ],
            "effects": [],
        }
    )
    conflict = SkillExecutionContract.model_validate(
        {
            "id": "execution-3",
            "skill": "webnovel-audit",
            "status": "conflict",
            "references": [REFERENCE],
            "evidence": [
                {
                    "kind": "conflict",
                    "description": "正式身份互相冲突",
                    "reference": REFERENCE,
                }
            ],
            "candidate": None,
            "decision_requests": [
                {"id": "decision-2", "question": "采用哪个身份？", "options": ["流民"]}
            ],
            "effects": [],
        }
    )

    assert ready.status == "ready"
    assert needs_decision.status == "needs_decision"
    assert conflict.status == "conflict"


@pytest.mark.parametrize(
    "payload",
    [
        {
            "id": "bad-ready",
            "skill": "webnovel-draft",
            "status": "ready",
            "references": [REFERENCE],
            "evidence": [],
            "candidate": None,
            "decision_requests": [],
            "effects": [],
        },
        {
            "id": "bad-conflict",
            "skill": "webnovel-audit",
            "status": "conflict",
            "references": [REFERENCE],
            "evidence": [],
            "candidate": None,
            "decision_requests": [],
            "effects": [],
        },
    ],
)
def test_skill_execution_contract_rejects_hidden_fallbacks(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        SkillExecutionContract.model_validate(payload)


def test_skill_execution_contract_rejects_effects_when_author_decision_is_required() -> None:
    with pytest.raises(ValidationError, match="BLOCKED_EFFECTS_UNEXPECTED"):
        SkillExecutionContract.model_validate(
            {
                "id": "blocked-effects",
                "skill": "webnovel-design-reader-contract",
                "status": "needs_decision",
                "references": [REFERENCE],
                "evidence": [],
                "candidate": None,
                "decision_requests": [
                    {"id": "direction", "question": "选择核心体验", "options": ["逆袭"]}
                ],
                "effects": [
                    {
                        "artifact_kind": "reader_contract",
                        "record_id": "contract-1",
                        "description": "错误的预先影响",
                    }
                ],
            }
        )
