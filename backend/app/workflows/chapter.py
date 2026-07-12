import json
from collections.abc import Sequence
from typing import Protocol

from app.agents.schemas import (
    ChapterDraft,
    ChapterPlan,
    ContinuityIssue,
    RevisionProposal,
    StyleIssue,
)
from app.domain.errors import WorkflowGateError
from app.domain.revision import RevisionWrite
from app.domain.task import Task, TaskKind
from app.repositories.database import DatabaseRepository
from app.repositories.drafts import DraftRepository
from app.repositories.revisions import RevisionRepository
from app.repositories.tasks import TasksRepository
from app.repositories.workspace import WorkspaceRepository
from app.workflows.memory import MemoryService
from app.workflows.task_service import TaskService


class ChapterRunner(Protocol):
    def invoke(self, agent: str, payload: dict[str, object]) -> object: ...


class ChapterService:
    def __init__(self, workspace: WorkspaceRepository, runner: ChapterRunner | None = None) -> None:
        self.workspace = workspace
        self.runner = runner

    def run(
        self,
        project_id: str,
        chapter_id: str,
        instruction: str,
        volume_id: str = "1",
    ) -> Task:
        if self.runner is None:
            raise WorkflowGateError("chapter runner is required")
        plan = self.runner.invoke(
            "ChapterPlanner",
            {"project_id": project_id, "chapter_id": chapter_id, "instruction": instruction},
        )
        if not isinstance(plan, ChapterPlan) or plan.chapter_id != chapter_id:
            raise WorkflowGateError("ChapterPlanner returned an invalid chapter plan")
        draft = self.runner.invoke(
            "DraftWriter",
            {"project_id": project_id, "chapter_id": chapter_id, "plan": plan.model_dump()},
        )
        if not isinstance(draft, ChapterDraft) or draft.chapter_id != chapter_id:
            raise WorkflowGateError("DraftWriter returned an invalid chapter draft")
        audit_payload: dict[str, object] = {
            "project_id": project_id,
            "chapter_id": chapter_id,
            "draft": draft.markdown,
        }
        continuity = self.runner.invoke("ContinuityAuditor", audit_payload)
        style = self.runner.invoke("StyleCritic", audit_payload)
        if not isinstance(continuity, list) or not all(
            isinstance(issue, ContinuityIssue) for issue in continuity
        ):
            raise WorkflowGateError("ContinuityAuditor returned an invalid issue report")
        if not isinstance(style, list) or not all(isinstance(issue, StyleIssue) for issue in style):
            raise WorkflowGateError("StyleCritic returned an invalid issue report")
        issues = self.validate_audit_issues(draft.markdown, continuity, style)
        revisions = self.runner.invoke(
            "DraftWriter",
            {
                "project_id": project_id,
                "chapter_id": chapter_id,
                "draft": draft.markdown,
                "issues": [issue.model_dump() for issue in issues],
                "instruction": "revise only the cited passages for reported issue IDs",
            },
        )
        if not isinstance(revisions, list) or not all(
            isinstance(revision, RevisionProposal) for revision in revisions
        ):
            raise WorkflowGateError("DraftWriter returned an invalid revision report")
        revised = self.apply_revisions(draft.markdown, issues, revisions)
        return self.start(project_id, chapter_id, plan.content, revised, [], volume_id)

    def start(
        self,
        project_id: str,
        chapter_id: str,
        plan: str,
        draft: str,
        issues: Sequence[dict[str, str]],
        volume_id: str = "1",
    ) -> Task:
        project = self.workspace.project_path(project_id)
        if (
            not (project / "canon/outline.md").is_file()
            or not (project / "canon/volumes" / f"{volume_id}.md").is_file()
        ):
            raise WorkflowGateError("approved book outline and volume are required")
        service = TaskService(TasksRepository(DatabaseRepository(self.workspace), project_id))
        task = service.create(TaskKind.WRITE)
        service.start(task.id)
        drafts = DraftRepository(self.workspace)
        drafts.write(project_id, task.id, "plan.md", plan)
        drafts.write(project_id, task.id, "chapter.md", self._apply_issues(draft, issues))
        drafts.write(
            project_id,
            task.id,
            "run.json",
            json.dumps(
                {"project_id": project_id, "chapter_id": chapter_id, "volume_id": volume_id}
            ),
        )
        return service.await_approval(task.id)

    def approve(self, project_id: str, task_id: str, chapter_id: str, volume_id: str = "1") -> Task:
        service = TaskService(TasksRepository(DatabaseRepository(self.workspace), project_id))
        service.approve(task_id)
        try:
            drafts = DraftRepository(self.workspace)
            manifest = json.loads(drafts.read(project_id, task_id, "run.json"))
            if manifest["project_id"] != project_id or manifest["chapter_id"] != chapter_id:
                raise WorkflowGateError("chapter approval does not match its run manifest")
            stored_volume_id = str(manifest["volume_id"])
            content = drafts.read(project_id, task_id, "chapter.md")
            revisions = RevisionRepository(self.workspace)
            message = f"确认：章节 {chapter_id}"
            revisions.confirm_batch(
                project_id,
                [
                    RevisionWrite(
                        path=f"canon/chapters/{chapter_id}.md",
                        content=content,
                        message=message,
                    ),
                    *MemoryService.summary_writes(chapter_id, stored_volume_id, content),
                ],
                revisions.current_revision(project_id),
            )
            DatabaseRepository(self.workspace).rebuild(project_id)
        except Exception:
            service.fail(task_id)
            raise
        return service.complete(task_id)

    @staticmethod
    def _apply_issues(draft: str, issues: Sequence[dict[str, str]]) -> str:
        issue_ids: set[str] = set()
        for issue in issues:
            issue_id = issue.get("id")
            citation = issue.get("citation")
            if not issue_id or not citation:
                raise WorkflowGateError("chapter issue requires an id and exact citation")
            if issue_id in issue_ids:
                raise WorkflowGateError("chapter issue ids must be unique")
            issue_ids.add(issue_id)
            target = issue.get("target")
            replacement = issue.get("replacement")
            if citation != target or not target or replacement is None or draft.count(target) != 1:
                raise WorkflowGateError("revision must target one cited local passage")
            draft = draft.replace(target, replacement, 1)
        return draft

    @staticmethod
    def validate_audit_issues(
        draft: str,
        continuity: Sequence[ContinuityIssue],
        style: Sequence[StyleIssue],
    ) -> list[ContinuityIssue | StyleIssue]:
        issues: list[ContinuityIssue | StyleIssue] = [*continuity, *style]
        ids = [issue.id for issue in issues]
        if len(ids) != len(set(ids)):
            raise WorkflowGateError("chapter issue ids must be globally unique")
        for issue in issues:
            start, end = issue.citation.character_range()
            if end > len(draft) or draft[start:end] != issue.citation.quote:
                raise WorkflowGateError(
                    "chapter issue citation must exactly match the original draft"
                )
        return issues

    @staticmethod
    def apply_revisions(
        draft: str,
        issues: Sequence[ContinuityIssue | StyleIssue],
        revisions: Sequence[RevisionProposal],
    ) -> str:
        issue_by_id = {issue.id: issue for issue in issues}
        revised_issue_ids: set[str] = set()
        edits: list[tuple[int, int, str]] = []
        for revision in revisions:
            issue = issue_by_id.get(revision.issue_id)
            if issue is None or revision.issue_id in revised_issue_ids:
                raise WorkflowGateError("revision must reference one reported issue id")
            revised_issue_ids.add(revision.issue_id)
            start, end = revision.citation.character_range()
            if start == 0 and end == len(draft):
                raise WorkflowGateError("revision must not rewrite the whole chapter")
            if (
                revision.target != revision.citation.location
                or revision.citation != issue.citation
                or end > len(draft)
                or draft[start:end] != revision.citation.quote
            ):
                raise WorkflowGateError("revision citation must match its reported issue and draft")
            edits.append((start, end, revision.replacement))
        edits.sort(reverse=True)
        previous_start = len(draft)
        for start, end, replacement in edits:
            if end > previous_start:
                raise WorkflowGateError("local revisions must not overlap")
            draft = draft[:start] + replacement + draft[end:]
            previous_start = start
        return draft
