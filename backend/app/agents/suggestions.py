"""建议通道：聚合各 Agent 的诊断输出，转化为可执行建议。

本模块将 DiagnosticsAgent 的诊断结论按类型映射为 Suggestion，
不引入模型调用；任何子步骤失败时返回空列表以实现降级。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agents.diagnostics import DiagnosticResult, DiagnosticsAgent
from app.repositories.workspace import WorkspaceRepository

# 建议类型
SuggestionType = Literal["planning", "optimization", "foreshadow", "material"]
# 建议优先级
SuggestionPriority = Literal["low", "medium", "high"]


class Suggestion(BaseModel):
    """单条建议。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    type: SuggestionType
    content: str = Field(description="建议内容，应可直接执行")
    reason: str = Field(description="建议依据，关联具体诊断结论")
    priority: SuggestionPriority


class SuggestionsChannel:
    """建议通道：聚合 DiagnosticsAgent 输出为分类建议。

    遵循"降级优先"原则：诊断或转化失败时返回空列表，不抛错。
    """

    # 诊断严重程度到建议优先级的映射
    _SEVERITY_TO_PRIORITY: dict[str, SuggestionPriority] = {
        "info": "low",
        "warning": "medium",
        "error": "high",
    }
    # 诊断类型到建议类型的映射
    _DIAGNOSTIC_TO_SUGGESTION: dict[str, SuggestionType] = {
        "data": "optimization",
        "plot": "planning",
        "foreshadowing": "foreshadow",
    }

    def __init__(self, workspace: WorkspaceRepository) -> None:
        self.workspace = workspace

    def collect(self, project_id: str) -> list[Suggestion]:
        """聚合诊断结果为建议列表。"""
        try:
            diagnostics = DiagnosticsAgent(self.workspace).run(project_id)
        except Exception:
            return []
        suggestions: list[Suggestion] = []
        for diagnostic in diagnostics:
            suggestion = self._translate(diagnostic)
            if suggestion is not None:
                suggestions.append(suggestion)
        return suggestions

    def _translate(self, diagnostic: DiagnosticResult) -> Suggestion | None:
        """将单条诊断结论转化为建议，无法转化时返回 None。"""
        suggestion_type = self._DIAGNOSTIC_TO_SUGGESTION.get(diagnostic.diagnostic_type)
        if suggestion_type is None:
            return None
        priority = self._SEVERITY_TO_PRIORITY.get(diagnostic.severity, "low")
        # 取第一条可能原因作为建议执行方向，其余归入 reason
        causes = diagnostic.possible_causes
        primary_cause = causes[0] if causes else "未明确"
        secondary_causes = "; ".join(causes[1:]) if len(causes) > 1 else ""
        reason = diagnostic.conclusion
        if secondary_causes:
            reason = f"{reason}；其他可能原因：{secondary_causes}"
        return Suggestion(
            type=suggestion_type,
            content=self._compose_content(diagnostic, primary_cause),
            reason=reason,
            priority=priority,
        )

    @staticmethod
    def _compose_content(diagnostic: DiagnosticResult, primary_cause: str) -> str:
        """根据诊断类型生成可执行建议内容。"""
        if diagnostic.diagnostic_type == "data":
            return f"针对「{diagnostic.target}」：检查 {primary_cause}，必要时调整近期章节策略。"
        if diagnostic.diagnostic_type == "plot":
            return f"针对「{diagnostic.target}」：{primary_cause}，建议在下一章规划时调整。"
        if diagnostic.diagnostic_type == "foreshadowing":
            return f"针对「{diagnostic.target}」：{primary_cause}，建议在近期章节安排回收。"
        return f"针对「{diagnostic.target}」：{primary_cause}。"
