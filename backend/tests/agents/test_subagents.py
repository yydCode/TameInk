from pathlib import Path

from deepagents import FilesystemPermission
from langchain_core.messages import AIMessage

from app.agents.context import ContextManifest
from app.agents.orchestrator import create_orchestrator
from app.agents.subagents import build_subagent_definitions
from tests.agents.fake_model import ScriptedChatModel
from tests.agents.test_backend import make_backend

EXPECTED_NAMES = {
    "StoryArchitect",
    "OutlineArchitect",
    "ChapterPlanner",
    "DraftWriter",
    "ContinuityAuditor",
    "StyleCritic",
    "MemoryCurator",
    "ImportAnalyst",
}


def test_eight_subagents_have_independent_contracts_and_minimal_permissions(tmp_path: Path) -> None:
    backend, _, _, _ = make_backend(tmp_path)
    definitions = build_subagent_definitions(backend)

    assert {definition.name for definition in definitions} == EXPECTED_NAMES
    assert len({definition.system_prompt for definition in definitions}) == 8
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


def test_orchestrator_real_graph_has_only_eight_agents_and_no_execute(tmp_path: Path) -> None:
    backend, _, _, _ = make_backend(tmp_path)
    model = ScriptedChatModel(responses=[AIMessage(content="summary")])

    graph = create_orchestrator(model, backend, profile_key="scriptedchatmodel")
    graph.invoke(
        {"messages": [{"role": "user", "content": "plan"}]},
        context_manifest=ContextManifest(sources=[], retrieved=[]),
    )

    assert "task" in model.bound_tool_names
    assert "execute" not in model.bound_tool_names
    task_description = model.bound_tool_descriptions["task"]
    assert "general-purpose" not in task_description
    assert all(name in task_description for name in EXPECTED_NAMES)


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
