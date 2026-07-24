"""v4-flash 真实重测：验证 P1 改进（番茄维度 + few-shot 注入）效果。

用法：
    cd /workspace/TameInk/backend
    .venv/bin/python scripts/v4_flash_p1_test.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

# 确保 backend 目录在 sys.path
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.agents.runtime import AgentRunner
from app.domain.commercial import CommercialProfile
from app.infrastructure.secrets import ApiKeyStore
from app.infrastructure.settings import ModelSettings, SettingsRepository
from app.workflows.commercial import CommercialService
from app.workflows.new_book import NewBookRequest, NewBookService
from app.workflows.outline import OutlineService
from app.repositories.workspace import WorkspaceRepository


# --- 自定义 keyring backend（绕过桌面环境依赖）---
class _MemoryKeyring:
    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def set_password(self, service: str, username: str, password: str) -> None:
        self._api_key = password

    def get_password(self, service: str, username: str) -> str | None:
        return self._api_key

    def delete_password(self, service: str, username: str) -> None:
        self._api_key = ""


def _print(title: str, payload: object) -> None:
    print(f"\n{'=' * 80}\n{title}\n{'=' * 80}")
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump(mode="json")
    if isinstance(payload, (dict, list)):
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str)[:8000])
    else:
        text = str(payload)
        print(text[:8000])
        if len(text) > 8000:
            print(f"... [截断，共 {len(text)} 字符]")


def main() -> int:
    api_key = os.environ.get("TAME_INK_API_KEY", "")
    if not api_key:
        print("[error] 请设置环境变量 TAME_INK_API_KEY")
        return 2
    workspace_dir = Path(tempfile.mkdtemp(prefix="tame-ink-v4-p1-"))
    print(f"[workspace] {workspace_dir}")

    workspace = WorkspaceRepository(workspace_dir)

    # 1. 创建项目 + 设定
    books = NewBookService(workspace)
    setting = books.create(
        NewBookRequest(
            project_id="fanqie-p1",
            title="镜面诡局",
            genre="都市悬疑",
            target_words=300000,
            constraints="第三人称，单线叙事，禁止穿越重生",
        ),
        "侦探陈砚调查城市连续失踪案，嫌疑人竟然是他自己。",
    )
    books.approve_setting("fanqie-p1", setting.task.id)
    print(f"[setting] approved id={setting.task.id}")

    # 2. 商业定位（番茄平台）
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
    commercial_task = CommercialService(workspace).create("fanqie-p1", profile)
    CommercialService(workspace).approve("fanqie-p1", commercial_task.id)
    print(f"[commercial] approved platform=fanqie id={commercial_task.id}")

    # 3. 大纲 + 分卷
    outlines = OutlineService(workspace)
    book = outlines.create_book(
        "fanqie-p1",
        "# 全书大纲\n陈砚调查失踪案，发现镜面人组织能复制人类外貌。"
        "组织内部有人想脱身，与陈砚合作。最终识破镜面人首领就是陈砚的镜像，"
        "代价是失去一段记忆。",
    )
    outlines.approve_book("fanqie-p1", book.id)
    volume = outlines.create_volume("fanqie-p1", "1", "# 第一卷：失踪\n主角发现镜面人存在，被警方列为嫌疑人。")
    outlines.approve_volume("fanqie-p1", volume.id, "1")
    print(f"[outline+volume] approved book={book.id} volume={volume.id}")

    # 4. 配置 v4-flash 模型
    settings_repo = SettingsRepository(workspace_dir / "settings.json")
    settings_repo.save(
        ModelSettings(
            base_url="https://api.deepseek.com",
            model="deepseek-chat",
            timeout=600,
            disable_thinking=True,
        )
    )
    print("[model] deepseek-chat (v4-flash compatible), disable_thinking=True")

    # 5. 构建 AgentRunner（使用内存 keyring）
    secrets = ApiKeyStore(backend=_MemoryKeyring(api_key))
    runner = AgentRunner(workspace, "fanqie-p1", settings_repo, secrets)

    # 6. 调用 ChapterPlanner
    planner_payload = {
        "project_id": "fanqie-p1",
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
    _print("ChapterPlanner 输出", plan_output.model_dump(mode="json") if hasattr(plan_output, "model_dump") else plan_output)

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
    _print("ChapterPlan 关键字段", chapter_plan)

    # 7. 调用 DraftWriter（新稿）
    draft_payload = {
        "project_id": "fanqie-p1",
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
    draft_data = draft_output.model_dump(mode="json") if hasattr(draft_output, "model_dump") else draft_output
    markdown = draft_data.get("markdown", "") if isinstance(draft_data, dict) else ""
    word_count = len(markdown.replace(" ", "").replace("\n", ""))
    print(f"[DraftWriter] markdown 字数（去空白后）= {word_count}")
    _print("ChapterDraft 正文（前 3000 字）", markdown[:3000])

    # 8. 调用 RetentionAuditor
    retention_payload = {
        "project_id": "fanqie-p1",
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
    report_data = retention_output.model_dump(mode="json") if hasattr(retention_output, "model_dump") else retention_output
    _print("CommercialReport 全量", report_data)

    # 9. P1 改进验证摘要
    print("\n" + "=" * 80)
    print("P1 改进验证摘要")
    print("=" * 80)
    dimensions = report_data.get("dimensions", []) if isinstance(report_data, dict) else []
    fanqie_dims = {"first_screen_hook", "pacing_density", "chapter_end_cliffhanger", "character_contrast"}
    found_fanqie = [d for d in dimensions if d.get("dimension") in fanqie_dims]
    print(f"- 番茄专属维度数量: {len(found_fanqie)}/4 期望")
    for d in found_fanqie:
        print(f"  * {d.get('dimension')}: score={d.get('score')} reason={d.get('reason', '')[:80]}")
    print(f"- 总分: {report_data.get('total_score') if isinstance(report_data, dict) else 'N/A'}")
    print(f"- 建议: {report_data.get('recommendation') if isinstance(report_data, dict) else 'N/A'}")
    print(f"- 正文实际字数: {word_count}（番茄铁律 2000-3000）")
    print(f"- Plan 中 target_word_count: {chapter_plan.get('target_word_count')}")
    print(f"- Plan 中 opening_hook_style: {chapter_plan.get('opening_hook_style')}")
    print(f"- Plan 中 scenes_count: {chapter_plan.get('scenes_count')}")
    print(f"- Plan 中 chapter_end_hook: {chapter_plan.get('chapter_end_hook')}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
