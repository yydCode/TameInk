from typing import Any

from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from app.infrastructure.settings import ModelSettings


class ModelConfigurationError(RuntimeError):
    pass


def build_model(settings: ModelSettings, api_key: str | None) -> ChatOpenAI:
    if api_key is None or not api_key.strip():
        raise ModelConfigurationError("MODEL_API_KEY_MISSING")
    return ChatOpenAI(
        api_key=SecretStr(api_key),
        base_url=settings.base_url,
        model=settings.model,
        timeout=settings.timeout,
        max_retries=0,
        use_responses_api=False,
    )


async def test_connection(model: Any) -> None:
    await model.ainvoke([{"role": "user", "content": "connection test"}])
