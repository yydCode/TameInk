import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class ModelSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    base_url: str
    model: str
    timeout: float = Field(gt=0, le=600)

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("MODEL_BASE_URL_CREDENTIALS_FORBIDDEN")
        if parsed.query or parsed.fragment:
            raise ValueError("MODEL_BASE_URL_COMPONENT_FORBIDDEN")
        if not parsed.hostname or parsed.path.startswith("//"):
            raise ValueError("MODEL_BASE_URL_INVALID")
        loopback = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        if parsed.scheme != "https" and not (parsed.scheme == "http" and loopback):
            raise ValueError("MODEL_BASE_URL_INSECURE")
        return value.rstrip("/")

    @field_validator("model")
    @classmethod
    def validate_model(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("MODEL_NAME_EMPTY")
        return value


class SettingsRepository:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> ModelSettings:
        try:
            payload = json.loads(self.path.read_text())
        except FileNotFoundError as error:
            raise RuntimeError("MODEL_SETTINGS_NOT_FOUND") from error
        except (OSError, json.JSONDecodeError) as error:
            raise RuntimeError("MODEL_SETTINGS_READ_FAILED") from error
        try:
            return ModelSettings.model_validate(payload)
        except ValidationError as error:
            raise RuntimeError("MODEL_SETTINGS_INVALID") from error

    def save(self, settings: ModelSettings) -> None:
        payload = json.dumps(settings.model_dump(mode="json"), sort_keys=True).encode()
        temporary = self.path.with_name(f".{self.path.name}.tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with temporary.open("wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            directory = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except OSError as error:
            raise RuntimeError("MODEL_SETTINGS_WRITE_FAILED") from error
