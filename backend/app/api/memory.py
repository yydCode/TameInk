from typing import Literal

from fastapi import APIRouter, Request, status
from pydantic import BaseModel, ConfigDict

from app.domain.project import MemoryRecord
from app.repositories.database import DatabaseRepository
from app.repositories.search import SearchHit, SearchRepository
from app.workflows.memory import MemoryKind, MemoryService

router = APIRouter(prefix="/projects/{project_id}", tags=["memory"])


class ProvenanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    location: str
    quote: str


class MemoryCreateRequest(ProvenanceRequest):
    id: str
    kind: Literal["fact", "event", "relationship", "foreshadowing"]


@router.post("/memory", response_model=MemoryRecord, status_code=status.HTTP_201_CREATED)
def create_memory(
    project_id: str, payload: MemoryCreateRequest, request: Request
) -> MemoryRecord:
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
