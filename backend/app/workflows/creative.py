import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol
from uuid import uuid4

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.agents.schemas import SkillExecutionContract
from app.agents.skills import P0Skill
from app.domain.creation import (
    ActualEvent,
    ArtifactKind,
    ArtifactStatus,
    AuthorDecision,
    CandidateArtifactRecord,
    CharacterState,
    CreativeBrief,
    EndingPlan,
    Expectation,
    ReaderContract,
    StoryCard,
    StoryEngine,
    validate_record_id,
)
from app.domain.errors import ArtifactDecisionError, WorkflowGateError
from app.domain.project import MemoryRecord, Project
from app.domain.revision import RevisionWrite
from app.domain.task import Task, TaskKind, TaskPurpose, TaskStatus
from app.repositories.artifacts import ArtifactsRepository
from app.repositories.canon import CanonRepository
from app.repositories.database import DatabaseRepository
from app.repositories.drafts import DraftRepository
from app.repositories.revisions import RevisionRepository
from app.repositories.tasks import TasksRepository
from app.repositories.workspace import WorkspaceRepository
from app.workflows.task_service import TaskService


class SkillRunner(Protocol):
    def execute_skill(
        self, skill: P0Skill, payload: dict[str, object]
    ) -> SkillExecutionContract: ...


