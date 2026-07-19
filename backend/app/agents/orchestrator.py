from threading import Lock

from deepagents import (
    FilesystemPermission,
    GeneralPurposeSubagentProfile,
    HarnessProfile,
    create_deep_agent,
    register_harness_profile,
)

from app.agents.backend import NovelWorkspaceBackend
from app.agents.context import TrustedAgentContext
from app.agents.contracts import TaskInputContractMiddleware, ValidatedOrchestrator
from app.agents.subagents import (
    CreativeAgentDefinition,
    build_subagent_definitions,
    subagent_input_schemas,
    subagent_payload_schemas,
)
from app.infrastructure.model import TameInkChatOpenAI

_PROFILE_LOCK = Lock()
_PROFILE_REGISTERED = False


def register_model_profile() -> None:
    global _PROFILE_REGISTERED  # noqa: PLW0603
    with _PROFILE_LOCK:
        if _PROFILE_REGISTERED:
            return
        register_harness_profile(
            "tame_ink_openai",
            HarnessProfile(
                excluded_tools=frozenset({"edit_file", "execute", "write_file", "write_todos"}),
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
        _PROFILE_REGISTERED = True


def create_orchestrator(
    model: TameInkChatOpenAI,
    backend: NovelWorkspaceBackend,
    definitions: list[CreativeAgentDefinition] | None = None,
) -> ValidatedOrchestrator:
    if not isinstance(model, TameInkChatOpenAI):
        raise RuntimeError("MODEL_PROVIDER_INVALID")
    try:
        provider = model._get_ls_params().get("ls_provider")
    except Exception as error:
        raise RuntimeError("MODEL_PROVIDER_INVALID") from error
    if provider != "tame_ink_openai":
        raise RuntimeError("MODEL_PROVIDER_INVALID")
    register_model_profile()
    selected_definitions = definitions or build_subagent_definitions(backend)
    graph = create_deep_agent(
        model=model,
        tools=[],
        system_prompt=(
            "你只负责委派给十个专业 Agent 并汇总候选结果，不得写入 canon 或 memory。"
            "调用 task 时 description 只提交业务 payload，禁止提交 context；context 由系统注入。"
        ),
        subagents=[definition.to_deepagent() for definition in selected_definitions],
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
    output_schemas = {
        definition.name: definition.output_schema for definition in selected_definitions
    }
    return ValidatedOrchestrator(graph, output_schemas)
