import json
from collections.abc import Callable, Mapping
from typing import Any

from langchain.agents.middleware.types import AgentMiddleware
from langchain.tools.tool_node import ToolCallRequest
from langchain_core.messages import AIMessage, ToolMessage
from pydantic import BaseModel, ValidationError

from app.agents.context import ContextManifest, TrustedAgentContext
from app.agents.schemas import (
    CommercialReport,
    ContinuityReport,
    DraftWriterResult,
    ReferencedOutput,
    SkillExecutionContract,
    SourceReference,
    StyleReport,
)
from app.agents.skills import P0Skill, is_candidate_kind_allowed


class OutputContractError(RuntimeError):
    pass


class TaskInputContractError(RuntimeError):
    pass


def validate_agent_output(
    output: ReferencedOutput,
    manifest: ContextManifest,
) -> ReferencedOutput:
    _validate_references(output.references, manifest)
    return output


def _validate_references(
    references: list[SourceReference], manifest: ContextManifest
) -> None:
    known_sources = {source.path for source in manifest.sources}
    known_sources.update(snippet.path for snippet in manifest.retrieved)
    if any(reference.path not in known_sources for reference in references):
        raise OutputContractError("REFERENCE_SOURCE_UNKNOWN")
    known_evidence: dict[tuple[str, str], list[str]] = {}
    for source in manifest.sources:
        known_evidence.setdefault((source.path, source.location), []).append(source.quote)
    for snippet in manifest.retrieved:
        known_evidence.setdefault((snippet.path, snippet.location), []).append(snippet.quote)
    if any(
        not any(
            reference.quote in evidence
            for evidence in known_evidence.get(
                (reference.path, reference.location), []
            )
        )
        for reference in references
    ):
        raise OutputContractError("REFERENCE_EVIDENCE_UNKNOWN")


def validate_agent_output_tree(
    output: ReferencedOutput,
    manifest: ContextManifest,
) -> ReferencedOutput:
    validate_agent_output(output, manifest)
    children: list[ReferencedOutput] = []
    if isinstance(output, (CommercialReport, ContinuityReport, StyleReport)):
        children.extend(output.issues)
    if isinstance(output, DraftWriterResult):
        children.extend(output.revisions)
    for child in children:
        validate_agent_output(child, manifest)
    if isinstance(output, SkillExecutionContract):
        for finding in output.evidence:
            _validate_references([finding.reference], manifest)
    return output


def validate_skill_execution(
    output: SkillExecutionContract,
    manifest: ContextManifest,
    expected_skill: P0Skill,
) -> SkillExecutionContract:
    validate_agent_output_tree(output, manifest)
    if output.skill != expected_skill:
        raise OutputContractError("SKILL_OUTPUT_MISMATCH")
    if output.candidate is not None and not is_candidate_kind_allowed(
        expected_skill, output.candidate.artifact_kind
    ):
        raise OutputContractError("SKILL_CANDIDATE_KIND_INVALID")
    return output


class TaskInputContractMiddleware(AgentMiddleware):
    def __init__(
        self,
        payload_schemas: Mapping[str, type[BaseModel]],
        input_schemas: Mapping[str, type[BaseModel]],
    ) -> None:
        self._payload_schemas = dict(payload_schemas)
        self._input_schemas = dict(input_schemas)

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Any],
    ) -> Any:
        if request.tool_call["name"] != "task":
            return handler(request)
        arguments = request.tool_call["args"]
        subagent_type = arguments.get("subagent_type")
        if not isinstance(subagent_type, str):
            raise TaskInputContractError("TASK_SUBAGENT_UNKNOWN")
        payload_schema = self._payload_schemas.get(subagent_type)
        input_schema = self._input_schemas.get(subagent_type)
        if payload_schema is None or input_schema is None:
            raise TaskInputContractError("TASK_SUBAGENT_UNKNOWN")
        trusted_context = request.runtime.context
        if not isinstance(trusted_context, TrustedAgentContext):
            raise TaskInputContractError("TASK_CONTEXT_MISSING")
        description = arguments.get("description")
        if not isinstance(description, str):
            raise TaskInputContractError("TASK_INPUT_INVALID")
        try:
            payload = payload_schema.model_validate_json(description)
            full_input = input_schema.model_validate(
                {
                    **payload.model_dump(mode="json"),
                    "context": trusted_context.manifest.model_dump(mode="json"),
                }
            )
        except (ValidationError, ValueError) as error:
            raise TaskInputContractError("TASK_INPUT_INVALID") from error
        modified_arguments = {
            **arguments,
            "description": full_input.model_dump_json(),
        }
        modified_call = {**request.tool_call, "args": modified_arguments}
        return handler(request.override(tool_call=modified_call))


