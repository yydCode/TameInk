from datetime import UTC, datetime

import yaml
from fastapi.testclient import TestClient

from app.agents.schemas import SkillExecutionContract
from app.domain.creation import CreativeBrief
from app.domain.revision import RevisionWrite
from app.main import create_app
from app.repositories.canon import CanonRepository
from app.repositories.database import DatabaseRepository
from app.repositories.revisions import RevisionRepository
from app.repositories.tasks import TasksRepository
from app.workflows.creative import CreativeService
from app.workflows.task_service import TaskService


class RecordedQueue:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, object, dict[str, object]]] = []

    def enqueue(self, project_id, task_id, kind, payload) -> None:
        self.calls.append((project_id, task_id, kind, payload))


def write_brief(workspace, project_id: str) -> None:
    now = datetime.now(UTC)
    brief = CreativeBrief(
        version=1,
        platform="fanqie",
        genre_scope="都市",
        initial_intent="写一个都市成长故事。",
        first_story_goal="完成第一笔交易。",
        constraints=["第三人称"],
        material_boundaries=["仅使用授权素材"],
        created_at=now,
        updated_at=now,
    )
    revisions = RevisionRepository(workspace)
    revisions.confirm(
        project_id,
        RevisionWrite(
            path="commitments/creative-brief.yaml",
            content=yaml.safe_dump(
                brief.model_dump(mode="json"), allow_unicode=True, sort_keys=True
            ),
            message="确认：创作简报 v1",
        ),
        revisions.current_revision(project_id),
    )


def create_project(client: TestClient) -> str:
    response = client.post(
        "/api/projects",
        json={
            "project_id": "creative-book",
            "title": "创作书",
            "genre": "都市",
            "target_words": 100000,
            "constraints": "第三人称",
            "setting_draft": "初始设定",
        },
    )
    assert response.status_code == 201
    return str(response.json()["task"]["id"])


def reader_contract_result() -> SkillExecutionContract:
    return SkillExecutionContract.model_validate(
        {
            "id": "reader-result",
            "skill": "webnovel-design-reader-contract",
            "status": "ready",
            "references": [
                {"path": "project.yaml", "location": "chars:0-1", "quote": "i"}
            ],
            "evidence": [],
            "candidate": {
                "artifact_kind": "reader_contract",
                "summary": "读者契约",
                "payload": {
                    "id": "reader-1",
                    "platform": "fanqie",
                    "channel": "都市",
                    "genre_scope": "都市成长",
                    "target_readers": ["都市读者"],
                    "core_experience": "主动选择改变处境",
                    "protagonist_promise": "每次压力都有行动",
                    "must_payoffs": ["看到选择产生后果"],
                    "forbidden_directions": [],
                    "evidence_refs": [],
                },
            },
            "decision_requests": [],
            "effects": [],
        }
    )


def test_creative_api_queues_skill_and_exposes_next_author_decision(tmp_path) -> None:
    application = create_app(tmp_path)
    queue = RecordedQueue()
    application.state.agent_jobs = queue
    with TestClient(application) as client:
        setting_task_id = create_project(client)
        approved = client.post(f"/api/projects/creative-book/setting/{setting_task_id}/approve")
        assert approved.status_code == 200
        write_brief(application.state.workspace, "creative-book")
        assert client.get("/api/projects/creative-book/creative/next").json()["skill"] == (
            "webnovel-research-genre"
        )
        started = client.post(
            "/api/projects/creative-book/creative/skills",
            json={"skill": "webnovel-design-reader-contract", "payload": {}},
        )
        assert started.status_code == 202
        task_id = started.json()["id"]
        assert queue.calls[0][2].value == "creative_skill"

        workspace = application.state.workspace
        tasks = TaskService(TasksRepository(DatabaseRepository(workspace), "creative-book"))
        tasks.start(task_id)
        CreativeService(workspace).store_skill_result(
            "creative-book", task_id, reader_contract_result()
        )
        artifact = client.get("/api/projects/creative-book/creative/artifacts").json()[0]
        action = client.get("/api/projects/creative-book/creative/next").json()
        assert action["kind"] == "decision"
        assert action["artifact_id"] == artifact["id"]

        confirmed = client.post(
            f"/api/projects/creative-book/creative/artifacts/{artifact['id']}/decisions",
            json={
                "expected_status": "awaiting_approval",
                "action": "accept",
                "effects": [],
                "target_layer": "commitment",
                "formal_path": "commitments/reader-contract.yaml",
            },
        )

    assert confirmed.status_code == 200, confirmed.json()
    assert confirmed.json()["status"] == "completed"


