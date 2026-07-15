import json
from pathlib import Path

import pytest
from deepagents import (
    GeneralPurposeSubagentProfile,
    HarnessProfile,
    create_deep_agent,
    register_harness_profile,
)
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.runnables import RunnableLambda

from app.agents.context import (
    ContextManifest,
    ManifestSource,
    RetrievedSnippet,
    TrustedAgentContext,
)
from app.agents.contracts import (
    OutputContractError,
    TaskInputContractMiddleware,
    ValidatedOrchestrator,
    validate_agent_output,
)
from app.agents.schemas import StorySetting
from app.agents.subagents import StoryArchitectInput, StoryArchitectPayload
from app.domain.project import ConfirmedContent
from tests.agents.fake_model import ScriptedChatModel
from tests.agents.test_backend import make_backend


def manifest(path: str = "canon/premise.md") -> ContextManifest:
    return ContextManifest(
        sources=[
            ManifestSource(
                path=path,
                sha256="a" * 64,
                excerpt="confirmed",
                location="paragraph 1",
                quote="confirmed quote",
            )
        ],
        retrieved=[RetrievedSnippet(path=path, location="paragraph 1", quote="confirmed quote")],
    )


def output(
    path: str,
    *,
    location: str = "paragraph 1",
    quote: str = "confirmed quote",
) -> StorySetting:
    return StorySetting.model_validate(
        {
            "id": "setting-1",
            "title": "setting",
            "content": "content",
            "references": [{"path": path, "location": location, "quote": quote}],
        }
    )


def test_output_parses_without_context_then_validates_known_sources() -> None:
    parsed = output("canon/premise.md")
    assert validate_agent_output(parsed, manifest()) is parsed
    excerpted = output("canon/premise.md", quote="confirmed")
    assert validate_agent_output(excerpted, manifest()) is excerpted
    with pytest.raises(OutputContractError, match="REFERENCE_SOURCE_UNKNOWN"):
        validate_agent_output(parsed, manifest("canon/outline.md"))
    with pytest.raises(OutputContractError, match="REFERENCE_EVIDENCE_UNKNOWN"):
        validate_agent_output(output("canon/premise.md", quote="FABRICATED"), manifest())
    with pytest.raises(OutputContractError, match="REFERENCE_EVIDENCE_UNKNOWN"):
        validate_agent_output(output("canon/premise.md", location="wrong location"), manifest())


def test_validated_orchestrator_invoke_cannot_skip_output_validation(tmp_path: Path) -> None:
    backend, canon, _, _ = make_backend(tmp_path)
    canon.write_markdown("story-01", "canon/premise.md", ConfirmedContent(markdown="confirmed"))
    task_call = {
        "name": "task",
        "args": {"subagent_type": "StoryArchitect", "description": "{}"},
        "id": "task-1",
    }

    class FakeGraph:
        def invoke(self, payload, config=None, *, context=None):
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

    received_contexts: list[TrustedAgentContext] = []

    class FakeGraph:
        def invoke(self, payload, config=None, *, context=None):
            received_contexts.append(context)
            return expected

    runtime = ValidatedOrchestrator(FakeGraph(), {"StoryArchitect": StorySetting})
    trusted_manifest = manifest()
    assert runtime.invoke({"messages": []}, context_manifest=trusted_manifest) is expected
    assert received_contexts == [TrustedAgentContext(manifest=trusted_manifest)]


@pytest.mark.parametrize(
    ("messages", "error_code"),
    [
        ([AIMessage(content="summary without delegation")], "TASK_DELEGATION_REQUIRED"),
        (
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "task",
                            "args": {"subagent_type": "StoryArchitect", "description": "{}"},
                            "id": "task-1",
                        }
                    ],
                )
            ],
            "TASK_RESULT_MISSING",
        ),
        (
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "task",
                            "args": {"subagent_type": "StoryArchitect", "description": "{}"},
                            "id": "task-1",
                        },
                        {
                            "name": "task",
                            "args": {"subagent_type": "StoryArchitect", "description": "{}"},
                            "id": "task-1",
                        },
                    ],
                )
            ],
            "TASK_CALL_ID_DUPLICATE",
        ),
        (
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "task",
                            "args": {"subagent_type": "StoryArchitect", "description": "{}"},
                            "id": "task-1",
                        }
                    ],
                ),
                ToolMessage(
                    content=output("canon/premise.md").model_dump_json(),
                    tool_call_id="task-1",
                ),
                ToolMessage(
                    content=output("canon/premise.md").model_dump_json(),
                    tool_call_id="task-1",
                ),
            ],
            "TASK_RESULT_DUPLICATE",
        ),
        (
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "task",
                            "args": {"subagent_type": "StoryArchitect", "description": "{}"},
                            "id": "task-1",
                        }
                    ],
                ),
                ToolMessage(
                    content=output("canon/premise.md").model_dump_json(),
                    tool_call_id="orphan",
                ),
            ],
            "TOOL_RESULT_ORPHAN",
        ),
    ],
)
def test_validated_orchestrator_fails_closed_on_invalid_delegation_results(
    messages: list, error_code: str
) -> None:
    class FakeGraph:
        def invoke(self, payload, config=None, *, context=None):
            return {"messages": messages}

    runtime = ValidatedOrchestrator(FakeGraph(), {"StoryArchitect": StorySetting})
    with pytest.raises(OutputContractError, match=error_code):
        runtime.invoke({"messages": []}, context_manifest=manifest())


