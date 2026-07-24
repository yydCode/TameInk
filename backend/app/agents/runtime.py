import json
import time
from collections.abc import Callable
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import uuid4

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, ValidationError

from app.agents.backend import NovelWorkspaceBackend
from app.agents.context import ContextBuilder, ContextRequest, ManifestSource, RetrievedSnippet
from app.agents.context_compiler import ChapterContextCompiler
from app.agents.contracts import OutputContractError, validate_agent_output_tree
from app.agents.schemas import (
    ChapterDraft,
    CommercialReport,
    ContinuityReport,
    DraftWriterResult,
    ReferencedOutput,
    StyleReport,
)
from app.agents.subagents import CreativeAgentDefinition, build_subagent_definitions
from app.infrastructure.model import build_model
from app.infrastructure.secrets import ApiKeyStore
from app.infrastructure.settings import SettingsRepository
from app.infrastructure.usage import (
    UsageBudgetExceededError,
    UsageCaptureHandler,
    UsageDataMissingError,
    UsageRecorder,
    elapsed_ms,
    utc_now,
)
from app.repositories.canon import CanonRepository
from app.repositories.database import DatabaseRepository
from app.repositories.drafts import DraftRepository
from app.repositories.search import SearchRepository
from app.repositories.workspace import WorkspaceRepository

AGENT_SKILLS = {
    "MarketStrategist": "webnovel-market",
    "StoryArchitect": "webnovel-architecture",
    "OutlineArchitect": "webnovel-architecture",
    "ChapterPlanner": "webnovel-chapter-planning",
    "DraftWriter": "webnovel-drafting",
    "ContinuityAuditor": "webnovel-continuity",
    "StyleCritic": "webnovel-retention",
    "RetentionAuditor": "webnovel-retention",
    "MemoryCurator": "webnovel-memory",
    "ImportAnalyst": "webnovel-continuity",
}


