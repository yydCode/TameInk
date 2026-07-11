from pydantic import BaseModel, ConfigDict, field_validator


class RevisionWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    content: str
    message: str

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        if not value.startswith("确认：") or len(value) <= len("确认："):
            raise ValueError("revision message must start with 确认：")
        return value


class Revision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    message: str
