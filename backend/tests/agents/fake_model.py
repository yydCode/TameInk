from collections.abc import Sequence
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_openai import ChatOpenAI


class ScriptedChatModel(BaseChatModel):
    responses: list[AIMessage]
    response_index: int = 0
    bound_tool_names: list[str] = []
    bound_tool_descriptions: dict[str, str] = {}

    @property
    def _llm_type(self) -> str:
        return "scripted-chat-model"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> "ScriptedChatModel":
        self.bound_tool_names = [tool.name for tool in tools]
        self.bound_tool_descriptions = {tool.name: tool.description for tool in tools}
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
        self.bound_tool_names = [tool.name for tool in tools]
        self.bound_tool_descriptions = {tool.name: tool.description for tool in tools}
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
