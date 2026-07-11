from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Project(StrictModel):
    id: str
    title: str
    language: str


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
    quote: str
