from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

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


class Task(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    id: str
    project_id: str
    kind: TaskKind
    status: TaskStatus
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
