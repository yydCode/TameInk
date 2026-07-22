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
    MemoryCuration,
    Outline,
    ReferencedOutput,
    SkillExecutionContract,
    StorySetting,
    StyleReport,
)
from app.agents.skills import P0Skill, skill_definition
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


@dataclass(frozen=True)
class P0SkillAgentDefinition:
    name: str
    description: str
    system_prompt: str
    skills: frozenset[P0Skill]
    output_schema: type[SkillExecutionContract]
    tools: list[BaseTool]
    permissions: list[FilesystemPermission]


def build_p0_skill_definitions(backend: NovelWorkspaceBackend) -> list[P0SkillAgentDefinition]:
    read_tools = build_repository_tools(backend, allow_draft_write=False)
    read_only = [FilesystemPermission(operations=["write"], paths=["/**"], mode="deny")]
    specs: list[tuple[str, str, str, frozenset[P0Skill]]] = [
        (
            "Researcher",
            "整理平台、题材与对标证据",
            "只整理可引用的公开或作者提供材料；区分事实、方法与未验证假设，"
            "不能把观察结论写成正式故事事实。",
            frozenset({"webnovel-research-genre"}),
        ),
        (
            "StoryEditor",
            "设计作者待确认的故事方向",
            "只生成读者契约、故事引擎、滚动故事卡或收尾规划候选。"
            "人物关键动机、主线转向和不可逆变化必须返回待作者决策项。",
            frozenset(
                {
                    "webnovel-design-reader-contract",
                    "webnovel-design-story-engine",
                    "webnovel-plan-rolling-story",
                    "webnovel-plan-ending",
                }
            ),
        ),
        (
            "ChapterPlanner",
            "把已确认故事卡拆成场景执行单元",
            "只规划当前章节。发现关键选择、缺失承诺或正式事实冲突时停止并要求作者决策。",
            frozenset({"webnovel-plan-chapter"}),
        ),
        (
            "DraftWriter",
            "执行已确认范围内的正文候选",
            "只生成正文、场景、对话或局部改写候选；不得新增未授权关键事实或改变人物核心选择。",
            frozenset({"webnovel-draft"}),
        ),
        (
            "ContinuityAuditor",
            "审计正式事实、因果与时间线",
            "只报告可由正式来源和候选正文共同证明的冲突；没有问题时返回空诊断候选。",
            frozenset({"webnovel-audit"}),
        ),
        (
            "PromiseAuditor",
            "审计读者契约、期待与兑现",
            "只报告承诺、读者问题和实际回报之间有引用证据的偏差，不用商业总分替代判断。",
            frozenset({"webnovel-audit"}),
        ),
        (
            "SceneAuditor",
            "审计人物选择、场景用途与对话行动",
            "只报告有精确正文证据的场景问题；不为追求固定公式而制造问题。",
            frozenset({"webnovel-audit"}),
        ),
        (
            "CognitiveLoadAuditor",
            "审计信息、视角与理解成本",
            "只报告读者无法依据当前上下文理解的具体位置，并提供证据和可选修订方向。",
            frozenset({"webnovel-audit"}),
        ),
        (
            "OpeningAuditor",
            "用18元素清单审核开篇结构",
            "逐条核对开篇18元素清单，对每项给出通过/未通过与引用证据；"
            "只做结构化开篇诊断，不输出商业总分或平台推荐判断。",
            frozenset({"webnovel-opening-audit"}),
        ),
        (
            "PoisonCheckAuditor",
            "检测会导致读者弃书的结构性毒点",
            "按毒点清单逐条核查正文；有证据才报告，没有毒点时返回空诊断；"
            "不为凑数制造问题，不输出商业判断。",
            frozenset({"webnovel-poison-check"}),
        ),
        (
            "MemoryCurator",
            "从确认正文提取实际状态候选",
            "只从作者确认的正文提取实际事件、人物变化和期待兑现；候选正文与推测不得进入结果。",
            frozenset({"webnovel-curate-memory"}),
        ),
    ]
    return [
        P0SkillAgentDefinition(
            name=name,
            description=description,
            system_prompt=prompt,
            skills=skills,
            output_schema=SkillExecutionContract,
            tools=read_tools,
            permissions=read_only,
        )
        for name, description, prompt, skills in specs
    ]


def select_p0_skill_agent(
    skill: P0Skill,
    payload: dict[str, object],
    definitions: list[P0SkillAgentDefinition],
) -> P0SkillAgentDefinition:
    requested_agent = skill_definition(skill).agent
    if skill == "webnovel-audit":
        audit_kind = payload.get("audit_kind")
        audit_agents = {
            "continuity": "ContinuityAuditor",
            "promise": "PromiseAuditor",
            "scene": "SceneAuditor",
            "cognitive_load": "CognitiveLoadAuditor",
        }
        if not isinstance(audit_kind, str) or audit_kind not in audit_agents:
            raise ValueError("AUDIT_KIND_INVALID")
        requested_agent = audit_agents[audit_kind]
    if requested_agent is None:
        raise ValueError("SKILL_EXECUTION_UNSUPPORTED")
    matches = [definition for definition in definitions if definition.name == requested_agent]
    if len(matches) != 1 or skill not in matches[0].skills:
        raise ValueError("SKILL_AGENT_MISMATCH")
    return matches[0]


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
            MemoryCuration,
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
