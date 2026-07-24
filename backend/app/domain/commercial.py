from datetime import date
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CommercialModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class CommercialTargets(CommercialModel):
    click_through_rate: float | None = Field(default=None, ge=0, le=1)
    chapter_one_completion_rate: float | None = Field(default=None, ge=0, le=1)
    chapter_three_retention_rate: float | None = Field(default=None, ge=0, le=1)
    follow_rate: float | None = Field(default=None, ge=0, le=1)
    revenue_per_thousand_opens_yuan: float | None = Field(default=None, ge=0)


class PlatformPacing(CommercialModel):
    """平台商业节奏配置——番茄/起点等平台的开篇钩子和章节节奏铁律。"""

    chapter_word_count: int = Field(default=2500, ge=1000, le=5000)
    opening_hook_lines: int = Field(default=7, ge=3, le=20)
    scenes_per_chapter: int = Field(default=1, ge=1, le=3)
    small_climax_every: int = Field(default=3, ge=1, le=10)
    big_climax_every: int = Field(default=10, ge=5, le=30)
    opening_hook_style: Literal["conflict", "scene", "dialogue"] = "conflict"
    chapter_end_cliffhanger: bool = True

    @classmethod
    def for_platform(cls, platform: str) -> "PlatformPacing":
        if platform == "fanqie":
            return cls(
                chapter_word_count=2500,
                opening_hook_lines=7,
                scenes_per_chapter=1,
                small_climax_every=3,
                big_climax_every=10,
                opening_hook_style="conflict",
                chapter_end_cliffhanger=True,
            )
        if platform == "qidian":
            return cls(
                chapter_word_count=3000,
                opening_hook_lines=15,
                scenes_per_chapter=2,
                small_climax_every=5,
                big_climax_every=15,
                opening_hook_style="scene",
                chapter_end_cliffhanger=True,
            )
        return cls()


class CommercialProfile(CommercialModel):
    schema_version: Literal[1] = 1
    platform: Literal["fanqie", "qidian", "jinjiang", "custom"]
    custom_platform: str | None = None
    monetization: Literal["free_ad", "paid_subscription", "custom"]
    target_reader: str
    core_fantasy: str
    differentiator: str
    emotional_payoffs: list[str] = Field(min_length=1, max_length=6)
    opening_promise: str
    first_thirty_chapter_promise: str
    update_cadence: str
    title_candidates: list[str] = Field(min_length=1, max_length=5)
    synopsis: str
    comparable_titles: list[str] = Field(default_factory=list, max_length=5)
    minimum_commercial_score: int = Field(default=70, ge=0, le=100)
    targets: CommercialTargets = Field(default_factory=CommercialTargets)
    platform_pacing: PlatformPacing | None = None

    @model_validator(mode="after")
    def ensure_platform_pacing(self) -> Self:
        if self.platform_pacing is None:
            self.platform_pacing = PlatformPacing.for_platform(self.platform)
        return self

    @field_validator(
        "target_reader",
        "core_fantasy",
        "differentiator",
        "opening_promise",
        "first_thirty_chapter_promise",
        "update_cadence",
        "synopsis",
    )
    @classmethod
    def validate_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("COMMERCIAL_TEXT_EMPTY")
        return stripped

    @field_validator("emotional_payoffs", "title_candidates", "comparable_titles")
    @classmethod
    def validate_text_list(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if any(not value for value in normalized) or len(normalized) != len(set(normalized)):
            raise ValueError("COMMERCIAL_LIST_INVALID")
        return normalized

    @model_validator(mode="after")
    def validate_platform(self) -> Self:
        if self.platform == "custom":
            if self.custom_platform is None or not self.custom_platform.strip():
                raise ValueError("CUSTOM_PLATFORM_REQUIRED")
            self.custom_platform = self.custom_platform.strip()
        elif self.custom_platform is not None:
            raise ValueError("CUSTOM_PLATFORM_FORBIDDEN")
        return self


class CommercialObservationInput(CommercialModel):
    observed_at: str
    impressions: int = Field(gt=0)
    opens: int = Field(gt=0)
    chapter_one_completions: int = Field(ge=0)
    chapter_three_completions: int = Field(ge=0)
    follows: int = Field(ge=0)
    read_minutes: int = Field(ge=0)
    revenue_cents: int = Field(ge=0)

    @field_validator("observed_at")
    @classmethod
    def validate_observed_at(cls, value: str) -> str:
        parts = value.split("-")
        if len(parts) != 3 or [len(part) for part in parts] != [4, 2, 2]:
            raise ValueError("OBSERVATION_DATE_INVALID")
        try:
            year, month, day = (int(part) for part in parts)
            date(year, month, day)
        except ValueError as error:
            raise ValueError("OBSERVATION_DATE_INVALID") from error
        if not 2000 <= year <= 2100:
            raise ValueError("OBSERVATION_DATE_INVALID")
        return value

    @model_validator(mode="after")
    def validate_funnel(self) -> Self:
        if self.opens > self.impressions:
            raise ValueError("OBSERVATION_FUNNEL_INVALID")
        if self.chapter_one_completions > self.opens:
            raise ValueError("OBSERVATION_FUNNEL_INVALID")
        if self.chapter_three_completions > self.chapter_one_completions:
            raise ValueError("OBSERVATION_FUNNEL_INVALID")
        if self.follows > self.opens:
            raise ValueError("OBSERVATION_FUNNEL_INVALID")
        return self


class CommercialObservation(CommercialObservationInput):
    id: str


class CommercialMetrics(CommercialModel):
    observations: int
    impressions: int
    opens: int
    chapter_one_completions: int
    chapter_three_completions: int
    follows: int
    read_minutes: int
    revenue_cents: int
    click_through_rate: float
    chapter_one_completion_rate: float
    chapter_three_retention_rate: float
    follow_rate: float
    average_read_minutes_per_open: float
    revenue_per_thousand_opens_yuan: float

    @classmethod
    def from_observations(cls, records: list[CommercialObservation]) -> "CommercialMetrics":
        totals = {
            field: sum(getattr(record, field) for record in records)
            for field in (
                "impressions",
                "opens",
                "chapter_one_completions",
                "chapter_three_completions",
                "follows",
                "read_minutes",
                "revenue_cents",
            )
        }
        impressions = totals["impressions"]
        opens = totals["opens"]

        def rate(numerator: int, denominator: int) -> float:
            return round(numerator / denominator, 4) if denominator else 0

        return cls(
            observations=len(records),
            **totals,
            click_through_rate=rate(opens, impressions),
            chapter_one_completion_rate=rate(totals["chapter_one_completions"], opens),
            chapter_three_retention_rate=rate(totals["chapter_three_completions"], opens),
            follow_rate=rate(totals["follows"], opens),
            average_read_minutes_per_open=rate(totals["read_minutes"], opens),
            revenue_per_thousand_opens_yuan=round(
                totals["revenue_cents"] * 10 / opens, 2
            )
            if opens
            else 0,
        )
