import asyncio

import pytest
from pydantic import SecretStr

from app.infrastructure.model import (
    ModelConfigurationError,
    build_model,
)
from app.infrastructure.model import (
    test_connection as check_connection,
)
from app.infrastructure.settings import ModelSettings


def configured_settings() -> ModelSettings:
    return ModelSettings(base_url="https://api.example.com/v1", model="model-1", timeout=30)


def test_build_model_requires_api_key() -> None:
    with pytest.raises(ModelConfigurationError, match="MODEL_API_KEY_MISSING"):
        build_model(configured_settings(), None)


def test_build_model_constructs_single_non_retrying_chat_openai(monkeypatch) -> None:
    calls: list[dict[str, object]] = []
    sentinel = object()

    def fake_chat_openai(**kwargs: object) -> object:
        calls.append(kwargs)
        return sentinel

    monkeypatch.setattr("app.infrastructure.model.ChatOpenAI", fake_chat_openai)

    result = build_model(configured_settings(), "secret-value")

    assert result is sentinel
    assert len(calls) == 1
    api_key = calls[0].pop("api_key")
    assert isinstance(api_key, SecretStr)
    assert api_key.get_secret_value() == "secret-value"
    assert "secret-value" not in repr(api_key)
    assert calls == [
        {
            "base_url": "https://api.example.com/v1",
            "model": "model-1",
            "timeout": 30.0,
            "max_retries": 0,
            "use_responses_api": False,
        }
    ]


def test_connection_only_invokes_model_when_explicitly_called() -> None:
    class FakeModel:
        def __init__(self) -> None:
            self.calls = 0

        async def ainvoke(self, messages: list[dict[str, str]]) -> object:
            self.calls += 1
            assert messages == [{"role": "user", "content": "connection test"}]
            return object()

    model = FakeModel()
    assert model.calls == 0
    asyncio.run(check_connection(model))
    assert model.calls == 1
