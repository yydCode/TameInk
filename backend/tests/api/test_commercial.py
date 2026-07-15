from pathlib import Path

from fastapi.testclient import TestClient

from app.agents.schemas import CommercialStrategy
from app.domain.commercial import CommercialProfile
from app.main import create_app


def commercial_profile() -> dict[str, object]:
    return {
        "schema_version": 1,
        "platform": "fanqie",
        "custom_platform": None,
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
        "comparable_titles": [],
        "minimum_commercial_score": 75,
        "targets": {
            "click_through_rate": None,
            "chapter_one_completion_rate": None,
            "chapter_three_retention_rate": None,
            "follow_rate": None,
            "revenue_per_thousand_opens_yuan": None,
        },
    }


def create_project(client: TestClient) -> str:
    created = client.post(
        "/api/projects",
        json={
            "project_id": "commercial-book",
            "title": "真话代价",
            "genre": "都市异能",
            "target_words": 800000,
            "constraints": "第三人称限知",
            "setting_draft": "故事设定",
        },
    ).json()
    task_id = str(created["task"]["id"])
    approved = client.post(
        f"/api/projects/commercial-book/setting/{task_id}/approve"
    )
    assert approved.status_code == 200
    return task_id


def test_commercial_profile_requires_approval_and_records_metrics(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path)) as client:
        create_project(client)
        assert client.get("/api/projects/commercial-book/commercial/profile").json() is None

        created = client.post(
            "/api/projects/commercial-book/commercial/draft",
            json=commercial_profile(),
        )
        assert created.status_code == 201
        task_id = created.json()["id"]
        assert client.get("/api/projects/commercial-book/commercial/profile").json() is None

        edited = {**commercial_profile(), "minimum_commercial_score": 80}
        updated = client.put(
            f"/api/projects/commercial-book/commercial/draft/{task_id}",
            json=edited,
        )
        assert updated.json()["minimum_commercial_score"] == 80

        approved = client.post(
            f"/api/projects/commercial-book/commercial/draft/{task_id}/approve"
        )
        profile = client.get("/api/projects/commercial-book/commercial/profile")

        observation = client.post(
            "/api/projects/commercial-book/commercial/observations",
            json={
                "observed_at": "2026-07-15",
                "impressions": 1000,
                "opens": 200,
                "chapter_one_completions": 140,
                "chapter_three_completions": 90,
                "follows": 30,
                "read_minutes": 1600,
                "revenue_cents": 2500,
            },
        )
        metrics = client.get("/api/projects/commercial-book/commercial/metrics")

    assert approved.json()["status"] == "completed"
    assert profile.json()["minimum_commercial_score"] == 80
    assert observation.status_code == 201
    assert metrics.json()["click_through_rate"] == 0.2
    assert metrics.json()["chapter_three_retention_rate"] == 0.45
    assert metrics.json()["revenue_per_thousand_opens_yuan"] == 125


def test_market_strategist_creates_an_unapproved_candidate(
    tmp_path: Path, monkeypatch
) -> None:
    reference = [{"path": "project.yaml", "location": "full document", "quote": "project"}]

    class FakeRunner:
        def invoke(self, agent: str, payload: dict[str, object]) -> object:
            assert agent == "MarketStrategist"
            assert payload["observed_metrics"] == {
                "observations": 0,
                "impressions": 0,
                "opens": 0,
                "chapter_one_completions": 0,
                "chapter_three_completions": 0,
                "follows": 0,
                "read_minutes": 0,
                "revenue_cents": 0,
                "click_through_rate": 0.0,
                "chapter_one_completion_rate": 0.0,
                "chapter_three_retention_rate": 0.0,
                "follow_rate": 0.0,
                "average_read_minutes_per_open": 0.0,
                "revenue_per_thousand_opens_yuan": 0.0,
            }
            return CommercialStrategy(
                id="strategy-1",
                profile=CommercialProfile.model_validate(commercial_profile()),
                references=reference,
            )

    monkeypatch.setattr("app.api.commercial._runner", lambda project_id, request: FakeRunner())
    with TestClient(create_app(tmp_path)) as client:
        create_project(client)
        generated = client.post(
            "/api/projects/commercial-book/commercial/agent",
            json={
                "platform": "fanqie",
                "monetization": "free_ad",
                "target_reader": "都市异能读者",
                "core_fantasy": "识破谎言并逆袭",
                "differentiator": "能力需要交换秘密",
                "comparable_titles": [],
                "instruction": "生成可验证的商业定位",
            },
        )
        formal_before = client.get(
            "/api/projects/commercial-book/commercial/profile"
        )
        task_id = generated.json()["task"]["id"]
        client.post(
            f"/api/projects/commercial-book/commercial/draft/{task_id}/approve"
        )
        formal_after = client.get(
            "/api/projects/commercial-book/commercial/profile"
        )

    assert generated.status_code == 201
    assert generated.json()["profile"]["platform"] == "fanqie"
    assert formal_before.json() is None
    assert formal_after.json()["core_fantasy"] == "普通人获得识破谎言的能力并逆转人生"
