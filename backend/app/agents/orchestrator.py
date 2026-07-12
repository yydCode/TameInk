from threading import Lock

from deepagents import (
    FilesystemPermission,
    GeneralPurposeSubagentProfile,
    HarnessProfile,
    create_deep_agent,
    register_harness_profile,
)
from langchain_openai import ChatOpenAI

from app.agents.backend import NovelWorkspaceBackend
from app.agents.context import TrustedAgentContext
from app.agents.contracts import TaskInputContractMiddleware, ValidatedOrchestrator
from app.agents.subagents import (
    build_subagent_definitions,
    subagent_input_schemas,
    subagent_payload_schemas,
)

_PROFILE_LOCK = Lock()
_REGISTERED_PROFILE_KEYS: set[str] = set()


def _register_model_profile(model_identifier: str) -> None:
    if not model_identifier or ":" in model_identifier:
        raise ValueError("MODEL_IDENTIFIER_INVALID")
    key = f"openai:{model_identifier}"
    with _PROFILE_LOCK:
        if key in _REGISTERED_PROFILE_KEYS:
            return
        register_harness_profile(
            key,
            HarnessProfile(
                excluded_tools=frozenset({"execute"}),
                general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
                tool_description_overrides={
                    "task": (
                        "委派给一个专业创作 Agent。description 必须是对应业务 payload Schema "
                        "的严格 JSON，只含业务字段；模型不得提供 context。可用 Agent：\n"
                        "{available_agents}"
                    ),
                },
            ),
        )
        _REGISTERED_PROFILE_KEYS.add(key)


def create_orchestrator(
    model: ChatOpenAI,
    backend: NovelWorkspaceBackend,
    *,
    model_identifier: str,
) -> ValidatedOrchestrator:
    if model.model_name != model_identifier:
        raise ValueError("MODEL_IDENTIFIER_MISMATCH")
    _register_model_profile(model_identifier)
    definitions = build_subagent_definitions(backend)
    graph = create_deep_agent(
        model=model,
        tools=[],
        system_prompt=(
            "你只负责委派给八个专业 Agent 并汇总候选结果，不得写入 canon 或 memory。"
            "调用 task 时 description 只提交业务 payload，禁止提交 context；context 由系统注入。"
        ),
        subagents=[definition.to_deepagent() for definition in definitions],
        backend=backend,
        permissions=[FilesystemPermission(operations=["write"], paths=["/**"], mode="deny")],
        middleware=[
            TaskInputContractMiddleware(
                subagent_payload_schemas(),
                subagent_input_schemas(),
            )
        ],
        context_schema=TrustedAgentContext,
    )
    output_schemas = {definition.name: definition.output_schema for definition in definitions}
    return ValidatedOrchestrator(graph, output_schemas)
