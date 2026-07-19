"""爆款拆解 Agent：分析输入的爆款小说文本，输出结构化拆解结果。

本模块遵循"降级优先"原则：分析失败时返回空结果，不抛错。
所有分析基于规则和统计，不依赖外部模型调用。
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# 拆解维度
AnalysisDimension = Literal["structure", "style", "rhythm", "hook"]

# 中文字符正则（用于字数统计）
_CHINESE_CHAR_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
# 中文引号对话正则（"..." 形式）
_DIALOGUE_PATTERN = re.compile(r"\u201c[^\u201d]*\u201d")
# 章节标题正则：匹配"第X章"标记（X 可为阿拉伯数字或中文数字）
_CHAPTER_TITLE_PATTERN = re.compile(r"第[\d一二三四五六七八九十百千零〇两]+章[^\n]*")
# 句子分隔正则：按中文句号、问号、叹号切分
_SENTENCE_SPLIT_PATTERN = re.compile(r"[。！？\n]+")


class ChapterAnalysis(BaseModel):
    """单章拆解结果。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    chapter_index: int = Field(description="章节序号，从 1 开始")
    word_count: int = Field(description="本章字数")
    dialogue_ratio: float = Field(description="对话占比，0-1")
    avg_paragraph_length: float = Field(description="平均段落长度")
    hook_type: str = Field(description="章末钩子类型：悬念/危机/反转/期待/无")
    climax_count: int = Field(description="爽点数量")
    climax_positions: list[str] = Field(description="爽点位置描述，如['开篇', '中段', '结尾']")
    key_events: list[str] = Field(description="关键事件列表")
    summary: str = Field(description="本章摘要，一句话")