class AgentRunner:
    """受控 Agent 执行器：用 with_structured_output 替代 deepagents 图。

    每个阶段是一次结构化 LLM 调用：编译上下文 → 读 Skill → 组装 prompt →
    with_structured_output → 验证引用 → 记录用量。
    """

    def __init__(
        self,
        workspace: WorkspaceRepository,
        project_id: str,
        settings: SettingsRepository,
        secrets: ApiKeyStore,
        before_invoke: Callable[[str, dict[str, object]], None] | None = None,
        after_invoke: Callable[[str, str | None, dict[str, object]], None] | None = None,
    ) -> None:
        self.workspace = workspace
        self.project_id = project_id
        self.canon = CanonRepository(workspace)
        self.drafts = DraftRepository(workspace)
        self.skill_root = Path(__file__).resolve().parents[3] / "skills"
        backend = NovelWorkspaceBackend(self.canon, self.drafts, project_id, str(uuid4()))
        model_settings = settings.load()
        self.model = build_model(model_settings, secrets.get())
        self.usage_recorder = UsageRecorder.from_environment(model=model_settings.model)
        definitions = build_subagent_definitions()
        self.definitions = {definition.name: definition for definition in definitions}
        self.context_builder = ContextBuilder(
            backend,
            lambda query: [
                hit.as_context()
                for hit in SearchRepository(
                    workspace, DatabaseRepository(workspace)
                ).search_literal(project_id, query)
            ],
        )
        self.context_compiler = ChapterContextCompiler(workspace, project_id)
        self.manifest = self.context_builder.build(self._context_request("Bootstrap", {}))
        self._run_traces: list[dict[str, object]] = []
        self.before_invoke = before_invoke
        self.after_invoke = after_invoke
        self._fanqie_fewshot_cache: str | None = None
        self._fanqie_feature_vector_cache: dict[str, object] | None = None

    def _context_request(self, agent: str, payload: dict[str, object]) -> ContextRequest:
        return self.context_compiler.request_for(agent, payload)

    def invoke(self, agent: str, payload: dict[str, object]) -> object:
        started = time.perf_counter()
        try:
            self.manifest = self.context_builder.build(self._context_request(agent, payload))
        except Exception as error:
            if self.after_invoke is not None:
                self.after_invoke(
                    agent,
                    type(error).__name__,
                    {"phase": "context_compile", "duration_ms": elapsed_ms(started)},
                )
            raise
        diagnostics = self._diagnostic_context(started)
        if self.before_invoke is not None:
            self.before_invoke(agent, diagnostics)
        definition = self.definitions.get(agent)
        if definition is None:
            raise OutputContractError("OUTPUT_SUBAGENT_UNKNOWN")
        try:
            output = self._translate(
                agent,
                payload,
                self._invoke_stage(definition, payload),
            )
        except Exception as error:
            if self.after_invoke is not None:
                self.after_invoke(
                    agent,
                    type(error).__name__,
                    {**self._diagnostic_context(started), "phase": "agent_execute"},
                )
            raise
        if self.after_invoke is not None:
            self.after_invoke(
                agent,
                None,
                {**self._diagnostic_context(started), "phase": "agent_execute"},
            )
        return output

    def _diagnostic_context(self, started: float) -> dict[str, object]:
        return {
            "stage": self.manifest.stage,
            "source_count": len(self.manifest.sources),
            "retrieved_count": len(self.manifest.retrieved),
            "query_count": len(self.manifest.queries),
            "total_characters": self.manifest.total_characters,
            "source_paths": sorted(self.manifest.allowed_paths()),
            "duration_ms": elapsed_ms(started),
        }

    def _invoke_stage(
        self,
        definition: CreativeAgentDefinition,
        payload: dict[str, object],
    ) -> ReferencedOutput:
        agent = definition.name
        skill = AGENT_SKILLS[agent]
        skill_file = self.skill_root / skill / "SKILL.md"
        skill_hash = sha256(skill_file.read_bytes()).hexdigest()
        skill_content = skill_file.read_text(encoding="utf-8")
        system_prompt = self._direct_system_prompt(definition, payload)
        full_system_prompt = f"{skill_content}\n\n{system_prompt}"
        schema = self._model_output_schema(definition, self.manifest)
        capture = UsageCaptureHandler() if self.usage_recorder is not None else None
        started_at = utc_now()
        started = time.perf_counter()
        try:
            structured_llm = self.model.with_structured_output(schema, method="function_calling")
            config: RunnableConfig = {}
            if capture is not None:
                config["callbacks"] = [capture]
            messages = [
                SystemMessage(content=full_system_prompt),
                HumanMessage(
                    content=json.dumps(
                        {
                            "payload": payload,
                            "context_manifest": self.manifest.model_dump(mode="json"),
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                ),
            ]
            raw_output = structured_llm.invoke(messages, config=config)
            if raw_output is None:
                raise OutputContractError("AGENT_OUTPUT_INVALID")
            if isinstance(raw_output, BaseModel):
                raw_output = raw_output.model_dump(mode="json")
            if not isinstance(raw_output, dict):
                raise OutputContractError("AGENT_OUTPUT_INVALID")
            try:
                enriched = self._attach_context_references(raw_output)
                if definition.output_schema is CommercialReport:
                    enriched = self._attach_commercial_score(enriched)
                    enriched = self._inject_fanqie_baseline_issues(enriched, payload)
                output = definition.output_schema.model_validate(enriched)
            except (ValidationError, ValueError, TypeError) as error:
                raise OutputContractError("AGENT_OUTPUT_INVALID") from error
            usage = capture.require() if capture is not None else None
            if self.usage_recorder is not None:
                self.usage_recorder.record(
                    agent=agent,
                    started_at=started_at,
                    duration_ms=elapsed_ms(started),
                    status="success",
                    usage=usage,
                )
            validated = validate_agent_output_tree(output, self.manifest)
            self._record_trace(agent, skill, skill_hash, started, status="success")
            return validated
        except Exception as error:
            self._record_trace(
                agent,
                skill,
                skill_hash,
                started,
                status="failed",
                error_code=type(error).__name__,
            )
            if self.usage_recorder is not None and not isinstance(error, UsageBudgetExceededError):
                try:
                    self.usage_recorder.record(
                        agent=agent,
                        started_at=started_at,
                        duration_ms=elapsed_ms(started),
                        status="failed",
                        usage=capture.usage if capture is not None else None,
                        error_code=type(error).__name__,
                    )
                except (UsageBudgetExceededError, UsageDataMissingError):
                    pass
            raise

    def run_traces(self) -> list[dict[str, object]]:
        return deepcopy(self._run_traces)

    def _record_trace(
        self,
        agent: str,
        skill: str,
        skill_hash: str,
        started: float,
        *,
        status: str,
        error_code: str | None = None,
    ) -> None:
        self._run_traces.append(
            {
                "agent": agent,
                "skill": skill,
                "skill_sha256": skill_hash,
                "stage": self.manifest.stage,
                "source_paths": sorted(self.manifest.allowed_paths()),
                "queries": list(self.manifest.queries),
                "total_characters": self.manifest.total_characters,
                "duration_ms": elapsed_ms(started),
                "status": status,
                "error_code": error_code,
            }
        )

    @staticmethod
    def _model_output_schema(
        definition: CreativeAgentDefinition,
        manifest: object | None = None,
    ) -> dict[str, Any]:
        schema = deepcopy(definition.output_schema.model_json_schema())

        def remove_references(node: object) -> None:
            if isinstance(node, dict):
                properties = node.get("properties")
                if isinstance(properties, dict) and "references" in properties:
                    del properties["references"]
                    required = node.get("required")
                    if isinstance(required, list):
                        node["required"] = [item for item in required if item != "references"]
                for value in node.values():
                    remove_references(value)
            elif isinstance(node, list):
                for value in node:
                    remove_references(value)

        remove_references(schema)
        if definition.output_schema is CommercialReport:
            properties = schema.get("properties")
            if isinstance(properties, dict):
                properties.pop("total_score", None)
            required = schema.get("required")
            if isinstance(required, list):
                schema["required"] = [item for item in required if item != "total_score"]
        properties = schema.get("properties")
        if not isinstance(properties, dict):
            raise OutputContractError("AGENT_OUTPUT_SCHEMA_INVALID")
        allowed_paths: list[str] = []
        if hasattr(manifest, "allowed_paths"):
            allowed_paths = sorted(manifest.allowed_paths())
        path_schema: dict[str, Any] = {"type": "string"}
        if allowed_paths:
            path_schema["enum"] = allowed_paths
        properties["context_reference_paths"] = {
            "type": "array",
            "items": path_schema,
            "minItems": 1,
            "uniqueItems": True,
        }
        required = schema.setdefault("required", [])
        if isinstance(required, list) and "context_reference_paths" not in required:
            required.append("context_reference_paths")
        return schema

    @staticmethod
    def _attach_commercial_score(raw_output: dict[str, Any]) -> dict[str, Any]:
        dimensions = raw_output.get("dimensions")
        if not isinstance(dimensions, list) or not dimensions:
            return raw_output
        scores: list[int] = []
        for item in dimensions:
            if not isinstance(item, dict):
                return raw_output
            score = item.get("score")
            if not isinstance(score, int) or isinstance(score, bool):
                return raw_output
            scores.append(score)
        return {
            **raw_output,
            "total_score": round(sum(scores) / len(scores)),
        }

    def _inject_fanqie_baseline_issues(
        self,
        raw_output: dict[str, Any],
        payload: dict[str, object],
    ) -> dict[str, Any]:
        """程序化基线偏离校验：对照番茄 TOP50 特征向量，追加 warning 级 issue。

        仅在 platform=fanqie 且特征向量已加载时执行。
        检查项：单章字数是否在 2000-3500 铁律内；开篇钩子类型是否属于主流。
        偏离时追加 CommercialIssue（warning 级，不阻塞 pass/revise 决策）。
        """
        platform = payload.get("platform")
        if platform is None:
            directive = payload.get("directive")
            if isinstance(directive, dict):
                platform = directive.get("platform")
        if platform != "fanqie":
            return raw_output
        vector = self._load_fanqie_feature_vector()
        if not vector:
            return raw_output
        draft = payload.get("draft")
        if not isinstance(draft, str) or not draft:
            return raw_output
        # 取一个可用的 manifest 路径作为 references 基底
        allowed = sorted(self.manifest.allowed_paths())
        if not allowed:
            return raw_output
        ref_path = allowed[0]
        issues = list(raw_output.get("issues") or [])
        # 1. 字数检查（番茄单章铁律 2000-3500）
        word_count = len(draft.replace(" ", "").replace("\n", ""))
        if word_count < 2000 or word_count > 3500:
            quote = draft[: min(50, len(draft))]
            issues.append(
                {
                    "id": f"baseline-wc-{word_count}",
                    "references": [
                        {
                            "path": ref_path,
                            "location": "baseline deviation check",
                            "quote": f"字数 {word_count} 偏离番茄单章铁律 2000-3500",
                        }
                    ],
                    "severity": "warning",
                    "dimension": "pacing_density",
                    "description": (
                        f"正文 {word_count} 字，偏离番茄单章铁律 2000-3500。"
                        "TOP50 爆款均遵循此铁律，建议调整篇幅。"
                    ),
                    "citation": {
                        "source": "draft",
                        "location": f"chars:0-{min(50, len(draft))}",
                        "quote": quote,
                    },
                }
            )
        # 2. 开篇钩子类型检查（对照 TOP50 主流钩子）
        dominant_hook = vector.get("dominant_hook_type") or "unknown"
        if dominant_hook and dominant_hook != "unknown":
            head = draft[:200]
            detected = self._classify_draft_hook(head)
            if detected != "unknown" and detected != dominant_hook:
                hook_dist = vector.get("hook_type_distribution") or {}
                total = vector.get("total_books") or 0
                dominant_pct = 0
                if total and isinstance(hook_dist, dict):
                    dom_count = hook_dist.get(dominant_hook, 0)
                    if isinstance(dom_count, int):
                        dominant_pct = round(dom_count * 100 / total)
                quote = head[: min(50, len(head))]
                issues.append(
                    {
                        "id": f"baseline-hook-{detected}",
                        "references": [
                            {
                                "path": ref_path,
                                "location": "baseline deviation check",
                                "quote": (
                                    f"开篇钩子={detected}，TOP50 主流={dominant_hook}"
                                    f"（占 {dominant_pct}%）"
                                ),
                            }
                        ],
                        "severity": "warning",
                        "dimension": "first_screen_hook",
                        "description": (
                            f"开篇钩子类型为 {detected}，但番茄 TOP50 主流为 "
                            f"{dominant_hook}（占 {dominant_pct}%）。"
                            "非主流开篇可能在首屏留存上吃亏，建议参照主流钩子调整。"
                        ),
                        "citation": {
                            "source": "draft",
                            "location": f"chars:0-{min(200, len(draft))}",
                            "quote": quote,
                        },
                    }
                )
        return {**raw_output, "issues": issues}

    @staticmethod
    def _classify_draft_hook(head_text: str) -> str:
        """对正文章首 200 字做开篇钩子类型分类（与 fetcher 口径一致）。"""
        if not head_text:
            return "unknown"
        from app.infrastructure.fanqie_bestseller_fetcher import _OPENING_HOOK_KEYWORDS

        for hook_type, keywords in _OPENING_HOOK_KEYWORDS.items():
            if any(kw in head_text for kw in keywords):
                return hook_type
        return "unknown"

    def _attach_context_references(self, raw_output: dict[str, Any]) -> dict[str, Any]:
        selected = raw_output.get("context_reference_paths")
        if (
            not isinstance(selected, list)
            or not selected
            or not all(isinstance(path, str) for path in selected)
        ):
            raise OutputContractError("CONTEXT_REFERENCE_SELECTION_INVALID")
        allowed = self.manifest.allowed_paths()
        if any(path not in allowed for path in selected):
            raise OutputContractError("REFERENCE_SOURCE_UNKNOWN")
        references: list[dict[str, str]] = []
        observed: set[tuple[str, str, str]] = set()
        context_sources: list[ManifestSource | RetrievedSnippet] = [
            *self.manifest.sources,
            *self.manifest.retrieved,
        ]
        for source in context_sources:
            if source.path not in selected:
                continue
            key = (source.path, source.location, source.quote)
            if key in observed:
                continue
            observed.add(key)
            references.append(
                {"path": source.path, "location": source.location, "quote": source.quote}
            )
        if not references:
            raise OutputContractError("CONTEXT_SOURCE_MISSING")
        enriched = {
            key: value for key, value in raw_output.items() if key != "context_reference_paths"
        }
        enriched["references"] = references
        for field in ("issues", "revisions"):
            children = enriched.get(field)
            if isinstance(children, list):
                enriched[field] = [
                    {**child, "references": references} if isinstance(child, dict) else child
                    for child in children
                ]
        return enriched

    @staticmethod
    def _platform_pacing_hint(payload: dict[str, object]) -> str:
        """根据 commercial_profile 平台生成节奏提示，注入 ChapterPlanner 的 direct prompt。"""
        platform = payload.get("platform")
        if platform is None:
            directive = payload.get("directive")
            if isinstance(directive, dict):
                platform = directive.get("platform")
        if platform == "fanqie":
            return (
                " 平台=番茄：单章 2000-3000 字铁律；"
                "开篇必须 conflict 剧情切入（场景切入仅限大神，禁用）；"
                "前 7 行（手机一屏）必须出现钩子；"
                "每 3 章一小爽，每 10 章一大爽；断章必须卡关键节点。"
            )
        if platform == "qidian":
            return (
                " 平台=起点：单章 3000 字左右；"
                "开篇可 scene 场景切入；前 15 行内出现钩子；"
                "每 5 章一小爽，每 15 章一大爽。"
            )
        return ""

    def _retention_fanqie_hint(self, payload: dict[str, object]) -> str:
        """番茄平台专属：RetentionAuditor 必须额外给出 4 项番茄商业维度评分。"""
        platform = payload.get("platform")
        if platform is None:
            directive = payload.get("directive")
            if isinstance(directive, dict):
                platform = directive.get("platform")
        if platform != "fanqie":
            return ""
        base_hint = (
            " 平台=番茄：除 7 项基础维度外，必须额外给出 4 项番茄专属维度评分——"
            "first_screen_hook（前 7 行手机一屏的钩子强度：是否有具体违和细节/动作而非主观感受）、"
            "pacing_density（节奏密度：无效环境铺垫与总结性解释占比越低分越高）、"
            "chapter_end_cliffhanger（断章质量：是否卡在身份/真相/反派行动节点，禁止自然收尾）、"
            "character_contrast（人设反差：主角与关键 NPC 是否有可被读者记住的反差锚点）。"
            "每个维度 score 必须基于正文 citation 给出，禁止主观印象打分。"
        )
        vector = self._load_fanqie_feature_vector()
        if not vector:
            return base_hint
        stats = vector.get("word_count_stats") or {}
        top_genres = vector.get("top_genres") or []
        dominant_hook = vector.get("dominant_hook_type") or "unknown"
        hook_dist = vector.get("hook_type_distribution") or {}
        dominant_hook_pct = 0
        total_books = vector.get("total_books") or 0
        if total_books and isinstance(hook_dist, dict):
            dominant_count = hook_dist.get(dominant_hook, 0)
            if isinstance(dominant_count, int) and isinstance(total_books, int):
                dominant_hook_pct = round(dominant_count * 100 / total_books)
        median_wc = stats.get("median", 0) if isinstance(stats, dict) else 0
        return (
            base_hint
            + f"\n参考番茄 TOP50 真实榜单（扫描日期 {vector.get('scan_date', 'N/A')}，"
            f"去重后 {total_books} 本）："
            f"- 主流题材 Top5：{', '.join(str(g) for g in top_genres[:5])}。"
            f"- 总书字数中位数：{round(median_wc / 10000, 1)} 万字。"
            f"- 主流开篇钩子：{dominant_hook}（占 {dominant_hook_pct}%）。"
            "评分应对照此基线：题材偏离主流应在 differentiation 维度扣分；"
            "开篇钩子非主流应在 first_screen_hook 维度说明。"
        )

    def _load_fanqie_feature_vector(self) -> dict[str, object] | None:
        """加载并缓存番茄爆款特征向量。

        读取 skills/webnovel-studio/references/fanqie-examples/fanqie_feature_vector_latest.json。
        文件不存在时返回 None（降级为现有硬编码 hint，向后兼容）。
        """
        if self._fanqie_feature_vector_cache is not None:
            return self._fanqie_feature_vector_cache
        vector_path = (
            self.skill_root / "webnovel-studio" / "references"
            / "fanqie-examples" / "fanqie_feature_vector_latest.json"
        )
        if not vector_path.is_file():
            self._fanqie_feature_vector_cache = {}
            return None
        try:
            data = json.loads(vector_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self._fanqie_feature_vector_cache = {}
            return None
        if not isinstance(data, dict):
            self._fanqie_feature_vector_cache = {}
            return None
        self._fanqie_feature_vector_cache = data
        return data

    def _load_fanqie_fewshot(self) -> str:
        """加载并缓存番茄爆款黄金三章参考库的结构拆解内容。

        读取 skills/webnovel-studio/references/fanqie-examples/ 下所有
        `*-pattern.md` 文件，拼接为 ChapterPlanner / DraftWriter 的 few-shot 参考。
        仅注入结构模板与平台铁律，禁止逐字模仿原文。
        """
        if self._fanqie_fewshot_cache is not None:
            return self._fanqie_fewshot_cache
        examples_dir = self.skill_root / "webnovel-studio" / "references" / "fanqie-examples"
        if not examples_dir.is_dir():
            self._fanqie_fewshot_cache = ""
            return ""
        parts: list[str] = []
        for path in sorted(examples_dir.glob("*-pattern.md")):
            try:
                content = path.read_text(encoding="utf-8").strip()
            except OSError:
                continue
            if content:
                parts.append(f"--- 参考：{path.stem} ---\n{content}")
        self._fanqie_fewshot_cache = "\n\n".join(parts)
        return self._fanqie_fewshot_cache

    def _fanqie_fewshot_hint(self, payload: dict[str, object]) -> str:
        """为番茄平台的 ChapterPlanner / DraftWriter 注入黄金三章 few-shot 模板。"""
        platform = payload.get("platform")
        if platform is None:
            directive = payload.get("directive")
            if isinstance(directive, dict):
                platform = directive.get("platform")
        if platform != "fanqie":
            return ""
        fewshot = self._load_fanqie_fewshot()
        if not fewshot:
            return ""
        return (
            "\n\n## 番茄爆款黄金三章结构参考（few-shot）\n"
            "以下结构拆解来自番茄平台现象级作品，仅供借鉴结构骨架，"
            "禁止逐字模仿原文情节、人物、对话、设定。\n\n"
            + fewshot
            + "\n\n## 应用要求\n"
            "1. 计划必须显式对应一种开篇切入方式（反差人设/异常事件/危机即开篇）。\n"
            "2. 前 7 行必须落实首屏钩子——给出违和细节或动作，禁止主观感受。\n"
            "3. 章末必须断在身份/真相/反派行动三个节点之一，禁止自然收尾。\n"
        )

    def _direct_system_prompt(
        self, definition: CreativeAgentDefinition, payload: dict[str, object]
    ) -> str:
        common = (
            f"你直接执行 {definition.name}，不要委派。{definition.system_prompt}"
            "严格按 response schema 输出。context_reference_paths 只选择实际支持结论的"
            "context_manifest 正式来源路径；references 由系统据此写入，模型不得虚构。"
        )
        if definition.name == "RetentionAuditor":
            fanqie_hint = self._retention_fanqie_hint(payload)
            return (
                common + "正文证据只放 citation；每个 issue.quote 必须是正文中唯一存在的完整原文。"
                "total_score 必须等于所有维度整数分数的 Python round 平均值。"
                + fanqie_hint
            )
        if definition.name in {"ContinuityAuditor", "StyleCritic"}:
            return (
                common + "正文证据只放 citation；每个 issue.quote 必须是正文中唯一存在的完整原文。"
                "没有可证实问题时 issues 必须为空，不得为了凑数制造问题。"
            )
        if definition.name == "ChapterPlanner":
            pacing = self._platform_pacing_hint(payload)
            fewshot = self._fanqie_fewshot_hint(payload)
            return (
                common + "计划必须把用户要求的篇幅、开篇事件、核心兑现、能力代价和章末钩子"
                "拆成可执行场景，不得把正文写作任务改成背景说明。"
                + pacing
                + " 必须显式填写 target_word_count（番茄单章铁律 2000-3000 字）、"
                "opening_hook_style（番茄默认 conflict 剧情切入，禁止 scene 场景切入）、"
                "scenes_count（番茄默认 1，最多 2）、chapter_end_hook（断章钩子，"
                "卡在关键节点如亮身份前/反派行动前/悬念揭晓前，禁止自然收尾）。"
                + fewshot
            )
        if definition.name == "DraftWriter":
            if "draft" in payload:
                return (
                    common + "当前是局部修订模式：markdown 必须为 null，revisions 至少一项。"
                    "每项 revision.issue_id 必须来自 payload.issues；target 必须等于 "
                    "citation.location；citation 必须与对应 issue 完全相同；"
                    "replacement 只替换该局部片段，不得重写整章。"
                )
            fewshot = self._fanqie_fewshot_hint(payload)
            return (
                common + "当前是新稿模式：markdown 必须是完整章节正文，revisions 必须为空。"
                "严格遵守 plan.target_word_count（番茄单章 2000-3000 字铁律，不得超标）；"
                "开篇首句即冲突，按 plan.opening_hook_style 切入；"
                "前 7 行（手机一屏）内必须出现第一个钩子，禁止环境铺垫开场；"
                "单章只写 plan.scenes_count 个核心场景，不要切碎成多节；"
                "章末必须按 plan.chapter_end_hook 断在关键节点，不要自然收尾；"
                "每句必须推进冲突或人设，删掉所有无效环境描写和总结性解释；"
                "不使用二级分节标题；能力规则必须通过动作和后果展示，不写设定说明。"
                + fewshot
            )
        if definition.name == "MemoryCurator":
            return (
                common + "只提取会影响后续连续性的持久事实。stable_id 使用稳定英文短横线格式；"
                "citation 必须精确指向 payload.draft 的字符范围和原文；"
                "没有持久更新时 updates 为空。"
            )
        return common

    @staticmethod
    def _translate(agent: str, payload: dict[str, object], output: ReferencedOutput) -> object:
        if agent == "DraftWriter":
            if not isinstance(output, DraftWriterResult):
                raise RuntimeError("AGENT_OUTPUT_INVALID")
            if "draft" in payload:
                return output.revisions
            if output.markdown is None:
                raise RuntimeError("AGENT_OUTPUT_INVALID")
            return ChapterDraft(
                id=output.id,
                chapter_id=output.chapter_id,
                markdown=output.markdown,
                references=output.references,
            )
        if agent == "ContinuityAuditor":
            if not isinstance(output, ContinuityReport):
                raise RuntimeError("AGENT_OUTPUT_INVALID")
            return output.issues
        if agent == "StyleCritic":
            if not isinstance(output, StyleReport):
                raise RuntimeError("AGENT_OUTPUT_INVALID")
            return output.issues
        if agent == "RetentionAuditor":
            if not isinstance(output, CommercialReport):
                raise RuntimeError("AGENT_OUTPUT_INVALID")
            return output
        return output


# 向后兼容别名
DeepAgentRunner = AgentRunner
