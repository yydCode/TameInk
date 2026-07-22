from pathlib import Path

from app.agents.context import ContextBudget, ContextIntent, ContextRequest
from app.agents.skills import P0Skill
from app.domain.creation import validate_record_id
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
        return ContextRequest(
            stage=agent,
            fixed_rules=fixed,
            volume=volume,
            summaries=summaries,
            entities=[],
            fts_queries=intent.queries() if intent is not None else [],
            budget=ContextBudget(),
        )

    def request_for_skill(self, skill: P0Skill, payload: dict[str, object]) -> ContextRequest:
        project = self.workspace.project_path(self.project_id)
        common = self._existing(
            project, ["project.yaml", "commitments/creative-brief.yaml"]
        )
        commitments = self._existing(
            project,
            ["commitments/reader-contract.yaml", "commitments/story-engine.yaml"],
        )
        record_paths = self._record_paths(project, payload)
        intent = self._intent(payload)
        fixed = common
        entities: list[str] = []
        if skill == "webnovel-research-genre":
            fixed = common
        elif skill == "webnovel-design-reader-contract":
            fixed = common
        elif skill == "webnovel-design-story-engine":
            fixed = [*common, *commitments[:1]]
        elif skill == "webnovel-plan-rolling-story":
            fixed = [*common, *commitments]
            entities = record_paths["characters"] + record_paths["expectations"]
        elif skill in {
            "webnovel-plan-chapter",
            "webnovel-draft",
            "webnovel-audit",
            "webnovel-opening-audit",
            "webnovel-poison-check",
        }:
            fixed = [*common, *commitments, *record_paths["story_cards"]]
            entities = [
                *record_paths["characters"],
                *record_paths["expectations"],
                *record_paths["actual_events"],
                *record_paths["chapters"],
            ]
        elif skill == "webnovel-curate-memory":
            fixed = [*common, *commitments]
            entities = [
                *record_paths["chapters"],
                *record_paths["characters"],
                *record_paths["expectations"],
                *record_paths["actual_events"],
            ]
        elif skill == "webnovel-plan-ending":
            fixed = [*common, *commitments, "commitments/ending-plan.yaml"]
            entities = [
                *record_paths["characters"],
                *record_paths["expectations"],
                *record_paths["actual_events"],
                *record_paths["story_cards"],
            ]
        else:
            raise ValueError("SKILL_CONTEXT_UNSUPPORTED")
        return ContextRequest(
            stage=skill,
            fixed_rules=self._existing(project, fixed),
            volume=[],
            summaries=[],
            entities=self._existing(project, entities),
            fts_queries=intent.queries() if intent is not None else [],
            budget=ContextBudget(),
        )

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
    def _record_paths(project: Path, payload: dict[str, object]) -> dict[str, list[str]]:
        def paths(key: str, directory: str, suffix: str) -> list[str]:
            raw = payload.get(key, [])
            if raw is None:
                return []
            if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
                raise ValueError("SKILL_CONTEXT_IDS_INVALID")
            result: list[str] = []
            for record_id in raw:
                validate_record_id(record_id)
                result.append(f"{directory}/{record_id}{suffix}")
            return result

        return {
            "characters": paths("character_ids", "canon/characters", ".yaml"),
            "expectations": paths("expectation_ids", "commitments/expectations", ".yaml"),
            "actual_events": paths("actual_event_ids", "canon/actual-events", ".yaml"),
            "story_cards": paths("story_card_ids", "commitments/story-cards", ".yaml"),
            "chapters": paths("confirmed_chapter_ids", "canon/chapters", ".md"),
        }

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
