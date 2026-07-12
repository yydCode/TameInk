import json

import pytest
from pydantic import ValidationError

from app.infrastructure.settings import ModelSettings, SettingsRepository


@pytest.mark.parametrize(
    "url",
    [
        "http://api.example.com/v1",
        "https://user:password@example.com/v1",
        "https://example.com/v1?key=value",
        "https://example.com/v1#fragment",
        "file:///tmp/model",
    ],
)
def test_model_settings_rejects_unsafe_base_url(url: str) -> None:
    with pytest.raises(ValidationError):
        ModelSettings(base_url=url, model="model-1", timeout=30)


@pytest.mark.parametrize(
    "url",
    [
        "https://api.example.com/v1",
        "http://127.0.0.1:8000/v1",
        "http://localhost:8000/v1",
        "http://[::1]:8000/v1",
    ],
)
def test_model_settings_accepts_https_or_loopback_http(url: str) -> None:
    settings = ModelSettings(base_url=url, model="model-1", timeout=30)
    assert str(settings.base_url).rstrip("/") == url


def test_model_settings_rejects_blank_model_and_invalid_timeout() -> None:
    with pytest.raises(ValidationError):
        ModelSettings(base_url="https://api.example.com", model=" ", timeout=30)
    with pytest.raises(ValidationError):
        ModelSettings(base_url="https://api.example.com", model="model-1", timeout=0)


def test_settings_repository_persists_only_non_sensitive_fields_atomically(tmp_path) -> None:
    repository = SettingsRepository(tmp_path / "settings.json")
    settings = ModelSettings(base_url="https://api.example.com/v1", model="model-1", timeout=45)

    repository.save(settings)

    assert repository.load() == settings
    persisted = json.loads((tmp_path / "settings.json").read_text())
    assert persisted == {
        "base_url": "https://api.example.com/v1",
        "model": "model-1",
        "timeout": 45.0,
    }
    assert not (tmp_path / ".settings.json.tmp").exists()


def test_settings_repository_missing_file_has_stable_error(tmp_path) -> None:
    repository = SettingsRepository(tmp_path / "missing.json")
    with pytest.raises(RuntimeError, match="MODEL_SETTINGS_NOT_FOUND"):
        repository.load()


def test_settings_repository_invalid_payload_has_stable_error(tmp_path) -> None:
    path = tmp_path / "settings.json"
    path.write_text('{"base_url":"file:///tmp/model","model":"model-1","timeout":30}')
    with pytest.raises(RuntimeError, match="MODEL_SETTINGS_INVALID"):
        SettingsRepository(path).load()
