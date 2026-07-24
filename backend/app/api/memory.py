from typing import Literal

from fastapi import APIRouter, Request, status
from pydantic import BaseModel, ConfigDict, Field

from app.agents.schemas import MemoryCandidate
from app.domain.project import MemoryRecord
from app.repositories.database import DatabaseRepository
from app.repositories.search import SearchHit, SearchRepository
from app.workflows.memory import MemoryKind, MemoryService

router = APIRouter(prefix="/projects/{project_id}", tags=["memory"])


@router.get("/tasks/{task_id}/memory-candidates", response_model=list[MemoryCandidate])
def list_memory_candidates(
    project_id: str, task_id: str, request: Request
) -> list[MemoryCandidate]:
    from app.workflows.chapter import ChapterService

    return ChapterService(request.app.state.workspace).read_memory_candidates(project_id, task_id)


class MemoryCandidateUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(min_length=1)


@router.put(
    "/tasks/{task_id}/memory-candidates/{stable_id}",
    response_model=list[MemoryCandidate],
)
def update_memory_candidate(
    project_id: str,
    task_id: str,
    stable_id: str,
    payload: MemoryCandidateUpdateRequest,
    request: Request,
) -> list[MemoryCandidate]:
    """P2: 人编辑 AI 提取的记忆候选内容。"""
    from app.workflows.chapter import ChapterService

    return ChapterService(request.app.state.workspace).update_memory_candidate(
        project_id, task_id, stable_id, payload.content
    )


class ProvenanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    location: str
    quote: str


class MemoryCreateRequest(ProvenanceRequest):
    id: str
    kind: Literal["fact", "event", "relationship", "foreshadowing"]


@router.post("/memory", response_model=MemoryRecord, status_code=status.HTTP_201_CREATED)
def create_memory(project_id: str, payload: MemoryCreateRequest, request: Request) -> MemoryRecord:
    return MemoryService(request.app.state.workspace).create(
        project_id,
        payload.id,
        payload.kind,
        payload.source,
        payload.location,
        payload.quote,
    )


@router.get("/memory", response_model=list[MemoryRecord])
def list_memory(project_id: str, request: Request) -> list[MemoryRecord]:
    return MemoryService(request.app.state.workspace).list_records(project_id)


@router.get("/memory/{kind}/{stable_id}", response_model=MemoryRecord)
def read_memory(
    project_id: str, kind: MemoryKind, stable_id: str, request: Request
) -> MemoryRecord:
    return MemoryService(request.app.state.workspace).read(project_id, stable_id, kind)


@router.put("/memory/{kind}/{stable_id}", response_model=MemoryRecord)
def correct_memory(
    project_id: str,
    kind: MemoryKind,
    stable_id: str,
    payload: ProvenanceRequest,
    request: Request,
) -> MemoryRecord:
    return MemoryService(request.app.state.workspace).correct(
        project_id,
        stable_id,
        kind,
        payload.source,
        payload.location,
        payload.quote,
    )


@router.post("/memory/{kind}/{stable_id}/revoke", response_model=MemoryRecord)
def revoke_memory(
    project_id: str, kind: MemoryKind, stable_id: str, request: Request
) -> MemoryRecord:
    return MemoryService(request.app.state.workspace).revoke(project_id, stable_id, kind)


@router.get("/search", response_model=list[SearchHit])
def search(project_id: str, q: str, request: Request) -> list[SearchHit]:
    workspace = request.app.state.workspace
    return SearchRepository(workspace, DatabaseRepository(workspace)).search(project_id, q)
