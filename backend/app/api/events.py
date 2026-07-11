import asyncio
from collections.abc import AsyncIterator

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.api.tasks import Service
from app.domain.task import TaskEvent

router = APIRouter(prefix="/projects/{project_id}/tasks", tags=["task-events"])


def error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code, content={"error": {"code": code, "message": message}}
    )


def encode_event(event: TaskEvent) -> str:
    data = event.model_dump_json()
    return f"id: {event.sequence}\nevent: {event.type}\ndata: {data}\n\n"


@router.get("/{task_id}/events", response_model=None)
async def stream_events(
    task_id: str,
    request: Request,
    service: Service,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    follow: bool = True,
) -> StreamingResponse | JSONResponse:
    try:
        after = 0 if last_event_id is None else int(last_event_id)
    except ValueError:
        return error_response(
            422, "LAST_EVENT_ID_INVALID", "Last-Event-ID must be a non-negative integer"
        )
    if after < 0:
        return error_response(
            422, "LAST_EVENT_ID_INVALID", "Last-Event-ID must be a non-negative integer"
        )

    existing = service.events(task_id)
    maximum = existing[-1].sequence if existing else 0
    if after > maximum:
        return error_response(
            416, "LAST_EVENT_ID_OUT_OF_RANGE", "Last-Event-ID exceeds current sequence"
        )

    async def generate() -> AsyncIterator[str]:
        cursor = after
        while True:
            events = service.events(task_id, cursor)
            for event in events:
                cursor = event.sequence
                yield encode_event(event)
            if not follow or await request.is_disconnected():
                return
            await asyncio.sleep(0.25)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
