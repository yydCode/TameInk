import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import yaml
from fastapi import APIRouter, Request, status
from pydantic import BaseModel, ConfigDict, Field

from app.domain.errors import CanonVersionConflictError
from app.domain.project import (
    ChapterNode,
    Project,
    ProjectDocument,
    ProjectSnapshot,
    ProjectStats,
    VolumeNode,
)
from app.domain.task import Task, TaskPurpose, TaskStatus
from app.repositories.canon import CanonRepository
from app.repositories.database import DatabaseRepository
from app.repositories.drafts import DraftRepository
from app.repositories.revisions import RevisionRepository
from app.repositories.tasks import TasksRepository
from app.repositories.workspace import WorkspaceRepository
from app.workflows.new_book import NewBookRequest, NewBookService

router = APIRouter(prefix="/projects", tags=["projects"])


class CreateProjectRequest(NewBookRequest):
    model_config = ConfigDict(extra="forbid", strict=True)

    setting_draft: str


class DraftContentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    path: str = Field(min_length=1)
    content: str
    base_revision: str | None


class DraftContentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    task_id: str
    path: str
    content: str
    revision: str | None


class WorkflowStatus(BaseModel):
    """Confirmed creative milestones required before chapter generation."""

    setting_confirmed: bool
    outline_confirmed: bool
    volume_one_confirmed: bool
    commercial_confirmed: bool


@router.post("", status_code=status.HTTP_201_CREATED)
def create_project(payload: CreateProjectRequest, request: Request) -> dict[str, object]:
    workspace: WorkspaceRepository = request.app.state.workspace
    result = NewBookService(workspace).create(
        NewBookRequest(**payload.model_dump(exclude={"setting_draft"})), payload.setting_draft
    )
    return {"project": result.project, "task": result.task}


@router.get("", response_model=list[Project])
def list_projects(request: Request) -> list[Project]:
    workspace: WorkspaceRepository = request.app.state.workspace
    canon = CanonRepository(workspace)
    return [canon.read_project(project_id) for project_id in workspace.project_ids()]


@router.get("/{project_id}", response_model=Project)
def get_project(project_id: str, request: Request) -> Project:
    workspace: WorkspaceRepository = request.app.state.workspace
    return CanonRepository(workspace).read_project(project_id)


@router.get("/{project_id}/snapshot", response_model=ProjectSnapshot)
def get_project_snapshot(project_id: str, request: Request) -> ProjectSnapshot:
    workspace: WorkspaceRepository = request.app.state.workspace
    project = CanonRepository(workspace).read_project(project_id)
    project_path = workspace.project_path(project_id)
    database = DatabaseRepository(workspace)
    database.initialize(project_id)
    tasks = TasksRepository(database, project_id).list_all()
    chapter_volumes = {
        task.chapter_id: task.volume_id
        for task in reversed(tasks)
        if task.purpose is TaskPurpose.CHAPTER
        and task.status is TaskStatus.COMPLETED
        and task.chapter_id is not None
    }

    documents: list[ProjectDocument] = []
    core_documents: tuple[
        tuple[
            str,
            Literal["setting", "outline", "commercial", "volume", "chapter"],
            str,
        ],
        ...,
    ] = (
        ("canon/world/setting.md", "setting", "故事设定"),
        ("canon/outline.md", "outline", "全书大纲"),
        ("canon/commercial.yaml", "commercial", "商业定位"),
    )
    for relative, kind, fallback in core_documents:
        path = project_path / relative
        if path.is_file():
            documents.append(_document(project_path, path, kind, fallback))

    volumes: list[VolumeNode] = []
    volume_by_id: dict[str, VolumeNode] = {}
    for path in _files(project_path / "canon/volumes", ".md"):
        document = _document(project_path, path, "volume", f"分卷 {path.stem}")
        volume = VolumeNode(**document.model_dump(), id=path.stem, chapters=[])
        volumes.append(volume)
        volume_by_id[path.stem] = volume
        documents.append(document)

    unassigned: list[ChapterNode] = []
    for path in _files(project_path / "canon/chapters", ".md"):
        volume_id = chapter_volumes.get(path.stem)
        document = _document(project_path, path, "chapter", f"章节 {path.stem}")
        chapter = ChapterNode(**document.model_dump(), id=path.stem, volume_id=volume_id)
        if volume_id is not None and volume_id in volume_by_id:
            volume_by_id[volume_id].chapters.append(chapter)
        else:
            unassigned.append(chapter)
        documents.append(document)

    active_foreshadow_count = 0
    for path in _files(project_path / "memory/foreshadowing", ".yaml"):
        try:
            payload = yaml.safe_load(path.read_text())
        except (OSError, yaml.YAMLError):
            continue
        if isinstance(payload, dict) and payload.get("status") == "active":
            active_foreshadow_count += 1
    chapters = [*unassigned, *(chapter for volume in volumes for chapter in volume.chapters)]
    return ProjectSnapshot(
        project=project,
        documents=documents,
        volumes=volumes,
        unassigned_chapters=unassigned,
        stats=ProjectStats(
            total_words=sum(chapter.word_count for chapter in chapters),
            chapter_count=len(chapters),
            volume_count=len(volumes),
            active_foreshadow_count=active_foreshadow_count,
        ),
    )


