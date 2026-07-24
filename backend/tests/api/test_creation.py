from pathlib import Path

from fastapi.testclient import TestClient

from app.agents.schemas import (
    ChapterDraft,
    ChapterPlan,
    CommercialDimensionScore,
    CommercialReport,
    MemoryCuration,
    Outline,
    StorySetting,
)
from app.infrastructure.model import ModelConfigurationError
from app.main import create_app


def test_creation_outline_draft_and_approval(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path)) as client:
        created = client.post(
            "/api/projects",
            json={
                "project_id": "night-01",
                "title": "长夜",
                "genre": "悬疑",
                "target_words": 1,
                "constraints": "x",
                "setting_draft": "draft",
            },
        )
        client.post(f"/api/projects/night-01/setting/{created.json()['task']['id']}/approve")
        task = client.post("/api/projects/night-01/design/outline", json={"content": "全书大纲"})
        approved = client.post(f"/api/projects/night-01/design/outline/{task.json()['id']}/approve")

    assert task.status_code == 201
    assert approved.json()["status"] == "completed"


def test_agent_generation_routes_store_candidate_drafts(tmp_path: Path, monkeypatch) -> None:
    reference = [{"path": "project.yaml", "location": "full document", "quote": "project"}]

    class FakeRunner:
        def invoke(self, agent: str, payload: dict[str, object]) -> object:
            if agent == "StoryArchitect":
                return StorySetting(
                    id="setting-1", title="新设定", content="# 新设定", references=reference
                )
            return Outline(
                id="outline-1",
                kind="book",
                title="全书大纲",
                content="# 全书大纲",
                references=reference,
            )

    monkeypatch.setattr(
        "app.infrastructure.jobs.create_runner", lambda *args, **kwargs: FakeRunner()
    )
    with TestClient(create_app(tmp_path)) as client:
        created = client.post(
            "/api/projects",
            json={
                "project_id": "agent-book",
                "title": "长夜",
                "genre": "悬疑",
                "target_words": 200000,
                "constraints": "第三人称",
                "setting_draft": "旧设定",
            },
        ).json()
        task_id = created["task"]["id"]
        generated_setting = client.post(
            f"/api/projects/agent-book/design/agent/setting/{task_id}",
            json={"instruction": "重新设计设定"},
        )
        client.post(f"/api/projects/agent-book/setting/{task_id}/approve")
        generated_outline = client.post(
            "/api/projects/agent-book/design/agent/outline",
            json={"instruction": "生成大纲"},
        )

    assert generated_setting.status_code == 202
    assert generated_setting.json()["status"] == "awaiting_approval"
    assert generated_outline.status_code == 202
    assert generated_outline.json()["status"] == "awaiting_approval"


def test_agent_chapter_route_runs_planner_writer_and_auditors(tmp_path: Path, monkeypatch) -> None:
    reference = [{"path": "canon/outline.md", "location": "full document", "quote": "大纲"}]
    dimensions = [
        "opening_urgency",
        "reader_promise",
        "emotional_payoff",
        "conflict_escalation",
        "information_clarity",
        "chapter_hook",
        "differentiation",
    ]

    class FakeRunner:
        def invoke(self, agent: str, payload: dict[str, object]) -> object:
            if agent == "ChapterPlanner":
                return ChapterPlan(
                    id="plan-1",
                    chapter_id="1",
                    content="章节计划",
                    context_intent={"keywords": ["生成正文"]},
                    references=reference,
                    chapter_end_hook="章末钩子",
                )
            if agent == "DraftWriter" and "draft" not in payload:
                return ChapterDraft(
                    id="draft-1", chapter_id="1", markdown="生成正文", references=reference
                )
            if agent in {"ContinuityAuditor", "StyleCritic"}:
                return []
            if agent == "RetentionAuditor":
                return CommercialReport(
                    id="commercial-1",
                    chapter_id="1",
                    total_score=80,
                    recommendation="pass",
                    dimensions=[
                        CommercialDimensionScore(dimension=dimension, score=80, reason="符合承诺")
                        for dimension in dimensions
                    ],
                    issues=[],
                    references=reference,
                )
            if agent == "MemoryCurator":
                return MemoryCuration(id="memory-1", updates=[], references=reference)
            raise AssertionError(agent)

    monkeypatch.setattr(
        "app.infrastructure.jobs.create_runner", lambda *args, **kwargs: FakeRunner()
    )
    with TestClient(create_app(tmp_path)) as client:
        created = client.post(
            "/api/projects",
            json={
                "project_id": "chapter-book",
                "title": "长夜",
                "genre": "悬疑",
                "target_words": 200000,
                "constraints": "第三人称",
                "setting_draft": "设定",
            },
        ).json()
        client.post(f"/api/projects/chapter-book/setting/{created['task']['id']}/approve")
        commercial = client.post(
            "/api/projects/chapter-book/commercial/draft",
            json={
                "platform": "fanqie",
                "monetization": "free_ad",
                "target_reader": "悬疑读者",
                "core_fantasy": "破解不可能犯罪",
                "differentiator": "线索反向误导",
                "emotional_payoffs": ["识破骗局"],
                "opening_promise": "第一章发生命案",
                "first_thirty_chapter_promise": "破解主案",
                "update_cadence": "每日两章",
                "title_candidates": ["长夜"],
                "synopsis": "侦探破解密室命案。",
            },
        ).json()
        client.post(f"/api/projects/chapter-book/commercial/draft/{commercial['id']}/approve")
        outline = client.post(
            "/api/projects/chapter-book/design/outline", json={"content": "大纲"}
        ).json()
        client.post(f"/api/projects/chapter-book/design/outline/{outline['id']}/approve")
        volume = client.post(
            "/api/projects/chapter-book/design/volumes/1", json={"content": "分卷"}
        ).json()
        client.post(f"/api/projects/chapter-book/design/volumes/1/{volume['id']}/approve")
        generated = client.post(
            "/api/projects/chapter-book/design/agent/chapters/1",
            json={"instruction": "生成第一章"},
        )
        task_id = generated.json()["id"]
        chapter_content = client.get(
            f"/api/projects/chapter-book/drafts/{task_id}", params={"path": "chapter.md"}
        ).json()["content"]
        commercial_score = client.get(
            f"/api/projects/chapter-book/commercial/reports/{task_id}"
        ).json()["commercial_report"]["total_score"]

    assert generated.status_code == 202
    assert generated.json()["status"] == "awaiting_approval"
    assert chapter_content == "生成正文"
    assert commercial_score == 80


