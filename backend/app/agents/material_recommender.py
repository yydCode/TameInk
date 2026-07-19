"""素材推荐 Agent：根据章节内容推荐素材、人物或对话片段。

本模块基于项目记忆库（facts/relationships）与已确认章节做规则化推荐，
不依赖模型调用；任何子步骤失败时返回空列表以实现降级。
不引入 Mock 数据。
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.project import MemoryRecord
from app.repositories.workspace import WorkspaceRepository
from app.workflows.memory import MemoryService

# 推荐类型
RecommendationType = Literal["material", "character", "dialogue"]


class Recommendation(BaseModel):
    """单条推荐。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    type: RecommendationType
    content: str = Field(description="推荐内容，如素材描述、人物画像或对话片段")
    reason: str = Field(description="推荐理由，关联章节或记忆来源")
    source: str = Field(description="来源引用，如记忆 id 或章节路径")


# 用于从章节正文中提取对话行的简化正则
_DIALOGUE_PATTERN = re.compile(r"[「“\"『]+([^”」\"』]{4,})[”」\"』]")
# 推荐结果上限，避免单章节返回过多推荐
_MAX_RECOMMENDATIONS = 10


class MaterialRecommender:
    """素材推荐 Agent：根据章节内容推荐素材/人物/对话。

    推荐来源：
    - material：从记忆库 facts 中提取尚未在该章节引用的事实作为可用素材
    - character：从记忆库 relationships 中提取与章节相关的人物关系
    - dialogue：从相邻章节提取可复用对话风格片段

    遵循"降级优先"原则：任何子步骤失败返回空列表，不抛错。
    """

    def __init__(self, workspace: WorkspaceRepository) -> None:
        self.workspace = workspace

    def recommend(self, project_id: str, chapter_id: str) -> list[Recommendation]:
        """根据章节内容返回推荐列表。"""
        recommendations: list[Recommendation] = []
        recommendations.extend(self._safe(self._recommend_material, project_id, chapter_id))
        recommendations.extend(self._safe(self._recommend_character, project_id, chapter_id))
        recommendations.extend(self._safe(self._recommend_dialogue, project_id, chapter_id))
        return recommendations[:_MAX_RECOMMENDATIONS]

    @staticmethod
    def _safe(
        func: Callable[[str, str], list[Recommendation]],
        project_id: str,
        chapter_id: str,
    ) -> list[Recommendation]:
        """包裹子推荐调用，失败时返回空列表以实现降级。"""
        try:
            return func(project_id, chapter_id)
        except Exception:
            return []

    # ------------------------------------------------------------------
    # 素材推荐：从记忆库 facts 中提取与当前章节相关的事实
    # ------------------------------------------------------------------
    def _recommend_material(self, project_id: str, chapter_id: str) -> list[Recommendation]:
        records = self._memory_records(project_id, kind="fact", status="active")
        if not records:
            return []
        chapter_source = f"canon/chapters/{chapter_id}.md"
        # 排除已在该章节引用的事实，保留可复用素材
        candidates = [record for record in records if record.source != chapter_source]
        if not candidates:
            return []
        # 取前 3 条作为推荐，避免过多
        recommendations: list[Recommendation] = []
        for record in candidates[:3]:
            content = record.content or record.quote
            recommendations.append(
                Recommendation(
                    type="material",
                    content=content,
                    reason="已确认事实，可作为后续章节的素材支撑",
                    source=f"memory/facts/{record.id}.yaml",
                )
            )
        return recommendations

    # ------------------------------------------------------------------
    # 人物推荐：从记忆库 relationships 中提取人物关系
    # ------------------------------------------------------------------
    def _recommend_character(self, project_id: str, chapter_id: str) -> list[Recommendation]:
        records = self._memory_records(project_id, kind="relationship", status="active")
        if not records:
            return []
        recommendations: list[Recommendation] = []
        for record in records[:3]:
            content = record.content or record.quote
            recommendations.append(
                Recommendation(
                    type="character",
                    content=content,
                    reason="已确认人物关系，可在本章或后续章节中复用",
                    source=f"memory/relationships/{record.id}.yaml",
                )
            )
        return recommendations

    # ------------------------------------------------------------------
    # 对话推荐：从相邻章节提取可复用对话片段
    # ------------------------------------------------------------------
    def _recommend_dialogue(self, project_id: str, chapter_id: str) -> list[Recommendation]:
        # 优先选取前一章作为对话风格参考
        previous = self._previous_chapter_path(project_id, chapter_id)
        if previous is None:
            return []
        try:
            content = previous.read_text(encoding="utf-8")
        except OSError:
            return []
        dialogues = _DIALOGUE_PATTERN.findall(content)
        if not dialogues:
            return []
        # 取最长的一条作为代表性对话片段
        representative = max(dialogues, key=len)
        source_path = previous.relative_to(
            self.workspace.project_path(project_id)
        ).as_posix()
        return [
            Recommendation(
                type="dialogue",
                content=representative,
                reason=f"来自相邻章节 {previous.stem} 的代表性对话，可作为风格参考",
                source=source_path,
            )
        ]

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------
    def _memory_records(
        self, project_id: str, *, kind: str, status: str
    ) -> list[MemoryRecord]:
        """从记忆库读取指定类型和状态的记录。"""
        records = MemoryService(self.workspace).list_records(project_id)
        return [record for record in records if record.kind == kind and record.status == status]

    def _previous_chapter_path(
        self, project_id: str, chapter_id: str
    ) -> Path | None:
        """返回当前章节的前一章路径，若不存在返回 None。"""
        try:
            current = int(chapter_id)
        except ValueError:
            return None
        if current <= 1:
            return None
        previous_id = str(current - 1)
        candidate = self.workspace.resolve_project_path(
            project_id, f"canon/chapters/{previous_id}.md"
        )
        if not candidate.is_file():
            return None
        return candidate
