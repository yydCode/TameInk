import re

import yaml
from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict

from app.agents.schemas import CommercialReport
from app.domain.task import TaskPurpose, TaskStatus
from app.repositories.database import DatabaseRepository
from app.repositories.drafts import DraftRepository
from app.repositories.tasks import TasksRepository

router = APIRouter(prefix="/projects/{project_id}/dashboard", tags=["dashboard"])


class ForeshadowingStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    status: str
    source: str
    content: str | None = None
    quote: str


class ChapterRhythm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chapter_id: str
    word_count: int
    volume_id: str | None = None


class CommercialTrendItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chapter_id: str
    task_id: str
    total_score: int
    recommendation: str


class CharacterStat(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    kind: str
    status: str
    source: str
    content: str | None = None


@router.get("/foreshadowing", response_model=list[ForeshadowingStatus])
def list_foreshadowing(project_id: str, request: Request) -> list[ForeshadowingStatus]:
    """P3: 伏笔追踪——哪些已埋、待回收、已过期。"""
    project = request.app.state.workspace.project_path(project_id)
    root = project / "memory" / "foreshadowing"
    if not root.is_dir():
        return []
    result: list[ForeshadowingStatus] = []
    for path in sorted(root.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text())
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(data, dict):
            continue
        result.append(
            ForeshadowingStatus(
                id=str(data.get("id", path.stem)),
                status=str(data.get("status", "unknown")),
                source=str(data.get("source", "")),
                content=data.get("content"),
                quote=str(data.get("quote", "")),
            )
        )
    return result


@router.get("/characters", response_model=list[CharacterStat])
def list_characters(project_id: str, request: Request) -> list[CharacterStat]:
    """P3: 角色与关系统计——谁出现在哪些章节、关系进展。"""
    project = request.app.state.workspace.project_path(project_id)
    result: list[CharacterStat] = []
    for subdir in ("relationships", "facts"):
        root = project / "memory" / subdir
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*.yaml")):
            try:
                data = yaml.safe_load(path.read_text())
            except (OSError, yaml.YAMLError):
                continue
            if not isinstance(data, dict):
                continue
            result.append(
                CharacterStat(
                    id=str(data.get("id", path.stem)),
                    kind=str(data.get("kind", subdir)),
                    status=str(data.get("status", "unknown")),
                    source=str(data.get("source", "")),
                    content=data.get("content"),
                )
            )
    return result


@router.get("/chapters", response_model=list[ChapterRhythm])
def list_chapter_rhythm(project_id: str, request: Request) -> list[ChapterRhythm]:
    """P3: 章节节奏曲线——每章字数和所属分卷。"""
    workspace = request.app.state.workspace
    project = workspace.project_path(project_id)
    chapters_root = project / "canon" / "chapters"
    if not chapters_root.is_dir():
        return []
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
    result: list[ChapterRhythm] = []
    for path in sorted(chapters_root.glob("*.md")):
        if not path.is_file():
            continue
        content = path.read_text()
        words = len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]|[A-Za-z0-9]+", content))
        result.append(
            ChapterRhythm(
                chapter_id=path.stem,
                word_count=words,
                volume_id=chapter_volumes.get(path.stem),
            )
        )
    return result


@router.get("/commercial-trend", response_model=list[CommercialTrendItem])
def list_commercial_trend(project_id: str, request: Request) -> list[CommercialTrendItem]:
    """P3: 商业分趋势——哪些章节商业分低、什么问题反复出现。"""
    workspace = request.app.state.workspace
    database = DatabaseRepository(workspace)
    database.initialize(project_id)
    tasks = TasksRepository(database, project_id).list_all()
    drafts = DraftRepository(workspace)
    result: list[CommercialTrendItem] = []
    for task in tasks:
        if task.purpose is not TaskPurpose.CHAPTER or task.status is not TaskStatus.COMPLETED:
            continue
        if task.chapter_id is None:
            continue
        files = drafts.list_files(project_id, task.id)
        if "commercial-report.json" not in files:
            continue
        try:
            report = CommercialReport.model_validate_json(
                drafts.read(project_id, task.id, "commercial-report.json")
            )
        except ValueError:
            continue
        result.append(
            CommercialTrendItem(
                chapter_id=task.chapter_id,
                task_id=task.id,
                total_score=report.total_score,
                recommendation=report.recommendation,
            )
        )
    return result
