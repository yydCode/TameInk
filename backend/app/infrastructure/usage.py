from __future__ import annotations

import json
import os
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from filelock import FileLock
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult


class UsageConfigurationError(RuntimeError):
    pass


class UsageDataMissingError(RuntimeError):
    pass


class UsageBudgetExceededError(RuntimeError):
    pass


@dataclass(frozen=True)
class Pricing:
    input_cny_per_million: float
    output_cny_per_million: float
    max_cost_cny: float

    @classmethod
    def from_environment(cls, *, required: bool) -> Pricing | None:
        input_value = os.environ.get("TAME_INK_INPUT_PRICE_CNY_PER_1M_TOKENS")
        output_value = os.environ.get("TAME_INK_OUTPUT_PRICE_CNY_PER_1M_TOKENS")
        max_value = os.environ.get("TAME_INK_MAX_COST_CNY", "20")
        if not input_value or not output_value:
            if required:
                raise UsageConfigurationError(
                    "TAME_INK_INPUT_PRICE_CNY_PER_1M_TOKENS and "
                    "TAME_INK_OUTPUT_PRICE_CNY_PER_1M_TOKENS are required"
                )
            return None
        return cls(
            input_cny_per_million=_positive_float(
                input_value, "TAME_INK_INPUT_PRICE_CNY_PER_1M_TOKENS"
            ),
            output_cny_per_million=_positive_float(
                output_value, "TAME_INK_OUTPUT_PRICE_CNY_PER_1M_TOKENS"
            ),
            max_cost_cny=_positive_float(max_value, "TAME_INK_MAX_COST_CNY"),
        )


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int
    output_tokens: int
    total_tokens: int


def _positive_float(value: str, name: str) -> float:
    try:
        parsed = float(value)
    except ValueError as error:
        raise UsageConfigurationError(f"{name} must be a positive number") from error
    if parsed <= 0:
        raise UsageConfigurationError(f"{name} must be a positive number")
    return parsed


def _nonnegative_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise UsageDataMissingError(f"{name} is missing or invalid")
    return value


def _mapping_value(value: object, *keys: str) -> object | None:
    if not isinstance(value, Mapping):
        return None
    for key in keys:
        if key in value:
            return cast(object, value[key])
    return None


def _usage_from_mapping(value: object) -> TokenUsage | None:
    if not isinstance(value, Mapping):
        return None
    nested = _mapping_value(value, "usage_metadata", "token_usage", "usage")
    if nested is not None:
        parsed = _usage_from_mapping(nested)
        if parsed is not None:
            return parsed
    input_value = _mapping_value(value, "input_tokens", "prompt_tokens")
    output_value = _mapping_value(value, "output_tokens", "completion_tokens")
    total_value = _mapping_value(value, "total_tokens", "total")
    if input_value is None or output_value is None:
        return None
    input_tokens = _nonnegative_int(input_value, "input_tokens")
    output_tokens = _nonnegative_int(output_value, "output_tokens")
    total_tokens = (
        _nonnegative_int(total_value, "total_tokens")
        if total_value is not None
        else input_tokens + output_tokens
    )
    if total_tokens != input_tokens + output_tokens:
        raise UsageDataMissingError("total_tokens does not equal input_tokens + output_tokens")
    return TokenUsage(input_tokens, output_tokens, total_tokens)


def extract_token_usage(value: object) -> TokenUsage | None:
    direct = _usage_from_mapping(value)
    if direct is not None:
        return direct
    for attribute in ("usage_metadata", "response_metadata", "llm_output"):
        nested = getattr(value, attribute, None)
        parsed = _usage_from_mapping(nested)
        if parsed is not None:
            return parsed
    if isinstance(value, LLMResult):
        for generation_group in value.generations:
            for generation in generation_group:
                parsed = extract_token_usage(getattr(generation, "message", generation))
                if parsed is not None:
                    return parsed
    return None


class UsageCaptureHandler(BaseCallbackHandler):
    def __init__(self) -> None:
        self.usage: TokenUsage | None = None

    def on_llm_end(self, response: LLMResult, **_: Any) -> None:
        observed = extract_token_usage(response)
        if observed is None:
            return
        if self.usage is None:
            self.usage = observed
            return
        self.usage = TokenUsage(
            input_tokens=self.usage.input_tokens + observed.input_tokens,
            output_tokens=self.usage.output_tokens + observed.output_tokens,
            total_tokens=self.usage.total_tokens + observed.total_tokens,
        )

    def require(self) -> TokenUsage:
        if self.usage is None:
            raise UsageDataMissingError("model response did not include token usage")
        return self.usage