class ValidatedOrchestrator:
    def __init__(
        self,
        graph: Any,
        output_schemas: Mapping[str, type[ReferencedOutput]],
    ) -> None:
        self._graph = graph
        self._output_schemas = dict(output_schemas)

    def invoke(
        self,
        payload: Any,
        config: Any = None,
        *,
        context_manifest: ContextManifest,
    ) -> dict[str, Any]:
        result, _ = self._invoke_validated(payload, config, context_manifest=context_manifest)
        return result

    def invoke_agent(
        self,
        agent: str,
        instruction: str,
        *,
        context_manifest: ContextManifest,
    ) -> ReferencedOutput:
        if agent not in self._output_schemas:
            raise OutputContractError("OUTPUT_SUBAGENT_UNKNOWN")
        payload = {
            "messages": [
                {
                    "role": "user",
                    "content": (
                        f"只委派给 {agent}。description 必须是严格 JSON："
                        f'{{"instruction":{json.dumps(instruction, ensure_ascii=False)}}}'
                    ),
                }
            ]
        }
        _, outputs = self._invoke_validated(payload, None, context_manifest=context_manifest)
        selected = [output for name, output in outputs if name == agent]
        if len(selected) != 1 or len(outputs) != 1:
            raise OutputContractError("TASK_DELEGATION_UNEXPECTED")
        return selected[0]

    def _invoke_validated(
        self,
        payload: Any,
        config: Any,
        *,
        context_manifest: ContextManifest,
    ) -> tuple[dict[str, Any], list[tuple[str, ReferencedOutput]]]:
        trusted_context = TrustedAgentContext(manifest=context_manifest)
        result: dict[str, Any] = self._graph.invoke(
            payload,
            config,
            context=trusted_context,
        )
        task_calls: dict[str, str] = {}
        all_call_ids: set[str] = set()
        for message in result.get("messages", []):
            if isinstance(message, AIMessage):
                for call in message.tool_calls:
                    call_id = call.get("id")
                    if not isinstance(call_id, str):
                        raise OutputContractError("OUTPUT_TASK_INVALID")
                    all_call_ids.add(call_id)
                    if call["name"] != "task":
                        continue
                    subagent_type = call["args"].get("subagent_type")
                    if not isinstance(subagent_type, str):
                        raise OutputContractError("OUTPUT_TASK_INVALID")
                    if call_id in task_calls:
                        raise OutputContractError("TASK_CALL_ID_DUPLICATE")
                    task_calls[call_id] = subagent_type
        if not task_calls:
            raise OutputContractError("TASK_DELEGATION_REQUIRED")
        task_results: dict[str, list[ToolMessage]] = {call_id: [] for call_id in task_calls}
        for message in result.get("messages", []):
            if not isinstance(message, ToolMessage):
                continue
            if message.tool_call_id not in all_call_ids:
                raise OutputContractError("TOOL_RESULT_ORPHAN")
            if message.tool_call_id in task_results:
                task_results[message.tool_call_id].append(message)
        outputs: list[tuple[str, ReferencedOutput]] = []
        for call_id, messages in task_results.items():
            if not messages:
                raise OutputContractError("TASK_RESULT_MISSING")
            if len(messages) != 1:
                raise OutputContractError("TASK_RESULT_DUPLICATE")
            message = messages[0]
            schema = self._output_schemas.get(task_calls[call_id])
            if schema is None:
                raise OutputContractError("OUTPUT_SUBAGENT_UNKNOWN")
            if not isinstance(message.content, str):
                raise OutputContractError("AGENT_OUTPUT_INVALID")
            try:
                parsed = schema.model_validate_json(message.content)
            except (ValidationError, ValueError, TypeError) as error:
                raise OutputContractError("AGENT_OUTPUT_INVALID") from error
            validate_agent_output_tree(parsed, context_manifest)
            outputs.append((task_calls[call_id], parsed))
        return result, outputs
