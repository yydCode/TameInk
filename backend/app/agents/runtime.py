import json
import time
from copy import deepcopy
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from app.agents.backend import NovelWorkspaceBackend
from app.agents.context import ContextBuilder, ContextRequest, ManifestSource, RetrievedSnippet
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


class DeepAgentRunner:
    def __init__(
        self,
        workspace: WorkspaceRepository,
        project_id: str,
        settings: SettingsRepository,
        secrets: ApiKeyStore,
    ) -> None:
        self.workspace = workspace
        self.project_id = project_id
        backend = NovelWorkspaceBackend(
            CanonRepository(workspace), DraftRepository(workspace), project_id, str(uuid4())
        )
        model_settings = settings.load()
        self.model = build_model(model_settings, secrets.get())
        self.usage_recorder = UsageRecorder.from_environment(model=model_settings.model)
        definitions = build_subagent_definitions(backend)
        self.definitions = {definition.name: definition for definition in definitions}
        self.manifest = ContextBuilder(
            backend,
            lambda query: [
                hit.as_context()
                for hit in SearchRepository(workspace, DatabaseRepository(workspace)).search(
                    project_id, query
                )
            ],
        ).build(self._context_request())

    def _context_request(self) -> ContextRequest:
        project = self.workspace.project_path(self.project_id)
        candidates = [
            "project.yaml",
            "canon/commercial.yaml",
            "canon/world/setting.md",
            "canon/outline.md",
            "canon/volumes/1.md",
            "memory/summaries/book.md",
        ]
        existing = [path for path in candidates if (project / Path(path)).is_file()]
        return ContextRequest(
            fixed_rules=existing,
            volume=[],
            summaries=[],
            entities=[],
            fts_queries=[],
        )

    def invoke(self, agent: str, payload: dict[str, object]) -> object:
        return self._translate(agent, payload, self._invoke_direct(agent, payload))

    def _invoke_direct(
        self, agent: str, payload: dict[str, object]
    ) -> ReferencedOutput:
        definition = self.definitions.get(agent)
        if definition is None:
            raise OutputContractError("OUTPUT_SUBAGENT_UNKNOWN")
        system_prompt = self._direct_system_prompt(definition, payload)
        structured = self.model.with_structured_output(
            self._model_output_schema(definition), method="function_calling"
        )
        capture = UsageCaptureHandler() if self.usage_recorder is not None else None
        if capture is not None:
            structured = structured.with_config({"callbacks": [capture]})
        started_at = utc_now()
        started = time.perf_counter()
        try:
            raw_output = structured.invoke(
                [
                    {"role": "system", "content": system_prompt},
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
                    },
                ]
            )
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
            return validate_agent_output_tree(output, self.manifest)
        except Exception as error:
            if self.usage_recorder is not None and not isinstance(
                error, UsageBudgetExceededError
            ):
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

    @staticmethod
    def _model_output_schema(definition: CreativeAgentDefinition) -> dict[str, Any]:
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
        references: list[dict[str, str]] = []
        observed: set[tuple[str, str, str]] = set()
        context_sources: list[ManifestSource | RetrievedSnippet] = [
            *self.manifest.sources,
            *self.manifest.retrieved,
        ]
        for source in context_sources:
            key = (source.path, source.location, source.quote)
            if key in observed:
                continue
            observed.add(key)
            references.append(
                {"path": source.path, "location": source.location, "quote": source.quote}
            )
        if not references:
            raise OutputContractError("CONTEXT_SOURCE_MISSING")
        enriched = {**raw_output, "references": references}
        for field in ("issues", "revisions"):
            children = enriched.get(field)
            if isinstance(children, list):
                enriched[field] = [
                    {**child, "references": references}
                    if isinstance(child, dict)
                    else child
                    for child in children
                ]
        return enriched

    @staticmethod
    def _direct_system_prompt(
        definition: CreativeAgentDefinition, payload: dict[str, object]
    ) -> str:
        common = (
            f"你直接执行 {definition.name}，不要委派。{definition.system_prompt}"
            "严格按 response schema 输出。references 由系统根据 context_manifest 写入，"
            "模型不得输出或虚构 references。"
        )
        if definition.name == "RetentionAuditor":
            return (
                common
                + "正文证据只放 citation；每个 issue.quote 必须是正文中唯一存在的完整原文。"
                "total_score 必须等于七项整数分数的 Python round 平均值。"
            )
        if definition.name in {"ContinuityAuditor", "StyleCritic"}:
            return (
                common
                + "正文证据只放 citation；每个 issue.quote 必须是正文中唯一存在的完整原文。"
                "没有可证实问题时 issues 必须为空，不得为了凑数制造问题。"
            )
        if definition.name == "ChapterPlanner":
            return (
                common
                + "计划必须把用户要求的篇幅、开篇事件、核心兑现、能力代价和章末钩子"
                "拆成可执行场景，不得把正文写作任务改成背景说明。"
            )
        if definition.name == "DraftWriter":
            if "draft" in payload:
                return (
                    common
                    + "当前是局部修订模式：markdown 必须为 null，revisions 至少一项。"
                    "每项 revision.issue_id 必须来自 payload.issues；target 必须等于 "
                    "citation.location；citation 必须与对应 issue 完全相同；"
                    "replacement 只替换该局部片段，不得重写整章。"
                )
            return (
                common
                + "当前是新稿模式：markdown 必须是完整章节正文，revisions 必须为空。"
                "严格遵守 plan 中的字符数和场景顺序；只保留一个章标题，不使用二级分节标题；"
                "能力规则必须通过动作和后果展示，不写设定说明。"
            )
        return common

    @staticmethod
    def _translate(
        agent: str, payload: dict[str, object], output: ReferencedOutput
    ) -> object:
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
