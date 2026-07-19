from fastapi import APIRouter, Request, status
from pydantic import BaseModel, ConfigDict

from app.domain.task import Task
from app.workflows.import_book import ChapterBoundary, ImportBookService

router = APIRouter(prefix="/projects/{project_id}/imports", tags=["imports"])


class BoundaryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    number: int
    title: str
    start: dict[str, int]
    end: dict[str, int]


class ConfirmBoundariesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_sha256: str
    source_size: int
    boundaries: list[BoundaryRequest]


def _boundary(chapter: ChapterBoundary) -> dict[str, object]:
    return {
        "number": chapter.number,
        "title": chapter.title,
        "start": chapter.start.__dict__,
        "end": chapter.end.__dict__,
    }


@router.post("/{import_id}", status_code=status.HTTP_201_CREATED)
async def upload_import(
    project_id: str, import_id: str, request: Request, encoding: str | None = None
) -> dict[str, object]:
    decoded, boundaries = ImportBookService(request.app.state.workspace).upload(
        project_id, import_id, await request.body(), encoding
    )
    source = request.app.state.workspace.resolve_project_path(
        project_id, f".tame-ink/imports/{import_id}.json"
    )
    record = __import__("json").loads(source.read_text())
    return {
        "encoding": decoded.encoding,
        "sha256": record["sha256"],
        "size": record["size"],
        "chapters": [_boundary(item) for item in boundaries],
    }


@router.post("/{import_id}/boundaries", status_code=status.HTTP_201_CREATED)
def confirm_boundaries(
    project_id: str, import_id: str, payload: ConfirmBoundariesRequest, request: Request
) -> dict[str, object]:
    task, boundaries = ImportBookService(request.app.state.workspace).confirm_boundaries(
        project_id,
        import_id,
        payload.source_sha256,
        payload.source_size,
        [item.model_dump() for item in payload.boundaries],
    )
    return {"task": task, "chapters": [_boundary(item) for item in boundaries]}


@router.post("/{import_id}/{task_id}/approve", response_model=Task)
def approve_import(project_id: str, import_id: str, task_id: str, request: Request) -> Task:
    return ImportBookService(request.app.state.workspace).approve(project_id, import_id, task_id)
