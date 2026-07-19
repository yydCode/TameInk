from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import yaml

BACKEND_ROOT = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.infrastructure.model import build_model
from app.infrastructure.secrets import ApiKeyStore
from app.infrastructure.settings import ModelSettings, SettingsRepository
from app.infrastructure.usage import (
    Pricing,
    UsageCaptureHandler,
    UsageBudgetExceededError,
    UsageRecorder,
    elapsed_ms,
    utc_now,
)


FIXTURE = Path(__file__).parent / "fixtures" / "continuity_cases.yaml"


def load_cases() -> list[dict[str, Any]]:
    data = yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))
    cases = data.get("cases") if isinstance(data, dict) else None
    if not isinstance(cases, list) or not cases:
        raise ValueError("evaluation fixture must contain non-empty cases")
    required = {"id", "category", "context", "candidate", "expected"}
    for case in cases:
        if not isinstance(case, dict) or set(case) != required:
            raise ValueError("evaluation case schema is invalid")
        if not isinstance(case["expected"], list) or not case["expected"]:
            raise ValueError("evaluation case must declare expected issue labels")
    return cases


def score(expected: set[str], predicted: set[str]) -> dict[str, float]:
    true_positive = len(expected & predicted)
    precision = true_positive / len(predicted) if predicted else 0.0
    recall = true_positive / len(expected) if expected else 1.0
    return {"precision": round(precision, 4), "recall": round(recall, 4)}


def resolve_model() -> tuple[ModelSettings, str]:
    workspace = Path(os.environ.get("TAME_INK_WORKSPACE", ".tame-ink-workspace"))
    settings = SettingsRepository(workspace / "settings.json").load()
    model_settings = settings.model_copy(
        update={
            "model": os.environ.get("TAME_INK_MODEL", settings.model),
            "base_url": os.environ.get("TAME_INK_BASE_URL", settings.base_url),
        }
    )
    api_key = os.environ.get("OPENAI_API_KEY") or ApiKeyStore().get()
    if api_key is None:
        raise RuntimeError("OPENAI_API_KEY or the configured Keyring API key is required")
    return model_settings, api_key


def build_recorder(report_path: Path, model: str) -> UsageRecorder:
    pricing = Pricing.from_environment(required=True)
    if pricing is None:
        raise RuntimeError("pricing configuration is required")
    return UsageRecorder(
        report_path.with_suffix(".usage.jsonl"),
        model=model,
        pricing=pricing,
        run_id=os.environ.get("TAME_INK_RUN_ID"),
        source="continuity-evaluation",
    )


def run_live(
    cases: list[dict[str, Any]], recorder: UsageRecorder, model: Any
) -> dict[str, Any]:
    results = []
    for case in cases:
        prompt = (
            "检查候选正文与已确认上下文的冲突。只返回 JSON，格式为 "
            '{"issues":["label"]}。可用标签：character_name, character_state, timeline, '
            "ability, foreshadowing, object_state, viewpoint。\n"
            f"上下文：{case['context']}\n候选正文：{case['candidate']}"
        )
        capture = UsageCaptureHandler()
        started_at = utc_now()
        started = time.perf_counter()
        try:
            response = model.with_config({"callbacks": [capture]}).invoke(prompt)
            recorder.record(
                agent=f"ContinuityEvaluator:{case['id']}",
                started_at=started_at,
                duration_ms=elapsed_ms(started),
                status="success",
                usage=capture.require(),
            )
        except Exception as error:
            if isinstance(error, UsageBudgetExceededError):
                raise
            recorder.record(
                agent=f"ContinuityEvaluator:{case['id']}",
                started_at=started_at,
                duration_ms=elapsed_ms(started),
                status="failed",
                usage=capture.usage,
                error_code=type(error).__name__,
            )
            raise
        parsed = json.loads(str(response.content))
        predicted = set(parsed.get("issues", []))
        results.append({"id": case["id"], **score(set(case["expected"]), predicted)})
    return {"model": model.model_name, "results": results}


def main() -> int:
    parser = argparse.ArgumentParser(description="Tame Ink continuity evaluation")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--fixture-only", action="store_true")
    mode.add_argument("--live", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    cases = load_cases()
    result: dict[str, Any] = {"fixture": str(FIXTURE), "cases": len(cases), "status": "valid"}
    if args.live:
        settings, api_key = resolve_model()
        report_path = args.report or Path(__file__).resolve().parents[1] / "output/live/continuity.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        recorder = build_recorder(report_path, settings.model)
        model = build_model(settings, api_key)
        result.update(run_live(cases, recorder, model))
        result["base_url"] = settings.base_url.split("?")[0]
        result["usage"] = recorder.summary()
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
