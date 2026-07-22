import os
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.domain.creation import (
    ActualEvent,
    CharacterState,
    EndingPlan,
    Expectation,
    ReaderContract,
    StoryCard,
    StoryEngine,
)
from app.domain.errors import (
    CanonContentError,
    StorageReadError,
    StorageWriteError,
    WorkspacePathViolationError,
)
from app.domain.project import ConfirmedContent, MemoryRecord, Project
from app.repositories.canon import CanonRepository
from app.repositories.workspace import WorkspaceRepository


def repository(tmp_path: Path) -> CanonRepository:
    workspace = WorkspaceRepository(tmp_path)
    workspace.create_project("story-01")
    return CanonRepository(workspace)


def test_project_yaml_round_trip_is_stable(tmp_path: Path) -> None:
    canon = repository(tmp_path)
    project = Project(id="story-01", title="长夜", language="zh-CN")
    canon.write_project(project)
    first = canon.project_file("story-01").read_bytes()

    assert canon.read_project("story-01") == project
    canon.write_project(canon.read_project("story-01"))
    assert canon.project_file("story-01").read_bytes() == first


def test_strict_models_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        Project.model_validate({"id": "story-01", "title": "书", "language": "zh-CN", "x": 1})


def test_confirmed_markdown_round_trip(tmp_path: Path) -> None:
    canon = repository(tmp_path)
    content = ConfirmedContent(markdown="# 第一章\n\n正文。\n")
    canon.write_markdown("story-01", "canon/chapters/0001.md", content)
    assert canon.read_markdown("story-01", "canon/chapters/0001.md") == content


def test_memory_yaml_round_trip(tmp_path: Path) -> None:
    canon = repository(tmp_path)
    memory = MemoryRecord(
        id="fact-001",
        kind="fact",
        status="active",
        source="canon/chapters/0001.md",
        location="line 1, column 1",
        quote="天在下雨",
    )
    canon.write_memory("story-01", "memory/facts/fact-001.yaml", memory)
    assert canon.read_memory("story-01", "memory/facts/fact-001.yaml") == memory


def test_creation_records_round_trip_in_separate_canon_and_commitment_layers(
    tmp_path: Path,
) -> None:
    canon = repository(tmp_path)
    decision_id = str(uuid4())
    common = {
        "schema_version": 1,
        "decision_id": decision_id,
        "confirmed_by": "author",
    }
    source = {
        "path": "canon/chapters/0001.md",
        "location": "paragraph 1",
        "quote": "主角得到入城资格",
    }
    contract = ReaderContract.model_validate(
        {
            **common,
            "id": "reader-contract",
            "platform": "fanqie",
            "channel": "male",
            "genre_scope": "都市高武",
            "target_readers": ["成长流读者"],
            "core_experience": "持续成长",
            "protagonist_promise": "主动解决问题",
            "must_payoffs": ["完成身份成长"],
            "forbidden_directions": [],
            "evidence_refs": [],
        }
    )
    engine = StoryEngine.model_validate(
        {
            **common,
            "id": "story-engine",
            "reader_contract_id": contract.id,
            "protagonist_role": "底层武者",
            "desire": "取得自由",
            "fear": "再次失去同伴",
            "value_priority": "先保护同伴",
            "action_mechanism": "完成任务换取资源",
            "world_pressure": "城市资格垄断",
            "conversion_chain": ["完成任务", "取得资源"],
            "state_dimensions": ["身份"],
            "variation_axes": ["任务对象"],
            "long_lines": ["取得公民身份"],
        }
    )
    character = CharacterState.model_validate(
        {
            **common,
            "id": "hero",
            "name": "林川",
            "desire": "取得自由",
            "fear": "失去同伴",
            "current_belief": "只有力量可靠",
            "value_priority": "同伴优先",
            "social_roles": ["流民"],
            "available_resources": ["短刀"],
            "relationship_stances": {},
            "decision_pattern": "危险时先确保同伴撤离",
            "choice_evidence": [],
        }
    )
    expectation = Expectation.model_validate(
        {
            **common,
            "id": "enter-city",
            "reader_question": "主角如何取得入城资格？",
            "contract_link": contract.id,
            "opened_by": source,
            "payoff_semantics": "主角获得正式资格",
            "scope": "local",
            "status": "opened",
            "strengthening_event_ids": [],
            "actual_payoff_event_ids": [],
            "next_expectation_ids": [],
        }
    )
    card = StoryCard.model_validate(
        {
            **common,
            "id": "card-01",
            "sequence": 1,
            "status": "current",
            "goal": "取得入城资格",
            "motivation": "救治同伴",
            "expectation_ids": [expectation.id],
            "hard_constraints": [],
            "soft_plan": ["寻找担保人"],
            "reaction_targets": ["守门人"],
            "long_line_contribution": ["身份成长"],
            "cycle_input": "无身份",
            "cycle_delta": "取得身份",
            "carried_assets": ["短刀"],
            "next_affordance": "进入城市",
            "scene_units": [],
            "actual_event_ids": [],
            "actual_payoff_ids": [],
        }
    )
    event = ActualEvent.model_validate(
        {
            **common,
            "id": "enter-city-event",
            "summary": "主角得到入城资格",
            "source": source,
            "participant_ids": [character.id],
            "state_changes": ["身份由流民变为居民"],
            "expectation_ops": ["enter-city:paid"],
        }
    )
    ending = EndingPlan.model_validate(
        {
            **common,
            "id": "ending-plan",
            "promise_resolutions": [
                {
                    "promise_id": "identity-growth",
                    "resolution": "must_pay",
                    "planned_payoff": "主角获得完整公民权",
                }
            ],
            "final_state_targets": ["主角拥有自主身份"],
            "shared_climax_links": ["身份线与同伴线共享高潮"],
            "post_climax_rewards": ["同伴安全生活"],
        }
    )

    canon.write_reader_contract("story-01", contract)
    canon.write_story_engine("story-01", engine)
    canon.write_character_state("story-01", character)
    canon.write_expectation("story-01", expectation)
    canon.write_story_card("story-01", card)
    canon.write_actual_event("story-01", event)
    canon.write_ending_plan("story-01", ending)

    assert canon.read_reader_contract("story-01") == contract
    assert canon.read_story_engine("story-01") == engine
    assert canon.read_character_state("story-01", character.id) == character
    assert canon.read_expectation("story-01", expectation.id) == expectation
    assert canon.read_story_card("story-01", card.id) == card
    assert canon.read_actual_event("story-01", event.id) == event
    assert canon.read_ending_plan("story-01") == ending


