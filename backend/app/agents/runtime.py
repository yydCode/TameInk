import json
import time
from collections.abc import Callable
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from deepagents import FilesystemPermission, create_deep_agent
from langchain.agents.structured_output import ToolStrategy
from pydantic import BaseModel, ValidationError

from app.agents.backend import NovelWorkspaceBackend
from app.agents.context import ContextBuilder, ContextRequest, ManifestSource, RetrievedSnippet
from app.agents.context_compiler import ChapterContextCompiler
from app.agents.contracts import OutputContractError, validate_agent_output_tree
from app.agents.orchestrator import register_model_profile
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


class DeepAgentRunner:
    def __init__(
        self,
        workspace: WorkspaceRepository,
        project_id: str,
        settings: SettingsRepository,
        secrets: ApiKeyStore,
        before_invoke: Callable[[str], None] | None = None,
        after_invoke: Callable[[str, str | None], None] | None = None,
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
        definitions = build_subagent_definitions(backend)
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

    def _context_request(self, agent: str, payload: dict[str, object]) -> ContextRequest:
        return self.context_compiler.request_for(agent, payload)

    def invoke(self, agent: str, payload: dict[str, object]) -> object:
        if self.before_invoke is not None:
            self.before_invoke(agent)
        self.manifest = self.context_builder.build(self._context_request(agent, payload))
        backend = NovelWorkspaceBackend(
            self.canon,
            self.drafts,
            self.project_id,
            str(uuid4()),
            skill_root=self.skill_root,
            read_allowlist=self.manifest.allowed_paths(),
        )
        definitions = {
            definition.name: definition for definition in build_subagent_definitions(backend)
        }
        definition = definitions.get(agent)
        if definition is None:
            raise OutputContractError("OUTPUT_SUBAGENT_UNKNOWN")
        try:
            output = self._translate(
                agent,
                payload,
                self._invoke_stage(definition, payload, backend),
            )
        except Exception as error:
            if self.after_invoke is not None:
                self.after_invoke(agent, type(error).__name__)
            raise
        if self.after_invoke is not None:
            self.after_invoke(agent, None)
        return output

    def _invoke_stage(
        self,
        definition: CreativeAgentDefinition,
        payload: dict[str, object],
        backend: NovelWorkspaceBackend,
    ) -> ReferencedOutput:
        agent = definition.name
        skill = AGENT_SKILLS[agent]
        skill_path = f"/skills/{skill}/SKILL.md"
        skill_hash = sha256((self.skill_root / skill / "SKILL.md").read_bytes()).hexdigest()
        system_prompt = self._direct_system_prompt(definition, payload)
        register_model_profile()
        graph = create_deep_agent(
            model=self.model,
            tools=[],
            system_prompt=(
                f"{system_prompt} 开始执行前必须先调用 read_file 读取 {skill_path}，"
                "并遵循其中引用的必要规则。不得读取 context_manifest 未声明的作品来源。"
            ),
            skills=["/skills"],
            permissions=[FilesystemPermission(operations=["write"], paths=["/**"], mode="deny")],
            backend=backend,
            response_format=ToolStrategy(
                self._model_output_schema(definition, self.manifest), handle_errors=False
            ),
            name=agent,
        )
        capture = UsageCaptureHandler() if self.usage_recorder is not None else None
        started_at = utc_now()
        started = time.perf_counter()
        try:
            config: dict[str, Any] = {"recursion_limit": 12}
            if capture is not None:
                config["callbacks"] = [capture]
            result = graph.invoke(
                cast(
                    Any,
                    {
                        "messages": [
                            {
                                "role": "user",
                                "content": json.dumps(
                                    {
                                        "payload": payload,
                                        "context_manifest": self.manifest.model_dump(mode="json"),
                                    },
                                    ensure_ascii=False,
                                    separators=(",", ":"),
                                ),
                            }
                        ]
                    },
                ),
                config=cast(Any, config),
            )
            if not self._skill_was_loaded(result, skill_path):
                raise OutputContractError("AGENT_SKILL_NOT_LOADED")
            raw_output = result.get("structured_response")
            if isinstance(raw_output, BaseModel):
                raw_output = raw_output.model_dump(mode="json")
            if not isinstance(raw_output, dict):
                raise OutputContractError("AGENT_OUTPUT_INVALID")
            try:
                enriched = self._attach_context_references(raw_output)
                if definition.output_schema is CommercialReport:
                    enriched = self._attach_commercial_score(enriched)
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
    def _skill_was_loaded(result: object, skill_path: str) -> bool:
        if not isinstance(result, dict):
            return False
        messages = result.get("messages")
        if not isinstance(messages, list):
            return False
        matching_call_ids: set[str] = set()
        for message in messages:
            for call in getattr(message, "tool_calls", []) or []:
                if call.get("name") != "read_file":
                    continue
                arguments = call.get("args", {})
                call_id = call.get("id")
                if (
                    isinstance(arguments, dict)
                    and arguments.get("file_path") == skill_path
                    and isinstance(call_id, str)
                ):
                    matching_call_ids.add(call_id)
        return any(
            getattr(message, "name", None) == "read_file"
            and getattr(message, "status", None) == "success"
            and getattr(message, "tool_call_id", None) in matching_call_ids
            for message in messages
        )

    @staticmethod
    def _direct_system_prompt(
        definition: CreativeAgentDefinition, payload: dict[str, object]
    ) -> str:
        common = (
            f"你直接执行 {definition.name}，不要委派。{definition.system_prompt}"
            "严格按 response schema 输出。context_reference_paths 只选择实际支持结论的"
            "context_manifest 正式来源路径；references 由系统据此写入，模型不得虚构。"
        )
        if definition.name == "RetentionAuditor":
            return (
                common + "正文证据只放 citation；每个 issue.quote 必须是正文中唯一存在的完整原文。"
                "total_score 必须等于七项整数分数的 Python round 平均值。"
            )
        if definition.name in {"ContinuityAuditor", "StyleCritic"}:
            return (
                common + "正文证据只放 citation；每个 issue.quote 必须是正文中唯一存在的完整原文。"
                "没有可证实问题时 issues 必须为空，不得为了凑数制造问题。"
            )
        if definition.name == "ChapterPlanner":
            return (
                common + "计划必须把用户要求的篇幅、开篇事件、核心兑现、能力代价和章末钩子"
                "拆成可执行场景，不得把正文写作任务改成背景说明。"
            )
        if definition.name == "DraftWriter":
            if "draft" in payload:
                return (
                    common + "当前是局部修订模式：markdown 必须为 null，revisions 至少一项。"
                    "每项 revision.issue_id 必须来自 payload.issues；target 必须等于 "
                    "citation.location；citation 必须与对应 issue 完全相同；"
                    "replacement 只替换该局部片段，不得重写整章。"
                )
            return (
                common + "当前是新稿模式：markdown 必须是完整章节正文，revisions 必须为空。"
                "严格遵守 plan 中的字符数和场景顺序；只保留一个章标题，不使用二级分节标题；"
                "能力规则必须通过动作和后果展示，不写设定说明。"
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
