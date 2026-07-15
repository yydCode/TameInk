from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import yaml

FIXTURE = Path(__file__).parent / "fixtures" / "continuity_cases.yaml"


def load_cases() -> list[dict[str, Any]]:
    data = yaml.safe_load(FIXTURE.read_text())
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


def run_live(cases: list[dict[str, Any]]) -> dict[str, Any]:
    from langchain_openai import ChatOpenAI

    api_key = os.environ.get("OPENAI_API_KEY")
    model_name = os.environ.get("TAME_INK_MODEL")
    base_url = os.environ.get("TAME_INK_BASE_URL")
    if not api_key or not model_name or not base_url:
        raise RuntimeError("--live requires OPENAI_API_KEY, TAME_INK_MODEL and TAME_INK_BASE_URL")
    model = ChatOpenAI(api_key=api_key, model=model_name, base_url=base_url, temperature=0)
    results = []
    for case in cases:
        prompt = (
            "检查候选正文与已确认上下文的冲突。只返回 JSON，格式为 "
            '{"issues":["label"]}。可用标签：character_name, character_state, timeline, '
            "ability, foreshadowing, object_state, viewpoint。\n"
            f"上下文：{case['context']}\n候选正文：{case['candidate']}"
        )
        response = model.invoke(prompt)
        parsed = json.loads(str(response.content))
        predicted = set(parsed.get("issues", []))
        results.append({"id": case["id"], **score(set(case["expected"]), predicted)})
    return {"model": model_name, "base_url": base_url, "results": results}


def main() -> int:
    parser = argparse.ArgumentParser(description="Tame Ink continuity evaluation")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--fixture-only", action="store_true")
    mode.add_argument("--live", action="store_true")
    args = parser.parse_args()
    cases = load_cases()
    result: dict[str, Any] = {"fixture": str(FIXTURE), "cases": len(cases), "status": "valid"}
    if args.live:
        result.update(run_live(cases))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

