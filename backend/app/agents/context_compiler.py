from pathlib import Path

from app.agents.context import ContextBudget, ContextIntent, ContextRequest
from app.repositories.workspace import WorkspaceRepository


class ChapterContextCompiler:
    def __init__(self, workspace: WorkspaceRepository, project_id: str) -> None:
        self.workspace = workspace
        self.project_id = project_id

    def request_for(self, agent: str, payload: dict[str, object]) -> ContextRequest:
        project = self.workspace.project_path(self.project_id)
        fixed = self._existing(
            project,
            [
                "project.yaml",
                "canon/commercial.yaml",
                "canon/premise.md",
                "canon/world/setting.md",
                "canon/outline.md",
            ],
        )
        volume_id = str(payload.get("volume_id", "1"))
        volume = self._existing(project, [f"canon/volumes/{volume_id}.md"])
        summaries = self._summary_paths(project, payload, volume_id)
        intent = self._intent(payload)
        directive = payload.get("directive")
        directive_queries: list[str] = []
        entity_paths: list[str] = []
        if isinstance(directive, dict):
            directive_queries = self._directive_fts_queries(directive)
            entity_paths = self._directive_entity_paths(directive, project)
        all_queries: list[str] = []
        if intent is not None:
            all_queries.extend(intent.queries())
        all_queries.extend(directive_queries)
        all_queries = list(dict.fromkeys(all_queries))
        return ContextRequest(
            stage=agent,
            fixed_rules=fixed,
            volume=volume,
            summaries=summaries,
            entities=entity_paths,
            fts_queries=all_queries,
            budget=ContextBudget(),
        )

    @staticmethod
    def _directive_fts_queries(directive: dict[str, object]) -> list[str]:
        queries: list[str] = []
        for field in ("required_characters", "focus_entities"):
            values = directive.get(field)
            if isinstance(values, list):
                for value in values:
                    if isinstance(value, str) and len(value) >= 2:
                        queries.append(value)
        return queries

    @staticmethod
    def _directive_entity_paths(
        directive: dict[str, object], project: Path
    ) -> list[str]:
        paths: list[str] = []
        ids = directive.get("resolve_foreshadowing_ids")
        if isinstance(ids, list):
            for fid in ids:
                if isinstance(fid, str) and fid:
                    relative = f"memory/foreshadowing/{fid}.yaml"
                    if (project / relative).is_file():
                        paths.append(relative)
        return paths

    @staticmethod
    def _existing(project: Path, candidates: list[str]) -> list[str]:
        return [path for path in candidates if (project / path).is_file()]

    def _summary_paths(
        self, project: Path, payload: dict[str, object], volume_id: str
    ) -> list[str]:
        candidates = [
            "memory/summaries/book.md",
            f"memory/summaries/volumes/{volume_id}.md",
        ]
        chapter_id = str(payload.get("chapter_id", ""))
        summary_root = project / "memory/summaries/chapters"
        if chapter_id.isdigit() and summary_root.is_dir():
            current = int(chapter_id)
            previous = sorted(
                (
                    (int(path.stem), path)
                    for path in summary_root.glob("*.md")
                    if path.stem.isdigit() and int(path.stem) < current
                ),
                reverse=True,
            )[:3]
            candidates.extend(
                path.relative_to(project).as_posix() for _, path in reversed(previous)
            )
        return self._existing(project, candidates)

    @staticmethod
    def _intent(payload: dict[str, object]) -> ContextIntent | None:
        candidates: list[object] = [payload.get("context_intent")]
        plan = payload.get("plan")
        if isinstance(plan, dict):
            candidates.append(plan.get("context_intent"))
        for candidate in candidates:
            if candidate is not None:
                return ContextIntent.model_validate(candidate)
        return None
