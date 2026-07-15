from dataclasses import dataclass

from deepagents import FilesystemPermission, SubAgent
from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict

from app.agents.backend import NovelWorkspaceBackend
from app.agents.context import ContextManifest
from app.agents.schemas import (
    ChapterPlan,
    CommercialReport,
    CommercialStrategy,
    ContinuityReport,
    DraftWriterResult,
    ImportAnalysis,
    MemoryUpdate,
    Outline,
    ReferencedOutput,
    StorySetting,
    StyleReport,
)
from app.agents.tools import build_repository_tools


class AgentPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    instruction: str


class StoryArchitectPayload(AgentPayload):
    pass


class MarketStrategistPayload(AgentPayload):
    pass


class OutlineArchitectPayload(AgentPayload):
    pass


class ChapterPlannerPayload(AgentPayload):
    pass


class DraftWriterPayload(AgentPayload):
    pass


class ContinuityAuditorPayload(AgentPayload):
    pass


class StyleCriticPayload(AgentPayload):
    pass


class RetentionAuditorPayload(AgentPayload):
    pass


class MemoryCuratorPayload(AgentPayload):
    pass


class ImportAnalystPayload(AgentPayload):
    pass


class AgentInput(AgentPayload):
    context: ContextManifest


class StoryArchitectInput(AgentInput):
    pass


class MarketStrategistInput(AgentInput):
    pass


class OutlineArchitectInput(AgentInput):
    pass


class ChapterPlannerInput(AgentInput):
    pass


class DraftWriterInput(AgentInput):
    pass


class ContinuityAuditorInput(AgentInput):
    pass


class StyleCriticInput(AgentInput):
    pass


class RetentionAuditorInput(AgentInput):
    pass


class MemoryCuratorInput(AgentInput):
    pass


class ImportAnalystInput(AgentInput):
    pass


@dataclass(frozen=True)
class CreativeAgentDefinition:
    name: str
    description: str
    system_prompt: str
    output_schema: type[ReferencedOutput]
    tools: list[BaseTool]
    permissions: list[FilesystemPermission]

    def to_deepagent(self) -> SubAgent:
        return {
            "name": self.name,
            "description": self.description,
            "system_prompt": self.system_prompt,
            "tools": self.tools,
            "permissions": self.permissions,
            "response_format": self.output_schema,
        }


def build_subagent_definitions(backend: NovelWorkspaceBackend) -> list[CreativeAgentDefinition]:
    read_tools = build_repository_tools(backend, allow_draft_write=False)
    write_tools = build_repository_tools(backend, allow_draft_write=True)
    read_only = [FilesystemPermission(operations=["write"], paths=["/**"], mode="deny")]
    draft_write = [
        FilesystemPermission(operations=["write"], paths=["/drafts/**"], mode="allow"),
        FilesystemPermission(operations=["write"], paths=["/**"], mode="deny"),
    ]
    specs: list[tuple[str, str, str, type[ReferencedOutput], bool]] = [
        (
            "MarketStrategist",
            "设计可验证的商业定位和作品包装",
            (
                "面向用户指定平台设计商业定位候选。区分事实、假设和待验证指标；"
                "不得伪造平台行业数据，不得照搬对标作品。"
            ),
            CommercialStrategy,
            False,
        ),
        (
            "StoryArchitect",
            "设计故事设定",
            "只依据清单来源设计故事设定，返回严格结构化候选。",
            StorySetting,
            False,
        ),
        (
            "OutlineArchitect",
            "设计全书或分卷大纲",
            "只依据已确认事实设计大纲，明确引用来源。",
            Outline,
            False,
        ),
        (
            "ChapterPlanner",
            "规划单章",
            "依据当前卷目标和记忆清单规划章节。",
            ChapterPlan,
            False,
        ),
        (
            "DraftWriter",
            "生成当前任务正文草稿",
            "生成正文候选，只能写当前任务的 /drafts。",
            DraftWriterResult,
            True,
        ),
        (
            "ContinuityAuditor",
            "审计连续性",
            "检查人物、时间线、能力和因果冲突，不修改事实。",
            ContinuityReport,
            False,
        ),
        (
            "StyleCritic",
            "审计文风",
            "检查视角、节奏、重复和章节钩子，不修改事实。",
            StyleReport,
            False,
        ),
        (
            "RetentionAuditor",
            "审计章节的读者留存与商业承诺",
            (
                "按七个商业维度审计候选章节，分数必须由正文证据支撑。"
                "问题引用精确 draft 字符范围；不得把主观判断冒充收入预测。"
            ),
            CommercialReport,
            False,
        ),
        (
            "MemoryCurator",
            "生成记忆更新候选",
            "仅生成可追溯记忆更新候选，不写正式 memory。",
            MemoryUpdate,
            False,
        ),
        (
            "ImportAnalyst",
            "分析导入作品",
            "分析导入内容并输出候选结构，不写正式事实。",
            ImportAnalysis,
            False,
        ),
    ]
    return [
        CreativeAgentDefinition(
            name,
            description,
            prompt,
            output_schema,
            write_tools if writable else read_tools,
            draft_write if writable else read_only,
        )
        for name, description, prompt, output_schema, writable in specs
    ]


def subagent_payload_schemas() -> dict[str, type[AgentPayload]]:
    return {
        "MarketStrategist": MarketStrategistPayload,
        "StoryArchitect": StoryArchitectPayload,
        "OutlineArchitect": OutlineArchitectPayload,
        "ChapterPlanner": ChapterPlannerPayload,
        "DraftWriter": DraftWriterPayload,
        "ContinuityAuditor": ContinuityAuditorPayload,
        "StyleCritic": StyleCriticPayload,
        "RetentionAuditor": RetentionAuditorPayload,
        "MemoryCurator": MemoryCuratorPayload,
        "ImportAnalyst": ImportAnalystPayload,
    }


def subagent_input_schemas() -> dict[str, type[AgentInput]]:
    return {
        "MarketStrategist": MarketStrategistInput,
        "StoryArchitect": StoryArchitectInput,
        "OutlineArchitect": OutlineArchitectInput,
        "ChapterPlanner": ChapterPlannerInput,
        "DraftWriter": DraftWriterInput,
        "ContinuityAuditor": ContinuityAuditorInput,
        "StyleCritic": StyleCriticInput,
        "RetentionAuditor": RetentionAuditorInput,
        "MemoryCurator": MemoryCuratorInput,
        "ImportAnalyst": ImportAnalystInput,
    }
