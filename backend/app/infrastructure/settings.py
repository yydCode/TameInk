import json
import os
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from filelock import FileLock
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class SettingsError(RuntimeError):
    pass


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
        self._lock = FileLock(f"{path}.lock")

    def load(self) -> ModelSettings:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            return self._load_locked()

    def _load_locked(self) -> ModelSettings:
        try:
            payload = json.loads(self.path.read_text())
        except FileNotFoundError as error:
            raise SettingsError("MODEL_SETTINGS_NOT_FOUND") from error
        except (OSError, json.JSONDecodeError) as error:
            raise SettingsError("MODEL_SETTINGS_READ_FAILED") from error
        try:
            return ModelSettings.model_validate(payload)
        except ValidationError as error:
            raise SettingsError("MODEL_SETTINGS_INVALID") from error

    def save(self, settings: ModelSettings) -> None:
        payload = json.dumps(settings.model_dump(mode="json"), sort_keys=True).encode()
        temporary: Path | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                with tempfile.NamedTemporaryFile(
                    mode="wb",
                    dir=self.path.parent,
                    prefix=f".{self.path.name}.",
                    suffix=".tmp",
                    delete=False,
                ) as stream:
                    temporary = Path(stream.name)
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path)
                temporary = None
                directory = os.open(self.path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
        except OSError as error:
            raise SettingsError("MODEL_SETTINGS_WRITE_FAILED") from error
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
