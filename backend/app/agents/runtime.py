import json
from pathlib import Path
from uuid import uuid4

from app.agents.backend import NovelWorkspaceBackend
from app.agents.context import ContextBuilder, ContextRequest
from app.agents.contracts import OutputContractError, validate_agent_output_tree
from app.agents.orchestrator import create_orchestrator
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
        self.model = build_model(settings.load(), secrets.get())
        definitions = build_subagent_definitions(backend)
        self.definitions = {definition.name: definition for definition in definitions}
        self.orchestrator = create_orchestrator(self.model, backend, definitions)
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
        if agent in {"MarketStrategist", "RetentionAuditor"}:
            return self._translate(agent, payload, self._invoke_direct(agent, payload))
        output = self.orchestrator.invoke_agent(
            agent,
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            context_manifest=self.manifest,
        )
        return self._translate(agent, payload, output)

    def _invoke_direct(
        self, agent: str, payload: dict[str, object]
    ) -> ReferencedOutput:
        definition = self.definitions.get(agent)
        if definition is None:
            raise OutputContractError("OUTPUT_SUBAGENT_UNKNOWN")
        system_prompt = self._direct_system_prompt(definition)
        structured = self.model.with_structured_output(
            definition.output_schema, method="function_calling"
        )
        output = structured.invoke(
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
        if not isinstance(output, ReferencedOutput):
            raise OutputContractError("AGENT_OUTPUT_INVALID")
        return validate_agent_output_tree(output, self.manifest)

    @staticmethod
    def _direct_system_prompt(definition: CreativeAgentDefinition) -> str:
        common = (
            f"你直接执行 {definition.name}，不要委派。{definition.system_prompt}"
            "严格按 response schema 输出。所有 references 数组只能逐字使用 "
            "context_manifest 中给出的正式来源 path、location、quote；"
            "不得为草稿创建 SourceReference。"
        )
        if definition.name == "RetentionAuditor":
            return (
                common
                + "正文证据只放 citation；每个 issue.quote 必须是正文中唯一存在的完整原文。"
                "total_score 必须等于七项整数分数的 Python round 平均值。"
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
