import pytest
from pydantic import ValidationError

from app.agents.schemas import (
    ChapterDraft,
    ChapterPlan,
    ContinuityIssue,
    ImportAnalysis,
    MemoryUpdate,
    Outline,
    RevisionProposal,
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
                "references": [REFERENCE],
            },
        ),
        (
            StyleIssue,
            {
                "id": "style-1",
                "severity": "warning",
                "description": "重复",
                "references": [REFERENCE],
            },
        ),
        (
            RevisionProposal,
            {
                "id": "revision-1",
                "target": "draft-1",
                "replacement": "替换",
                "reason": "修复",
                "references": [REFERENCE],
            },
        ),
        (
            MemoryUpdate,
            {"id": "memory-1", "operation": "create", "content": "事实", "references": [REFERENCE]},
        ),
        (
            ImportAnalysis,
            {"id": "import-1", "summary": "分析", "content": "结构", "references": [REFERENCE]},
        ),
    ],
)
def test_agent_output_schemas_accept_strict_valid_payload(schema, payload) -> None:
    result = schema.model_validate(payload, context={"known_sources": {"canon/premise.md"}})
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
        StorySetting.model_validate(payload, context={"known_sources": {"canon/premise.md"}})


@pytest.mark.parametrize("field", ["path", "location", "quote"])
def test_reference_rejects_missing_or_blank_required_parts(field: str) -> None:
    payload = dict(REFERENCE)
    payload[field] = ""
    with pytest.raises(ValidationError):
        SourceReference.model_validate(payload, context={"known_sources": {"canon/premise.md"}})


@pytest.mark.parametrize(
    "path", ["/etc/passwd", "canon/../memory/facts/a.yaml", "canon\\premise.md", "drafts/a.md"]
)
def test_reference_rejects_non_formal_paths(path: str) -> None:
    with pytest.raises(ValidationError):
        SourceReference.model_validate(
            {**REFERENCE, "path": path}, context={"known_sources": {path}}
        )


def test_reference_rejects_unknown_source() -> None:
    with pytest.raises(ValidationError, match="REFERENCE_SOURCE_UNKNOWN"):
        SourceReference.model_validate(REFERENCE, context={"known_sources": {"canon/outline.md"}})


def test_output_rejects_missing_references_and_blank_ids() -> None:
    with pytest.raises(ValidationError):
        ChapterDraft.model_validate(
            {"id": " ", "chapter_id": "chapter-1", "markdown": "正文", "references": []},
            context={"known_sources": set()},
        )
