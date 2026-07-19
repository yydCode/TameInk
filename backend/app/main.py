import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.commercial import router as commercial_router
from app.api.creation import router as creation_router
from app.api.events import router as events_router
from app.api.health import router as health_router
from app.api.imports import router as imports_router
from app.api.memory import router as memory_router
from app.api.projects import router as projects_router
from app.api.settings import router as settings_router
from app.api.tasks import router as tasks_router
from app.domain.errors import (
    ActiveTaskConflictError,
    ImportEncodingAmbiguousError,
    InvalidTaskTransitionError,
    TameInkError,
    TaskNotFoundError,
)
from app.infrastructure.jobs import DurableAgentQueue
from app.infrastructure.secrets import ApiKeyStore
from app.infrastructure.settings import SettingsRepository
from app.repositories.database import DatabaseRepository
from app.repositories.tasks import TasksRepository
from app.repositories.workspace import WorkspaceRepository
from app.workflows.task_service import TaskService


def create_app(workspace_root: Path, *, queue_immediate: bool = True) -> FastAPI:
    workspace = WorkspaceRepository(workspace_root)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        projects = workspace.root / "projects"
        if projects.is_dir():
            for project in sorted(projects.iterdir()):
                if project.is_dir() and not project.is_symlink():
                    database = DatabaseRepository(workspace)
                    database.initialize(project.name)
                    TaskService(TasksRepository(database, project.name)).recover_interrupted()
        yield

    application = FastAPI(title="Tame Ink API", version="0.1.0", lifespan=lifespan)
    application.state.workspace = workspace
    application.state.model_settings = SettingsRepository(workspace.root / "settings.json")
    application.state.api_keys = ApiKeyStore()
    application.state.agent_jobs = DurableAgentQueue(workspace.root, immediate=queue_immediate)
    application.include_router(health_router, prefix="/api")
    application.include_router(tasks_router, prefix="/api")
    application.include_router(events_router, prefix="/api")
    application.include_router(settings_router, prefix="/api")
    application.include_router(projects_router, prefix="/api")
    application.include_router(imports_router, prefix="/api")
    application.include_router(creation_router, prefix="/api")
    application.include_router(memory_router, prefix="/api")
    application.include_router(commercial_router, prefix="/api")

    @application.exception_handler(TameInkError)
    async def tame_ink_error(_: Request, error: TameInkError) -> JSONResponse:
        if isinstance(error, TaskNotFoundError):
            status_code, message = 404, "task not found"
        elif isinstance(error, ActiveTaskConflictError):
            status_code, message = 409, "active write task exists"
        elif isinstance(error, InvalidTaskTransitionError):
            status_code, message = 409, "task transition is not allowed"
        else:
            status_code, message = 400, "request could not be processed"
        content: dict[str, object] = {"error": {"code": error.code, "message": message}}
        if isinstance(error, ImportEncodingAmbiguousError):
            content["candidates"] = error.candidates
        return JSONResponse(
            status_code=status_code,
            content=content,
        )

    return application


app = create_app(
    Path(os.environ.get("TAME_INK_WORKSPACE", ".tame-ink-workspace")),
    queue_immediate=False,
)
