"""番茄小说榜单抓取器 + 开篇钩子分类器。

接入 novelcatch.com 公开 JSON API（/api/rank），抓取番茄 TOP50 榜单，
并基于公开 metadata（logline/premise）做开篇钩子类型分类。

设计原则：
- 仅抓取公开榜单 metadata，不抓取小说正文（避免版权风险）。
- 失败即抛 RuntimeError，不静默降级（调用方决定是否回退）。
- 钩子分类复用 bestseller_analyzer 的关键词映射，保证口径一致。
"""

from __future__ import annotations

from typing import Any

import httpx

from app.domain.fanqie_bestseller import (
    BestsellerEntry,
    BestsellerSnapshot,
    FeatureVector,
    WordCountStats,
)

# 四个榜单配置：(gender, list_name, 中文标签)
_RANK_LISTS: tuple[tuple[str, str, str], ...] = (
    ("m", "read", "男频阅读榜"),
    ("m", "new", "男频新书榜"),
    ("f", "read", "女频阅读榜"),
    ("f", "new", "女频新书榜"),
)

# 开篇钩子类型映射：novelcatch metadata → 5 类标签
# 与 bestseller_analyzer._HOOK_KEYWORDS 对齐，但增加“冲突”维度
_OPENING_HOOK_KEYWORDS: dict[str, tuple[str, ...]] = {
    "conflict": ("杀", "死", "逃", "抓", "逃出", "陷入", "对决", "冲突", "威胁"),
    "suspense": ("？", "?", "谜", "诡异", "违和", "不对劲", "秘密", "隐藏"),
    "reversal": ("竟然", "原来", "居然", "不料", "谁知", "其实"),
    "expectation": ("即将", "明天", "下一步", "很快", "随后", "等待"),
}


