#!/usr/bin/env python3
"""校验网络小说项目目录的必需文件。"""

import argparse
from pathlib import Path

REQUIRED_FILES = [
    "brief.md",
    "story-bible.md",
    "outline.md",
    "chapter-plan.md",
    "characters.md",
    "world-rules.md",
    "timeline.md",
    "foreshadowing.md",
    "chapter-ledger.md",
    "style-guide.md",
    "previous-summary.md",
]

MIN_HEADINGS = {
    "brief.md": [["# 项目简报", "# Brief"]],
    "story-bible.md": [["# 小说事实库", "# Story Bible"], ["## 核心设定", "## Core Premise"], ["## 不可违背事实", "## Non-Negotiable Canon"]],
    "outline.md": [["# 大纲", "# Outline"]],
    "chapter-plan.md": [["# 章节计划", "# Chapter Plan"]],
    "characters.md": [["# 人物表", "# Characters"]],
    "world-rules.md": [["# 世界规则", "# World Rules"]],
    "timeline.md": [["# 时间线", "# Timeline"]],
    "foreshadowing.md": [["# 伏笔表", "# Foreshadowing"]],
    "chapter-ledger.md": [["# 章节台账", "# Chapter Ledger"]],
    "style-guide.md": [["# 风格指南", "# Style Guide"]],
    "previous-summary.md": [["# 最新摘要", "# Previous Summary"]],
}


def has_any(text: str, options: list[str]) -> bool:
    return any(option in text for option in options)


def main() -> None:
    parser = argparse.ArgumentParser(description="校验网络小说项目目录。")
    parser.add_argument("project", help="项目目录")
    args = parser.parse_args()

    project_dir = Path(args.project).expanduser().resolve()
    errors = []
    warnings = []

    if not project_dir.exists():
        errors.append(f"项目目录不存在：{project_dir}")
    elif not project_dir.is_dir():
        errors.append(f"项目路径不是目录：{project_dir}")

    if not errors:
        chapters_dir = project_dir / "chapters"
        if not chapters_dir.exists():
            errors.append("缺少 chapters/ 章节目录")
        elif not chapters_dir.is_dir():
            errors.append("chapters 存在，但不是目录")

        for filename in REQUIRED_FILES:
            path = project_dir / filename
            if not path.exists():
                errors.append(f"缺少必需文件：{filename}")
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if not text.strip():
                warnings.append(f"空文件：{filename}")
            for heading_options in MIN_HEADINGS.get(filename, []):
                if not has_any(text, heading_options):
                    warnings.append(f"{filename} 缺少标题之一：{', '.join(heading_options)}")

            if "TBD" in text or "待定" in text:
                warnings.append(f"{filename} 仍包含待补占位符")

    if errors:
        print("项目校验失败：")
        for error in errors:
            print(f"错误：{error}")
    else:
        print(f"项目校验通过：{project_dir}")

    if warnings:
        print("警告：")
        for warning in warnings:
            print(f"警告：{warning}")

    raise SystemExit(1 if errors else 0)


if __name__ == "__main__":
    main()
