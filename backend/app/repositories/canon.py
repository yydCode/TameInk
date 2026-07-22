import os
from pathlib import Path
from typing import Any, TypeVar

import yaml
from pydantic import BaseModel, ValidationError

from app.domain.commercial import CommercialProfile
from app.domain.creation import (
    ActualEvent,
    CharacterState,
    CreativeBrief,
    EndingPlan,
    Expectation,
    ReaderContract,
    StoryCard,
    StoryEngine,
    validate_record_id,
)
from app.domain.errors import (
    CanonContentError,
    StorageReadError,
    StorageWriteError,
    WorkspacePathViolationError,
)
from app.domain.paths import resolve_formal_path, validate_formal_path
from app.domain.project import ConfirmedContent, MemoryRecord, Project
from app.repositories.workspace import WorkspaceRepository

ModelT = TypeVar("ModelT", bound=BaseModel)


class CanonRepository:
    def __init__(self, workspace: WorkspaceRepository) -> None:
        self.workspace = workspace

    def project_file(self, project_id: str) -> Path:
        return self.workspace.resolve_project_path(project_id, "project.yaml")

    def write_project(self, project: Project) -> None:
        self._write_yaml(self.project_file(project.id), project.model_dump(mode="json"))

    def read_project(self, project_id: str) -> Project:
        return self._validate(Project, self._read_yaml(self.project_file(project_id)))

    def read_commercial(self, project_id: str) -> CommercialProfile:
        path = self._formal_path(project_id, "canon/commercial.yaml", ".yaml")
        return self._validate(CommercialProfile, self._read_yaml(path))

    def write_markdown(self, project_id: str, relative: str, content: ConfirmedContent) -> None:
        path = self._formal_path(project_id, relative, ".md")
        self._replace(path, content.markdown.encode())

    def read_markdown(self, project_id: str, relative: str) -> ConfirmedContent:
        path = self._formal_path(project_id, relative, ".md")
        return self._validate(ConfirmedContent, {"markdown": self._read_text(path)})

    def write_memory(self, project_id: str, relative: str, memory: MemoryRecord) -> None:
        path = self._formal_path(project_id, relative, ".yaml")
        self._write_yaml(path, memory.model_dump(mode="json"))

    def read_memory(self, project_id: str, relative: str) -> MemoryRecord:
        path = self._formal_path(project_id, relative, ".yaml")
        return self._validate(MemoryRecord, self._read_yaml(path))

    def write_reader_contract(self, project_id: str, contract: ReaderContract) -> None:
        self._write_record(project_id, "commitments/reader-contract.yaml", contract)

    def write_creative_brief(self, project_id: str, brief: CreativeBrief) -> None:
        self._write_record(project_id, "commitments/creative-brief.yaml", brief)

    def read_creative_brief(self, project_id: str) -> CreativeBrief:
        return self._read_record(project_id, "commitments/creative-brief.yaml", CreativeBrief)

    def read_reader_contract(self, project_id: str) -> ReaderContract:
        return self._read_record(project_id, "commitments/reader-contract.yaml", ReaderContract)

    def write_story_engine(self, project_id: str, engine: StoryEngine) -> None:
        self._write_record(project_id, "commitments/story-engine.yaml", engine)

    def read_story_engine(self, project_id: str) -> StoryEngine:
        return self._read_record(project_id, "commitments/story-engine.yaml", StoryEngine)

    def write_ending_plan(self, project_id: str, plan: EndingPlan) -> None:
        self._write_record(project_id, "commitments/ending-plan.yaml", plan)

    def read_ending_plan(self, project_id: str) -> EndingPlan:
        return self._read_record(project_id, "commitments/ending-plan.yaml", EndingPlan)

    def write_character_state(self, project_id: str, character: CharacterState) -> None:
        self._write_record(
            project_id, f"canon/characters/{character.id}.yaml", character
        )

    def read_character_state(self, project_id: str, record_id: str) -> CharacterState:
        validate_record_id(record_id)
        return self._read_record(
            project_id, f"canon/characters/{record_id}.yaml", CharacterState
        )

    def write_expectation(self, project_id: str, expectation: Expectation) -> None:
        self._write_record(
            project_id, f"commitments/expectations/{expectation.id}.yaml", expectation
        )

    def read_expectation(self, project_id: str, record_id: str) -> Expectation:
        validate_record_id(record_id)
        return self._read_record(
            project_id, f"commitments/expectations/{record_id}.yaml", Expectation
        )

    def list_expectations(self, project_id: str) -> list[Expectation]:
        """Read every confirmed expectation, sorted by id for stable ordering.

        Returns an empty list when the directory does not exist yet. A single
        unreadable or malformed file raises, since a corrupt commitment is a
        real integrity problem the caller should surface rather than hide.
        """
        root = self.workspace.project_path(project_id) / "commitments/expectations"
        if not root.is_dir():
            return []
        expectations: list[Expectation] = []
        for path in sorted(root.glob("*.yaml")):
            expectations.append(
                self._read_record(
                    project_id, f"commitments/expectations/{path.stem}.yaml", Expectation
                )
            )
        return expectations

    def list_story_cards(self, project_id: str) -> list[StoryCard]:
        """Read every confirmed story card, sorted by sequence then id.

        Returns an empty list when the directory does not exist yet. A single
        unreadable or malformed file raises, since a corrupt commitment is a
        real integrity problem the caller should surface rather than hide.
        """
        root = self.workspace.project_path(project_id) / "commitments/story-cards"
        if not root.is_dir():
            return []
        cards: list[StoryCard] = []
        for path in sorted(root.glob("*.yaml")):
            cards.append(
                self._read_record(
                    project_id, f"commitments/story-cards/{path.stem}.yaml", StoryCard
                )
            )
        return sorted(cards, key=lambda card: (card.sequence, card.id))

    def write_story_card(self, project_id: str, card: StoryCard) -> None:
        self._write_record(project_id, f"commitments/story-cards/{card.id}.yaml", card)

    def read_story_card(self, project_id: str, record_id: str) -> StoryCard:
        validate_record_id(record_id)
        return self._read_record(
            project_id, f"commitments/story-cards/{record_id}.yaml", StoryCard
        )

    def write_actual_event(self, project_id: str, event: ActualEvent) -> None:
        self._write_record(project_id, f"canon/actual-events/{event.id}.yaml", event)

    def read_actual_event(self, project_id: str, record_id: str) -> ActualEvent:
        validate_record_id(record_id)
        return self._read_record(
            project_id, f"canon/actual-events/{record_id}.yaml", ActualEvent
        )

    def _write_record(self, project_id: str, relative: str, record: BaseModel) -> None:
        path = self._formal_path(project_id, relative, ".yaml")
        self._write_yaml(path, record.model_dump(mode="json"))

    def _read_record(
        self, project_id: str, relative: str, model: type[ModelT]
    ) -> ModelT:
        path = self._formal_path(project_id, relative, ".yaml")
        return self._validate(model, self._read_yaml(path))

    def _formal_path(self, project_id: str, relative: str, suffix: str) -> Path:
        pure = validate_formal_path(relative)
        if pure.suffix != suffix:
            raise WorkspacePathViolationError(relative)
        return resolve_formal_path(self.workspace.project_path(project_id), relative)

    def _write_yaml(self, path: Path, data: dict[str, Any]) -> None:
        try:
            payload = yaml.safe_dump(data, allow_unicode=True, sort_keys=True).encode()
        except yaml.YAMLError as error:
            raise CanonContentError(str(path)) from error
        self._replace(path, payload)

    def _read_yaml(self, path: Path) -> Any:
        try:
            return yaml.safe_load(self._read_text(path))
        except yaml.YAMLError as error:
            raise CanonContentError(str(path)) from error

    @staticmethod
    def _read_text(path: Path) -> str:
        try:
            return path.read_text()
        except OSError as error:
            raise StorageReadError(str(path)) from error

    @staticmethod
    def _validate(model: type[ModelT], data: Any) -> ModelT:
        try:
            return model.model_validate(data)
        except ValidationError as error:
            raise CanonContentError(model.__name__) from error

    @staticmethod
    def _replace(path: Path, payload: bytes) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(f".{path.name}.tmp")
            with temporary.open("wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            CanonRepository._sync_directory(path.parent)
        except OSError as error:
            raise StorageWriteError(str(path)) from error

    @staticmethod
    def _sync_directory(path: Path) -> None:
        directory = os.open(path, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