def test_validated_orchestrator_accepts_multiple_complete_task_results() -> None:
    calls = [
        {
            "name": "task",
            "args": {"subagent_type": "StoryArchitect", "description": "{}"},
            "id": f"task-{index}",
        }
        for index in (1, 2)
    ]
    expected = {
        "messages": [
            AIMessage(content="", tool_calls=calls),
            *[
                ToolMessage(
                    content=output("canon/premise.md").model_dump_json(),
                    tool_call_id=call["id"],
                )
                for call in calls
            ],
            AIMessage(content="delegated summary"),
        ]
    }

    class FakeGraph:
        def invoke(self, payload, config=None, *, context=None):
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
                        "context": {
                            "sources": [
                                {
                                    "path": "canon/premise.md",
                                    "sha256": "0" * 64,
                                    "excerpt": "FABRICATED",
                                }
                            ],
                            "retrieved": [],
                        },
                    }
                ),
            },
            "TASK_INPUT_INVALID",
        ),
        (
            {
                "subagent_type": "UnknownAgent",
                "description": json.dumps({"instruction": "design"}),
            },
            "TASK_SUBAGENT_UNKNOWN",
        ),
    ],
)
def test_task_input_middleware_rejects_invalid_before_dispatch(
    tmp_path: Path, task_args: dict[str, str], error_code: str
) -> None:
    called: list[str] = []
    backend, canon, _, _ = make_backend(tmp_path)
    canon.write_markdown("story-01", "canon/premise.md", ConfirmedContent(markdown="confirmed"))

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
        backend=backend,
        subagents=[
            {"name": "StoryArchitect", "description": "test", "runnable": RunnableLambda(subagent)}
        ],
        middleware=[
            TaskInputContractMiddleware(
                {"StoryArchitect": StoryArchitectPayload},
                {"StoryArchitect": StoryArchitectInput},
            )
        ],
        context_schema=TrustedAgentContext,
    )
    with pytest.raises(RuntimeError, match=error_code):
        graph.invoke(
            {"messages": [{"role": "user", "content": "delegate"}]},
            context=TrustedAgentContext(manifest=manifest()),
        )
    assert called == []
    assert canon.read_markdown("story-01", "canon/premise.md").markdown == "confirmed"


def test_task_input_middleware_requires_runtime_manifest_before_dispatch() -> None:
    called: list[str] = []

    def subagent(state):
        called.append("called")
        return {"messages": [AIMessage(content="done")]}

    model = ScriptedChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "task",
                        "args": {
                            "subagent_type": "StoryArchitect",
                            "description": json.dumps({"instruction": "design"}),
                        },
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
        middleware=[
            TaskInputContractMiddleware(
                {"StoryArchitect": StoryArchitectPayload},
                {"StoryArchitect": StoryArchitectInput},
            )
        ],
        context_schema=TrustedAgentContext,
    )
    with pytest.raises(RuntimeError, match="TASK_CONTEXT_MISSING"):
        graph.invoke({"messages": [{"role": "user", "content": "delegate"}]})
    assert called == []


def test_task_input_middleware_injects_full_trusted_manifest_without_cross_run_leak() -> None:
    called: list[str] = []

    def subagent(state):
        called.append(state["messages"][0].content)
        return {"messages": [AIMessage(content="done")]}

    payload = {"instruction": "design"}
    model = ScriptedChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "task",
                        "args": {
                            "subagent_type": "StoryArchitect",
                            "description": json.dumps(payload),
                        },
                        "id": "task-1",
                    }
                ],
            ),
            AIMessage(content="summary"),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "task",
                        "args": {
                            "subagent_type": "StoryArchitect",
                            "description": json.dumps(payload),
                        },
                        "id": "task-2",
                    }
                ],
            ),
            AIMessage(content="summary 2"),
        ]
    )
    graph = create_deep_agent(
        model=model,
        subagents=[
            {"name": "StoryArchitect", "description": "test", "runnable": RunnableLambda(subagent)}
        ],
        middleware=[
            TaskInputContractMiddleware(
                {"StoryArchitect": StoryArchitectPayload},
                {"StoryArchitect": StoryArchitectInput},
            )
        ],
        context_schema=TrustedAgentContext,
    )
    first = manifest("canon/premise.md")
    second = manifest("canon/outline.md")
    graph.invoke(
        {"messages": [{"role": "user", "content": "delegate"}]},
        context=TrustedAgentContext(manifest=first),
    )
    graph.invoke(
        {"messages": [{"role": "user", "content": "delegate again"}]},
        context=TrustedAgentContext(manifest=second),
    )
    parsed = [StoryArchitectInput.model_validate_json(item) for item in called]
    assert parsed[0].context == first
    assert parsed[1].context == second
    assert parsed[0].context != parsed[1].context
