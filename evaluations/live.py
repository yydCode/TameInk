from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.infrastructure.usage import (  # noqa: E402
    Pricing,
    TokenUsage,
    UsageDataMissingError,
    UsageRecorder,
)
from app.infrastructure.model import build_model  # noqa: E402
from run import load_cases, resolve_model, run_live  # noqa: E402


def safe_base_url(value: str) -> str:
    parsed = urlsplit(value)
    return urlunsplit((parsed.scheme, parsed.hostname or "", parsed.path.rstrip("/"), "", ""))


def promptfoo_usage(payload: dict[str, Any]) -> TokenUsage:
    results = payload.get("results", {}).get("results")
    if not isinstance(results, list) or len(results) != 1:
        raise UsageDataMissingError("promptfoo result count is invalid")
    usage = results[0].get("tokenUsage")
    if not isinstance(usage, dict):
        raise UsageDataMissingError("promptfoo result did not include token usage")
    prompt = usage.get("prompt")
    completion = usage.get("completion")
    total = usage.get("total")
    if not all(isinstance(item, int) and item > 0 for item in (prompt, completion, total)):
        raise UsageDataMissingError("promptfoo token usage is missing or zero")
    if total != prompt + completion:
        raise UsageDataMissingError("promptfoo token usage total is inconsistent")
    return TokenUsage(prompt, completion, total)


def run_commercial_case(
    index: int,
    env: dict[str, str],
    recorder: UsageRecorder,
    output_dir: Path,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", prefix=f"promptfoo-{index}-", dir=output_dir, delete=False
    ) as stream:
        result_path = Path(stream.name)
    try:
        started = time.perf_counter()
        started_at = datetime.now(timezone.utc)
        command = [
            "pnpm",
            "exec",
            "promptfoo",
            "eval",
            "-c",
            "promptfooconfig.live.yaml",
            "--filter-range",
            f"{index}:{index + 1}",
            "--max-concurrency",
            "1",
            "--no-cache",
            "--no-table",
            "--no-share",
            "--output",
            str(result_path),
        ]
        subprocess.run(
            command,
            cwd=ROOT / "evaluations",
            env=env,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        usage = promptfoo_usage(payload)
        recorder.record(
            agent=f"CommercialEvaluator:{index + 1}",
            started_at=started_at,
            duration_ms=round((time.perf_counter() - started) * 1000),
            status="success",
            usage=usage,
        )
        result = payload["results"]["results"][0]
        return {
            "index": index,
            "passed": bool(result.get("success")),
            "grading_pass": bool(result.get("gradingResult", {}).get("pass")),
            "token_usage": usage.__dict__,
        }
    finally:
        result_path.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Tame Ink live model evaluation")
    parser.add_argument(
        "--report", type=Path, default=ROOT / "output/live/model-evaluation.json"
    )
    args = parser.parse_args()

    args.report.parent.mkdir(parents=True, exist_ok=True)
    run_id = os.environ.get("TAME_INK_RUN_ID", str(uuid4()))
    recorder: UsageRecorder | None = None
    settings = None
    try:
        settings, api_key = resolve_model()
        pricing = Pricing.from_environment(required=True)
        if pricing is None:
            raise RuntimeError("pricing configuration is required")
        usage_path = Path(
            os.environ.get("TAME_INK_USAGE_LOG", str(args.report.with_suffix(".usage.jsonl")))
        )
        recorder = UsageRecorder(
            usage_path,
            model=settings.model,
            pricing=pricing,
            run_id=run_id,
            source="live-evaluation",
        )
        existing = recorder.summary()
        if float(existing["total_cost_cny"]) >= pricing.max_cost_cny:
            raise RuntimeError("configured live evaluation budget is already exhausted")

        model = build_model(settings, api_key)
        continuity = run_live(load_cases(), recorder, model)
        commercial_env = dict(os.environ)
        commercial_env.update(
            {
                "OPENAI_API_KEY": api_key,
                "TAME_INK_MODEL": settings.model,
                "TAME_INK_BASE_URL": settings.base_url,
            }
        )
        commercial = [
            run_commercial_case(index, commercial_env, recorder, args.report.parent)
            for index in range(3)
        ]
        report = {
            "status": "passed",
            "run_id": run_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "model": settings.model,
            "base_url": safe_base_url(settings.base_url),
            "pricing": {
                "input_cny_per_1m_tokens": pricing.input_cny_per_million,
                "output_cny_per_1m_tokens": pricing.output_cny_per_million,
                "max_cost_cny": pricing.max_cost_cny,
            },
            "continuity": continuity,
            "commercial": commercial,
            "usage": recorder.summary(),
            "usage_log": str(usage_path),
        }
        args.report.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except Exception as error:
        report = {
            "status": "failed",
            "run_id": run_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "model": settings.model if settings is not None else None,
            "error_code": type(error).__name__,
            "usage": recorder.summary() if recorder is not None else None,
        }
        args.report.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
