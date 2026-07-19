import json
from datetime import UTC, datetime

import pytest
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from app.infrastructure.usage import (
    Pricing,
    TokenUsage,
    UsageBudgetExceededError,
    UsageCaptureHandler,
    UsageConfigurationError,
    UsageDataMissingError,
    UsageRecorder,
    extract_token_usage,
)


def test_pricing_requires_explicit_positive_prices(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TAME_INK_INPUT_PRICE_CNY_PER_1M_TOKENS", raising=False)
    monkeypatch.delenv("TAME_INK_OUTPUT_PRICE_CNY_PER_1M_TOKENS", raising=False)

    with pytest.raises(UsageConfigurationError):
        Pricing.from_environment(required=True)

    monkeypatch.setenv("TAME_INK_INPUT_PRICE_CNY_PER_1M_TOKENS", "0.2")
    monkeypatch.setenv("TAME_INK_OUTPUT_PRICE_CNY_PER_1M_TOKENS", "0")
    with pytest.raises(UsageConfigurationError):
        Pricing.from_environment(required=True)


def test_extract_token_usage_accepts_langchain_message_metadata() -> None:
    message = AIMessage(
        content="{}",
        usage_metadata={"input_tokens": 12, "output_tokens": 8, "total_tokens": 20},
    )

    assert extract_token_usage(message) == TokenUsage(12, 8, 20)
    result = LLMResult(generations=[[ChatGeneration(message=message)]])
    assert extract_token_usage(result) == TokenUsage(12, 8, 20)


def test_usage_capture_fails_when_provider_omits_usage() -> None:
    capture = UsageCaptureHandler()
    capture.on_llm_end(LLMResult(generations=[[ChatGeneration(message=AIMessage(content="{}"))]]))

    with pytest.raises(UsageDataMissingError):
        capture.require()


def test_usage_capture_accumulates_multi_turn_agent_calls() -> None:
    capture = UsageCaptureHandler()
    for input_tokens, output_tokens in ((12, 8), (20, 10)):
        message = AIMessage(
            content="{}",
            usage_metadata={
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
            },
        )
        capture.on_llm_end(LLMResult(generations=[[ChatGeneration(message=message)]]))

    assert capture.require() == TokenUsage(32, 18, 50)


def test_usage_recorder_writes_cost_without_prompt_or_secret(tmp_path) -> None:
    log = tmp_path / "usage.jsonl"
    recorder = UsageRecorder(
        log,
        model="model-1",
        pricing=Pricing(2.0, 4.0, 20.0),
        run_id="run-1",
        source="test",
    )

    recorder.record(
        agent="DraftWriter",
        started_at=datetime.now(UTC),
        duration_ms=123,
        status="success",
        usage=TokenUsage(1_000_000, 500_000, 1_500_000),
    )

    payload = json.loads(log.read_text().strip())
    assert payload["run_id"] == "run-1"
    assert payload["total_tokens"] == 1_500_000
    assert payload["total_cost_cny"] == 4.0
    assert "prompt" not in payload
    assert "secret" not in log.read_text()


def test_usage_recorder_rejects_budget_overrun_after_recording(tmp_path) -> None:
    recorder = UsageRecorder(
        tmp_path / "usage.jsonl",
        model="model-1",
        pricing=Pricing(10.0, 10.0, 1.0),
        run_id="run-1",
        source="test",
    )

    with pytest.raises(UsageBudgetExceededError):
        recorder.record(
            agent="StoryArchitect",
            started_at=datetime.now(UTC),
            duration_ms=1,
            status="success",
            usage=TokenUsage(100_000, 100_000, 200_000),
        )