def test_agent_generation_returns_stable_configuration_error(tmp_path: Path, monkeypatch) -> None:
    def missing_key(*args: object, **kwargs: object) -> object:
        raise ModelConfigurationError("MODEL_API_KEY_MISSING")

    monkeypatch.setattr("app.infrastructure.jobs.create_runner", missing_key)
    with TestClient(create_app(tmp_path)) as client:
        created = client.post(
            "/api/projects",
            json={
                "project_id": "missing",
                "title": "缺少配置",
                "genre": "悬疑",
                "target_words": 1000,
                "constraints": "第三人称",
                "setting_draft": "设定",
            },
        ).json()
        client.post(f"/api/projects/missing/setting/{created['task']['id']}/approve")
        response = client.post(
            "/api/projects/missing/design/agent/outline",
            json={"instruction": "生成大纲"},
        )

    assert response.status_code == 202
    assert response.json()["status"] == "failed"
    assert response.json()["error_code"] == "MODEL_API_KEY_MISSING"
    assert "sensitive" not in response.text


def test_agent_generation_hides_provider_error_details(tmp_path: Path, monkeypatch) -> None:
    class FailedRunner:
        def invoke(self, agent: str, payload: dict[str, object]) -> object:
            raise RuntimeError("provider response contained sensitive detail")

    monkeypatch.setattr(
        "app.infrastructure.jobs.create_runner", lambda *args, **kwargs: FailedRunner()
    )
    with TestClient(create_app(tmp_path)) as client:
        created = client.post(
            "/api/projects",
            json={
                "project_id": "failed",
                "title": "失败任务",
                "genre": "悬疑",
                "target_words": 1000,
                "constraints": "第三人称",
                "setting_draft": "设定",
            },
        ).json()
        client.post(f"/api/projects/failed/setting/{created['task']['id']}/approve")
        response = client.post(
            "/api/projects/failed/design/agent/outline",
            json={"instruction": "生成大纲"},
        )

    assert response.status_code == 202
    assert response.json()["status"] == "failed"
    assert response.json()["error_code"] == "RuntimeError"
    assert "provider response" not in response.text


def test_failed_agent_task_retries_as_new_linked_task(tmp_path: Path, monkeypatch) -> None:
    class FailedRunner:
        def invoke(self, agent: str, payload: dict[str, object]) -> object:
            raise RuntimeError("private provider detail")

    reference = [{"path": "project.yaml", "location": "full document", "quote": "project"}]

    class SuccessfulRunner:
        def invoke(self, agent: str, payload: dict[str, object]) -> object:
            return Outline(
                id="outline-retry",
                kind="book",
                title="重试大纲",
                content="# 重试成功",
                references=reference,
            )

    monkeypatch.setattr(
        "app.infrastructure.jobs.create_runner", lambda *args, **kwargs: FailedRunner()
    )
    with TestClient(create_app(tmp_path)) as client:
        created = client.post(
            "/api/projects",
            json={
                "project_id": "retry-book",
                "title": "重试书",
                "genre": "悬疑",
                "target_words": 1000,
                "constraints": "第三人称",
                "setting_draft": "设定",
            },
        ).json()
        client.post(f"/api/projects/retry-book/setting/{created['task']['id']}/approve")
        failed = client.post(
            "/api/projects/retry-book/design/agent/outline",
            json={"instruction": "生成大纲"},
        ).json()
        monkeypatch.setattr(
            "app.infrastructure.jobs.create_runner",
            lambda *args, **kwargs: SuccessfulRunner(),
        )
        retried = client.post(f"/api/projects/retry-book/tasks/{failed['id']}/retry")

    assert failed["status"] == "failed"
    assert retried.status_code == 202
    assert retried.json()["status"] == "awaiting_approval"
    assert retried.json()["retry_of_task_id"] == failed["id"]
    assert retried.json()["id"] != failed["id"]
