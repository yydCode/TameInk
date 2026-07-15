import asyncio

import pytest
from pydantic import SecretStr

from app.infrastructure.model import (
    ModelConfigurationError,
    TameInkChatOpenAI,
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

    monkeypatch.setattr("app.infrastructure.model.TameInkChatOpenAI", fake_chat_openai)

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


def test_build_model_can_explicitly_disable_provider_thinking(monkeypatch) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        "app.infrastructure.model.TameInkChatOpenAI",
        lambda **kwargs: calls.append(kwargs),
    )
    settings = configured_settings().model_copy(update={"disable_thinking": True})

    build_model(settings, "secret-value")

    assert calls[0]["extra_body"] == {"thinking": {"type": "disabled"}}


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


def test_tame_ink_model_preserves_complex_identifier_and_tracking_fields() -> None:
    model = TameInkChatOpenAI(
        api_key=SecretStr("test-key"),
        model="ft:gpt-4o-mini:org:custom",
        temperature=0.2,
        max_tokens=123,
    )
    parent = super(TameInkChatOpenAI, model)._get_ls_params()
    params = model._get_ls_params()

    assert model.model_name == "ft:gpt-4o-mini:org:custom"
    assert params == {**parent, "ls_provider": "tame_ink_openai"}
    assert params["ls_model_name"] == "ft:gpt-4o-mini:org:custom"
    assert params["ls_temperature"] == 0.2
    assert params["ls_max_tokens"] == 123


def test_factory_accepts_complex_model_identifier() -> None:
    settings = ModelSettings(
        base_url="https://api.example.com/v1",
        model="ft:gpt-4o-mini:org:custom",
        timeout=30,
    )
    model = build_model(settings, "test-key")
    assert isinstance(model, TameInkChatOpenAI)
    assert model.model_name == "ft:gpt-4o-mini:org:custom"
