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


CommercialDimension = Literal[
    "opening_urgency",
    "reader_promise",
    "emotional_payoff",
    "conflict_escalation",
    "information_clarity",
    "chapter_hook",
    "differentiation",
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
        expected = {
            "opening_urgency",
            "reader_promise",
            "emotional_payoff",
            "conflict_escalation",
            "information_clarity",
            "chapter_hook",
            "differentiation",
        }
        observed = {dimension.dimension for dimension in self.dimensions}
        if observed != expected or len(self.dimensions) != len(expected):
            raise ValueError("COMMERCIAL_DIMENSIONS_INVALID")
        mean = round(sum(dimension.score for dimension in self.dimensions) / len(expected))
        if self.total_score != mean:
            raise ValueError("COMMERCIAL_SCORE_INVALID")
        return self


class MemoryUpdate(ReferencedOutput):
    operation: Literal["create", "update", "close"]
    content: str


class ImportAnalysis(ReferencedOutput):
    summary: str
    content: str
