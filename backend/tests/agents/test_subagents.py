from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from deepagents import FilesystemPermission, create_deep_agent
from langchain_core.messages import AIMessage
from pydantic import SecretStr

from app.agents.context import ContextManifest
from app.agents.contracts import OutputContractError
from app.agents.orchestrator import create_orchestrator
from app.agents.subagents import (
    build_p0_skill_definitions,
    build_subagent_definitions,
    select_p0_skill_agent,
)
from tests.agents.fake_model import ScriptedOpenAIModel, ScriptedTameInkModel
from tests.agents.test_backend import make_backend

EXPECTED_NAMES = {
    "MarketStrategist",
    "StoryArchitect",
    "OutlineArchitect",
    "ChapterPlanner",
    "DraftWriter",
    "ContinuityAuditor",
    "StyleCritic",
    "RetentionAuditor",
    "MemoryCurator",
    "ImportAnalyst",
}


def test_ten_subagents_have_independent_contracts_and_minimal_permissions(tmp_path: Path) -> None:
    backend, _, _, _ = make_backend(tmp_path)
    definitions = build_subagent_definitions(backend)

    assert {definition.name for definition in definitions} == EXPECTED_NAMES
    assert len({definition.system_prompt for definition in definitions}) == 10
    assert all(definition.output_schema is not None for definition in definitions)
    assert all(not hasattr(definition, "input_schema") for definition in definitions)
    writers = [
        definition
        for definition in definitions
        if any(tool.name == "save_draft" for tool in definition.tools)
    ]
    assert [definition.name for definition in writers] == ["DraftWriter"]
    assert all(
        "execute" not in {tool.name for tool in definition.tools} for definition in definitions
    )


def test_concurrent_tame_model_orchestrator_construction_is_idempotent(tmp_path: Path) -> None:
    backend, _, _, _ = make_backend(tmp_path)
    models = [
        ScriptedTameInkModel(
            api_key=SecretStr("test-key"),
            model=f"ft:gpt-4o-mini:org:custom-{index}",
            responses=[AIMessage(content="summary")],
        )
        for index in range(16)
    ]
    with ThreadPoolExecutor(max_workers=16) as executor:
        orchestrators = list(
            executor.map(lambda model: create_orchestrator(model, backend), models)
        )
    assert len(orchestrators) == 16


@pytest.mark.parametrize("kind", ["ordinary", "forged"])
def test_orchestrator_rejects_uncontrolled_provider_before_registration_or_graph(
    tmp_path: Path, monkeypatch, kind: str
) -> None:
    backend, _, _, _ = make_backend(tmp_path)

    class ForgedProviderModel(ScriptedTameInkModel):
        def _get_ls_params(self, stop=None, **kwargs):
            params = super()._get_ls_params(stop=stop, **kwargs)
            return {**params, "ls_provider": "openai"}

    model_class = ScriptedOpenAIModel if kind == "ordinary" else ForgedProviderModel
    model = model_class(
        api_key=SecretStr("test-key"),
        model="ft:gpt-4o-mini:org:uncontrolled",
        responses=[AIMessage(content="summary")],
    )
    calls: list[str] = []
    monkeypatch.setattr(
        "app.agents.orchestrator.register_harness_profile",
        lambda *args, **kwargs: calls.append("register"),
    )
    monkeypatch.setattr(
        "app.agents.orchestrator.create_deep_agent",
        lambda *args, **kwargs: calls.append("graph"),
    )
    monkeypatch.setattr("app.agents.orchestrator._PROFILE_REGISTERED", False)

    with pytest.raises(RuntimeError, match="MODEL_PROVIDER_INVALID"):
        create_orchestrator(model, backend)  # type: ignore[arg-type]
    assert calls == []


def test_orchestrator_real_graph_has_only_ten_agents_and_no_execute(tmp_path: Path) -> None:
    backend, _, _, _ = make_backend(tmp_path)
    model = ScriptedTameInkModel(
        api_key=SecretStr("test-key"),
        model="tame-ink-contract-test",
        responses=[AIMessage(content="summary")],
    )

    graph = create_orchestrator(model, backend)
    with pytest.raises(OutputContractError, match="TASK_DELEGATION_REQUIRED"):
        graph.invoke(
            {"messages": [{"role": "user", "content": "plan"}]},
            context_manifest=ContextManifest(sources=[], retrieved=[]),
        )

    assert "task" in model.bound_tool_names
    assert "execute" not in model.bound_tool_names
    task_description = model.bound_tool_descriptions["task"]
    assert "general-purpose" not in task_description
    assert all(name in task_description for name in EXPECTED_NAMES)


