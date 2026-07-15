from typing import Any

from langchain_core.language_models.base import LangSmithParams
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from app.infrastructure.settings import ModelSettings


class ModelConfigurationError(RuntimeError):
    pass


class TameInkChatOpenAI(ChatOpenAI):
    """Isolate Tame Ink harness policy through LangChain's provider tracking hook."""

    def _get_ls_params(
        self,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> LangSmithParams:
        params = super()._get_ls_params(stop=stop, **kwargs)
        return LangSmithParams(**{**params, "ls_provider": "tame_ink_openai"})


def build_model(settings: ModelSettings, api_key: str | None) -> TameInkChatOpenAI:
    if api_key is None or not api_key.strip():
        raise ModelConfigurationError("MODEL_API_KEY_MISSING")
    provider_options: dict[str, Any] = {}
    if settings.disable_thinking:
        provider_options["extra_body"] = {"thinking": {"type": "disabled"}}
    return TameInkChatOpenAI(
        api_key=SecretStr(api_key),
        base_url=settings.base_url,
        model=settings.model,
        timeout=settings.timeout,
        max_retries=0,
        use_responses_api=False,
        **provider_options,
    )


async def test_connection(model: Any) -> None:
    await model.ainvoke([{"role": "user", "content": "connection test"}])
