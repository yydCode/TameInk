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


class StyleIssue(ReferencedOutput):
    severity: Literal["warning", "error"]
    description: str


class RevisionProposal(ReferencedOutput):
    target: str
    replacement: str
    reason: str


class MemoryUpdate(ReferencedOutput):
    operation: Literal["create", "update", "close"]
    content: str


class ImportAnalysis(ReferencedOutput):
    summary: str
    content: str
