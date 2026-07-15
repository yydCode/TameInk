import re
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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
    path: str
    location: str
    quote: str

    @model_validator(mode="after")
    def validate_source(self) -> Self:
        try:
            validate_formal_path(self.path)
        except WorkspacePathViolationError as error:
            raise ValueError("REFERENCE_PATH_INVALID") from error
        return self


class DraftCitation(StrictSchema):
    source: Literal["draft"]
    location: str
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
    references: list[SourceReference] = Field(min_length=1)


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


class MemoryUpdate(ReferencedOutput):
    operation: Literal["create", "update", "close"]
    content: str


class ImportAnalysis(ReferencedOutput):
    summary: str
    content: str
