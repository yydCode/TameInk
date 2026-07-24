import re
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.agents.context import ContextIntent
from app.domain.commercial import CommercialProfile
from app.domain.errors import WorkspacePathViolationError
from app.domain.paths import validate_formal_path


class StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    @field_validator("*", mode="before")
    @classmethod
    def reject_blank_strings(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            raise ValueError("TEXT_EMPTY")
        return value


class SourceReference(StrictSchema):
    path: str = Field(
        description=(
            "Confirmed formal source path supplied by the context manifest. "
            "Never use draft paths; draft evidence belongs in citation."
        )
    )
    location: str = Field(description="Exact location supplied by the context manifest")
    quote: str = Field(description="Exact quote supplied by the context manifest")

    @model_validator(mode="after")
    def validate_source(self) -> Self:
        try:
            validate_formal_path(self.path)
        except WorkspacePathViolationError as error:
            raise ValueError("REFERENCE_PATH_INVALID") from error
        return self


class DraftCitation(StrictSchema):
    source: Literal["draft"]
    location: str = Field(
        pattern=r"^chars:\d+-\d+$",
        description="Zero-based, end-exclusive character range such as chars:0-12",
    )
    quote: str

    def character_range(self) -> tuple[int, int]:
        match = re.fullmatch(r"chars:(\d+)-(\d+)", self.location)
        if match is None:
            raise ValueError("DRAFT_LOCATION_INVALID")
        start, end = (int(value) for value in match.groups())
        if start >= end:
            raise ValueError("DRAFT_LOCATION_INVALID")
        return start, end

    @model_validator(mode="after")
    def validate_location(self) -> Self:
        self.character_range()
        return self


class ReferencedOutput(StrictSchema):
    id: str
    references: list[SourceReference] = Field(
        min_length=1,
        description="Use only exact confirmed references supplied by the context manifest",
    )


class StorySetting(ReferencedOutput):
    title: str
    content: str


class Outline(ReferencedOutput):
    kind: Literal["book", "volume"]
    title: str
    content: str


class ChapterPlan(ReferencedOutput):
    chapter_id: str
    content: str
    context_intent: ContextIntent
    target_word_count: int = Field(default=2500, ge=1000, le=5000)
    opening_hook_style: Literal["conflict", "scene", "dialogue"] = "conflict"
    scenes_count: int = Field(default=1, ge=1, le=3)
    chapter_end_hook: str = Field(min_length=1)


class ChapterDraft(ReferencedOutput):
    chapter_id: str
    markdown: str


class ContinuityIssue(ReferencedOutput):
    severity: Literal["warning", "error"]
    description: str
    citation: DraftCitation


class StyleIssue(ReferencedOutput):
    severity: Literal["warning", "error"]
    description: str
    citation: DraftCitation


BASE_COMMERCIAL_DIMENSIONS: frozenset[str] = frozenset(
    {
        "opening_urgency",
        "reader_promise",
        "emotional_payoff",
        "conflict_escalation",
        "information_clarity",
        "chapter_hook",
        "differentiation",
    }
)

FANQIE_COMMERCIAL_DIMENSIONS: frozenset[str] = frozenset(
    {
        "first_screen_hook",  # 前 7 行（手机一屏）钩子强度
        "pacing_density",  # 节奏密度——无效铺垫占比
        "chapter_end_cliffhanger",  # 断章质量——是否卡在关键节点
        "character_contrast",  # 人设反差——主角/NPC 是否有立体反差
    }
)

CommercialDimension = Literal[
    # 通用 7 维度
    "opening_urgency",
    "reader_promise",
    "emotional_payoff",
    "conflict_escalation",
    "information_clarity",
    "chapter_hook",
    "differentiation",
    # 番茄平台专属
    "first_screen_hook",
    "pacing_density",
    "chapter_end_cliffhanger",
    "character_contrast",
]


class CommercialIssue(ReferencedOutput):
    severity: Literal["warning", "error"]
    dimension: CommercialDimension
    description: str
    citation: DraftCitation


class CommercialDimensionScore(StrictSchema):
    dimension: CommercialDimension
    score: int = Field(ge=0, le=100)
    reason: str


class RevisionProposal(ReferencedOutput):
    issue_id: str
    target: str
    replacement: str
    reason: str
    citation: DraftCitation


class DraftWriterResult(ReferencedOutput):
    chapter_id: str
    markdown: str | None = None
    revisions: list[RevisionProposal] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_mode(self) -> Self:
        if (self.markdown is None) == (len(self.revisions) == 0):
            raise ValueError("DRAFT_WRITER_MODE_INVALID")
        return self


class ContinuityReport(ReferencedOutput):
    issues: list[ContinuityIssue]


class StyleReport(ReferencedOutput):
    issues: list[StyleIssue]


class CommercialStrategy(ReferencedOutput):
    profile: CommercialProfile


class CommercialReport(ReferencedOutput):
    chapter_id: str
    total_score: int = Field(ge=0, le=100)
    recommendation: Literal["pass", "revise"]
    dimensions: list[CommercialDimensionScore]
    issues: list[CommercialIssue]

    @model_validator(mode="after")
    def validate_dimensions(self) -> Self:
        observed = {dimension.dimension for dimension in self.dimensions}
        # 必须包含全部 7 个基础维度
        if not BASE_COMMERCIAL_DIMENSIONS.issubset(observed):
            raise ValueError("COMMERCIAL_DIMENSIONS_INVALID")
        # 不得出现基础维度 + 番茄维度之外的维度
        allowed = BASE_COMMERCIAL_DIMENSIONS | FANQIE_COMMERCIAL_DIMENSIONS
        if not observed.issubset(allowed):
            raise ValueError("COMMERCIAL_DIMENSIONS_INVALID")
        # 不得有重复维度
        if len(self.dimensions) != len(observed):
            raise ValueError("COMMERCIAL_DIMENSIONS_INVALID")
        mean = round(
            sum(dimension.score for dimension in self.dimensions) / len(self.dimensions)
        )
        if self.total_score != mean:
            raise ValueError("COMMERCIAL_SCORE_INVALID")
        return self


class MemoryCandidate(StrictSchema):
    stable_id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    kind: Literal["fact", "event", "relationship", "foreshadowing"]
    operation: Literal["create", "update", "close"]
    content: str
    citation: DraftCitation


class MemoryCuration(ReferencedOutput):
    updates: list[MemoryCandidate] = Field(max_length=20)


class ImportAnalysis(ReferencedOutput):
    summary: str
    content: str


class ChapterDirective(StrictSchema):
    """人给章节创作的结构化方向指令——人决策、AI 执行的核心载体。"""

    required_characters: list[str] = Field(default_factory=list, max_length=20)
    resolve_foreshadowing_ids: list[str] = Field(default_factory=list, max_length=10)
    plant_foreshadowing: list[str] = Field(default_factory=list, max_length=10)
    emotional_tone: str = ""
    pacing: Literal["slow", "medium", "fast"] = "medium"
    focus_entities: list[str] = Field(default_factory=list, max_length=20)
    key_events: list[str] = Field(default_factory=list, max_length=10)
    target_word_count: int | None = Field(default=None, ge=500, le=20_000)

    def to_planner_payload(self) -> dict[str, object]:
        return {
            "required_characters": self.required_characters,
            "resolve_foreshadowing_ids": self.resolve_foreshadowing_ids,
            "plant_foreshadowing": self.plant_foreshadowing,
            "emotional_tone": self.emotional_tone,
            "pacing": self.pacing,
            "focus_entities": self.focus_entities,
            "key_events": self.key_events,
            "target_word_count": self.target_word_count,
        }

    def fts_queries(self) -> list[str]:
        return [*[c for c in self.required_characters if len(c) >= 2],
                *[e for e in self.focus_entities if len(e) >= 2]]


class LocalRevisionRequest(StrictSchema):
    """局部重生成请求：人选中一段文字，给出修改指令，AI 只重写该段。"""

    start: int = Field(ge=0)
    end: int = Field(gt=0)
    instruction: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if self.start >= self.end:
            raise ValueError("LOCAL_REVISION_RANGE_INVALID")
        return self


class AuditFeedback(StrictSchema):
    """人对审计结果的反馈：决定哪些问题要改、添加自己的修改意见。"""

    accepted_issue_ids: list[str] = Field(default_factory=list)
    custom_revisions: list[dict[str, str]] = Field(default_factory=list)