@pytest.mark.parametrize(
    "path",
    ["canon/chapters/a.txt", "memory/facts/a.md", ".tame-ink/drafts/a.md", "canon/../project.yaml"],
)
def test_rejects_unsupported_formal_paths(tmp_path: Path, path: str) -> None:
    canon = repository(tmp_path)
    with pytest.raises((WorkspacePathViolationError, CanonContentError)):
        canon.write_markdown("story-01", path, ConfirmedContent(markdown="ok\n"))


def test_rejects_empty_markdown() -> None:
    with pytest.raises(ValidationError):
        ConfirmedContent(markdown="   ")


@pytest.mark.parametrize(
    "path",
    [
        "canon/premise.md",
        "canon/outline.md",
        "canon/volumes/volume-01.md",
        "canon/characters/hero.md",
        "canon/world/city.md",
        "canon/chapters/0001.md",
        "memory/summaries/book.md",
        "memory/summaries/volumes/volume-01.md",
        "memory/summaries/chapters/0001.md",
    ],
)
def test_allows_only_document_paths_from_the_formal_whitelist(tmp_path: Path, path: str) -> None:
    canon = repository(tmp_path)
    content = ConfirmedContent(markdown="内容\n")

    canon.write_markdown("story-01", path, content)

    assert canon.read_markdown("story-01", path) == content


@pytest.mark.parametrize(
    "path",
    [
        "canon/arbitrary.md",
        "canon/chapters/nested/0001.md",
        "canon/chapters/.",
        "memory/summaries/other.md",
        "memory/facts/nested/fact.yaml",
        "memory/facts/fact.md",
    ],
)
def test_rejects_paths_outside_exact_formal_whitelist(tmp_path: Path, path: str) -> None:
    canon = repository(tmp_path)

    with pytest.raises(WorkspacePathViolationError):
        canon.write_markdown("story-01", path, ConfirmedContent(markdown="内容\n"))


