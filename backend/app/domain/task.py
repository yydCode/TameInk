from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.errors import TameInkError
from app.domain.paths import validate_project_id


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class TaskKind(StrEnum):
    READ = "read"
    WRITE = "write"


class TaskPurpose(StrEnum):
    MANUAL = "manual"
    SETTING = "setting"
    COMMERCIAL = "commercial"
    BOOK_OUTLINE = "book_outline"
    VOLUME_OUTLINE = "volume_outline"
    CHAPTER = "chapter"
    IMPORT = "import"
    COMMERCIAL_AUDIT = "commercial_audit"
    MEMORY_CURATION = "memory_curation"
    EXPORT = "export"


class Task(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    id: str
    project_id: str
    kind: TaskKind
    purpose: TaskPurpose = TaskPurpose.MANUAL
    status: TaskStatus
    subject_id: str | None = Field(default=None, max_length=128)
    volume_id: str | None = Field(default=None, max_length=128)
    chapter_id: str | None = Field(default=None, max_length=128)
    parent_task_id: str | None = None
    retry_of_task_id: str | None = None
    cancel_requested_at: datetime | None = None
    error_code: str | None = Field(default=None, max_length=128)
    error_message: str | None = Field(default=None, max_length=1000)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    created_at: datetime
    updated_at: datetime

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        parsed = UUID(value)
        if str(parsed) != value:
            raise ValueError("task id must be a canonical UUID")
        return value

    @field_validator("project_id")
    @classmethod
    def validate_project(cls, value: str) -> str:
        try:
            return validate_project_id(value)
        except TameInkError as error:
            raise ValueError("invalid project id") from error

    @field_validator("created_at", "updated_at")
    @classmethod
    def validate_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must include a timezone")
        return value

    @field_validator("cancel_requested_at", "started_at", "finished_at", mode="before")
    @classmethod
    def validate_optional_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return cls.validate_timestamp(value)

    @field_validator("subject_id", "volume_id", "chapter_id", "error_code", "error_message")
    @classmethod
    def validate_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.strip() or value != value.strip():
            raise ValueError("optional task text must not be blank or padded")
        return value

    @field_validator("parent_task_id", "retry_of_task_id")
    @classmethod
    def validate_related_task_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = UUID(value)
        if str(parsed) != value:
            raise ValueError("related task id must be a canonical UUID")
        return value

    @model_validator(mode="after")
    def validate_lifecycle(self) -> "Task":
        if self.updated_at < self.created_at:
            raise ValueError("task update cannot precede creation")
        for timestamp in (self.cancel_requested_at, self.started_at, self.finished_at):
            if timestamp is not None and timestamp < self.created_at:
                raise ValueError("task lifecycle timestamp cannot precede creation")
        if self.finished_at is not None and self.started_at is not None:
            if self.finished_at < self.started_at:
                raise ValueError("task finish cannot precede start")
        if self.duration_ms is not None and self.finished_at is None:
            raise ValueError("task duration requires a finish timestamp")
        if self.retry_of_task_id == self.id or self.parent_task_id == self.id:
            raise ValueError("task cannot reference itself")
        return self


class TaskEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    task_id: str
    project_id: str
    sequence: int = Field(gt=0)
    type: str
    timestamp: datetime
    data: dict[str, Any]

    @field_validator("task_id")
    @classmethod
    def validate_task_id(cls, value: str) -> str:
        parsed = UUID(value)
        if str(parsed) != value:
            raise ValueError("task id must be a canonical UUID")
        return value

    @field_validator("project_id")
    @classmethod
    def validate_event_project(cls, value: str) -> str:
        try:
            return validate_project_id(value)
        except TameInkError as error:
            raise ValueError("invalid project id") from error

    @field_validator("type")
    @classmethod
    def validate_type(cls, value: str) -> str:
        if not value.strip() or value != value.strip():
            raise ValueError("event type must not be blank")
        return value

    @field_validator("timestamp")
    @classmethod
    def validate_event_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must include a timezone")
        return value
