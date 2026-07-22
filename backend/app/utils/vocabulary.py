"""词汇重复检测：扫描章节正文，发现 AI 写作常见的高频重复词汇和套话。

检测逻辑：
1. 对整个文本进行 2-4 字 n-gram 频率统计
2. 按每千字出现次数归一化
3. 超过阈值的词组视为重复
4. 另外维护一份 AI 写作套话白名单，遇到即标记（不考虑频率）

不引入任何外部依赖，纯 Python 实现，不需要 LLM 调用。
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

# ── AI 写作套话列表（来自网文创作研究，AI 生成正文中高频出现的刻板词汇）──
_AI_CLICHES: list[str] = [
    "不由得",
    "心头一震",
    "心中一凛",
    "嘴角微扬",
    "淡淡地",
    "淡淡一笑",
    "冷哼一声",
    "冷冷地",
    "轻笑一声",
    "低声说道",
    "喃喃自语",
    "忍不住",
    "不禁",
    "皱了皱眉",
    "眉头微皱",
    "眸中闪过",
    "微微一顿",
    "缓缓开口",
    "沉声说道",
    "轻轻地",
]

# ── 中文标点和无意义字符（n-gram 分割时跳过）────────────────────────────────
_SKIP_CHARS = frozenset("，。！？；：""''《》【】（）、\n\r\t… ")

# 高频重复的阈值：每千字超过此次数视为重复
_FREQUENCY_THRESHOLD_PER_1K = 3.0


@dataclass(frozen=True)
class VocabularyIssue:
    """单条词汇重复问题。"""

    phrase: str
    count: int
    per_thousand: float
    category: str  # "repetitive" | "cliche"
    suggestion: str


def detect_repetitive_vocabulary(text: str) -> list[VocabularyIssue]:
    """检测正文中的重复词汇和 AI 套话。

    参数
    ----
    text : str
        章节正文（markdown 格式，检测时剥离 markdown 语法）

    返回
    ----
    list[VocabularyIssue]
        发现的问题列表，按严重程度排序（套话优先，然后按每千字频率降序）
    """
    # 剥离 markdown 语法
    plain = _strip_markdown(text)
    if not plain.strip():
        return []

    # 中文字符总数（用于归一化）
    chinese_chars = len(re.findall(r"[㐀-䶿一-鿿]", plain))
    if chinese_chars == 0:
        return []

    issues: list[VocabularyIssue] = []

    # ── 1. 套话检测 ────────────────────────────────────────────────────────
    for cliche in _AI_CLICHES:
        count = plain.count(cliche)
        if count >= 2:  # 出现 2 次及以上即标记
            per_k = round(count / chinese_chars * 1000, 1)
            issues.append(
                VocabularyIssue(
                    phrase=cliche,
                    count=count,
                    per_thousand=per_k,
                    category="cliche",
                    suggestion=f"「{cliche}」是 AI 生成文本的常见套话，建议改用更具体的动作描写。",
                )
            )

    # ── 2. 高频 n-gram 检测（2-4 字）────────────────────────────────────────
    ngram_counts = _count_ngrams(plain, sizes=(2, 3, 4))
    for phrase, count in ngram_counts.items():
        # 已经被套话检测覆盖的跳过
        if any(phrase in c for c in _AI_CLICHES):
            continue
        per_k = count / chinese_chars * 1000
        if per_k >= _FREQUENCY_THRESHOLD_PER_1K:
            issues.append(
                VocabularyIssue(
                    phrase=phrase,
                    count=count,
                    per_thousand=round(per_k, 1),
                    category="repetitive",
                    suggestion=f"「{phrase}」每千字出现 {round(per_k, 1)} 次，"
                    "建议检查是否有同义替换或改变句式。",
                )
            )

    # 套话排在前面，然后按每千字频率降序
    issues.sort(key=lambda x: (x.category != "cliche", -x.per_thousand))
    return issues


def _strip_markdown(text: str) -> str:
    """去除 markdown 语法，保留可读文本。"""
    # 去除标题标记
    text = re.sub(r"^#+\s+", "", text, flags=re.MULTILINE)
    # 去除粗体/斜体
    text = re.sub(r"\*{1,3}(.*?)\*{1,3}", r"\1", text)
    # 去除链接
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    return text


def _count_ngrams(text: str, sizes: tuple[int, ...]) -> Counter[str]:
    """统计中文文本中各尺寸 n-gram 的出现次数，过滤含标点的片段。"""
    counter: Counter[str] = Counter()
    # 提取连续中文字符块
    segments = re.findall(r"[㐀-䶿一-鿿]+", text)
    for segment in segments:
        for size in sizes:
            for i in range(len(segment) - size + 1):
                ngram = segment[i : i + size]
                counter[ngram] += 1
    # 只保留出现 3 次以上的（提高性能，低频词不用报告）
    return Counter({k: v for k, v in counter.items() if v >= 3})