class BestsellerAnalysis(BaseModel):
    """整本爆款拆解结果。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    source_title: str = Field(description="来源书名")
    source_genre: str = Field(description="来源题材")
    total_words: int = Field(description="总字数")
    total_chapters: int = Field(description="总章节数")
    avg_chapter_words: float = Field(description="平均每章字数")
    avg_dialogue_ratio: float = Field(description="平均对话占比")
    avg_paragraph_length: float = Field(description="平均段落长度")
    hook_type_distribution: dict[str, int] = Field(description="钩子类型分布")
    climax_density: float = Field(description="爽点密度：平均每章爽点数")
    chapter_analyses: list[ChapterAnalysis] = Field(description="逐章拆解结果")
    overall_pattern: str = Field(description="整体套路总结")


class BestsellerAnalyzer:
    """爆款拆解 Agent：对爆款小说文本做规则化拆解。

    所有子分析均以 try/except 包裹，单点失败不影响整体。
    输入为空或格式异常时返回空结果（valid BestsellerAnalysis with zero chapters）。
    """

    # 章末钩子检测窗口：最后 N 个字符
    _HOOK_WINDOW = 200
    # 章前摘要长度上限
    _SUMMARY_LIMIT = 100
    # 关键事件提取窗口：前 N 个字符
    _KEY_EVENT_WINDOW = 200
    # 关键事件最大条数
    _KEY_EVENT_MAX = 3

    # 爽点关键词列表
    _CLIMAX_KEYWORDS: tuple[str, ...] = (
        "震惊", "倒吸凉气", "不可思议", "赚大了", "突破", "升级",
        "打脸", "逆转", "翻盘", "暴击", "秒杀", "碾压", "惊艳",
        "骇然", "愣住", "呆住", "傻眼", "沸腾", "炸裂",
    )

    # 钩子类型关键词映射
    _HOOK_KEYWORDS: dict[str, tuple[str, ...]] = {
        "悬念": ("？", "?"),
        "危机": ("危险", "紧张", "绝境", "杀机", "死局"),
        "反转": ("竟然", "原来", "居然", "不料", "谁知"),
        "期待": ("即将", "明天", "下一步", "很快", "随后"),
    }

    def analyze(
        self,
        source_title: str,
        source_genre: str,
        chapters: list[str],
    ) -> BestsellerAnalysis:
        """分析爆款文本，返回结构化拆解结果。

        失败时返回空结果（0 章节），不抛错。
        """
        try:
            normalized = self._normalize_chapters(chapters)
            if not normalized:
                return self._empty_analysis(source_title, source_genre)

            chapter_analyses: list[ChapterAnalysis] = []
            for index, text in enumerate(normalized, start=1):
                analysis = self._safe_analyze_chapter(index, text)
                chapter_analyses.append(analysis)

            return self._build_overall(source_title, source_genre, chapter_analyses)
        except Exception:
            return self._empty_analysis(source_title, source_genre)

    # ------------------------------------------------------------------
    # 章节归一化：处理含"第X章"标记的单字符串
    # ------------------------------------------------------------------
    def _normalize_chapters(self, chapters: list[str]) -> list[str]:
        """归一化章节列表。

        - 输入为空或全部空白时返回空列表
        - 单个元素包含多个"第X章"标记时，按标记拆分
        - 否则按原列表返回，过滤空白项
        """
        if not chapters:
            return []

        normalized: list[str] = []
        for raw in chapters:
            if not raw or not raw.strip():
                continue
            # 若单个元素包含多个章节标记，则按标记拆分
            if len(_CHAPTER_TITLE_PATTERN.findall(raw)) > 1:
                normalized.extend(self._split_by_chapter_title(raw))
            else:
                normalized.append(raw.strip())

        return [item for item in normalized if item]

    @staticmethod
    def _split_by_chapter_title(text: str) -> list[str]:
        """按"第X章"标记拆分文本为多章。"""
        # 使用 split 保留分隔符
        parts = re.split(r"(?=第[\d一二三四五六七八九十百千零〇两]+章)", text)
        result: list[str] = []
        for part in parts:
            part = part.strip()
            if part:
                result.append(part)
        return result

    # ------------------------------------------------------------------
    # 单章分析
    # ------------------------------------------------------------------
    def _safe_analyze_chapter(self, index: int, text: str) -> ChapterAnalysis:
        """包裹单章分析，失败时返回零值结果。"""
        try:
            return self._analyze_chapter(index, text)
        except Exception:
            return ChapterAnalysis(
                chapter_index=index,
                word_count=0,
                dialogue_ratio=0.0,
                avg_paragraph_length=0.0,
                hook_type="无",
                climax_count=0,
                climax_positions=[],
                key_events=[],
                summary="",
            )

    def _analyze_chapter(self, index: int, text: str) -> ChapterAnalysis:
        """对单章做规则化拆解。"""
        word_count = self._count_words(text)
        dialogue_ratio = self._calc_dialogue_ratio(text, word_count)
        avg_paragraph_length = self._calc_avg_paragraph_length(text)
        hook_type = self._detect_hook_type(text)
        climax_positions = self._detect_climax_positions(text)
        climax_count = sum(1 for _ in self._iter_climax_matches(text))
        key_events = self._extract_key_events(text)
        summary = self._extract_summary(text)

        return ChapterAnalysis(
            chapter_index=index,
            word_count=word_count,
            dialogue_ratio=dialogue_ratio,
            avg_paragraph_length=avg_paragraph_length,
            hook_type=hook_type,
            climax_count=climax_count,
            climax_positions=climax_positions,
            key_events=key_events,
            summary=summary,
        )

    # ------------------------------------------------------------------
    # 字数统计：中文字符数
    # ------------------------------------------------------------------
    @staticmethod
    def _count_words(text: str) -> int:
        """统计中文字符数。"""
        return len(_CHINESE_CHAR_PATTERN.findall(text))

    # ------------------------------------------------------------------
    # 对话占比：中文引号内字符数 / 总中文字数
    # ------------------------------------------------------------------
    @staticmethod
    def _calc_dialogue_ratio(text: str, word_count: int) -> float:
        """计算对话占比（中文引号内字符数占总字数比例，0-1）。"""
        if word_count <= 0:
            return 0.0
        dialogue_chars = sum(
            len(_CHINESE_CHAR_PATTERN.findall(match))
            for match in _DIALOGUE_PATTERN.findall(text)
        )
        return min(dialogue_chars / word_count, 1.0)

    # ------------------------------------------------------------------
    # 平均段落长度：按换行分段
    # ------------------------------------------------------------------
    @staticmethod
    def _calc_avg_paragraph_length(text: str) -> float:
        """计算平均段落长度（按换行分段，中文字符数）。"""
        paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
        if not paragraphs:
            return 0.0
        total = sum(len(_CHINESE_CHAR_PATTERN.findall(p)) for p in paragraphs)
        return total / len(paragraphs) if paragraphs else 0.0

    # ------------------------------------------------------------------
    # 章末钩子类型检测
    # ------------------------------------------------------------------
    def _detect_hook_type(self, text: str) -> str:
        """检测章末钩子类型：悬念/危机/反转/期待/无。"""
        if not text:
            return "无"
        tail = text[-self._HOOK_WINDOW:]
        for hook_type, keywords in self._HOOK_KEYWORDS.items():
            if any(keyword in tail for keyword in keywords):
                return hook_type
        return "无"

    # ------------------------------------------------------------------
    # 爽点检测
    # ------------------------------------------------------------------
    def _iter_climax_matches(self, text: str) -> list[str]:
        """返回文本中所有爽点关键词匹配。"""
        return [kw for kw in self._CLIMAX_KEYWORDS if kw in text]

    def _detect_climax_positions(self, text: str) -> list[str]:
        """检测爽点位置：开篇/中段/结尾三段分布。"""
        if not text:
            return []
        length = len(text)
        if length == 0:
            return []
        # 将文本三等分
        third = length // 3
        segments = [
            ("开篇", text[: third]),
            ("中段", text[third : 2 * third]),
            ("结尾", text[2 * third :]),
        ]
        positions: list[str] = []
        for label, segment in segments:
            if any(kw in segment for kw in self._CLIMAX_KEYWORDS):
                positions.append(label)
        return positions

    # ------------------------------------------------------------------
    # 关键事件提取：从前 N 字中切分句子
    # ------------------------------------------------------------------
    def _extract_key_events(self, text: str) -> list[str]:
        """从前 N 字中提取关键事件（句子列表）。"""
        if not text:
            return []
        head = text[: self._KEY_EVENT_WINDOW]
        sentences = [s.strip() for s in _SENTENCE_SPLIT_PATTERN.split(head) if s.strip()]
        return sentences[: self._KEY_EVENT_MAX]

    # ------------------------------------------------------------------
    # 摘要提取：前 N 字内的首句
    # ------------------------------------------------------------------
    def _extract_summary(self, text: str) -> str:
        """提取本章摘要（前 100 字内的首句）。"""
        if not text:
            return ""
        head = text[: self._SUMMARY_LIMIT]
        sentences = [s.strip() for s in _SENTENCE_SPLIT_PATTERN.split(head) if s.strip()]
        if sentences:
            return sentences[0]
        return head.strip()

    # ------------------------------------------------------------------
    # 整体统计与套路总结
    # ------------------------------------------------------------------
    def _build_overall(
        self,
        source_title: str,
        source_genre: str,
        chapter_analyses: list[ChapterAnalysis],
    ) -> BestsellerAnalysis:
        """聚合单章结果，生成整体拆解。"""
        total_chapters = len(chapter_analyses)
        total_words = sum(c.word_count for c in chapter_analyses)
        avg_chapter_words = total_words / total_chapters if total_chapters else 0.0
        avg_dialogue = (
            sum(c.dialogue_ratio for c in chapter_analyses) / total_chapters
            if total_chapters
            else 0.0
        )
        avg_paragraph = (
            sum(c.avg_paragraph_length for c in chapter_analyses) / total_chapters
            if total_chapters
            else 0.0
        )

        hook_distribution: dict[str, int] = {}
        for c in chapter_analyses:
            hook_distribution[c.hook_type] = hook_distribution.get(c.hook_type, 0) + 1

        total_climax = sum(c.climax_count for c in chapter_analyses)
        climax_density = total_climax / total_chapters if total_chapters else 0.0

        overall_pattern = self._summarize_pattern(
            avg_chapter_words=avg_chapter_words,
            avg_dialogue=avg_dialogue,
            avg_paragraph=avg_paragraph,
            hook_distribution=hook_distribution,
            climax_density=climax_density,
            total_chapters=total_chapters,
        )

        return BestsellerAnalysis(
            source_title=source_title,
            source_genre=source_genre,
            total_words=total_words,
            total_chapters=total_chapters,
            avg_chapter_words=avg_chapter_words,
            avg_dialogue_ratio=avg_dialogue,
            avg_paragraph_length=avg_paragraph,
            hook_type_distribution=hook_distribution,
            climax_density=climax_density,
            chapter_analyses=chapter_analyses,
            overall_pattern=overall_pattern,
        )

    @staticmethod
    def _summarize_pattern(
        avg_chapter_words: float,
        avg_dialogue: float,
        avg_paragraph: float,
        hook_distribution: dict[str, int],
        climax_density: float,
        total_chapters: int,
    ) -> str:
        """基于统计结果生成整体套路文字描述。"""
        if total_chapters == 0:
            return "无有效章节，无法生成套路总结。"

        # 找出占比最高的钩子类型
        dominant_hook = (
            max(hook_distribution.items(), key=lambda item: item[1])[0]
            if hook_distribution
            else "无"
        )

        # 对话风格判定
        if avg_dialogue >= 0.4:
            dialogue_style = "对话驱动型（对话占比高，节奏快）"
        elif avg_dialogue >= 0.2:
            dialogue_style = "对话与叙述并重型"
        else:
            dialogue_style = "叙述主导型（描写多，节奏沉稳）"

        # 段落风格判定
        if avg_paragraph >= 80:
            paragraph_style = "长段落（信息密度高）"
        elif avg_paragraph >= 40:
            paragraph_style = "中等段落（阅读节奏适中）"
        else:
            paragraph_style = "短段落（节奏明快，适合移动端阅读）"

        # 爽点密度判定
        if climax_density >= 2.0:
            climax_style = "爽点密集（每章多处爆点）"
        elif climax_density >= 1.0:
            climax_style = "爽点适中（每章至少一处爆点）"
        else:
            climax_style = "爽点稀疏（部分章节无爆点）"

        return (
            f"全书共 {total_chapters} 章，平均每章 {avg_chapter_words:.0f} 字。"
            f"风格：{dialogue_style}，{paragraph_style}。"
            f"章末钩子以「{dominant_hook}」为主，{climax_style}。"
            f"建议开篇快速建立冲突，章末持续抛出钩子以维持留存。"
        )

    # ------------------------------------------------------------------
    # 空结果构造（降级使用）
    # ------------------------------------------------------------------
    @staticmethod
    def _empty_analysis(source_title: str, source_genre: str) -> BestsellerAnalysis:
        """构造空拆解结果（降级时使用）。"""
        return BestsellerAnalysis(
            source_title=source_title,
            source_genre=source_genre,
            total_words=0,
            total_chapters=0,
            avg_chapter_words=0.0,
            avg_dialogue_ratio=0.0,
            avg_paragraph_length=0.0,
            hook_type_distribution={},
            climax_density=0.0,
            chapter_analyses=[],
            overall_pattern="无有效章节，无法生成套路总结。",
        )
