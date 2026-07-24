from collections.abc import Sequence
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_openai import ChatOpenAI

from app.infrastructure.model import TameInkChatOpenAI


def _extract_tool_info(tool: Any) -> tuple[str, str]:
    """从 BaseTool 或 dict 中提取 name 和 description。"""
    if isinstance(tool, dict):
        name = tool.get("title") or tool.get("name") or "schema"
        description = tool.get("description", "")
        return name, description
    return tool.name, getattr(tool, "description", "")


class ScriptedChatModel(BaseChatModel):
    responses: list[AIMessage]
    response_index: int = 0
    bound_tool_names: list[str] = []
    bound_tool_descriptions: dict[str, str] = {}

    @property
    def _llm_type(self) -> str:
        return "scripted-chat-model"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> "ScriptedChatModel":
        self.bound_tool_names = [_extract_tool_info(tool)[0] for tool in tools]
        self.bound_tool_descriptions = dict(_extract_tool_info(tool) for tool in tools)
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        response = self.responses[self.response_index]
        self.response_index += 1
        return ChatResult(generations=[ChatGeneration(message=response)])


class ScriptedOpenAIModel(ChatOpenAI):
    responses: list[AIMessage]
    response_index: int = 0
    bound_tool_names: list[str] = []
    bound_tool_descriptions: dict[str, str] = {}

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> "ScriptedOpenAIModel":
        self.bound_tool_names = [_extract_tool_info(tool)[0] for tool in tools]
        self.bound_tool_descriptions = dict(_extract_tool_info(tool) for tool in tools)
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        response = self.responses[self.response_index]
        self.response_index += 1
        return ChatResult(generations=[ChatGeneration(message=response)])


class ScriptedTameInkModel(TameInkChatOpenAI):
    responses: list[AIMessage]
    response_index: int = 0
    bound_tool_names: list[str] = []
    bound_tool_descriptions: dict[str, str] = {}

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> "ScriptedTameInkModel":
        self.bound_tool_names = [_extract_tool_info(tool)[0] for tool in tools]
        self.bound_tool_descriptions = dict(_extract_tool_info(tool) for tool in tools)
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        response = self.responses[self.response_index]
        self.response_index += 1
        return ChatResult(generations=[ChatGeneration(message=response)])
