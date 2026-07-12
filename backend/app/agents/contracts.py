from collections.abc import Callable, Mapping
from typing import Any

from langchain.agents.middleware.types import AgentMiddleware
from langchain.tools.tool_node import ToolCallRequest
from langchain_core.messages import AIMessage, ToolMessage
from pydantic import BaseModel, ValidationError

from app.agents.context import ContextManifest
from app.agents.schemas import ReferencedOutput


class OutputContractError(RuntimeError):
    pass


class TaskInputContractError(RuntimeError):
    pass


def validate_agent_output(
    output: ReferencedOutput,
    manifest: ContextManifest,
) -> ReferencedOutput:
    known_sources = {source.path for source in manifest.sources}
    known_sources.update(snippet.path for snippet in manifest.retrieved)
    if any(reference.path not in known_sources for reference in output.references):
        raise OutputContractError("REFERENCE_SOURCE_UNKNOWN")
    return output


class TaskInputContractMiddleware(AgentMiddleware):
    def __init__(self, schemas: Mapping[str, type[BaseModel]]) -> None:
        self._schemas = dict(schemas)

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
        schema = self._schemas.get(subagent_type)
        if schema is None:
            raise TaskInputContractError("TASK_SUBAGENT_UNKNOWN")
        description = arguments.get("description")
        if not isinstance(description, str):
            raise TaskInputContractError("TASK_INPUT_INVALID")
        try:
            schema.model_validate_json(description)
        except (ValidationError, ValueError) as error:
            raise TaskInputContractError("TASK_INPUT_INVALID") from error
        return handler(request)


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
        result: dict[str, Any] = self._graph.invoke(payload, config)
        task_calls: dict[str, str] = {}
        for message in result.get("messages", []):
            if isinstance(message, AIMessage):
                for call in message.tool_calls:
                    if call["name"] == "task":
                        call_id = call.get("id")
                        subagent_type = call["args"].get("subagent_type")
                        if not isinstance(call_id, str) or not isinstance(subagent_type, str):
                            raise OutputContractError("OUTPUT_TASK_INVALID")
                        task_calls[call_id] = subagent_type
        for message in result.get("messages", []):
            if not isinstance(message, ToolMessage) or message.tool_call_id not in task_calls:
                continue
            schema = self._output_schemas.get(task_calls[message.tool_call_id])
            if schema is None:
                raise OutputContractError("OUTPUT_SUBAGENT_UNKNOWN")
            if not isinstance(message.content, str):
                raise OutputContractError("AGENT_OUTPUT_INVALID")
            try:
                parsed = schema.model_validate_json(message.content)
            except (ValidationError, ValueError, TypeError) as error:
                raise OutputContractError("AGENT_OUTPUT_INVALID") from error
            validate_agent_output(parsed, context_manifest)
        return result
