from fastapi import APIRouter, Request, status

from app.workflows.import_book import ChapterBoundary, ImportBookService

router = APIRouter(prefix="/projects/{project_id}/imports", tags=["imports"])


def _boundary(chapter: ChapterBoundary) -> dict[str, object]:
    return {
        "number": chapter.number,
        "title": chapter.title,
        "start": chapter.start.__dict__,
        "body_start": chapter.body_start.__dict__,
    }


@router.post("/{import_id}", status_code=status.HTTP_201_CREATED)
async def upload_import(
    project_id: str, import_id: str, request: Request, encoding: str | None = None
) -> dict[str, object]:
    decoded, boundaries = ImportBookService(request.app.state.workspace).upload(
        project_id, import_id, await request.body(), encoding
    )
    return {"encoding": decoded.encoding, "chapters": [_boundary(item) for item in boundaries]}


@router.post("/{import_id}/boundaries", status_code=status.HTTP_201_CREATED)
def confirm_boundaries(project_id: str, import_id: str, request: Request) -> dict[str, object]:
    task, boundaries = ImportBookService(request.app.state.workspace).confirm_boundaries(
        project_id, import_id
    )
    return {"task": task, "chapters": [_boundary(item) for item in boundaries]}
