from typing import Any

from deepagents import (
    FilesystemPermission,
    GeneralPurposeSubagentProfile,
    HarnessProfile,
    create_deep_agent,
    register_harness_profile,
)
from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.graph.state import CompiledStateGraph

from app.agents.backend import NovelWorkspaceBackend
from app.agents.subagents import build_subagent_definitions


def create_orchestrator(
    model: BaseChatModel,
    backend: NovelWorkspaceBackend,
    *,
    profile_key: str = "openai",
) -> CompiledStateGraph[Any, Any, Any, Any]:
    register_harness_profile(
        profile_key,
        HarnessProfile(
            excluded_tools=frozenset({"execute"}),
            general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
            tool_description_overrides={
                "task": "委派给一个专业创作 Agent。可用 Agent：\n{available_agents}",
            },
        ),
    )
    definitions = build_subagent_definitions(backend)
    return create_deep_agent(
        model=model,
        tools=[],
        system_prompt="你只负责委派给八个专业 Agent 并汇总候选结果，不得写入 canon 或 memory。",
        subagents=[definition.to_deepagent() for definition in definitions],
        backend=backend,
        permissions=[FilesystemPermission(operations=["write"], paths=["/**"], mode="deny")],
    )
