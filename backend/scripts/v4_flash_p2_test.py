"""v4-flash P2 重测：验证番茄真实榜单数据接入 + 黄金三章评估效果。

流程：
1. 确保番茄 TOP50 特征向量已加载（若不存在则先抓取）
2. 跑完整 ChapterPlanner → DraftWriter → RetentionAuditor 链路
3. 调用 evaluate_chapter.py 评估生成的 draft
4. 对比 P1 → P2 指标

用法：
    cd /workspace/TameInk/backend
    .venv/bin/python scripts/v4_flash_p2_test.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from _runner_helper import (
    BACKEND_DIR,
    print_json,
)
from app.domain.commercial import CommercialProfile
from app.workflows.commercial import CommercialService
from app.workflows.new_book import NewBookRequest, NewBookService
from app.workflows.outline import OutlineService

# scripts 目录加入 sys.path 以便 import evaluate_chapter
sys.path.insert(0, str(BACKEND_DIR / "scripts"))
from evaluate_chapter import (  # noqa: E402
    evaluate_chapter_end_cliffhanger,
    evaluate_first_7_lines_hook,
    evaluate_scene_count,
    evaluate_word_count,
)

# API key 从环境变量读取，避免硬编码泄露
DEFAULT_API_KEY = os.environ.get("TAME_INK_API_KEY", "")


def _ensure_feature_vector() -> dict | None:
    """确保番茄特征向量已存在；不存在则跳过（不阻塞主流程）。"""
    vector_path = (
        BACKEND_DIR.parent / "skills" / "webnovel-studio" / "references"
        / "fanqie-examples" / "fanqie_feature_vector_latest.json"
    )
    if not vector_path.is_file():
        print("[vector] 特征向量不存在，尝试抓取...")
        try:
            from app.infrastructure.fanqie_bestseller_fetcher import FanqieBestsellerFetcher
            fetcher = FanqieBestsellerFetcher()
            snapshots = fetcher.fetch_top50_all_lists()
            vector = fetcher.build_feature_vector(snapshots)
            vector_path.parent.mkdir(parents=True, exist_ok=True)
            vector_path.write_text(
                json.dumps(vector.model_dump(mode="json"), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(f"[vector] 抓取并落盘: {vector_path}")
            return vector.model_dump(mode="json")
        except RuntimeError as error:
            print(f"[vector] 抓取失败（不阻塞）: {error}")
            return None
    data = json.loads(vector_path.read_text(encoding="utf-8"))
    print(f"[vector] 已加载: {vector_path} (scan_date={data.get('scan_date')})")
    return data


def main() -> int:
    api_key = DEFAULT_API_KEY
    # 0. 确保特征向量
    feature_vector = _ensure_feature_vector()

    # 1. 构建项目（与 p1 一致的设定）
    from _runner_helper import build_runner
    runner, workspace, workspace_dir = build_runner(
        project_id="fanqie-p2", api_key=api_key
    )
    print(f"[workspace] {workspace_dir}")

    books = NewBookService(workspace)
    setting = books.create(
        NewBookRequest(
            project_id="fanqie-p2",
            title="镜面诡局",
            genre="都市悬疑",
            target_words=300000,
            constraints="第三人称，单线叙事，禁止穿越重生",
        ),
        "侦探陈砚调查城市连续失踪案，嫌疑人竟然是他自己。",
    )
    books.approve_setting("fanqie-p2", setting.task.id)

    profile = CommercialProfile(
        platform="fanqie",
        monetization="free_ad",
        target_reader="追求强反转的悬疑读者",
        core_fantasy="识破镜面人换身阴谋",
        differentiator="主角自己就是嫌疑人之一",
        emotional_payoffs=["识破镜面人身份", "揭穿幕后组织"],
        opening_promise="第一章结尾主角在监控里看到另一个自己",
        first_thirty_chapter_promise="揭开镜面人组织的存在",
        update_cadence="每日两章",
        title_candidates=["镜面诡局"],
        synopsis="侦探陈砚调查城市连续失踪案，所有证据指向他自己。",
        minimum_commercial_score=70,
    )
    commercial_task = CommercialService(workspace).create("fanqie-p2", profile)
    CommercialService(workspace).approve("fanqie-p2", commercial_task.id)

    outlines = OutlineService(workspace)
    book = outlines.create_book(
        "fanqie-p2",
        "# 全书大纲\n陈砚调查失踪案，发现镜面人组织能复制人类外貌。"
        "组织内部有人想脱身，与陈砚合作。最终识破镜面人首领就是陈砚的镜像，"
        "代价是失去一段记忆。",
    )
    outlines.approve_book("fanqie-p2", book.id)
    volume = outlines.create_volume(
        "fanqie-p2", "1", "# 第一卷：失踪\n主角发现镜面人存在，被警方列为嫌疑人。"
    )
    outlines.approve_volume("fanqie-p2", volume.id, "1")
    print("[prerequisites] setting + commercial + outline + volume 全部确认")

    # 2. ChapterPlanner
    planner_payload = {
        "project_id": "fanqie-p2",
        "chapter_id": "0001",
        "volume_id": "1",
        "instruction": "第一章：陈砚接手失踪案，深夜在监控中看到另一个自己走出案发现场。",
        "platform": "fanqie",
        "platform_pacing": profile.platform_pacing.model_dump(mode="json"),
    }
    print("\n[ChapterPlanner] invoking...")
    try:
        plan_output = runner.invoke("ChapterPlanner", planner_payload)
    except Exception as error:
        print(f"[ChapterPlanner] FAILED: {type(error).__name__}: {error}")
        return 1
    plan = plan_output
    chapter_plan = {
        "id": plan.id,
        "chapter_id": plan.chapter_id,
        "content": plan.content,
        "context_intent": plan.context_intent.model_dump(mode="json")
        if hasattr(plan.context_intent, "model_dump")
        else plan.context_intent,
        "target_word_count": getattr(plan, "target_word_count", None),
        "opening_hook_style": getattr(plan, "opening_hook_style", None),
        "scenes_count": getattr(plan, "scenes_count", None),
        "chapter_end_hook": getattr(plan, "chapter_end_hook", None),
    }
    print_json("ChapterPlan 关键字段", chapter_plan)

    # 3. DraftWriter
    draft_payload = {
        "project_id": "fanqie-p2",
        "chapter_id": "0001",
        "volume_id": "1",
        "plan": chapter_plan,
        "platform": "fanqie",
        "platform_pacing": profile.platform_pacing.model_dump(mode="json"),
    }
    print("\n[DraftWriter] invoking (new draft)...")
    try:
        draft_output = runner.invoke("DraftWriter", draft_payload)
    except Exception as error:
        print(f"[DraftWriter] FAILED: {type(error).__name__}: {error}")
        return 1
    draft_data = draft_output.model_dump(mode="json")
    markdown = draft_data.get("markdown", "") or ""
    word_count = len(markdown.replace(" ", "").replace("\n", ""))
    print(f"[DraftWriter] markdown 字数（去空白后）= {word_count}")
    print_json("ChapterDraft 正文（前 3000 字）", markdown[:3000])

    # 4. RetentionAuditor
    retention_payload = {
        "project_id": "fanqie-p2",
        "chapter_id": "0001",
        "volume_id": "1",
        "plan": chapter_plan,
        "draft": markdown,
        "platform": "fanqie",
        "platform_pacing": profile.platform_pacing.model_dump(mode="json"),
    }
    print("\n[RetentionAuditor] invoking...")
    try:
        retention_output = runner.invoke("RetentionAuditor", retention_payload)
    except Exception as error:
        print(f"[RetentionAuditor] FAILED: {type(error).__name__}: {error}")
        return 1
    report_data = retention_output.model_dump(mode="json")
    print_json("CommercialReport 全量", report_data)

    # 5. 黄金三章评估
    print("\n[evaluate_chapter] 4 项硬指标评估...")
    eval_report = {
        "1_first_7_lines_hook": evaluate_first_7_lines_hook(markdown),
        "2_word_count": evaluate_word_count(markdown),
        "3_scene_count": evaluate_scene_count(markdown),
        "4_chapter_end_cliffhanger": evaluate_chapter_end_cliffhanger(
            markdown, api_key, "https://api.deepseek.com", "deepseek-chat"
        ),
    }

    # 6. P1 → P2 对比摘要
    print("\n" + "=" * 80)
    print("P2 改进验证摘要（番茄真实榜单数据 + 黄金三章评估）")
    print("=" * 80)
    dimensions = report_data.get("dimensions", [])
    fanqie_dims = {"first_screen_hook", "pacing_density", "chapter_end_cliffhanger", "character_contrast"}
    found_fanqie = [d for d in dimensions if d.get("dimension") in fanqie_dims]
    print(f"- 番茄专属维度数量: {len(found_fanqie)}/4 期望")
    for d in found_fanqie:
        print(f"  * {d.get('dimension')}: score={d.get('score')} reason={d.get('reason', '')[:80]}")
    print(f"- 总分: {report_data.get('total_score')}")
    print(f"- 建议: {report_data.get('recommendation')}")

    # RetentionAuditor 是否注入了 TOP50 基线参照
    issues = report_data.get("issues", [])
    baseline_issues = [i for i in issues if "baseline" in (i.get("id", "") or "")]
    print(f"- 程序化基线校验产出 issues: {len(baseline_issues)}")
    for issue in baseline_issues:
        print(f"  * {issue.get('id')}: {issue.get('description', '')[:100]}")

    # 4 项硬指标
    h1 = eval_report["1_first_7_lines_hook"]
    h2 = eval_report["2_word_count"]
    h3 = eval_report["3_scene_count"]
    h4 = eval_report["4_chapter_end_cliffhanger"]
    print("\n黄金三章 4 项硬指标：")
    print(f"1. 前 7 行钩子: has_hook={h1['has_hook']}, hook_type={h1['hook_type']}")
    print(f"2. 字数检查: word_count={h2['word_count']}, in_range={h2['in_range']} (范围 {h2['range']})")
    print(f"3. 场景数: scene_count={h3['scene_count']} (期望 {h3['expected']})")
    print(f"4. 章末断章: is_cliffhanger={h4.get('is_cliffhanger')}, node_type={h4.get('node_type')}")
    if h4.get("reason"):
        print(f"   理由: {h4['reason'][:120]}")

    # 特征向量统计
    if feature_vector:
        print(f"\n参考特征向量（scan_date={feature_vector.get('scan_date')}）:")
        print(f"- total_books={feature_vector.get('total_books')}")
        print(f"- top_genres={feature_vector.get('top_genres')}")
        print(f"- dominant_hook_type={feature_vector.get('dominant_hook_type')}")
        print(f"- word_count_stats={feature_vector.get('word_count_stats')}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
