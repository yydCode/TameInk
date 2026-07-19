from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.errors import TameInkError
from app.domain.paths import validate_project_id


class TaskLogLevel(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class TaskDiagnosticLog(BaseModel):
    """A safe, structured diagnostic event. It never carries prompt or content text."""

    model_config = ConfigDict(extra="forbid", strict=True)

    id: int = Field(gt=0)
    task_id: str
    project_id: str
    timestamp: datetime
    level: TaskLogLevel
    component: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,63}$")
    event: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,63}$")
    agent: str | None = Field(default=None, pattern=r"^[A-Za-z][A-Za-z0-9]{0,63}$")
    details: dict[str, Any]

    @field_validator("task_id")
    @classmethod
    def validate_task_id(cls, value: str) -> str:
        parsed = UUID(value)
        if str(parsed) != value:
            raise ValueError("task id must be a canonical UUID")
        return value

    @field_validator("project_id")
    @classmethod
    def validate_project_id(cls, value: str) -> str:
        try:
            return validate_project_id(value)
        except TameInkError as error:
            raise ValueError("invalid project id") from error

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must include a timezone")
        return value
