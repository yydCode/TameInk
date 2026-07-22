"""从作者一句话想法生成创作简报草稿。

这是一个同步、单次的模型调用，独立于异步 skill/job 架构。用于新建项目时
把作者的自然语言想法拆解成结构化草稿（书名/题材/首个故事目标/创作意图），
作者随后可编辑确认。生成失败时抛错，由 API 层转译为友好提示。

不写入任何 canon 或 commitment；输出纯粹是待作者审阅的草稿建议。
"""

from __future__ import annotations

import asyncio

from pydantic import BaseModel, ConfigDict, Field

from app.infrastructure.model import build_model
from app.infrastructure.secrets import ApiKeyStore
from app.infrastructure.settings import SettingsRepository


class BriefDraft(BaseModel):
    """AI 从一句话想法拆解出的创作简报草稿。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    title: str = Field(description="书名建议，符合番茄平台风格，8-15 字")
    genre_scope: str = Field(description="题材定位，如「都市重生·校园逆袭」")
    first_story_goal: str = Field(
        description="首个故事目标：主角第一卷要完成什么，并留下什么读者期待"
    )
    initial_intent: str = Field(description="一句话创作意图：这个故事给读者的核心体验")


_SYSTEM_PROMPT = (
    "你是资深网文编辑。作者会用一两句话描述想写的故事，"
    "你把它拆解成结构化的创作简报草稿，供作者修改确认。"
    "书名要符合番茄平台读者习惯、有点击欲；题材定位要具体到子类型；"
    "首个故事目标必须是可执行的具体目标，不能空泛；"
    "创作意图用一句话点明核心爽感体验。严格按 schema 输出，不要多余解释。"
)


class BriefDraftService:
    def __init__(self, settings: SettingsRepository, secrets: ApiKeyStore) -> None:
        self.settings = settings
        self.secrets = secrets

    async def draft(self, idea: str) -> BriefDraft:
        config = await asyncio.to_thread(self.settings.load)
        api_key = await asyncio.to_thread(self.secrets.get)
        model = build_model(config, api_key)
        # DeepSeek 等 OpenAI 兼容后端不支持默认的 json_schema response_format，
        # 改用 function_calling 方式约束结构化输出。
        structured = model.with_structured_output(BriefDraft, method="function_calling")
        result = await structured.ainvoke(
            [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": idea.strip()},
            ]
        )
        if not isinstance(result, BriefDraft):
            raise RuntimeError("BRIEF_DRAFT_INVALID")
        return result