def _files(directory: Path, suffix: str) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(path for path in directory.iterdir() if path.is_file() and path.suffix == suffix)


def _document(
    project_path: Path,
    path: Path,
    kind: Literal["setting", "outline", "commercial", "volume", "chapter"],
    fallback_title: str,
) -> ProjectDocument:
    content = path.read_text()
    heading = re.search(r"^#{1,6}[ \t]+(.+?)[ \t]*$", content, flags=re.MULTILINE)
    title = heading.group(1).strip() if heading is not None else fallback_title
    words = re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]|[A-Za-z0-9]+", content)
    return ProjectDocument(
        path=str(path.relative_to(project_path)),
        kind=kind,
        title=title,
        word_count=len(words),
        updated_at=datetime.fromtimestamp(path.stat().st_mtime, tz=UTC),
    )


@router.get("/{project_id}/workflow-status", response_model=WorkflowStatus)
def get_workflow_status(project_id: str, request: Request) -> WorkflowStatus:
    workspace: WorkspaceRepository = request.app.state.workspace
    # Resolve through the workspace repository so the endpoint keeps the same path checks as writes.
    return WorkflowStatus(
        setting_confirmed=workspace.resolve_project_path(
            project_id, "canon/world/setting.md"
        ).is_file(),
        outline_confirmed=workspace.resolve_project_path(project_id, "canon/outline.md").is_file(),
        volume_one_confirmed=workspace.resolve_project_path(
            project_id, "canon/volumes/1.md"
        ).is_file(),
        commercial_confirmed=workspace.resolve_project_path(
            project_id, "canon/commercial.yaml"
        ).is_file(),
    )


@router.get("/{project_id}/drafts/{task_id}", response_model=DraftContentResponse)
def get_draft(project_id: str, task_id: str, path: str, request: Request) -> DraftContentResponse:
    workspace: WorkspaceRepository = request.app.state.workspace
    TasksRepository(DatabaseRepository(workspace), project_id).get(task_id)
    content = DraftRepository(workspace).read(project_id, task_id, path)
    revision = RevisionRepository(workspace).current_revision(project_id)
    return DraftContentResponse(task_id=task_id, path=path, content=content, revision=revision)


@router.put("/{project_id}/drafts/{task_id}", response_model=DraftContentResponse)
def save_draft(
    project_id: str, task_id: str, payload: DraftContentRequest, request: Request
) -> DraftContentResponse:
    workspace: WorkspaceRepository = request.app.state.workspace
    TasksRepository(DatabaseRepository(workspace), project_id).get(task_id)
    revision = RevisionRepository(workspace).current_revision(project_id)
    if payload.base_revision != revision:
        raise CanonVersionConflictError("formal content changed while editing")
    DraftRepository(workspace).write(project_id, task_id, payload.path, payload.content)
    return DraftContentResponse(
        task_id=task_id,
        path=payload.path,
        content=payload.content,
        revision=revision,
    )


@router.post("/{project_id}/setting/{task_id}/approve", response_model=Task)
def approve_setting(project_id: str, task_id: str, request: Request) -> Task:
    return NewBookService(request.app.state.workspace).approve_setting(project_id, task_id)
