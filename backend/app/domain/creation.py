import re
from datetime import datetime
from pathlib import PurePosixPath
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.errors import TameInkError
from app.domain.paths import validate_formal_path, validate_project_id

RECORD_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

FormalLayer = Literal["canon", "commitment"]
TransientLayer = Literal["candidate", "hypothesis"]
ArtifactStatus = Literal[
    "candidate",
    "needs_decision",
    "conflict",
    "ready",
    "awaiting_approval",
    "accepted",
    "rejected",
]
ArtifactKind = Literal[
    "reader_contract",
    "story_engine",
    "character_state",
    "expectation",
    "story_card",
    "chapter_plan",
    "chapter_draft",
    "evidence_finding",
    "actual_event",
    "memory_proposal",
    "ending_plan",
]
DecisionAction = Literal["accept", "reject", "mix", "revise", "replan"]


def validate_record_id(value: str) -> str:
    if RECORD_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("RECORD_ID_INVALID")
    return value


class CreationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    @field_validator("*", mode="before")
    @classmethod
    def reject_blank_strings(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            raise ValueError("TEXT_EMPTY")
        return value


class FormalEvidence(CreationModel):
    path: str
    location: str
    quote: str

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        try:
            validate_formal_path(value)
        except TameInkError as error:
            raise ValueError("FORMAL_EVIDENCE_PATH_INVALID") from error
        return value


class ConfirmedRecord(CreationModel):
    schema_version: Literal[1] = 1
    id: str
    decision_id: str
    confirmed_by: Literal["author"] = "author"

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return validate_record_id(value)

    @field_validator("decision_id")
    @classmethod
    def validate_decision_id(cls, value: str) -> str:
        parsed = UUID(value)
        if str(parsed) != value:
            raise ValueError("DECISION_ID_INVALID")
        return value


class CreativeBrief(CreationModel):
    """Author-owned direction that every early-stage skill must preserve."""

    schema_version: Literal[1] = 1
    version: int = Field(ge=1)
    confirmed_by: Literal["author"] = "author"
    platform: str
    genre_scope: str
    initial_intent: str
    first_story_goal: str
    constraints: list[str] = Field(min_length=1)
    material_boundaries: list[str] = Field(min_length=1)
    created_at: datetime
    updated_at: datetime

    @field_validator("constraints", "material_boundaries")
    @classmethod
    def validate_unique_non_blank_list(cls, value: list[str]) -> list[str]:
        if any(not item.strip() or item != item.strip() for item in value):
            raise ValueError("TEXT_LIST_INVALID")
        if len(set(value)) != len(value):
            raise ValueError("TEXT_LIST_DUPLICATED")
        return value

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def parse_timestamp(cls, value: object) -> object:
        if isinstance(value, str):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value

    @field_validator("created_at", "updated_at")
    @classmethod
    def validate_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("TIMESTAMP_TIMEZONE_REQUIRED")
        return value

    @model_validator(mode="after")
    def validate_update_order(self) -> Self:
        if self.updated_at < self.created_at:
            raise ValueError("CREATIVE_BRIEF_TIMESTAMP_INVALID")
        return self


class ReaderContract(ConfirmedRecord):
    platform: str
    channel: str
    genre_scope: str
    target_readers: list[str] = Field(min_length=1)
    core_experience: str
    protagonist_promise: str
    must_payoffs: list[str] = Field(min_length=1)
    forbidden_directions: list[str] = Field(default_factory=list)
    evidence_refs: list[FormalEvidence] = Field(default_factory=list)

    @field_validator("target_readers", "must_payoffs", "forbidden_directions")
    @classmethod
    def validate_unique_text_list(cls, value: list[str]) -> list[str]:
        if any(not item.strip() or item != item.strip() for item in value):
            raise ValueError("TEXT_LIST_INVALID")
        if len(set(value)) != len(value):
            raise ValueError("TEXT_LIST_DUPLICATED")
        return value


class StoryEngine(ConfirmedRecord):
    reader_contract_id: str
    protagonist_role: str
    desire: str
    fear: str
    value_priority: str
    action_mechanism: str
    world_pressure: str
    conversion_chain: list[str] = Field(min_length=2)
    state_dimensions: list[str] = Field(min_length=1)
    variation_axes: list[str] = Field(min_length=1)
    long_lines: list[str] = Field(min_length=1)
    ending_direction: str | None = None

    @field_validator("reader_contract_id")
    @classmethod
    def validate_contract_id(cls, value: str) -> str:
        return validate_record_id(value)

    @field_validator("conversion_chain", "state_dimensions", "variation_axes", "long_lines")
    @classmethod
    def validate_unique_non_blank_lists(cls, value: list[str]) -> list[str]:
        if any(not item.strip() or item != item.strip() for item in value):
            raise ValueError("TEXT_LIST_INVALID")
        if len(set(value)) != len(value):
            raise ValueError("TEXT_LIST_DUPLICATED")
        return value


class CharacterChoiceEvidence(CreationModel):
    event_id: str
    choice: str
    reason: str
    source: FormalEvidence

    @field_validator("event_id")
    @classmethod
    def validate_event_id(cls, value: str) -> str:
        return validate_record_id(value)


class CharacterState(ConfirmedRecord):
    name: str
    desire: str
    fear: str
    current_belief: str
    value_priority: str
    social_roles: list[str] = Field(default_factory=list)
    available_resources: list[str] = Field(default_factory=list)
    relationship_stances: dict[str, str] = Field(default_factory=dict)
    decision_pattern: str
    choice_evidence: list[CharacterChoiceEvidence] = Field(default_factory=list)

    @field_validator("social_roles", "available_resources")
    @classmethod
    def validate_unique_non_blank_lists(cls, value: list[str]) -> list[str]:
        if any(not item.strip() or item != item.strip() for item in value):
            raise ValueError("TEXT_LIST_INVALID")
        if len(set(value)) != len(value):
            raise ValueError("TEXT_LIST_DUPLICATED")
        return value

    @field_validator("relationship_stances")
    @classmethod
    def validate_relationship_stances(cls, value: dict[str, str]) -> dict[str, str]:
        for character_id, stance in value.items():
            validate_record_id(character_id)
            if not stance.strip() or stance != stance.strip():
                raise ValueError("RELATIONSHIP_STANCE_INVALID")
        return value


class Expectation(ConfirmedRecord):
    reader_question: str
    contract_link: str
    opened_by: FormalEvidence
    payoff_semantics: str
    scope: Literal["local", "long_term"]
    status: Literal["opened", "strengthened", "partially_paid", "paid", "invalidated"]
    strengthening_event_ids: list[str] = Field(default_factory=list)
    actual_payoff_event_ids: list[str] = Field(default_factory=list)
    state_change: str | None = None
    next_expectation_ids: list[str] = Field(default_factory=list)
    invalidation_decision_id: str | None = None

    @field_validator(
        "contract_link",
        "strengthening_event_ids",
        "actual_payoff_event_ids",
        "next_expectation_ids",
    )
    @classmethod
    def validate_linked_ids(cls, value: str | list[str]) -> str | list[str]:
        if isinstance(value, str):
            return validate_record_id(value)
        if len(set(value)) != len(value):
            raise ValueError("RECORD_ID_LIST_DUPLICATED")
        return [validate_record_id(item) for item in value]

    @field_validator("invalidation_decision_id")
    @classmethod
    def validate_optional_decision_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = UUID(value)
        if str(parsed) != value:
            raise ValueError("DECISION_ID_INVALID")
        return value

    @model_validator(mode="after")
    def validate_payoff_state(self) -> Self:
        if self.status in {"partially_paid", "paid"} and not self.actual_payoff_event_ids:
            raise ValueError("EXPECTATION_PAYOFF_EVIDENCE_REQUIRED")
        if self.status == "invalidated" and self.invalidation_decision_id is None:
            raise ValueError("EXPECTATION_INVALIDATION_DECISION_REQUIRED")
        if self.status != "invalidated" and self.invalidation_decision_id is not None:
            raise ValueError("EXPECTATION_INVALIDATION_DECISION_UNEXPECTED")
        return self


class StoryConstraint(CreationModel):
    kind: Literal["must", "must_not", "fact", "promise", "platform"]
    description: str
    source: FormalEvidence


class SceneUnit(CreationModel):
    id: str
    sequence: int = Field(gt=0)
    entry_state: str
    local_intention: str
    foreground_purpose: str
    required_information: list[str] = Field(default_factory=list)
    action_reaction_chain: list[str] = Field(min_length=1)
    state_delta: str | None = None
    expectation_ops: list[str] = Field(default_factory=list)
    exit_link: str

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return validate_record_id(value)


class StoryCard(ConfirmedRecord):
    sequence: int = Field(gt=0)
    status: Literal["planned", "current", "completed", "superseded"]
    goal: str
    motivation: str
    expectation_ids: list[str] = Field(default_factory=list)
    hard_constraints: list[StoryConstraint] = Field(default_factory=list)
    soft_plan: list[str] = Field(default_factory=list)
    reaction_targets: list[str] = Field(default_factory=list)
    long_line_contribution: list[str] = Field(default_factory=list)
    cycle_input: str
    cycle_delta: str
    carried_assets: list[str] = Field(default_factory=list)
    next_affordance: str
    scene_units: list[SceneUnit] = Field(default_factory=list)
    actual_event_ids: list[str] = Field(default_factory=list)
    actual_payoff_ids: list[str] = Field(default_factory=list)
    drift_decision_id: str | None = None

    @field_validator("expectation_ids", "actual_event_ids", "actual_payoff_ids")
    @classmethod
    def validate_record_ids(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("RECORD_ID_LIST_DUPLICATED")
        return [validate_record_id(item) for item in value]

    @field_validator("drift_decision_id")
    @classmethod
    def validate_optional_decision_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = UUID(value)
        if str(parsed) != value:
            raise ValueError("DECISION_ID_INVALID")
        return value

    @model_validator(mode="after")
    def validate_completed_card(self) -> Self:
        if self.status == "completed" and not self.actual_event_ids:
            raise ValueError("COMPLETED_STORY_CARD_REQUIRES_ACTUAL_EVENTS")
        return self


class ActualEvent(ConfirmedRecord):
    summary: str
    source: FormalEvidence
    participant_ids: list[str] = Field(default_factory=list)
    state_changes: list[str] = Field(min_length=1)
    expectation_ops: list[str] = Field(default_factory=list)

    @field_validator("participant_ids")
    @classmethod
    def validate_participant_ids(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("RECORD_ID_LIST_DUPLICATED")
        return [validate_record_id(item) for item in value]

    @model_validator(mode="after")
    def validate_chapter_source(self) -> Self:
        if not self.source.path.startswith("canon/chapters/"):
            raise ValueError("ACTUAL_EVENT_SOURCE_MUST_BE_CHAPTER")
        return self


class PromiseResolution(CreationModel):
    promise_id: str
    resolution: Literal["must_pay", "intentional_open_end", "invalidated"]
    planned_payoff: str

    @field_validator("promise_id")
    @classmethod
    def validate_promise_id(cls, value: str) -> str:
        return validate_record_id(value)


class EndingPlan(ConfirmedRecord):
    promise_resolutions: list[PromiseResolution] = Field(min_length=1)
    final_state_targets: list[str] = Field(min_length=1)
    shared_climax_links: list[str] = Field(min_length=1)
    post_climax_rewards: list[str] = Field(default_factory=list)


class EvidenceFinding(CreationModel):
    id: str
    finding_type: Literal[
        "continuity", "promise", "character", "scene", "dialogue", "cognitive_load", "style"
    ]
    certainty: Literal["deterministic", "hypothesis"]
    description: str
    evidence: list[FormalEvidence] = Field(min_length=1)
    counter_hypothesis: str | None = None
    affected_record_ids: list[str] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return validate_record_id(value)

    @field_validator("affected_record_ids")
    @classmethod
    def validate_record_ids(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("RECORD_ID_LIST_DUPLICATED")
        return [validate_record_id(item) for item in value]


class DecisionEffect(CreationModel):
    record_kind: ArtifactKind
    record_id: str
    description: str

    @field_validator("record_id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return validate_record_id(value)


class AuthorDecision(CreationModel):
    id: str
    project_id: str
    artifact_id: str
    expected_status: ArtifactStatus
    action: DecisionAction
    rationale: str | None = None
    effects: list[DecisionEffect] = Field(default_factory=list)
    target_layer: FormalLayer | None = None
    formal_path: str | None = None
    # 段落级审批合并后的最终正文。仅 chapter_draft 的 mix 决策使用：
    # 作者逐段接受/改写后，前端把合并结果放这里，写入 canon 的是它而非原始候选。
    content_override: str | None = None
    created_at: datetime

    @field_validator("id", "artifact_id")
    @classmethod
    def validate_uuid(cls, value: str) -> str:
        parsed = UUID(value)
        if str(parsed) != value:
            raise ValueError("UUID_INVALID")
        return value

    @field_validator("project_id")
    @classmethod
    def validate_project(cls, value: str) -> str:
        try:
            return validate_project_id(value)
        except TameInkError as error:
            raise ValueError("PROJECT_ID_INVALID") from error

    @field_validator("formal_path")
    @classmethod
    def validate_optional_formal_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            validate_formal_path(value)
        except TameInkError as error:
            raise ValueError("FORMAL_TARGET_INVALID") from error
        return value

    @field_validator("created_at")
    @classmethod
    def validate_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("TIMESTAMP_TIMEZONE_REQUIRED")
        return value

    @model_validator(mode="after")
    def validate_promotion_target(self) -> Self:
        promotes = self.action in {"accept", "mix"}
        if promotes != (self.target_layer is not None and self.formal_path is not None):
            raise ValueError("DECISION_PROMOTION_TARGET_INVALID")
        if self.target_layer == "canon" and self.formal_path is not None:
            if not self.formal_path.startswith(("canon/", "memory/")):
                raise ValueError("DECISION_CANON_TARGET_INVALID")
        if self.target_layer == "commitment" and self.formal_path is not None:
            if not self.formal_path.startswith("commitments/"):
                raise ValueError("DECISION_COMMITMENT_TARGET_INVALID")
        if self.content_override is not None:
            if self.action != "mix":
                raise ValueError("CONTENT_OVERRIDE_REQUIRES_MIX")
            if not self.content_override.strip():
                raise ValueError("CONTENT_OVERRIDE_EMPTY")
        return self


class CandidateArtifactRecord(CreationModel):
    id: str
    project_id: str
    task_id: str
    kind: ArtifactKind
    source_layer: TransientLayer
    status: ArtifactStatus
    payload_path: str
    accepted_layer: FormalLayer | None = None
    formal_path: str | None = None
    accepted_decision_id: str | None = None
    created_at: datetime
    updated_at: datetime

    @field_validator("id", "accepted_decision_id")
    @classmethod
    def validate_optional_uuid(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = UUID(value)
        if str(parsed) != value:
            raise ValueError("UUID_INVALID")
        return value

    @field_validator("task_id")
    @classmethod
    def validate_task_id(cls, value: str) -> str:
        parsed = UUID(value)
        if str(parsed) != value:
            raise ValueError("UUID_INVALID")
        return value

    @field_validator("project_id")
    @classmethod
    def validate_project(cls, value: str) -> str:
        try:
            return validate_project_id(value)
        except TameInkError as error:
            raise ValueError("PROJECT_ID_INVALID") from error

    @field_validator("payload_path")
    @classmethod
    def validate_payload_path(cls, value: str) -> str:
        parts = value.split("/")
        pure = PurePosixPath(value)
        if "\\" in value or pure.is_absolute() or any(part in {"", ".", ".."} for part in parts):
            raise ValueError("CANDIDATE_PAYLOAD_PATH_INVALID")
        return value

    @field_validator("formal_path")
    @classmethod
    def validate_optional_formal_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            validate_formal_path(value)
        except TameInkError as error:
            raise ValueError("FORMAL_TARGET_INVALID") from error
        return value

    @field_validator("created_at", "updated_at")
    @classmethod
    def validate_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("TIMESTAMP_TIMEZONE_REQUIRED")
        return value

    @model_validator(mode="after")
    def validate_lifecycle(self) -> Self:
        accepted_fields = (
            self.accepted_layer is not None,
            self.formal_path is not None,
            self.accepted_decision_id is not None,
        )
        if self.status == "accepted":
            if (
                not all(accepted_fields)
                or self.source_layer != "candidate"
                or self.kind == "evidence_finding"
            ):
                raise ValueError("ARTIFACT_ACCEPTANCE_INVALID")
        elif any(accepted_fields):
            raise ValueError("ARTIFACT_ACCEPTANCE_FIELDS_UNEXPECTED")
        if self.updated_at < self.created_at:
            raise ValueError("ARTIFACT_TIMESTAMP_INVALID")
        if self.kind == "evidence_finding" and self.source_layer != "hypothesis":
            raise ValueError("EVIDENCE_FINDING_MUST_BE_HYPOTHESIS")
        return self
