from typing import Literal

from fastapi import APIRouter, Request, status
from pydantic import BaseModel, ConfigDict, Field

from app.agents.schemas import CommercialReport, CommercialStrategy
from app.api.creation import _run_agent, _runner
from app.domain.commercial import (
    CommercialMetrics,
    CommercialObservation,
    CommercialObservationInput,
    CommercialProfile,
)
from app.domain.task import Task
from app.repositories.commercial import CommercialRepository
from app.repositories.database import DatabaseRepository
from app.workflows.chapter import ChapterService
from app.workflows.commercial import CommercialService

router = APIRouter(prefix="/projects/{project_id}/commercial", tags=["commercial"])


class CommercialBrief(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    platform: Literal["fanqie", "qidian", "jinjiang", "custom"] = "fanqie"
    monetization: Literal["free_ad", "paid_subscription", "custom"] = "free_ad"
    target_reader: str = Field(min_length=1)
    core_fantasy: str = Field(min_length=1)
    differentiator: str = Field(min_length=1)
    comparable_titles: list[str] = Field(default_factory=list, max_length=5)
    instruction: str = Field(min_length=1)


class GeneratedCommercialResponse(BaseModel):
    task: Task
    profile: CommercialProfile


class StoredCommercialAuditResponse(BaseModel):
    commercial_report: CommercialReport
    minimum_commercial_score: int
    commercial_gate_passed: bool


@router.get("/profile", response_model=CommercialProfile | None)
def get_profile(project_id: str, request: Request) -> CommercialProfile | None:
    return CommercialService(request.app.state.workspace).read(project_id)


@router.get(
    "/reports/{task_id}", response_model=StoredCommercialAuditResponse | None
)
def get_stored_commercial_report(
    project_id: str, task_id: str, request: Request
) -> StoredCommercialAuditResponse | None:
    profile = CommercialService(request.app.state.workspace).read(project_id)
    report = ChapterService(request.app.state.workspace).read_commercial_report(
        project_id, task_id
    )
    if profile is None or report is None:
        return None
    return StoredCommercialAuditResponse(
        commercial_report=report,
        minimum_commercial_score=profile.minimum_commercial_score,
        commercial_gate_passed=ChapterService.commercial_gate_passed(
            report, profile.minimum_commercial_score
        ),
    )


@router.post("/draft", response_model=Task, status_code=status.HTTP_201_CREATED)
def create_profile_draft(
    project_id: str, payload: CommercialProfile, request: Request
) -> Task:
    return CommercialService(request.app.state.workspace).create(project_id, payload)


@router.post(
    "/agent",
    response_model=GeneratedCommercialResponse,
    status_code=status.HTTP_201_CREATED,
)
async def generate_profile(
    project_id: str, payload: CommercialBrief, request: Request
) -> GeneratedCommercialResponse:
    def run() -> GeneratedCommercialResponse:
        metrics = _repository(project_id, request).metrics(project_id)
        output = _runner(project_id, request).invoke(
            "MarketStrategist",
            {
                "brief": payload.model_dump(mode="json"),
                "observed_metrics": metrics.model_dump(mode="json"),
                "instruction": payload.instruction,
            },
        )
        if not isinstance(output, CommercialStrategy):
            raise RuntimeError("AGENT_OUTPUT_INVALID")
        if (
            output.profile.platform != payload.platform
            or output.profile.monetization != payload.monetization
        ):
            raise RuntimeError("AGENT_OUTPUT_INVALID")
        task = CommercialService(request.app.state.workspace).create(
            project_id, output.profile
        )
        return GeneratedCommercialResponse(task=task, profile=output.profile)

    return await _run_agent(run)


@router.put("/draft/{task_id}", response_model=CommercialProfile)
def update_profile_draft(
    project_id: str,
    task_id: str,
    payload: CommercialProfile,
    request: Request,
) -> CommercialProfile:
    return CommercialService(request.app.state.workspace).write_draft(
        project_id, task_id, payload
    )


@router.get("/draft/{task_id}", response_model=CommercialProfile)
def get_profile_draft(
    project_id: str, task_id: str, request: Request
) -> CommercialProfile:
    return CommercialService(request.app.state.workspace).read_draft(project_id, task_id)


@router.post("/draft/{task_id}/approve", response_model=Task)
def approve_profile(project_id: str, task_id: str, request: Request) -> Task:
    return CommercialService(request.app.state.workspace).approve(project_id, task_id)


def _repository(project_id: str, request: Request) -> CommercialRepository:
    database = DatabaseRepository(request.app.state.workspace)
    database.initialize(project_id)
    return CommercialRepository(database)


@router.get("/observations", response_model=list[CommercialObservation])
def list_observations(project_id: str, request: Request) -> list[CommercialObservation]:
    return _repository(project_id, request).list_all(project_id)


@router.post(
    "/observations",
    response_model=CommercialObservation,
    status_code=status.HTTP_201_CREATED,
)
def create_observation(
    project_id: str, payload: CommercialObservationInput, request: Request
) -> CommercialObservation:
    return _repository(project_id, request).add(project_id, payload)


@router.get("/metrics", response_model=CommercialMetrics)
def get_metrics(project_id: str, request: Request) -> CommercialMetrics:
    return _repository(project_id, request).metrics(project_id)