class FanqieBestsellerFetcher:
    """番茄榜单抓取器。

    用法：
        fetcher = FanqieBestsellerFetcher()
        snapshots = fetcher.fetch_top50_all_lists()
        vector = fetcher.build_feature_vector(snapshots)
    """

    def __init__(
        self,
        base_url: str = "https://novelcatch.com",
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    # ------------------------------------------------------------------
    # 抓取
    # ------------------------------------------------------------------
    def fetch_rank(
        self,
        gender: str = "m",
        list_name: str = "read",
        category: str = "all",
        limit: int = 50,
    ) -> BestsellerSnapshot:
        """抓取单个榜单的 TOP50。"""
        url = f"{self.base_url}/api/rank"
        params = {"gender": gender, "list": list_name, "category": category}
        try:
            with httpx.Client(timeout=self.timeout, headers={"User-Agent": "TameInk/0.1"}) as client:
                response = client.get(url, params=params)
                response.raise_for_status()
                payload: dict[str, Any] = response.json()
        except httpx.HTTPError as error:
            raise RuntimeError(f"FANQIE_FETCH_FAILED: {error}") from error
        scan_date = str(payload.get("scanDate", ""))
        rows = payload.get("rows") or []
        if not isinstance(rows, list):
            rows = []
        entries: list[BestsellerEntry] = []
        for row in rows[:limit]:
            entry = self._parse_entry(row, gender, list_name)
            if entry is not None:
                entries.append(entry)
        return BestsellerSnapshot(
            scan_date=scan_date,
            list_name=list_name,
            gender=gender,  # type: ignore[arg-type]
            category=category,
            total=len(entries),
            entries=entries,
        )

    def fetch_top50_all_lists(self) -> list[BestsellerSnapshot]:
        """抓取 4 个榜单的 TOP50。"""
        snapshots: list[BestsellerSnapshot] = []
        for gender, list_name, _label in _RANK_LISTS:
            snapshot = self.fetch_rank(gender=gender, list_name=list_name)
            snapshots.append(snapshot)
        return snapshots

    # ------------------------------------------------------------------
    # 解析
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_entry(
        row: dict[str, Any],
        gender: str,
        list_name: str,
    ) -> BestsellerEntry | None:
        """解析单行 JSON 为 BestsellerEntry。字段缺失时返回 None。"""
        try:
            return BestsellerEntry(
                book_id=str(row.get("book_id", "")),
                book_name=str(row.get("book_name", "")),
                author=str(row.get("author", "")),
                word_count=int(row.get("word_count", 0) or 0),
                category=str(row.get("category", "")),
                category_id=int(row.get("category_id", 0) or 0),
                gender=gender,  # type: ignore[arg-type]
                status=str(row.get("status", "")),
                score=float(row.get("score", 0) or 0),
                rank=int(row.get("rank", 0) or 0),
                dissected=bool(row.get("dissected", False)),
                logline=str(row.get("logline", "") or ""),
                premise=str(row.get("premise", "") or ""),
                llm_tags=list(row.get("llmTags", []) or []),
                platform_tags=list(row.get("platformTags", []) or []),
                list_name=list_name,
            )
        except (ValueError, TypeError):
            return None

    # ------------------------------------------------------------------
    # 开篇钩子类型分类（仅用公开 metadata，不抓原文）
    # ------------------------------------------------------------------
    @staticmethod
    def classify_opening_hook(entry: BestsellerEntry) -> str:
        """基于 logline + premise 做开篇钩子类型分类。

        返回 conflict / suspense / reversal / expectation / unknown。
        不抓取小说正文，仅用 novelcatch 公开的 metadata 字段。
        """
        text = f"{entry.logline} {entry.premise}"
        if not text.strip():
            return "unknown"
        # 按优先级匹配：conflict > suspense > reversal > expectation
        for hook_type, keywords in _OPENING_HOOK_KEYWORDS.items():
            if any(kw in text for kw in keywords):
                return hook_type
        return "unknown"

    # ------------------------------------------------------------------
    # 特征向量构建
    # ------------------------------------------------------------------
    def build_feature_vector(
        self,
        snapshots: list[BestsellerSnapshot],
    ) -> FeatureVector:
        """聚合多榜去重后的 TOP50，构建特征向量。"""
        # 按 book_id 去重，保留 rank 最小（排名最高）的条目
        deduped: dict[str, BestsellerEntry] = {}
        scan_date = ""
        source_lists: list[str] = []
        for snapshot in snapshots:
            if not scan_date:
                scan_date = snapshot.scan_date
            if snapshot.list_name and snapshot.list_name not in source_lists:
                source_lists.append(snapshot.list_name)
            for entry in snapshot.entries:
                existing = deduped.get(entry.book_id)
                if existing is None or entry.rank < existing.rank:
                    deduped[entry.book_id] = entry
        entries = list(deduped.values())
        total = len(entries)
        if total == 0:
            return FeatureVector(
                scan_date=scan_date,
                total_books=0,
                word_count_stats=WordCountStats(median=0, p25=0, p75=0, mean=0.0),
                source_lists=source_lists,
            )
        # 题材分布
        genre_distribution: dict[str, int] = {}
        for entry in entries:
            genre = entry.category or "未知"
            genre_distribution[genre] = genre_distribution.get(genre, 0) + 1
        # 字数分布
        word_counts = sorted(entry.word_count for entry in entries)
        word_count_stats = WordCountStats(
            median=self._percentile(word_counts, 50),
            p25=self._percentile(word_counts, 25),
            p75=self._percentile(word_counts, 75),
            mean=round(sum(word_counts) / total, 1),
        )
        # 钩子类型分布
        hook_type_distribution: dict[str, int] = {}
        for entry in entries:
            hook_type = self.classify_opening_hook(entry)
            hook_type_distribution[hook_type] = hook_type_distribution.get(hook_type, 0) + 1
        # top 题材（前 5）
        top_genres = [
            genre
            for genre, _ in sorted(
                genre_distribution.items(), key=lambda item: item[1], reverse=True
            )[:5]
        ]
        # 主流钩子类型
        dominant_hook_type = max(
            hook_type_distribution.items(), key=lambda item: item[1]
        )[0] if hook_type_distribution else "unknown"
        return FeatureVector(
            scan_date=scan_date,
            total_books=total,
            genre_distribution=genre_distribution,
            word_count_stats=word_count_stats,
            hook_type_distribution=hook_type_distribution,
            top_genres=top_genres,
            dominant_hook_type=dominant_hook_type,
            source_lists=source_lists,
        )

    @staticmethod
    def _percentile(sorted_values: list[int], pct: int) -> int:
        """计算分位数（最近秩法）。"""
        if not sorted_values:
            return 0
        n = len(sorted_values)
        if n == 1:
            return sorted_values[0]
        # 最近秩法：index = ceil(pct/100 * n) - 1
        import math
        index = max(0, min(n - 1, math.ceil(pct / 100 * n) - 1))
        return sorted_values[index]
