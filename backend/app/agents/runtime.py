import json
from pathlib import Path
from uuid import uuid4

from app.agents.backend import NovelWorkspaceBackend
from app.agents.context import ContextBuilder, ContextRequest
from app.agents.orchestrator import create_orchestrator
from app.agents.schemas import (
    ChapterDraft,
    ContinuityReport,
    DraftWriterResult,
    ReferencedOutput,
    StyleReport,
)
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
        model = build_model(settings.load(), secrets.get())
        self.orchestrator = create_orchestrator(model, backend)
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
        output = self.orchestrator.invoke_agent(
            agent,
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            context_manifest=self.manifest,
        )
        return self._translate(agent, payload, output)

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
        return output