class NextCreativeAction(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    kind: Literal["execute", "decision", "input", "wait", "recover", "complete"]
    skill: P0Skill | None = None
    artifact_id: str | None = None
    task_id: str | None = None
    reason: str = Field(min_length=1)


@dataclass(frozen=True)
class CreativeProjectCreated:
    project: Project
    task: Task


class CreativeExport(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    task: Task
    path: str
    chapter_count: int = Field(ge=1)


class CreativeService:
    def __init__(self, workspace: WorkspaceRepository, runner: SkillRunner | None = None) -> None:
        self.workspace = workspace
        self.runner = runner

    def start_project(
        self,
        project_id: str,
        title: str,
        brief: CreativeBrief,
    ) -> CreativeProjectCreated:
        project_path = self.workspace.project_path(project_id)
        if (project_path / "project.yaml").exists():
            raise WorkflowGateError("creative project already exists")
        self.workspace.create_project(project_id)
        project = Project(
            id=project_id,
            title=title,
            language="zh-CN",
            genre=brief.genre_scope,
            constraints="\n".join(brief.constraints),
        )
        CanonRepository(self.workspace).write_project(project)
        database = DatabaseRepository(self.workspace)
        database.initialize(project_id)
        revisions = RevisionRepository(self.workspace)
        before = revisions.current_revision(project_id)
        if before is None:
            raise WorkflowGateError("project revision baseline is missing")
        revisions.confirm(
            project_id,
            RevisionWrite(
                path="commitments/creative-brief.yaml",
                content=yaml.safe_dump(
                    brief.model_dump(mode="json"), allow_unicode=True, sort_keys=True
                ),
                message="确认：创作简报 v1",
            ),
            before,
        )
        DatabaseRepository(self.workspace).rebuild(project_id)
        task = self.create_skill_task(
            project_id,
            "webnovel-research-genre",
            {"instruction": "基于已确认的创作简报，整理题材与读者证据。"},
        )
        return CreativeProjectCreated(project=project, task=task)

    def create_skill_task(
        self, project_id: str, skill: P0Skill, payload: dict[str, object]
    ) -> Task:
        self._ensure_executable_skill(skill)
        self._require_creative_brief(project_id)
        database = DatabaseRepository(self.workspace)
        database.initialize(project_id)
        task = TaskService(TasksRepository(database, project_id)).create(
            TaskKind.WRITE,
            self._purpose_for(skill),
            subject_id=skill,
        )
        DraftRepository(self.workspace).write(
            project_id,
            task.id,
            "request.json",
            json.dumps(
                {"skill": skill, "payload": payload}, ensure_ascii=False, separators=(",", ":")
            ),
            overwrite=False,
        )
        return task

    def execute_skill_task(
        self, project_id: str, task_id: str, skill: P0Skill, payload: dict[str, object]
    ) -> Task:
        if self.runner is None:
            raise WorkflowGateError("creative skill runner is required")
        database = DatabaseRepository(self.workspace)
        database.initialize(project_id)
        tasks = TaskService(TasksRepository(database, project_id))
        task = tasks.get(task_id)
        if task.status is not TaskStatus.RUNNING:
            raise WorkflowGateError("creative skill task must be running")
        if task.subject_id != skill:
            raise WorkflowGateError("creative skill task does not match request")
        result = self.runner.execute_skill(skill, payload)
        return self._store_result(project_id, task, result)

    def store_skill_result(
        self, project_id: str, task_id: str, result: SkillExecutionContract
    ) -> Task:
        """Store a pre-validated Skill result for deterministic or test execution."""
        database = DatabaseRepository(self.workspace)
        database.initialize(project_id)
        task = TaskService(TasksRepository(database, project_id)).get(task_id)
        if task.status is not TaskStatus.RUNNING:
            raise WorkflowGateError("creative skill task must be running")
        if task.subject_id != result.skill:
            raise WorkflowGateError("creative skill task does not match result")
        return self._store_result(project_id, task, result)

    def decide(self, project_id: str, decision: AuthorDecision) -> Task:
        database = DatabaseRepository(self.workspace)
        database.initialize(project_id)
        artifacts = ArtifactsRepository(database, project_id)
        artifact = artifacts.get(decision.artifact_id)
        task_service = TaskService(TasksRepository(database, project_id))
        task = task_service.get(artifact.task_id)
        if task.status is not TaskStatus.AWAITING_APPROVAL:
            raise WorkflowGateError("creative artifact task is not awaiting author decision")
        if decision.action in {"accept", "mix"}:
            self._confirm_artifact(project_id, artifact, decision, artifacts)
            task_service.approve(task.id)
            return task_service.complete(task.id)
        artifacts.decide(decision)
        return task_service.reject(task.id)

    def next_action(self, project_id: str) -> NextCreativeAction:
        database = DatabaseRepository(self.workspace)
        database.initialize(project_id)
        tasks = TasksRepository(database, project_id).list_all()
        active = next(
            (
                task
                for task in tasks
                if task.status in {TaskStatus.PENDING, TaskStatus.RUNNING}
                and task.subject_id is not None
            ),
            None,
        )
        if active is not None:
            return NextCreativeAction(
                kind="wait",
                task_id=active.id,
                reason="当前创作任务正在等待执行或生成结果。",
            )
        recoverable = next(
            (
                task
                for task in tasks
                if task.status in {TaskStatus.FAILED, TaskStatus.INTERRUPTED}
                and task.subject_id is not None
            ),
            None,
        )
        if recoverable is not None:
            return NextCreativeAction(
                kind="recover",
                task_id=recoverable.id,
                reason="创作任务中断或失败，需由作者明确重试。",
            )
        artifacts = ArtifactsRepository(database, project_id).list_all()
        incomplete = next(
            (artifact for artifact in artifacts if artifact.status == "candidate"), None
        )
        if incomplete is not None:
            return NextCreativeAction(
                kind="recover",
                artifact_id=incomplete.id,
                task_id=incomplete.task_id,
                reason="候选保存未完成，需检查任务并明确重试。",
            )
        for status in ("conflict", "needs_decision", "awaiting_approval"):
            blocked = next((artifact for artifact in artifacts if artifact.status == status), None)
            if blocked is not None:
                return NextCreativeAction(
                    kind="decision",
                    artifact_id=blocked.id,
                    reason="存在等待作者处理的候选、冲突或关键选择。",
                )
        project = self.workspace.project_path(project_id)
        if not (project / "commitments/creative-brief.yaml").is_file():
            return NextCreativeAction(
                kind="input",
                reason="尚未确认创作简报；请先明确平台、题材、首个故事目标、约束和素材边界。",
            )
        if not artifacts:
            return NextCreativeAction(
                kind="execute", skill="webnovel-research-genre", reason="先整理题材与读者证据。"
            )
        if not (project / "commitments/reader-contract.yaml").is_file():
            return NextCreativeAction(
                kind="execute",
                skill="webnovel-design-reader-contract",
                reason="读者契约尚未由作者确认。",
            )
        if not (project / "commitments/story-engine.yaml").is_file():
            return NextCreativeAction(
                kind="execute",
                skill="webnovel-design-story-engine",
                reason="故事引擎尚未由作者确认。",
            )
        story_cards = project / "commitments/story-cards"
        if not any(story_cards.glob("*.yaml")):
            return NextCreativeAction(
                kind="execute",
                skill="webnovel-plan-rolling-story",
                reason="当前没有已确认的滚动故事卡。",
            )
        current_card_id = self._current_story_card_id(project)
        if current_card_id is None:
            return NextCreativeAction(
                kind="input",
                reason="请将一张故事卡标记为 current，以开始本轮章节创作。",
            )
        last_purpose = self._last_chapter_task_purpose(tasks)
        if last_purpose is TaskPurpose.CHAPTER:
            return NextCreativeAction(
                kind="execute",
                skill="webnovel-curate-memory",
                reason="上一章已批准，请整理新增事实与期待变化到记忆库。",
            )
        return NextCreativeAction(
            kind="execute",
            skill="webnovel-plan-chapter",
            reason="当前故事卡已确认，请生成章节场景执行清单。",
        )

    def export_confirmed_chapters(
        self, project_id: str, export_id: str = "manuscript"
    ) -> CreativeExport:
        validate_record_id(export_id)
        database = DatabaseRepository(self.workspace)
        database.initialize(project_id)
        tasks = TaskService(TasksRepository(database, project_id))
        task = tasks.create(TaskKind.WRITE, TaskPurpose.EXPORT, subject_id=export_id)
        tasks.start(task.id)
        try:
            project = self.workspace.project_path(project_id)
            chapter_root = project / "canon/chapters"
            chapters = sorted(path for path in chapter_root.glob("*.md") if path.is_file())
            if not chapters:
                raise WorkflowGateError("confirmed chapters are required before export")
            content = "\n\n".join(
                CanonRepository(self.workspace)
                .read_markdown(project_id, path.relative_to(project).as_posix())
                .markdown
                .rstrip()
                for path in chapters
            ) + "\n"
            relative = f".tame-ink/exports/{export_id}.md"
            target = self.workspace.resolve_project_path(project_id, relative)
            temporary = target.with_name(f".{target.name}.tmp")
            target.parent.mkdir(parents=True, exist_ok=True)
            with temporary.open("w") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        except Exception:
            if tasks.get(task.id).status is TaskStatus.RUNNING:
                tasks.fail(task.id, "EXPORT_FAILED", "confirmed chapter export failed")
            raise
        return CreativeExport(
            task=tasks.complete(task.id), path=relative, chapter_count=len(chapters)
        )

    def set_current_story_card(self, project_id: str, card_id: str) -> StoryCard:
        """Mark one confirmed story card as the active production unit.

        Promotes the target card to status "current" and demotes any card that
        was previously "current" back to "planned", in a single atomic revision
        so the workflow never sees two current cards or none mid-write. This is
        the author-facing action behind next_action's "input" step, replacing
        the need to hand-edit YAML.
        """
        validate_record_id(card_id)
        canon = CanonRepository(self.workspace)
        cards = canon.list_story_cards(project_id)
        target = next((card for card in cards if card.id == card_id), None)
        if target is None:
            raise WorkflowGateError("story card to activate does not exist")

        writes: list[RevisionWrite] = []
        for card in cards:
            if card.id == card_id and card.status != "current":
                updated = card.model_copy(update={"status": "current"})
            elif card.id != card_id and card.status == "current":
                updated = card.model_copy(update={"status": "planned"})
            else:
                continue
            writes.append(
                RevisionWrite(
                    path=f"commitments/story-cards/{updated.id}.yaml",
                    content=yaml.safe_dump(
                        updated.model_dump(mode="json"), allow_unicode=True, sort_keys=True
                    ),
                    message="确认：设置当前故事卡",
                )
            )

        if writes:
            revisions = RevisionRepository(self.workspace)
            before = revisions.current_revision(project_id)
            if before is None:
                raise WorkflowGateError("project revision baseline is missing")
            revisions.confirm_batch(project_id, writes, before)
            DatabaseRepository(self.workspace).rebuild(project_id)
        return canon.read_story_card(project_id, card_id)

    def _store_result(
        self, project_id: str, task: Task, result: SkillExecutionContract
    ) -> Task:
        if task.subject_id != result.skill:
            raise WorkflowGateError("creative skill result does not match task")
        drafts = DraftRepository(self.workspace)
        artifact_id = str(uuid4())
        payload_path = f"artifacts/{artifact_id}.json"
        payload = result.model_dump(mode="json")
        drafts.write(
            project_id,
            task.id,
            payload_path,
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        )
        if result.candidate is None:
            kind: ArtifactKind = "evidence_finding"
            source_layer: Literal["candidate", "hypothesis"] = "hypothesis"
        else:
            kind = result.candidate.artifact_kind
            source_layer = "hypothesis" if kind == "evidence_finding" else "candidate"
        now = datetime.now(UTC)
        artifact = CandidateArtifactRecord(
            id=artifact_id,
            project_id=project_id,
            task_id=task.id,
            kind=kind,
            source_layer=source_layer,
            status="candidate",
            payload_path=payload_path,
            created_at=now,
            updated_at=now,
        )
        artifacts = ArtifactsRepository(DatabaseRepository(self.workspace), project_id)
        artifacts.create(artifact)
        targets: dict[str, ArtifactStatus] = {
            "ready": "ready",
            "needs_decision": "needs_decision",
            "conflict": "conflict",
        }
        target = targets[result.status]
        artifact = artifacts.transition(artifact.id, "candidate", target)
        if target == "ready":
            artifacts.transition(artifact.id, "ready", "awaiting_approval")
        tasks = TaskService(TasksRepository(DatabaseRepository(self.workspace), project_id))
        tasks.repository.append_event(
            task.id,
            "creative.skill_result_stored",
            {"artifact_id": artifact.id, "skill": result.skill, "status": result.status},
        )
        return tasks.await_approval(task.id)

    def _confirm_artifact(
        self,
        project_id: str,
        artifact: CandidateArtifactRecord,
        decision: AuthorDecision,
        artifacts: ArtifactsRepository,
    ) -> None:
        if decision.formal_path is None:
            raise ArtifactDecisionError("author decision requires a formal path")
        result = self._read_result(project_id, artifact)
        if result.candidate is None:
            raise ArtifactDecisionError("blocked result has no candidate to confirm")
        content = self._formal_content(artifact.kind, result.candidate.payload, decision)
        revisions = RevisionRepository(self.workspace)
        before = revisions.current_revision(project_id)
        if before is None:
            raise WorkflowGateError("project revision baseline is missing")
        revision = revisions.confirm(
            project_id,
            RevisionWrite(
                path=decision.formal_path,
                content=content,
                message=f"确认：{artifact.kind}",
            ),
            before,
        )
        try:
            artifacts.decide(decision)
        except Exception:
            revisions.rollback(project_id, before, revision.id)
            raise
        DatabaseRepository(self.workspace).rebuild(project_id)

    def _read_result(
        self, project_id: str, artifact: CandidateArtifactRecord
    ) -> SkillExecutionContract:
        try:
            raw = DraftRepository(self.workspace).read(
                project_id, artifact.task_id, artifact.payload_path
            )
            return SkillExecutionContract.model_validate_json(raw)
        except (OSError, ValidationError, ValueError) as error:
            raise WorkflowGateError("stored creative result is invalid") from error

    @staticmethod
    def _formal_content(
        kind: ArtifactKind, payload: dict[str, object], decision: AuthorDecision
    ) -> str:
        if kind == "chapter_draft":
            # 段落级审批：作者逐段接受/改写后合并的正文经 content_override 传入，
            # 优先于 AI 原始 markdown 写入 canon。这让段落级编辑真正落地。
            if decision.content_override is not None and decision.content_override.strip():
                return decision.content_override
            markdown = payload.get("markdown")
            if not isinstance(markdown, str) or not markdown.strip():
                raise ArtifactDecisionError("chapter draft payload is invalid")
            return markdown
        models: dict[ArtifactKind, type[BaseModel]] = {
            "reader_contract": ReaderContract,
            "story_engine": StoryEngine,
            "character_state": CharacterState,
            "expectation": Expectation,
            "story_card": StoryCard,
            "chapter_plan": StoryCard,
            "actual_event": ActualEvent,
            "memory_proposal": MemoryRecord,
            "ending_plan": EndingPlan,
        }
        model = models.get(kind)
        if model is None:
            raise ArtifactDecisionError(f"{kind} cannot be directly formalized")
        try:
            fields = payload if kind == "memory_proposal" else {
                **payload,
                "decision_id": decision.id,
                "confirmed_by": "author",
            }
            confirmed = model.model_validate(
                fields
            )
            return yaml.safe_dump(
                confirmed.model_dump(mode="json"), allow_unicode=True, sort_keys=True
            )
        except (ValidationError, yaml.YAMLError) as error:
            raise ArtifactDecisionError("candidate payload cannot become formal content") from error

    @staticmethod
    def _current_story_card_id(project) -> str | None:  # type: ignore[no-untyped-def]
        """Return the id of the story card marked status: current, if any.

        Story cards are stored as YAML under commitments/story-cards/. A card
        is the active production unit when its status field equals "current".
        Malformed or unreadable cards are skipped rather than raising, so a
        single bad file cannot block the whole workflow.
        """
        card_root = project / "commitments/story-cards"
        for path in sorted(card_root.glob("*.yaml")):
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8"))
            except (OSError, yaml.YAMLError):
                continue
            if isinstance(data, dict) and data.get("status") == "current":
                card_id = data.get("id")
                if isinstance(card_id, str) and card_id:
                    return card_id
        return None

    @staticmethod
    def _last_chapter_task_purpose(tasks: list[Task]) -> TaskPurpose | None:
        """Return the purpose of the most recent completed chapter-cycle task.

        Only CHAPTER and MEMORY_CURATION tasks advance the per-chapter loop;
        tasks is ordered newest-first (created_at DESC), so the first match
        reflects the latest step the author actually completed. Returns None
        when no chapter-cycle task has completed yet.
        """
        cycle_purposes = {TaskPurpose.CHAPTER, TaskPurpose.MEMORY_CURATION}
        for task in tasks:
            if task.status is TaskStatus.COMPLETED and task.purpose in cycle_purposes:
                return task.purpose
        return None

    @staticmethod
    def _purpose_for(skill: P0Skill) -> TaskPurpose:
        if skill == "webnovel-draft":
            return TaskPurpose.CHAPTER
        if skill == "webnovel-curate-memory":
            return TaskPurpose.MEMORY_CURATION
        if skill == "webnovel-plan-ending":
            return TaskPurpose.EXPORT
        return TaskPurpose.SETTING

    @staticmethod
    def _ensure_executable_skill(skill: P0Skill) -> None:
        if skill == "webnovel-studio":
            raise WorkflowGateError("webnovel studio is a shared policy, not an executable skill")

    def _require_creative_brief(self, project_id: str) -> None:
        path = self.workspace.project_path(project_id) / "commitments/creative-brief.yaml"
        if not path.is_file():
            raise WorkflowGateError("creative brief must be author-confirmed before AI execution")
