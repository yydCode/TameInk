"""诊断 Agent：分析项目数据、剧情信息量与伏笔铺设情况。

本模块遵循"降级优先"原则：任何子诊断失败或数据缺失时返回空列表，不抛错。
不引入 Mock 数据；所有结论均来自项目实际存储（商业观测、已确认章节、记忆库）。
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.commercial import CommercialMetrics
from app.domain.project import MemoryRecord
from app.repositories.commercial import CommercialRepository
from app.repositories.database import DatabaseRepository
from app.repositories.workspace import WorkspaceRepository
from app.workflows.memory import MemoryService

# 诊断类型
DiagnosticType = Literal["data", "plot", "foreshadowing"]
# 严重程度
DiagnosticSeverity = Literal["info", "warning", "error"]


class DiagnosticResult(BaseModel):
    """单条诊断结论。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    diagnostic_type: DiagnosticType
    target: str = Field(description="诊断对象，如「第 115 章」或「整体完读率」")
    conclusion: str = Field(description="诊断结论，简明陈述事实")
    possible_causes: list[str] = Field(
        default_factory=list, description="可能原因候选列表，按可能性排序"
    )
    severity: DiagnosticSeverity


# 中文字符与英文单词的正则，用于估算字数（与 projects.py 中保持一致）
_WORD_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]|[A-Za-z0-9]+")
# 章节文件名正则：纯数字章节号
_CHAPTER_ID_PATTERN = re.compile(r"^\d+$")


