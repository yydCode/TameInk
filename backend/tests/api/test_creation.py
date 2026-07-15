from pathlib import Path

from fastapi.testclient import TestClient

from app.agents.schemas import ChapterDraft, ChapterPlan, Outline, StorySetting
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


def test_agent_generation_routes_store_candidate_drafts(
    tmp_path: Path, monkeypatch
) -> None:
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

    monkeypatch.setattr("app.api.creation._runner", lambda project_id, request: FakeRunner())
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

    assert generated_setting.json()["content"] == "# 新设定"
    assert generated_outline.status_code == 201
    assert generated_outline.json()["content"] == "# 全书大纲"
    assert generated_outline.json()["task"]["status"] == "awaiting_approval"


def test_agent_chapter_route_runs_planner_writer_and_auditors(
    tmp_path: Path, monkeypatch
) -> None:
    reference = [{"path": "canon/outline.md", "location": "full document", "quote": "大纲"}]

    class FakeRunner:
        def invoke(self, agent: str, payload: dict[str, object]) -> object:
            if agent == "ChapterPlanner":
                return ChapterPlan(
                    id="plan-1", chapter_id="1", content="章节计划", references=reference
                )
            if agent == "DraftWriter" and "draft" not in payload:
                return ChapterDraft(
                    id="draft-1", chapter_id="1", markdown="生成正文", references=reference
                )
            if agent in {"ContinuityAuditor", "StyleCritic"}:
                return []
            return []

    monkeypatch.setattr("app.api.creation._runner", lambda project_id, request: FakeRunner())
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
        client.post(
            f"/api/projects/chapter-book/setting/{created['task']['id']}/approve"
        )
        outline = client.post(
            "/api/projects/chapter-book/design/outline", json={"content": "大纲"}
        ).json()
        client.post(f"/api/projects/chapter-book/design/outline/{outline['id']}/approve")
        volume = client.post(
            "/api/projects/chapter-book/design/volumes/1", json={"content": "分卷"}
        ).json()
        client.post(
            f"/api/projects/chapter-book/design/volumes/1/{volume['id']}/approve"
        )
        generated = client.post(
            "/api/projects/chapter-book/design/agent/chapters/1",
            json={"instruction": "生成第一章"},
        )

    assert generated.status_code == 201
    assert generated.json()["content"] == "生成正文"
    assert generated.json()["task"]["status"] == "awaiting_approval"


def test_agent_generation_returns_stable_configuration_error(
    tmp_path: Path, monkeypatch
) -> None:
    def missing_key(project_id: str, request: object) -> object:
        raise ModelConfigurationError("MODEL_API_KEY_MISSING")

    monkeypatch.setattr("app.api.creation._runner", missing_key)
    with TestClient(create_app(tmp_path)) as client:
        response = client.post(
            "/api/projects/missing/design/agent/outline",
            json={"instruction": "生成大纲"},
        )

    assert response.status_code == 400
    assert response.json() == {
        "detail": {
            "code": "MODEL_API_KEY_MISSING",
            "message": "agent configuration invalid",
        }
    }


def test_agent_generation_hides_provider_error_details(tmp_path: Path, monkeypatch) -> None:
    class FailedRunner:
        def invoke(self, agent: str, payload: dict[str, object]) -> object:
            raise RuntimeError("provider response contained sensitive detail")

    monkeypatch.setattr("app.api.creation._runner", lambda project_id, request: FailedRunner())
    with TestClient(create_app(tmp_path)) as client:
        response = client.post(
            "/api/projects/failed/design/agent/outline",
            json={"instruction": "生成大纲"},
        )

    assert response.status_code == 502
    assert response.json() == {
        "detail": {"code": "AGENT_RUN_FAILED", "message": "agent generation failed"}
    }
