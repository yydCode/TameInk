import io
import json
import os
import zipfile
from typing import Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict

from app.domain.paths import iter_formal_files, validate_formal_path
from app.domain.revision import Revision
from app.infrastructure.settings import SettingsError
from app.repositories.commercial import CommercialRepository
from app.repositories.database import DatabaseRepository
from app.repositories.revisions import RevisionRepository
from app.repositories.tasks import TasksRepository
from app.workflows.commercial import CommercialService

router = APIRouter(prefix="/projects/{project_id}", tags=["project-resources"])


class DocumentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    path: str
    content: str
    revision: str | None


class RevisionDiff(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    path: str
    status: Literal["added", "modified", "deleted"]
    patch: str


class RestoreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_revision: str


@router.get("/documents", response_model=DocumentResponse)
def read_document(project_id: str, request: Request, path: str = Query()) -> DocumentResponse:
    relative = validate_formal_path(path).as_posix()
    target = request.app.state.workspace.resolve_project_path(project_id, relative)
    return DocumentResponse(
        path=relative,
        content=target.read_text(encoding="utf-8"),
        revision=RevisionRepository(request.app.state.workspace).current_revision(project_id),
    )


@router.get("/revisions", response_model=list[Revision])
def list_revisions(project_id: str, request: Request) -> list[Revision]:
    return RevisionRepository(request.app.state.workspace).history(project_id)


@router.get("/revisions/diff", response_model=list[RevisionDiff])
def compare_revisions(
    project_id: str, request: Request, base: str = Query(), target: str = Query()
) -> list[RevisionDiff]:
    return [
        RevisionDiff.model_validate(item)
        for item in RevisionRepository(request.app.state.workspace).diff(project_id, base, target)
    ]


@router.post("/revisions/{revision_id}/restore", response_model=Revision)
def restore_revision(
    project_id: str, revision_id: str, payload: RestoreRequest, request: Request
) -> Revision:
    revision = RevisionRepository(request.app.state.workspace).rollback(
        project_id, revision_id, payload.expected_revision
    )
    DatabaseRepository(request.app.state.workspace).rebuild(project_id)
    return revision


@router.get("/exports/project.zip")
def export_project(project_id: str, request: Request) -> Response:
    project = request.app.state.workspace.project_path(project_id)
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in iter_formal_files(project):
            archive.writestr(path.relative_to(project).as_posix(), path.read_bytes())
    return Response(
        content=stream.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{project_id}.zip"'},
    )


@router.get("/exports/commercial.json")
def export_commercial(project_id: str, request: Request) -> Response:
    database = DatabaseRepository(request.app.state.workspace)
    database.initialize(project_id)
    repository = CommercialRepository(database)
    profile = CommercialService(request.app.state.workspace).read(project_id)
    payload = {
        "project_id": project_id,
        "profile": None if profile is None else profile.model_dump(mode="json"),
        "metrics": repository.metrics(project_id).model_dump(mode="json"),
        "observations": [item.model_dump(mode="json") for item in repository.list_all(project_id)],
    }
    return Response(
        content=json.dumps(payload, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{project_id}-commercial.json"'},
    )


@router.get("/usage")
def project_usage(project_id: str, request: Request) -> dict[str, object]:
    database = DatabaseRepository(request.app.state.workspace)
    database.initialize(project_id)
    repository = TasksRepository(database, project_id)
    totals: dict[str, float] = {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "total_cost_cny": 0.0,
    }
    request_count = 0
    for task in repository.list_all():
        for event in repository.events(task.id):
            if event.type != "agent.stage.completed":
                continue
            if isinstance(event.data.get("total_tokens"), int):
                request_count += 1
            for key in totals:
                value = event.data.get(key)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    totals[key] += float(value)
    try:
        model = request.app.state.model_settings.load().model
    except SettingsError:
        model = None
    return {
        "project_id": project_id,
        "model": model,
        "request_count": request_count,
        "input_tokens": int(totals["input_tokens"]),
        "output_tokens": int(totals["output_tokens"]),
        "total_tokens": int(totals["total_tokens"]),
        "total_cost_cny": round(totals["total_cost_cny"], 8),
        "pricing_configured": bool(
            os.environ.get("TAME_INK_INPUT_PRICE_CNY_PER_1M_TOKENS")
            and os.environ.get("TAME_INK_OUTPUT_PRICE_CNY_PER_1M_TOKENS")
        ),
    }