class DiagnosticsAgent:
    """诊断 Agent：聚合三类诊断输出。

    所有子诊断均以 try/except 包裹，单点失败不影响其他诊断。
    模型未配置或调用失败时返回空列表（本实现为纯规则分析，不依赖模型）。
    """

    # 数据诊断阈值：完读率低于此值视为异常
    _DATA_COMPLETION_WARN = 0.5
    _DATA_RETENTION_WARN = 0.3
    # 剧情诊断阈值：章节字数相对均值偏离超过此比例视为异常
    _PLOT_DEVIATION_RATIO = 0.5
    # 伏笔诊断阈值：铺设章节与最新章节差距超过此值视为铺设过久
    _FORESHADOW_SPAN_WARN = 30

    def __init__(self, workspace: WorkspaceRepository) -> None:
        self.workspace = workspace

    def run(self, project_id: str) -> list[DiagnosticResult]:
        """运行三类诊断并返回汇总结果。"""
        results: list[DiagnosticResult] = []
        results.extend(self._safe_run(self._diagnose_data, project_id))
        results.extend(self._safe_run(self._diagnose_plot, project_id))
        results.extend(self._safe_run(self._diagnose_foreshadowing, project_id))
        return results

    @staticmethod
    def _safe_run(
        func: Callable[[str], list[DiagnosticResult]], project_id: str
    ) -> list[DiagnosticResult]:
        """包裹子诊断调用，失败时返回空列表以实现降级。"""
        try:
            return func(project_id)
        except Exception:
            return []

    # ------------------------------------------------------------------
    # 数据诊断：分析 commercial metrics 完读率
    # ------------------------------------------------------------------
    def _diagnose_data(self, project_id: str) -> list[DiagnosticResult]:
        database = DatabaseRepository(self.workspace)
        database.initialize(project_id)
        metrics: CommercialMetrics = CommercialRepository(database).metrics(project_id)

        # 数据不足时返回 info 提示，便于用户判断诊断可信度
        if metrics.observations == 0:
            return [
                DiagnosticResult(
                    diagnostic_type="data",
                    target="商业观测数据",
                    conclusion="尚未录入任何商业观测数据，无法进行数据诊断。",
                    possible_causes=["项目尚未发布", "数据录入流程未启动"],
                    severity="info",
                )
            ]

        results: list[DiagnosticResult] = []
        # 第一章完读率
        if metrics.chapter_one_completion_rate < self._DATA_COMPLETION_WARN:
            results.append(
                DiagnosticResult(
                    diagnostic_type="data",
                    target="第一章完读率",
                    conclusion=(
                        f"第一章完读率为 {metrics.chapter_one_completion_rate:.1%}，"
                        f"低于 {self._DATA_COMPLETION_WARN:.0%} 警戒线。"
                    ),
                    possible_causes=[
                        "开篇钩子不够吸引目标读者",
                        "标题/简介与正文预期不符",
                        "首章信息密度过高或过低",
                    ],
                    severity="warning",
                )
            )
        # 三章留存率
        if metrics.chapter_three_retention_rate < self._DATA_RETENTION_WARN:
            results.append(
                DiagnosticResult(
                    diagnostic_type="data",
                    target="三章留存率",
                    conclusion=(
                        f"三章留存率为 {metrics.chapter_three_retention_rate:.1%}，"
                        f"低于 {self._DATA_RETENTION_WARN:.0%} 警戒线。"
                    ),
                    possible_causes=[
                        "前三章承诺未兑现",
                        "冲突升级节奏过慢",
                        "核心卖点未在前三章呈现",
                    ],
                    severity="warning",
                )
            )
        return results

    # ------------------------------------------------------------------
    # 剧情诊断：分析章节信息量（字数偏离均值）
    # ------------------------------------------------------------------
    def _diagnose_plot(self, project_id: str) -> list[DiagnosticResult]:
        chapters = self._list_chapters(project_id)
        if len(chapters) < 2:
            # 章节数不足时无法计算偏离，返回空列表（不引入 Mock）
            return []

        word_counts = [count for _, count in chapters]
        average = sum(word_counts) / len(word_counts)
        if average <= 0:
            return []

        results: list[DiagnosticResult] = []
        threshold = average * self._PLOT_DEVIATION_RATIO
        for chapter_id, count in chapters:
            if count < threshold:
                results.append(
                    DiagnosticResult(
                        diagnostic_type="plot",
                        target=f"第 {chapter_id} 章",
                        conclusion=(
                            f"本章字数约 {count}，明显低于章节均值 {average:.0f}"
                            f"（偏离超过 {self._PLOT_DEVIATION_RATIO:.0%}）。"
                        ),
                        possible_causes=[
                            "场景过渡过快，未充分展开",
                            "信息密度过高，省略了必要描写",
                            "章节切分不当，应与相邻章合并",
                        ],
                        severity="warning",
                    )
                )
            elif count > average * (1 + self._PLOT_DEVIATION_RATIO):
                results.append(
                    DiagnosticResult(
                        diagnostic_type="plot",
                        target=f"第 {chapter_id} 章",
                        conclusion=(
                            f"本章字数约 {count}，明显高于章节均值 {average:.0f}"
                            f"（偏离超过 {self._PLOT_DEVIATION_RATIO:.0%}）。"
                        ),
                        possible_causes=[
                            "章节承载过多场景，建议拆分",
                            "存在冗余描写或离题支线",
                            "对话过长未及时收束",
                        ],
                        severity="info",
                    )
                )
        return results

    # ------------------------------------------------------------------
    # 伏笔诊断：标记铺设过久的 active 伏笔
    # ------------------------------------------------------------------
    def _diagnose_foreshadowing(self, project_id: str) -> list[DiagnosticResult]:
        records: list[MemoryRecord] = MemoryService(self.workspace).list_records(project_id)
        active_foreshadows = [
            record
            for record in records
            if record.kind == "foreshadowing" and record.status == "active"
        ]
        if not active_foreshadows:
            return []

        # 计算当前最大章节号，用于估算伏笔铺设时长
        chapter_ids = [
            int(path.stem)
            for path in self._chapter_paths(project_id)
            if _CHAPTER_ID_PATTERN.match(path.stem)
        ]
        if not chapter_ids:
            return []
        latest_chapter = max(chapter_ids)

        results: list[DiagnosticResult] = []
        for record in active_foreshadows:
            source_chapter = self._extract_chapter_id(record.source)
            if source_chapter is None:
                continue
            span = latest_chapter - source_chapter
            if span >= self._FORESHADOW_SPAN_WARN:
                results.append(
                    DiagnosticResult(
                        diagnostic_type="foreshadowing",
                        target=f"伏笔 {record.id}",
                        conclusion=(
                            f"该伏笔铺设于第 {source_chapter} 章，"
                            f"距今已 {span} 章未兑现（超过 {self._FORESHADOW_SPAN_WARN} 章）。"
                        ),
                        possible_causes=[
                            "原计划回收点尚未到达，需检查大纲进度",
                            "伏笔已被遗忘，应在近期章节回收",
                            "可考虑通过支线提前部分兑现以维持读者记忆",
                        ],
                        severity="warning",
                    )
                )
        return results

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------
    def _chapter_paths(self, project_id: str) -> list[Path]:
        """返回已确认章节文件路径列表，按章节号排序。"""
        root = self.workspace.resolve_project_path(project_id, "canon/chapters")
        if not root.is_dir():
            return []
        paths = [path for path in root.iterdir() if path.is_file() and path.suffix == ".md"]
        # 按文件名（章节号）数值排序
        return sorted(paths, key=lambda p: (not _CHAPTER_ID_PATTERN.match(p.stem), p.stem))

    def _list_chapters(self, project_id: str) -> list[tuple[str, int]]:
        """返回 [(chapter_id, word_count), ...] 列表。"""
        result: list[tuple[str, int]] = []
        for path in self._chapter_paths(project_id):
            try:
                content = path.read_text(encoding="utf-8")
            except OSError:
                continue
            count = len(_WORD_PATTERN.findall(content))
            result.append((path.stem, count))
        return result

    @staticmethod
    def _extract_chapter_id(source: str) -> int | None:
        """从 memory source 路径中提取章节号。

        source 形如 `canon/chapters/115.md`，提取出 115。
        """
        match = re.match(r"^canon/chapters/(\d+)\.md$", source.strip())
        if match is None:
            return None
        return int(match.group(1))
