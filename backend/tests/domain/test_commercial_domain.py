import pytest
from pydantic import ValidationError

from app.domain.commercial import (
    CommercialMetrics,
    CommercialObservation,
    CommercialProfile,
)


def profile_payload() -> dict[str, object]:
    return {
        "platform": "fanqie",
        "monetization": "free_ad",
        "target_reader": "喜欢快节奏都市异能的年轻读者",
        "core_fantasy": "普通人获得识破谎言的能力并逆转人生",
        "differentiator": "能力每次使用都会暴露一段自身秘密",
        "emotional_payoffs": ["识破骗局", "身份逆袭"],
        "opening_promise": "第一章完成能力觉醒并付出首次代价",
        "first_thirty_chapter_promise": "完成三次阶梯式逆袭并揭示幕后组织",
        "update_cadence": "每日两章，每章 2200 字",
        "title_candidates": ["我能听见所有谎言", "真话代价"],
        "synopsis": "主角能识破所有谎言，却必须用自己的秘密交换答案。",
        "minimum_commercial_score": 75,
    }


def test_commercial_profile_validates_platform_and_unique_lists() -> None:
    profile = CommercialProfile.model_validate(profile_payload())
    assert profile.platform == "fanqie"
    assert profile.targets.click_through_rate is None

    invalid = {**profile_payload(), "platform": "custom"}
    with pytest.raises(ValidationError, match="CUSTOM_PLATFORM_REQUIRED"):
        CommercialProfile.model_validate(invalid)

    duplicated = {**profile_payload(), "title_candidates": ["同名", "同名"]}
    with pytest.raises(ValidationError, match="COMMERCIAL_LIST_INVALID"):
        CommercialProfile.model_validate(duplicated)


def test_commercial_metrics_are_computed_from_raw_counts() -> None:
    records = [
        CommercialObservation(
            id="one",
            observed_at="2026-07-15",
            impressions=1000,
            opens=200,
            chapter_one_completions=150,
            chapter_three_completions=100,
            follows=40,
            read_minutes=1800,
            revenue_cents=2500,
        ),
        CommercialObservation(
            id="two",
            observed_at="2026-07-16",
            impressions=500,
            opens=100,
            chapter_one_completions=70,
            chapter_three_completions=50,
            follows=20,
            read_minutes=900,
            revenue_cents=1500,
        ),
    ]

    metrics = CommercialMetrics.from_observations(records)

    assert metrics.click_through_rate == 0.2
    assert metrics.chapter_one_completion_rate == 0.7333
    assert metrics.chapter_three_retention_rate == 0.5
    assert metrics.follow_rate == 0.2
    assert metrics.average_read_minutes_per_open == 9
    assert metrics.revenue_per_thousand_opens_yuan == 133.33


def test_observation_rejects_impossible_funnel() -> None:
    with pytest.raises(ValidationError, match="OBSERVATION_FUNNEL_INVALID"):
        CommercialObservation(
            id="bad",
            observed_at="2026-07-15",
            impressions=100,
            opens=80,
            chapter_one_completions=40,
            chapter_three_completions=50,
            follows=10,
            read_minutes=100,
            revenue_cents=0,
        )


def test_observation_rejects_nonexistent_calendar_date() -> None:
    with pytest.raises(ValidationError, match="OBSERVATION_DATE_INVALID"):
        CommercialObservation(
            id="bad-date",
            observed_at="2026-02-31",
            impressions=100,
            opens=80,
            chapter_one_completions=40,
            chapter_three_completions=20,
            follows=10,
            read_minutes=100,
            revenue_cents=0,
        )
