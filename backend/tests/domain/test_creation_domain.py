from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.domain.creation import (
    ActualEvent,
    AuthorDecision,
    CandidateArtifactRecord,
    Expectation,
    ReaderContract,
    StoryCard,
)


def evidence(path: str = "canon/chapters/0001.md") -> dict[str, str]:
    return {"path": path, "location": "paragraph 1", "quote": "已确认原文"}


def confirmed() -> dict[str, object]:
    return {
        "schema_version": 1,
        "id": "record-01",
        "decision_id": str(uuid4()),
        "confirmed_by": "author",
    }


def test_reader_contract_requires_unique_explicit_payoffs() -> None:
    payload = {
        **confirmed(),
        "platform": "fanqie",
        "channel": "male",
        "genre_scope": "都市高武",
        "target_readers": ["成长流读者"],
        "core_experience": "持续突破认知与能力边界",
        "protagonist_promise": "主角主动解决每阶段问题",
        "must_payoffs": ["身份成长", "身份成长"],
        "forbidden_directions": [],
        "evidence_refs": [],
    }

    with pytest.raises(ValidationError, match="TEXT_LIST_DUPLICATED"):
        ReaderContract.model_validate(payload)


def test_expectation_requires_payoff_or_invalidation_evidence_for_terminal_state() -> None:
    payload = {
        **confirmed(),
        "reader_question": "主角何时公开身份？",
        "contract_link": "reader-contract",
        "opened_by": evidence(),
        "payoff_semantics": "相关人物确认主角真实身份并改变关系",
        "scope": "long_term",
        "status": "paid",
        "strengthening_event_ids": [],
        "actual_payoff_event_ids": [],
        "next_expectation_ids": [],
    }

    with pytest.raises(ValidationError, match="EXPECTATION_PAYOFF_EVIDENCE_REQUIRED"):
        Expectation.model_validate(payload)

    invalidated = {**payload, "status": "invalidated"}
    with pytest.raises(ValidationError, match="EXPECTATION_INVALIDATION_DECISION_REQUIRED"):
        Expectation.model_validate(invalidated)


def test_completed_story_card_requires_actual_events() -> None:
    payload = {
        **confirmed(),
        "sequence": 1,
        "status": "completed",
        "goal": "取得入城资格",
        "motivation": "救治同伴",
        "expectation_ids": [],
        "hard_constraints": [],
        "soft_plan": [],
        "reaction_targets": [],
        "long_line_contribution": [],
        "cycle_input": "无身份、无资源",
        "cycle_delta": "取得身份",
        "carried_assets": [],
        "next_affordance": "进入城市主线",
        "scene_units": [],
        "actual_event_ids": [],
        "actual_payoff_ids": [],
    }

    with pytest.raises(ValidationError, match="COMPLETED_STORY_CARD_REQUIRES_ACTUAL_EVENTS"):
        StoryCard.model_validate(payload)


def test_actual_event_must_quote_confirmed_chapter() -> None:
    payload = {
        **confirmed(),
        "summary": "主角得到入城资格",
        "source": evidence("commitments/story-cards/card-01.yaml"),
        "participant_ids": ["hero"],
        "state_changes": ["身份由流民变为居民"],
        "expectation_ops": [],
    }

    with pytest.raises(ValidationError, match="ACTUAL_EVENT_SOURCE_MUST_BE_CHAPTER"):
        ActualEvent.model_validate(payload)


def test_candidate_artifact_cannot_claim_acceptance_without_author_decision() -> None:
    now = datetime.now(UTC)
    payload = {
        "id": str(uuid4()),
        "project_id": "story-01",
        "task_id": str(uuid4()),
        "kind": "story_card",
        "source_layer": "candidate",
        "status": "accepted",
        "payload_path": "story-card.json",
        "created_at": now,
        "updated_at": now,
    }

    with pytest.raises(ValidationError, match="ARTIFACT_ACCEPTANCE_INVALID"):
        CandidateArtifactRecord.model_validate(payload)

    hypothesis = {
        **payload,
        "source_layer": "hypothesis",
        "accepted_layer": "commitment",
        "formal_path": "commitments/story-cards/card-01.yaml",
        "accepted_decision_id": str(uuid4()),
    }
    with pytest.raises(ValidationError, match="ARTIFACT_ACCEPTANCE_INVALID"):
        CandidateArtifactRecord.model_validate(hypothesis)

    finding = {
        **payload,
        "kind": "evidence_finding",
        "source_layer": "candidate",
        "status": "candidate",
    }
    with pytest.raises(ValidationError, match="EVIDENCE_FINDING_MUST_BE_HYPOTHESIS"):
        CandidateArtifactRecord.model_validate(finding)


def test_author_decision_requires_target_matching_the_formal_layer() -> None:
    now = datetime.now(UTC)
    payload = {
        "id": str(uuid4()),
        "project_id": "story-01",
        "artifact_id": str(uuid4()),
        "expected_status": "awaiting_approval",
        "action": "accept",
        "effects": [],
        "target_layer": "commitment",
        "formal_path": "canon/characters/hero.yaml",
        "created_at": now,
    }

    with pytest.raises(ValidationError, match="DECISION_COMMITMENT_TARGET_INVALID"):
        AuthorDecision.model_validate(payload)

    without_target = {**payload, "target_layer": None, "formal_path": None}
    with pytest.raises(ValidationError, match="DECISION_PROMOTION_TARGET_INVALID"):
        AuthorDecision.model_validate(without_target)
