"""黄金三章自动评估脚本。

输入一个章节 markdown 文件，输出 4 项硬指标：
1. 前 7 行是否有钩子（规则检测）
2. 字数是否在 2000-3500（硬性）
3. 场景数（按空行/分隔符检测）
4. 章末是否卡在关键节点（LLM 判断，需 --api-key）

用法：
    cd /workspace/TameInk/backend
    .venv/bin/python scripts/evaluate_chapter.py <chapter.md> [--api-key sk-xxx]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from _runner_helper import BACKEND_DIR  # noqa: F401  (ensures sys.path)

from app.agents.bestseller_analyzer import BestsellerAnalyzer
from app.infrastructure.model import build_model
from app.infrastructure.settings import ModelSettings

# 中文汉字范围（与 bestseller_analyzer 一致）
_CHINESE_CHAR = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
# 主观感受词（“感到不安”“心想”等）——出现则不算强钩子
_SUBJECTIVE_WORDS = ("感到", "心想", "觉得", "似乎", "仿佛", "不由得", "忍不住")
# 钩子关键词映射（复用 bestseller_analyzer）
_ANALYZER = BestsellerAnalyzer()


class CliffhangerJudgment(BaseModel):
    """LLM 章末判断结构化输出。"""

    is_cliffhanger: bool = Field(description="是否断在关键节点")
    node_type: Literal[
        "identity_reveal", "truth_reveal", "villain_action", "rule_reversal", "none"
    ] = Field(description="断章节点类型")
    reason: str = Field(description="判断理由")


def evaluate_first_7_lines_hook(markdown: str) -> dict:
    """指标 1：前 7 行是否有钩子（规则检测）。"""
    lines = [ln.strip() for ln in markdown.split("\n") if ln.strip()]
    first_7 = lines[:7]
    if not first_7:
        return {
            "has_hook": False,
            "hook_type": "无",
            "first_7_lines": [],
            "reasoning": "前 7 行为空",
        }
    # 复用 bestseller_analyzer 的钩子关键词检测（对前 7 行整体）
    head_text = "\n".join(first_7)
    hook_type = _ANALYZER._detect_hook_type(head_text)
    # 检查是否含主观感受词（弱钩子信号）
    has_subjective = any(w in head_text for w in _SUBJECTIVE_WORDS)
    # 检查是否含具体动作/冲突信号
    has_action = bool(_CHINESE_CHAR.findall(head_text))
    has_hook = hook_type != "无" and not has_subjective and has_action
    reasoning = (
        f"钩子类型={hook_type}，含主观感受词={has_subjective}，"
        f"含具体动作={has_action}"
    )
    return {
        "has_hook": has_hook,
        "hook_type": hook_type,
        "first_7_lines": first_7,
        "reasoning": reasoning,
    }


def evaluate_word_count(markdown: str) -> dict:
    """指标 2：字数是否在 2000-3500（硬性，去空白后中文字符）。"""
    no_space = markdown.replace(" ", "").replace("\n", "")
    word_count = len(no_space)
    in_range = 2000 <= word_count <= 3500
    return {
        "word_count": word_count,
        "in_range": in_range,
        "range": [2000, 3500],
    }


def evaluate_scene_count(markdown: str) -> dict:
    """指标 3：场景数（按连续空行分隔）。"""
    # 按连续 ≥2 个换行分段
    blocks = re.split(r"\n\s*\n", markdown.strip())
    scenes = [b.strip() for b in blocks if b.strip()]
    return {
        "scene_count": len(scenes),
        "expected": 1,
        "separators": [f"block_{i+1}_len={len(s)}" for i, s in enumerate(scenes)],
    }


def evaluate_chapter_end_cliffhanger(
    markdown: str,
    api_key: str | None,
    base_url: str,
    model: str,
) -> dict:
    """指标 4：章末是否卡在关键节点（LLM 判断）。"""
    if not api_key:
        return {
            "is_cliffhanger": None,
            "node_type": "skipped",
            "reason": "未提供 --api-key，跳过 LLM 判断",
        }
    # 取最后 300 字
    tail = markdown.strip()[-300:]
    if not tail:
        return {
            "is_cliffhanger": False,
            "node_type": "none",
            "reason": "章节末尾为空",
        }
    try:
        settings = ModelSettings(
            base_url=base_url, model=model, timeout=120, disable_thinking=True
        )
        llm = build_model(settings, api_key)
        structured = llm.with_structured_output(CliffhangerJudgment, method="function_calling")
        from langchain_core.messages import HumanMessage, SystemMessage
        messages = [
            SystemMessage(
                content=(
                    "你是番茄小说编辑，判断章节末尾是否断在关键节点。"
                    "关键节点包括：身份揭晓前、真相揭露前、反派行动前、规则反转前。"
                    "禁止自然收尾（如主角入睡、时间过渡、总结思考）。"
                )
            ),
            HumanMessage(content=f"章节末尾：\n{tail}"),
        ]
        result = structured.invoke(messages)
        if isinstance(result, BaseModel):
            result = result.model_dump(mode="json")
        return result
    except Exception as error:
        return {
            "is_cliffhanger": None,
            "node_type": "error",
            "reason": f"{type(error).__name__}: {error}",
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="黄金三章自动评估")
    parser.add_argument("chapter_path", help="章节 markdown 文件路径")
    parser.add_argument("--api-key", default=None, help="LLM API key（用于章末 LLM 判断）")
    parser.add_argument("--base-url", default="https://api.deepseek.com")
    parser.add_argument("--model", default="deepseek-chat")
    parser.add_argument("--out", default=None, help="评估结果落盘路径（默认 <chapter>.evaluation.json）")
    args = parser.parse_args()

    chapter_path = Path(args.chapter_path)
    if not chapter_path.is_file():
        print(f"[error] 文件不存在: {chapter_path}")
        return 1
    markdown = chapter_path.read_text(encoding="utf-8")
    print(f"[eval] 评估章节: {chapter_path}（{len(markdown)} 字符）")

    report = {
        "chapter_path": str(chapter_path),
        "1_first_7_lines_hook": evaluate_first_7_lines_hook(markdown),
        "2_word_count": evaluate_word_count(markdown),
        "3_scene_count": evaluate_scene_count(markdown),
        "4_chapter_end_cliffhanger": evaluate_chapter_end_cliffhanger(
            markdown, args.api_key, args.base_url, args.model
        ),
    }

    # 打印摘要
    print("\n" + "=" * 80)
    print("评估结果摘要")
    print("=" * 80)
    h1 = report["1_first_7_lines_hook"]
    h2 = report["2_word_count"]
    h3 = report["3_scene_count"]
    h4 = report["4_chapter_end_cliffhanger"]
    print(f"1. 前 7 行钩子: has_hook={h1['has_hook']}, hook_type={h1['hook_type']}")
    print(f"2. 字数检查: word_count={h2['word_count']}, in_range={h2['in_range']} (范围 {h2['range']})")
    print(f"3. 场景数: scene_count={h3['scene_count']} (期望 {h3['expected']})")
    print(f"4. 章末断章: is_cliffhanger={h4.get('is_cliffhanger')}, node_type={h4.get('node_type')}")
    if h4.get("reason"):
        print(f"   理由: {h4['reason'][:120]}")

    # 落盘
    out_path = Path(args.out) if args.out else chapter_path.with_suffix(".evaluation.json")
    out_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n[eval] 评估结果落盘: {out_path}")

    # 退出码：4 项全 pass 返回 0
    all_pass = (
        h1["has_hook"]
        and h2["in_range"]
        and h3["scene_count"] == h3["expected"]
        and h4.get("is_cliffhanger") is True
    )
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
