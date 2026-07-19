"""套路模板 Agent：从拆解结果提炼可复用的创作模板。

本模块基于 BestsellerAnalysis 生成 PatternTemplate，供章节生成参考。
遵循"降级优先"原则：输入异常时返回零值模板，不抛错。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.agents.bestseller_analyzer import BestsellerAnalysis


class PatternTemplate(BaseModel):
    """套路模板：从爆款拆解结果提炼的可复用模板。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    template_name: str = Field(description="模板名称")
    source_title: str = Field(description="来源爆款书名")
    genre: str = Field(description="适用题材")
    chapter_length_range: tuple[int, int] = Field(description="章节字数范围")
    dialogue_ratio_range: tuple[float, float] = Field(description="对话占比范围")
    paragraph_length_max: int = Field(description="段落最大长度建议")
    hook_distribution: dict[str, float] = Field(description="钩子类型建议分布")
    climax_density: float = Field(description="建议爽点密度")
    chapter_structure: list[str] = Field(
        description="建议章节结构：如['开篇钩子', '冲突升级', '爽点爆发', '章末钩子']"
    )
    notes: str = Field(description="使用备注")


class PatternTemplateBuilder:
    """套路模板构建器：从 BestsellerAnalysis 提炼可复用模板。

    失败时返回零值模板，不抛错。
    """

    # 章节字数浮动比例：均值 ± 20%
    _CHAPTER_LENGTH_RATIO = 0.2
    # 对话占比浮动比例：均值 ± 20%
    _DIALOGUE_RATIO_RANGE = 0.2
    # 段落最大长度系数：平均段落长度 × 1.5
    _PARAGRAPH_LENGTH_FACTOR = 1.5

    def build_from_analysis(
        self,
        analysis: BestsellerAnalysis,
        template_name: str,
    ) -> PatternTemplate:
        """从拆解结果生成可复用的套路模板。

        失败时返回零值模板。
        """
        try:
            chapter_length_range = self._calc_chapter_length_range(
                analysis.avg_chapter_words
            )
            dialogue_ratio_range = self._calc_dialogue_ratio_range(
                analysis.avg_dialogue_ratio
            )
            paragraph_length_max = self._calc_paragraph_length_max(
                analysis.avg_paragraph_length
            )
            hook_distribution = self._calc_hook_distribution(
                analysis.hook_type_distribution, analysis.total_chapters
            )
            chapter_structure = self._derive_chapter_structure(analysis)

            notes = self._build_notes(analysis)

            return PatternTemplate(
                template_name=template_name,
                source_title=analysis.source_title,
                genre=analysis.source_genre,
                chapter_length_range=chapter_length_range,
                dialogue_ratio_range=dialogue_ratio_range,
                paragraph_length_max=paragraph_length_max,
                hook_distribution=hook_distribution,
                climax_density=analysis.climax_density,
                chapter_structure=chapter_structure,
                notes=notes,
            )
        except Exception:
            return self._empty_template(template_name, analysis)

    # ------------------------------------------------------------------
    # 章节字数范围：[均值 × 0.8, 均值 × 1.2]
    # ------------------------------------------------------------------
    def _calc_chapter_length_range(self, avg_chapter_words: float) -> tuple[int, int]:
        """计算建议章节字数范围。"""
        if avg_chapter_words <= 0:
            return (0, 0)
        lower = int(avg_chapter_words * (1 - self._CHAPTER_LENGTH_RATIO))
        upper = int(avg_chapter_words * (1 + self._CHAPTER_LENGTH_RATIO))
        # 保证下限非负且不超过上限
        lower = max(0, min(lower, upper))
        return (lower, upper)

    # ------------------------------------------------------------------
    # 对话占比范围：[均值 × 0.8, 均值 × 1.2]
    # ------------------------------------------------------------------
    def _calc_dialogue_ratio_range(
        self, avg_dialogue_ratio: float
    ) -> tuple[float, float]:
        """计算建议对话占比范围。"""
        if avg_dialogue_ratio <= 0:
            return (0.0, 0.0)
        lower = avg_dialogue_ratio * (1 - self._DIALOGUE_RATIO_RANGE)
        upper = avg_dialogue_ratio * (1 + self._DIALOGUE_RATIO_RANGE)
        # 上限不超过 1.0
        return (max(0.0, lower), min(1.0, upper))

    # ------------------------------------------------------------------
    # 段落最大长度：平均段落长度 × 1.5
    # ------------------------------------------------------------------
    def _calc_paragraph_length_max(self, avg_paragraph_length: float) -> int:
        """计算建议段落最大长度。"""
        if avg_paragraph_length <= 0:
            return 0
        return int(avg_paragraph_length * self._PARAGRAPH_LENGTH_FACTOR)

    # ------------------------------------------------------------------
    # 钩子分布：各类型占比（0-1）
    # ------------------------------------------------------------------
    @staticmethod
    def _calc_hook_distribution(
        hook_type_distribution: dict[str, int], total_chapters: int
    ) -> dict[str, float]:
        """统计各钩子类型占比。"""
        if total_chapters <= 0 or not hook_type_distribution:
            return {}
        return {
            hook_type: count / total_chapters
            for hook_type, count in hook_type_distribution.items()
        }

    # ------------------------------------------------------------------
    # 章节结构：基于爽点位置分布生成
    # ------------------------------------------------------------------
    def _derive_chapter_structure(self, analysis: BestsellerAnalysis) -> list[str]:
        """基于爽点位置分布推导建议章节结构。"""
        if not analysis.chapter_analyses:
            return ["开篇钩子", "冲突升级", "爽点爆发", "章末钩子"]

        # 统计各位置出现爽点的章节占比
        position_counts = {"开篇": 0, "中段": 0, "结尾": 0}
        for chapter in analysis.chapter_analyses:
            for pos in chapter.climax_positions:
                if pos in position_counts:
                    position_counts[pos] += 1

        total = len(analysis.chapter_analyses)
        structure: list[str] = []

        # 开篇：若超过半数章节在开篇有爽点，则建议"开篇钩子+爽点"
        if position_counts["开篇"] / total >= 0.5:
            structure.append("开篇钩子")
            structure.append("开篇爽点")
        else:
            structure.append("开篇钩子")

        # 中段：冲突升级必备
        structure.append("冲突升级")
        if position_counts["中段"] / total >= 0.5:
            structure.append("中段爽点")

        # 结尾：爽点爆发 + 章末钩子
        if position_counts["结尾"] / total >= 0.5:
            structure.append("爽点爆发")
        structure.append("章末钩子")

        return structure

    # ------------------------------------------------------------------
    # 使用备注
    # ------------------------------------------------------------------
    @staticmethod
    def _build_notes(analysis: BestsellerAnalysis) -> str:
        """生成模板使用备注。"""
        if analysis.total_chapters == 0:
            return "来源拆解无有效章节，模板数值仅供参考。"
        return (
            f"本模板提炼自《{analysis.source_title}》"
            f"（{analysis.source_genre}），"
            f"基于 {analysis.total_chapters} 章统计。"
            f"建议章节字数控制在均值 ±20% 范围内，"
            f"保持爽点密度 {analysis.climax_density:.1f} 个/章以上。"
        )

    # ------------------------------------------------------------------
    # 空模板构造（降级使用）
    # ------------------------------------------------------------------
    @staticmethod
    def _empty_template(
        template_name: str, analysis: BestsellerAnalysis
    ) -> PatternTemplate:
        """构造零值模板（降级时使用）。"""
        return PatternTemplate(
            template_name=template_name,
            source_title=analysis.source_title,
            genre=analysis.source_genre,
            chapter_length_range=(0, 0),
            dialogue_ratio_range=(0.0, 0.0),
            paragraph_length_max=0,
            hook_distribution={},
            climax_density=0.0,
            chapter_structure=[],
            notes="模板生成失败，数值为空。",
        )