def test_exact_model_profile_does_not_pollute_other_openai_model(tmp_path: Path) -> None:
    backend, _, _, _ = make_backend(tmp_path)
    tame_model = ScriptedTameInkModel(
        api_key=SecretStr("test-key"),
        model="ft:gpt-4o-mini:org:custom",
        responses=[AIMessage(content="summary")],
    )
    first = create_orchestrator(tame_model, backend)
    with pytest.raises(OutputContractError):
        first.invoke(
            {"messages": [{"role": "user", "content": "plan"}]},
            context_manifest=ContextManifest(sources=[], retrieved=[]),
        )
    first_description = tame_model.bound_tool_descriptions["task"]

    repeated_model = ScriptedTameInkModel(
        api_key=SecretStr("test-key"),
        model="ft:gpt-4o-mini:org:another",
        responses=[AIMessage(content="summary")],
    )
    repeated = create_orchestrator(repeated_model, backend)
    with pytest.raises(OutputContractError):
        repeated.invoke(
            {"messages": [{"role": "user", "content": "plan"}]},
            context_manifest=ContextManifest(sources=[], retrieved=[]),
        )
    assert repeated_model.bound_tool_descriptions["task"] == first_description

    other_model = ScriptedOpenAIModel(
        api_key=SecretStr("test-key"),
        model="unrelated-profile-model",
        responses=[AIMessage(content="summary")],
    )
    graph = create_deep_agent(model=other_model, backend=backend)
    graph.invoke({"messages": [{"role": "user", "content": "answer"}]})

    assert "task" in other_model.bound_tool_names
    assert "general-purpose" in other_model.bound_tool_descriptions["task"]


def test_orchestrator_main_permissions_deny_all_writes(tmp_path: Path) -> None:
    backend, _, _, _ = make_backend(tmp_path)
    definitions = build_subagent_definitions(backend)
    draft_writer = next(item for item in definitions if item.name == "DraftWriter")
    read_only = next(item for item in definitions if item.name == "StoryArchitect")

    assert draft_writer.permissions == [
        FilesystemPermission(operations=["write"], paths=["/drafts/**"], mode="allow"),
        FilesystemPermission(operations=["write"], paths=["/**"], mode="deny"),
    ]
    assert read_only.permissions == [
        FilesystemPermission(operations=["write"], paths=["/**"], mode="deny")
    ]


def test_p0_skill_agents_have_no_draft_write_or_implicit_audit_role(tmp_path: Path) -> None:
    backend, _, _, _ = make_backend(tmp_path)
    definitions = build_p0_skill_definitions(backend)

    assert {definition.name for definition in definitions} == {
        "Researcher",
        "StoryEditor",
        "ChapterPlanner",
        "DraftWriter",
        "ContinuityAuditor",
        "PromiseAuditor",
        "SceneAuditor",
        "CognitiveLoadAuditor",
        "OpeningAuditor",
        "PoisonCheckAuditor",
        "MemoryCurator",
    }
    assert all(
        "save_draft" not in {tool.name for tool in definition.tools} for definition in definitions
    )
    assert all(
        definition.permissions
        == [FilesystemPermission(operations=["write"], paths=["/**"], mode="deny")]
        for definition in definitions
    )
    audit = select_p0_skill_agent(
        "webnovel-audit", {"audit_kind": "promise"}, definitions
    )
    assert audit.name == "PromiseAuditor"
    opening = select_p0_skill_agent("webnovel-opening-audit", {}, definitions)
    assert opening.name == "OpeningAuditor"
    with pytest.raises(ValueError, match="AUDIT_KIND_INVALID"):
        select_p0_skill_agent("webnovel-audit", {}, definitions)
    with pytest.raises(ValueError, match="SKILL_EXECUTION_UNSUPPORTED"):
        select_p0_skill_agent("webnovel-studio", {}, definitions)