@pytest.mark.parametrize(
    "data",
    [
        {"id": "Upper", "title": "书", "language": "zh-CN"},
        {"id": "story-01", "title": "   ", "language": "zh-CN"},
        {"id": "story-01", "title": "书", "language": "   "},
    ],
)
def test_project_schema_rejects_invalid_identity_and_blank_fields(data: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        Project.model_validate(data)


@pytest.mark.parametrize("field", ["id", "source", "location", "quote"])
def test_memory_schema_rejects_blank_required_fields(field: str) -> None:
    data = {
        "id": "fact-001",
        "kind": "fact",
        "status": "active",
        "source": "canon/chapters/0001.md",
        "location": "line 1, column 1",
        "quote": "原文",
    }
    data[field] = "   "

    with pytest.raises(ValidationError):
        MemoryRecord.model_validate(data)


def test_invalid_yaml_maps_to_canon_content_error_with_cause(tmp_path: Path) -> None:
    canon = repository(tmp_path)
    canon.project_file("story-01").write_text("title: [unterminated")

    with pytest.raises(CanonContentError) as raised:
        canon.read_project("story-01")

    assert raised.value.code == "SCHEMA_VALIDATION_FAILED"
    assert raised.value.__cause__ is not None


def test_invalid_yaml_schema_maps_to_canon_content_error_with_cause(tmp_path: Path) -> None:
    canon = repository(tmp_path)
    canon.project_file("story-01").write_text("id: story-01\ntitle: '   '\nlanguage: zh-CN\n")

    with pytest.raises(CanonContentError) as raised:
        canon.read_project("story-01")

    assert raised.value.code == "SCHEMA_VALIDATION_FAILED"
    assert raised.value.__cause__ is not None


def test_read_io_failure_maps_to_stable_error_with_cause(tmp_path: Path) -> None:
    canon = repository(tmp_path)

    with pytest.raises(StorageReadError) as raised:
        canon.read_project("story-01")

    assert raised.value.code == "STORAGE_READ_FAILED"
    assert isinstance(raised.value.__cause__, FileNotFoundError)


def test_write_io_failure_maps_to_stable_error_with_cause(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    canon = repository(tmp_path)
    monkeypatch.setattr(
        "app.repositories.canon.os.replace", lambda *args: (_ for _ in ()).throw(OSError("replace"))
    )

    with pytest.raises(StorageWriteError) as raised:
        canon.write_project(Project(id="story-01", title="长夜", language="zh-CN"))

    assert raised.value.code == "STORAGE_WRITE_FAILED"
    assert isinstance(raised.value.__cause__, OSError)


def test_replace_fsyncs_parent_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    canon = repository(tmp_path)
    opened: list[Path] = []
    real_open = os.open

    def record_open(path: str | bytes | Path, flags: int) -> int:
        opened.append(Path(path))
        return real_open(path, flags)

    monkeypatch.setattr("app.repositories.canon.os.open", record_open)
    canon.write_project(Project(id="story-01", title="长夜", language="zh-CN"))

    assert canon.project_file("story-01").parent in opened


def test_list_expectations_empty_when_no_directory(tmp_path: Path) -> None:
    from app.repositories.canon import CanonRepository
    from app.repositories.workspace import WorkspaceRepository
    workspace = WorkspaceRepository(tmp_path)
    workspace.create_project("exp-test")
    result = CanonRepository(workspace).list_expectations("exp-test")
    assert result == []


def test_list_expectations_returns_all_confirmed_sorted_by_id(tmp_path: Path) -> None:
    from app.domain.creation import FormalEvidence
    from app.repositories.canon import CanonRepository
    from app.repositories.workspace import WorkspaceRepository
    workspace = WorkspaceRepository(tmp_path)
    workspace.create_project("exp-test")
    repo = CanonRepository(workspace)

    decision_id = str(uuid4())
    for exp_id in ["beta-exp", "alpha-exp"]:
        exp = Expectation(
            id=exp_id,
            decision_id=decision_id,
            confirmed_by="author",
            reader_question=f"{exp_id} 问题",
            contract_link="rc-1",
            opened_by=FormalEvidence(
                path="canon/chapters/chapter-1.md",
                location="chars:0-30",
                quote="第一章",
            ),
            payoff_semantics="主角成功",
            scope="local",
            status="opened",
        )
        repo.write_expectation("exp-test", exp)

    result = repo.list_expectations("exp-test")
    assert len(result) == 2
    assert [e.id for e in result] == ["alpha-exp", "beta-exp"]  # sorted by filename