@dataclass(frozen=True)
class UsageEvent:
    run_id: str
    source: str
    agent: str
    model: str
    started_at: str
    duration_ms: int
    status: str
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    input_cost_cny: float | None
    output_cost_cny: float | None
    total_cost_cny: float | None
    error_code: str | None


class UsageRecorder:
    def __init__(
        self,
        path: Path,
        model: str,
        pricing: Pricing,
        run_id: str | None = None,
        source: str = "backend",
    ) -> None:
        self.path = path
        self.model = model
        self.pricing = pricing
        self.run_id = run_id or os.environ.get("TAME_INK_RUN_ID", str(uuid4()))
        self.source = source
        self._lock = FileLock(f"{path}.lock")

    @classmethod
    def from_environment(
        cls, *, model: str, source: str = "backend", required: bool = False
    ) -> UsageRecorder | None:
        path_value = os.environ.get("TAME_INK_USAGE_LOG")
        pricing = Pricing.from_environment(required=required or path_value is not None)
        if path_value is None:
            return None
        if pricing is None:
            raise UsageConfigurationError("pricing is required when TAME_INK_USAGE_LOG is set")
        return cls(Path(path_value), model, pricing, source=source)

    def record(
        self,
        *,
        agent: str,
        started_at: datetime,
        duration_ms: int,
        status: str,
        usage: TokenUsage | None,
        error_code: str | None = None,
    ) -> UsageEvent:
        input_cost: float | None = None
        output_cost: float | None = None
        total_cost: float | None = None
        if usage is not None:
            input_cost = usage.input_tokens * self.pricing.input_cny_per_million / 1_000_000
            output_cost = usage.output_tokens * self.pricing.output_cny_per_million / 1_000_000
            total_cost = round(input_cost + output_cost, 8)
        event = UsageEvent(
            run_id=self.run_id,
            source=self.source,
            agent=agent,
            model=self.model,
            started_at=started_at.isoformat(),
            duration_ms=duration_ms,
            status=status,
            input_tokens=usage.input_tokens if usage else None,
            output_tokens=usage.output_tokens if usage else None,
            total_tokens=usage.total_tokens if usage else None,
            input_cost_cny=input_cost,
            output_cost_cny=output_cost,
            total_cost_cny=total_cost,
            error_code=error_code,
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            existing_cost = self._existing_cost_locked()
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(event.__dict__, ensure_ascii=False) + "\n")
        if total_cost is not None and existing_cost + total_cost > self.pricing.max_cost_cny:
            raise UsageBudgetExceededError(
                f"model cost exceeded budget: {existing_cost + total_cost:.8f} CNY > "
                f"{self.pricing.max_cost_cny:.8f} CNY"
            )
        return event

    def _existing_cost_locked(self) -> float:
        if not self.path.exists():
            return 0.0
        total = 0.0
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            value = payload.get("total_cost_cny")
            if isinstance(value, (int, float)):
                total += float(value)
        return total

    def events(self) -> list[dict[str, object]]:
        if not self.path.exists():
            return []
        return [
            json.loads(line)
            for line in self.path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def summary(self) -> dict[str, object]:
        events = self.events()

        def numeric_values(key: str) -> list[float]:
            values: list[float] = []
            for event in events:
                value = event.get(key)
                if isinstance(value, bool):
                    continue
                if isinstance(value, (int, float)):
                    values.append(float(value))
            return values

        numeric = {
            key: sum(numeric_values(key))
            for key in ("input_tokens", "output_tokens", "total_tokens", "total_cost_cny")
        }
        return {
            "request_count": len(events),
            "input_tokens": int(numeric["input_tokens"]),
            "output_tokens": int(numeric["output_tokens"]),
            "total_tokens": int(numeric["total_tokens"]),
            "total_cost_cny": round(numeric["total_cost_cny"], 8),
        }


def utc_now() -> datetime:
    return datetime.now(UTC)


def elapsed_ms(started: float) -> int:
    return max(0, round((time.perf_counter() - started) * 1000))
