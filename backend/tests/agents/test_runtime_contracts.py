import json
from pathlib import Path

import pytest
from deepagents import (
    GeneralPurposeSubagentProfile,
    HarnessProfile,
    create_deep_agent,
    register_harness_profile,
)
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from app.agents.context import ContextManifest, ManifestSource
from app.agents.contracts import (
    OutputContractError,
    TaskInputContractMiddleware,
    ValidatedOrchestrator,
    validate_agent_output,
)
from app.agents.schemas import StorySetting
from app.agents.subagents import StoryArchitectInput
from app.domain.project import ConfirmedContent
from tests.agents.fake_model import ScriptedChatModel
from tests.agents.test_backend import make_backend


def manifest(path: str = "canon/premise.md") -> ContextManifest:
    return ContextManifest(
        sources=[ManifestSource(path=path, sha256="a" * 64, excerpt="confirmed")],
        retrieved=[],
    )


def output(path: str) -> StorySetting:
    return StorySetting.model_validate(
        {
            "id": "setting-1",
            "title": "setting",
            "content": "content",
            "references": [{"path": path, "location": "paragraph 1", "quote": "confirmed"}],
        }
    )


def test_output_parses_without_context_then_validates_known_sources() -> None:
    parsed = output("canon/premise.md")
    assert validate_agent_output(parsed, manifest()) is parsed
    with pytest.raises(OutputContractError, match="REFERENCE_SOURCE_UNKNOWN"):
        validate_agent_output(parsed, manifest("canon/outline.md"))


def test_validated_orchestrator_invoke_cannot_skip_output_validation(tmp_path: Path) -> None:
    _, canon, _, _ = make_backend(tmp_path)
    canon.write_markdown("story-01", "canon/premise.md", ConfirmedContent(markdown="confirmed"))
    task_call = {
        "name": "task",
        "args": {"subagent_type": "StoryArchitect", "description": "{}"},
        "id": "task-1",
    }

    class FakeGraph:
        def invoke(self, payload, config=None):
            from langchain_core.messages import ToolMessage

            return {
                "messages": [
                    AIMessage(content="", tool_calls=[task_call]),
                    ToolMessage(
                        content=output("canon/outline.md").model_dump_json(), tool_call_id="task-1"
                    ),
                ]
            }

    runtime = ValidatedOrchestrator(FakeGraph(), {"StoryArchitect": StorySetting})
    with pytest.raises(OutputContractError, match="REFERENCE_SOURCE_UNKNOWN"):
        runtime.invoke({"messages": []}, context_manifest=manifest())
    assert canon.read_markdown("story-01", "canon/premise.md").markdown == "confirmed"


def test_validated_orchestrator_accepts_known_structured_result() -> None:
    from langchain_core.messages import ToolMessage

    task_call = {
        "name": "task",
        "args": {"subagent_type": "StoryArchitect", "description": "{}"},
        "id": "task-1",
    }
    expected = {
        "messages": [
            AIMessage(content="", tool_calls=[task_call]),
            ToolMessage(
                content=output("canon/premise.md").model_dump_json(),
                tool_call_id="task-1",
            ),
        ]
    }

    class FakeGraph:
        def invoke(self, payload, config=None):
            return expected

    runtime = ValidatedOrchestrator(FakeGraph(), {"StoryArchitect": StorySetting})
    assert runtime.invoke({"messages": []}, context_manifest=manifest()) is expected


@pytest.mark.parametrize(
    ("task_args", "error_code"),
    [
        (
            {"subagent_type": "StoryArchitect", "description": "not-json"},
            "TASK_INPUT_INVALID",
        ),
        (
            {
                "subagent_type": "StoryArchitect",
                "description": json.dumps(
                    {
                        "instruction": "design",
                        "context": {"sources": [], "retrieved": []},
                        "extra": "forbidden",
                    }
                ),
            },
            "TASK_INPUT_INVALID",
        ),
        (
            {
                "subagent_type": "UnknownAgent",
                "description": json.dumps(
                    {"instruction": "design", "context": {"sources": [], "retrieved": []}}
                ),
            },
            "TASK_SUBAGENT_UNKNOWN",
        ),
    ],
)
def test_task_input_middleware_rejects_invalid_before_dispatch(
    task_args: dict[str, str], error_code: str
) -> None:
    called: list[str] = []

    def subagent(state):
        called.append("called")
        return {"messages": [AIMessage(content="done")]}

    register_harness_profile(
        "scriptedchatmodel",
        HarnessProfile(general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False)),
    )
    model = ScriptedChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "task",
                        "args": task_args,
                        "id": "task-1",
                    }
                ],
            )
        ]
    )
    graph = create_deep_agent(
        model=model,
        subagents=[
            {"name": "StoryArchitect", "description": "test", "runnable": RunnableLambda(subagent)}
        ],
        middleware=[TaskInputContractMiddleware({"StoryArchitect": StoryArchitectInput})],
    )
    with pytest.raises(RuntimeError, match=error_code):
        graph.invoke({"messages": [{"role": "user", "content": "delegate"}]})
    assert called == []


def test_task_input_middleware_allows_valid_envelope_to_dispatch() -> None:
    called: list[str] = []

    def subagent(state):
        called.append(state["messages"][0].content)
        return {"messages": [AIMessage(content="done")]}

    envelope = {
        "instruction": "design",
        "context": {"sources": [], "retrieved": []},
    }
    model = ScriptedChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "task",
                        "args": {
                            "subagent_type": "StoryArchitect",
                            "description": json.dumps(envelope),
                        },
                        "id": "task-1",
                    }
                ],
            ),
            AIMessage(content="summary"),
        ]
    )
    graph = create_deep_agent(
        model=model,
        subagents=[
            {"name": "StoryArchitect", "description": "test", "runnable": RunnableLambda(subagent)}
        ],
        middleware=[TaskInputContractMiddleware({"StoryArchitect": StoryArchitectInput})],
    )
    graph.invoke({"messages": [{"role": "user", "content": "delegate"}]})
    assert called == [json.dumps(envelope)]
