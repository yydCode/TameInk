from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from app.agents.skills import P0Skill
from app.domain.creation import (
    ArtifactStatus,
    AuthorDecision,
    CandidateArtifactRecord,
    CreativeBrief,
    DecisionAction,
    DecisionEffect,
    Expectation,
    FormalLayer,
    StoryCard,
)
from app.domain.task import Task
from app.infrastructure.jobs import AgentJobKind, JobQueue
from app.infrastructure.model import ModelConfigurationError
from app.infrastructure.secrets import ApiKeyStore, SecretStoreError
from app.infrastructure.settings import SettingsError, SettingsRepository
from app.repositories.artifacts import ArtifactsRepository
from app.repositories.canon import CanonRepository
from app.repositories.database import DatabaseRepository
from app.repositories.workspace import WorkspaceRepository
from app.workflows.brief_draft import BriefDraft, BriefDraftService
from app.workflows.creative import CreativeExport, CreativeService, NextCreativeAction

router = APIRouter(prefix="/projects/{project_id}/creative", tags=["creative"])


class CreativeSkillRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    skill: P0Skill
    payload: dict[str, object] = Field(default_factory=dict)


class CreativeStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    title: str = Field(min_length=1)
    platform: str = Field(min_length=1)
    genre_scope: str = Field(min_length=1)
    initial_intent: str = Field(min_length=1)
    first_story_goal: str = Field(min_length=1)
    constraints: list[str] = Field(min_length=1)
    material_boundaries: list[str] = Field(min_length=1)


class AuthorDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    expected_status: ArtifactStatus
    action: DecisionAction
    rationale: str | None = None
    effects: list[DecisionEffect] = Field(default_factory=list)
    target_layer: FormalLayer | None = None
    formal_path: str | None = None
    content_override: str | None = None


class ExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    export_id: str = "manuscript"


@router.post("/start", status_code=status.HTTP_201_CREATED)
def start_project(
    project_id: str, payload: CreativeStartRequest, request: Request
) -> dict[str, object]:
    workspace: WorkspaceRepository = request.app.state.workspace
    created = CreativeService(workspace).start_project(
        project_id,
        payload.title,
        CreativeBrief(
            version=1,
            platform=payload.platform,
            genre_scope=payload.genre_scope,
            initial_intent=payload.initial_intent,
            first_story_goal=payload.first_story_goal,
            constraints=payload.constraints,
            material_boundaries=payload.material_boundaries,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        ),
    )
    _jobs(request).enqueue(
        created.project.id,
        created.task.id,
        AgentJobKind.CREATIVE_SKILL,
        {
            "skill": "webnovel-research-genre",
            "payload": {"instruction": "基于已确认的创作简报，整理题材与读者证据。"},
        },
    )
    return {"project": created.project, "task": created.task}


@router.post("/skills", response_model=Task, status_code=status.HTTP_202_ACCEPTED)
def run_skill(project_id: str, payload: CreativeSkillRequest, request: Request) -> Task:
    workspace: WorkspaceRepository = request.app.state.workspace
    task = CreativeService(workspace).create_skill_task(project_id, payload.skill, payload.payload)
    _jobs(request).enqueue(
        project_id,
        task.id,
        AgentJobKind.CREATIVE_SKILL,
        {"skill": payload.skill, "payload": payload.payload},
    )
    return task


@router.get("/next", response_model=NextCreativeAction)
def next_action(project_id: str, request: Request) -> NextCreativeAction:
    return CreativeService(request.app.state.workspace).next_action(project_id)


class BriefDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    idea: str = Field(min_length=1, max_length=2000)


@router.post("/brief-draft", response_model=BriefDraft)
async def brief_draft(
    project_id: str, payload: BriefDraftRequest, request: Request
) -> BriefDraft:
    """把作者一句话想法拆解成创作简报草稿（同步 AI 调用，不写入 canon）。"""
    settings: SettingsRepository = request.app.state.model_settings
    secrets: ApiKeyStore = request.app.state.api_keys
    try:
        return await BriefDraftService(settings, secrets).draft(payload.idea)
    except (SettingsError, SecretStoreError, ModelConfigurationError) as error:
        raise HTTPException(
            status_code=400,
            detail={"code": str(error), "message": "模型未配置或不可用"},
        ) from error
    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail={"code": "BRIEF_DRAFT_FAILED", "message": "AI 起草失败，请重试"},
        ) from error


@router.post("/exports", response_model=CreativeExport, status_code=status.HTTP_201_CREATED)
def export_confirmed_chapters(
    project_id: str, payload: ExportRequest, request: Request
) -> CreativeExport:
    return CreativeService(request.app.state.workspace).export_confirmed_chapters(
        project_id, payload.export_id
    )


@router.get("/artifacts", response_model=list[CandidateArtifactRecord])
def list_artifacts(project_id: str, request: Request) -> list[CandidateArtifactRecord]:
    workspace: WorkspaceRepository = request.app.state.workspace
    database = DatabaseRepository(workspace)
    database.initialize(project_id)
    return ArtifactsRepository(database, project_id).list_all()


@router.get("/expectations", response_model=list[Expectation])
def list_expectations(project_id: str, request: Request) -> list[Expectation]:
    """Confirmed reader expectations, for the expectation heatmap."""
    workspace: WorkspaceRepository = request.app.state.workspace
    return CanonRepository(workspace).list_expectations(project_id)


@router.get("/story-cards", response_model=list[StoryCard])
def list_story_cards(project_id: str, request: Request) -> list[StoryCard]:
    """Confirmed story cards, sorted by sequence, for the inline card picker."""
    workspace: WorkspaceRepository = request.app.state.workspace
    return CanonRepository(workspace).list_story_cards(project_id)


class SetCurrentCardRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    card_id: str = Field(min_length=1)


@router.post("/story-cards/current", response_model=StoryCard)
def set_current_story_card(
    project_id: str, payload: SetCurrentCardRequest, request: Request
) -> StoryCard:
    """Mark one story card as the active production unit (status: current).

    Demotes any previously current card to planned in the same atomic commit.
    Calling this endpoint is the author-facing action that resolves the
    next_action 'input' step that asks them to select a story card.
    """
    return CreativeService(request.app.state.workspace).set_current_story_card(
        project_id, payload.card_id
    )


@router.post("/artifacts/{artifact_id}/decisions", response_model=Task)
def decide(
    project_id: str,
    artifact_id: str,
    payload: AuthorDecisionRequest,
    request: Request,
) -> Task:
    decision = AuthorDecision(
        id=str(uuid4()),
        project_id=project_id,
        artifact_id=artifact_id,
        expected_status=payload.expected_status,
        action=payload.action,
        rationale=payload.rationale,
        effects=payload.effects,
        target_layer=payload.target_layer,
        formal_path=payload.formal_path,
        content_override=payload.content_override,
        created_at=datetime.now(UTC),
    )
    return CreativeService(request.app.state.workspace).decide(project_id, decision)


def _jobs(request: Request) -> JobQueue:
    return cast(JobQueue, request.app.state.agent_jobs)
