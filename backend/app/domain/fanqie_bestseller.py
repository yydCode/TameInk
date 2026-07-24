"""番茄小说榜单数据模型。

封装从 novelcatch.com 公开 JSON API 抓取的榜单条目，以及聚合后的
“番茄爆款特征向量”，供 RetentionAuditor 对照打分。
"""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FanqieModel(BaseModel):
    """番茄榜单数据模型基类，与 CommercialModel 风格一致。"""

    model_config = ConfigDict(extra="forbid", strict=True)


class BestsellerEntry(FanqieModel):
    """单本榜单条目——对应 novelcatch /api/rank 响应中的一行。"""

    book_id: str = Field(min_length=1)
    book_name: str = Field(min_length=1)
    author: str
    word_count: int = Field(ge=0)
    category: str
    category_id: int
    gender: Literal["m", "f"]
    status: str
    score: float = Field(ge=0)
    rank: int = Field(ge=1)
    dissected: bool = False
    logline: str = ""
    premise: str = ""
    llm_tags: list[str] = Field(default_factory=list)
    platform_tags: list[str] = Field(default_factory=list)
    list_name: str = Field(default="")


class BestsellerSnapshot(FanqieModel):
    """单次榜单扫描结果——一个榜（如“男频阅读榜”）的 TOP50。"""

    scan_date: str = Field(description="扫描日期 YYYY-MM-DD")
    list_name: str
    gender: Literal["m", "f"]
    category: str
    total: int = Field(ge=0)
    entries: list[BestsellerEntry] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_total(self) -> Self:
        if self.total != len(self.entries):
            raise ValueError("BESTSELLER_SNAPSHOT_TOTAL_MISMATCH")
        return self


class WordCountStats(FanqieModel):
    """总书字数分布统计。"""

    median: int
    p25: int
    p75: int
    mean: float


class FeatureVector(FanqieModel):
    """番茄爆款特征向量——TOP50 聚合后供 RetentionAuditor 对照。

    所有字段都来自公开榜单 metadata 聚合，不包含任何小说原文。
    """

    scan_date: str
    total_books: int = Field(ge=0)
    genre_distribution: dict[str, int] = Field(default_factory=dict)
    word_count_stats: WordCountStats
    hook_type_distribution: dict[str, int] = Field(default_factory=dict)
    top_genres: list[str] = Field(default_factory=list)
    dominant_hook_type: str = "unknown"
    source_lists: list[str] = Field(default_factory=list)