def test_creative_start_creates_only_the_first_research_task(tmp_path) -> None:
    application = create_app(tmp_path)
    queue = RecordedQueue()
    application.state.agent_jobs = queue
    with TestClient(application) as client:
        response = client.post(
            "/api/projects/p0-book/creative/start",
            json={
                "title": "P0 新书",
                "platform": "fanqie",
                "genre_scope": "都市职场成长",
                "initial_intent": "我想写一个都市职场成长故事。",
                "first_story_goal": "主角必须完成第一笔交易。",
                "constraints": ["第三人称限知"],
                "material_boundaries": ["仅使用授权素材"],
            },
        )
        next_action = client.get("/api/projects/p0-book/creative/next")

    assert response.status_code == 201
    assert response.json()["project"]["id"] == "p0-book"
    assert response.json()["task"]["subject_id"] == "webnovel-research-genre"
    brief = CanonRepository(application.state.workspace).read_creative_brief("p0-book")
    assert brief.genre_scope == "都市职场成长"
    assert queue.calls[0][0] == "p0-book"
    assert next_action.json()["kind"] == "wait"


def _story_card_yaml(card_id: str, sequence: int, status: str) -> str:
    return yaml.safe_dump(
        {
            "id": card_id,
            "schema_version": 1,
            "decision_id": "00000000-0000-0000-0000-000000000001",
            "confirmed_by": "author",
            "sequence": sequence,
            "status": status,
            "goal": f"目标{sequence}",
            "motivation": f"动机{sequence}",
            "cycle_input": "低谷",
            "cycle_delta": "达成里程碑",
            "next_affordance": "敌方注意到主角",
        },
        allow_unicode=True,
    )


def _write_card(workspace, project_id: str, card_id: str, sequence: int, status: str) -> None:
    revisions = RevisionRepository(workspace)
    revisions.confirm(
        project_id,
        RevisionWrite(
            path=f"commitments/story-cards/{card_id}.yaml",
            content=_story_card_yaml(card_id, sequence, status),
            message=f"确认：故事卡 {card_id}",
        ),
        revisions.current_revision(project_id),
    )


def test_list_story_cards_returns_all_confirmed(tmp_path) -> None:
    application = create_app(tmp_path)
    workspace = application.state.workspace
    workspace.create_project("card-book")
    CanonRepository(workspace).write_project(
        __import__("app.domain.project", fromlist=["Project"]).Project(
            id="card-book", title="卡片书", language="zh-CN"
        )
    )
    DatabaseRepository(workspace).initialize("card-book")
    _write_card(workspace, "card-book", "card-alpha", 1, "planned")
    _write_card(workspace, "card-book", "card-beta", 2, "current")

    with TestClient(application) as client:
        response = client.get("/api/projects/card-book/creative/story-cards")

    assert response.status_code == 200
    cards = response.json()
    assert [c["id"] for c in cards] == ["card-alpha", "card-beta"]
    assert [c["status"] for c in cards] == ["planned", "current"]


def test_set_current_story_card_promotes_and_demotes(tmp_path) -> None:
    application = create_app(tmp_path)
    workspace = application.state.workspace
    workspace.create_project("card-book")
    CanonRepository(workspace).write_project(
        __import__("app.domain.project", fromlist=["Project"]).Project(
            id="card-book", title="卡片书", language="zh-CN"
        )
    )
    DatabaseRepository(workspace).initialize("card-book")
    _write_card(workspace, "card-book", "card-alpha", 1, "current")
    _write_card(workspace, "card-book", "card-beta", 2, "planned")

    with TestClient(application) as client:
        response = client.post(
            "/api/projects/card-book/creative/story-cards/current",
            json={"card_id": "card-beta"},
        )
        assert response.status_code == 200
        assert response.json()["id"] == "card-beta"
        assert response.json()["status"] == "current"
        listed = client.get("/api/projects/card-book/creative/story-cards")

    cards = {c["id"]: c["status"] for c in listed.json()}
    assert cards["card-alpha"] == "planned"
    assert cards["card-beta"] == "current"


def test_brief_draft_returns_structured_draft(tmp_path, monkeypatch) -> None:
    application = create_app(tmp_path)

    async def fake_draft(self, idea: str):
        from app.workflows.brief_draft import BriefDraft
        return BriefDraft(
            title="重生之最强学霸",
            genre_scope="都市重生·校园逆袭",
            first_story_goal="第一卷拿下省状元。",
            initial_intent="普通人靠记忆力逆袭打脸。",
        )

    monkeypatch.setattr("app.workflows.brief_draft.BriefDraftService.draft", fake_draft)
    with TestClient(application) as client:
        response = client.post(
            "/api/projects/any/creative/brief-draft",
            json={"idea": "都市重生逆袭"},
        )

    assert response.status_code == 200
    assert response.json()["title"] == "重生之最强学霸"
    assert response.json()["genre_scope"] == "都市重生·校园逆袭"
