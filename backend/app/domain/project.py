from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

from app.domain.errors import TameInkError
from app.domain.paths import validate_formal_path, validate_project_id


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Project(StrictModel):
    id: str
    title: str
    language: str
    genre: str | None = None
    target_words: int | None = None
    constraints: str | None = None

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        try:
            return validate_project_id(value)
        except TameInkError as error:
            raise ValueError("invalid project id") from error

    @field_validator("title", "language")
    @classmethod
    def validate_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("value must not be blank")
        return stripped

    @field_validator("genre", "constraints")
    @classmethod
    def validate_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return cls.validate_text(value)

    @field_validator("target_words")
    @classmethod
    def validate_target_words(cls, value: int | None) -> int | None:
        if value is not None and value <= 0:
            raise ValueError("target words must be positive")
        return value


class ConfirmedContent(StrictModel):
    markdown: str

    @field_validator("markdown")
    @classmethod
    def validate_markdown(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("markdown must not be empty")
        return value


class MemoryRecord(StrictModel):
    id: str
    kind: Literal["fact", "event", "relationship", "foreshadowing"]
    status: Literal["active", "resolved", "superseded"]
    source: str
    location: str
    quote: str

    @field_validator("id", "location", "quote")
    @classmethod
    def validate_non_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("value must not be blank")
        return stripped

    @field_validator("source")
    @classmethod
    def validate_source(cls, value: str) -> str:
        stripped = value.strip()
        try:
            validate_formal_path(stripped)
        except TameInkError as error:
            raise ValueError("invalid memory source") from error
        return stripped
