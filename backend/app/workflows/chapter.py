import json
from collections.abc import Sequence
from typing import Protocol, TypeVar

from app.agents.schemas import (
    ChapterDraft,
    ChapterPlan,
    CommercialIssue,
    CommercialReport,
    ContinuityIssue,
    MemoryCandidate,
    MemoryCuration,
    RevisionProposal,
    StyleIssue,
)
from app.domain.errors import CommercialGateError, WorkflowGateError
from app.domain.revision import RevisionWrite
from app.domain.task import Task, TaskKind, TaskPurpose
from app.repositories.database import DatabaseRepository
from app.repositories.drafts import DraftRepository
from app.repositories.revisions import RevisionRepository
from app.repositories.tasks import TasksRepository
from app.repositories.workspace import WorkspaceRepository
from app.workflows.commercial import CommercialService
from app.workflows.memory import MemoryService
from app.workflows.task_service import TaskService


class ChapterRunner(Protocol):
    def invoke(self, agent: str, payload: dict[str, object]) -> object: ...


AuditIssue = ContinuityIssue | StyleIssue | CommercialIssue
AuditIssueT = TypeVar("AuditIssueT", ContinuityIssue, StyleIssue, CommercialIssue)


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
        self._require_prerequisites(project_id, volume_id)
        service = TaskService(TasksRepository(DatabaseRepository(self.workspace), project_id))
        task = service.create(
            TaskKind.WRITE,
            TaskPurpose.CHAPTER,
            subject_id=chapter_id,
            volume_id=volume_id,
            chapter_id=chapter_id,
        )
        service.start(task.id)
        try:
            return self.run_for_task(project_id, task.id, chapter_id, instruction, volume_id)
        except Exception as error:
            current = service.get(task.id)
            if current.status.value == "running":
                service.fail(task.id, type(error).__name__, "chapter generation failed")
            raise

    def run_for_task(
        self,
        project_id: str,
        task_id: str,
        chapter_id: str,
        instruction: str,
        volume_id: str = "1",
    ) -> Task:
        if self.runner is None:
            raise WorkflowGateError("chapter runner is required")
        self._require_prerequisites(project_id, volume_id)
        service = TaskService(TasksRepository(DatabaseRepository(self.workspace), project_id))
        task = service.get(task_id)
        if task.status.value != "running":
            raise WorkflowGateError("chapter generation task must be running")
        if task.chapter_id != chapter_id or task.volume_id != volume_id:
            raise WorkflowGateError("chapter generation task metadata does not match")
        commercial_profile = CommercialService(self.workspace).read(project_id)
        if commercial_profile is None:
            raise WorkflowGateError("approved commercial profile is required")
        plan = self.runner.invoke(
            "ChapterPlanner",
            {
                "project_id": project_id,
                "chapter_id": chapter_id,
                "volume_id": volume_id,
                "instruction": instruction,
            },
        )
        if not isinstance(plan, ChapterPlan) or plan.chapter_id != chapter_id:
            raise WorkflowGateError("ChapterPlanner returned an invalid chapter plan")
        draft = self.runner.invoke(
            "DraftWriter",
            {
                "project_id": project_id,
                "chapter_id": chapter_id,
                "volume_id": volume_id,
                "plan": plan.model_dump(),
            },
        )
        if not isinstance(draft, ChapterDraft) or draft.chapter_id != chapter_id:
            raise WorkflowGateError("DraftWriter returned an invalid chapter draft")
        audit_payload: dict[str, object] = {
            "project_id": project_id,
            "chapter_id": chapter_id,
            "volume_id": volume_id,
            "plan": plan.model_dump(),
            "draft": draft.markdown,
        }
        continuity = self.runner.invoke("ContinuityAuditor", audit_payload)
        style = self.runner.invoke("StyleCritic", audit_payload)
        commercial = self.runner.invoke("RetentionAuditor", audit_payload)
        if not isinstance(continuity, list) or not all(
            isinstance(issue, ContinuityIssue) for issue in continuity
        ):
            raise WorkflowGateError("ContinuityAuditor returned an invalid issue report")
        if not isinstance(style, list) or not all(isinstance(issue, StyleIssue) for issue in style):
            raise WorkflowGateError("StyleCritic returned an invalid issue report")
        if not isinstance(commercial, CommercialReport) or commercial.chapter_id != chapter_id:
            raise WorkflowGateError("RetentionAuditor returned an invalid commercial report")
        continuity = self.normalize_audit_citations(draft.markdown, continuity)
        style = self.normalize_audit_citations(draft.markdown, style)
        commercial = self.normalize_commercial_report(draft.markdown, commercial)
        issues = self.validate_audit_issues(draft.markdown, continuity, style, commercial.issues)
        if issues:
            revisions = self.runner.invoke(
                "DraftWriter",
                {
                    "project_id": project_id,
                    "chapter_id": chapter_id,
                    "volume_id": volume_id,
                    "plan": plan.model_dump(),
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
        else:
            revised = draft.markdown
        final_commercial = self.runner.invoke(
            "RetentionAuditor",
            {
                "project_id": project_id,
                "chapter_id": chapter_id,
                "volume_id": volume_id,
                "plan": plan.model_dump(),
                "draft": revised,
                "instruction": (
                    "score the revised candidate without assuming prior issues are fixed"
                ),
            },
        )
        if (
            not isinstance(final_commercial, CommercialReport)
            or final_commercial.chapter_id != chapter_id
        ):
            raise WorkflowGateError("RetentionAuditor returned an invalid commercial report")
        final_commercial = self.normalize_commercial_report(revised, final_commercial)
        self.validate_audit_issues(revised, [], [], final_commercial.issues)
        memory = self.runner.invoke(
            "MemoryCurator",
            {
                "project_id": project_id,
                "chapter_id": chapter_id,
                "volume_id": volume_id,
                "draft": revised,
                "instruction": "extract only durable facts supported by exact draft citations",
            },
        )
        if not isinstance(memory, MemoryCuration):
            raise WorkflowGateError("MemoryCurator returned an invalid candidate list")
        self.validate_memory_candidates(revised, memory.updates)
        return self._store_candidate(
            project_id,
            task_id,
            chapter_id,
            plan.content,
            revised,
            [],
            volume_id,
            commercial_report=final_commercial,
            minimum_commercial_score=commercial_profile.minimum_commercial_score,
            memory_candidates=memory,
            audit_reports={
                "continuity": [issue.model_dump(mode="json") for issue in continuity],
                "style": [issue.model_dump(mode="json") for issue in style],
                "initial_commercial": commercial.model_dump(mode="json"),
            },
        )

    def start(
        self,
        project_id: str,
        chapter_id: str,
        plan: str,
        draft: str,
        issues: Sequence[dict[str, str]],
        volume_id: str = "1",
        commercial_report: CommercialReport | None = None,
        minimum_commercial_score: int | None = None,
        memory_candidates: MemoryCuration | None = None,
        audit_reports: dict[str, object] | None = None,
    ) -> Task:
        if (commercial_report is None) != (minimum_commercial_score is None):
            raise WorkflowGateError(
                "commercial report and score threshold must be provided together"
            )
        self._require_prerequisites(project_id, volume_id)
        service = TaskService(TasksRepository(DatabaseRepository(self.workspace), project_id))
        task = service.create(
            TaskKind.WRITE,
            TaskPurpose.CHAPTER,
            subject_id=chapter_id,
            volume_id=volume_id,
            chapter_id=chapter_id,
        )
        service.start(task.id)
        return self._store_candidate(
            project_id,
            task.id,
            chapter_id,
            plan,
            draft,
            issues,
            volume_id,
            commercial_report,
            minimum_commercial_score,
            memory_candidates,
            audit_reports,
        )

    def _store_candidate(
        self,
        project_id: str,
        task_id: str,
        chapter_id: str,
        plan: str,
        draft: str,
        issues: Sequence[dict[str, str]],
        volume_id: str,
        commercial_report: CommercialReport | None,
        minimum_commercial_score: int | None,
        memory_candidates: MemoryCuration | None,
        audit_reports: dict[str, object] | None,
    ) -> Task:
        service = TaskService(TasksRepository(DatabaseRepository(self.workspace), project_id))
        drafts = DraftRepository(self.workspace)
        drafts.write(project_id, task_id, "plan.md", plan)
        drafts.write(project_id, task_id, "chapter.md", self._apply_issues(draft, issues))
        commercial_gate_passed: bool | None = None
        if commercial_report is not None:
            if minimum_commercial_score is None:
                raise WorkflowGateError("commercial score threshold is required")
            commercial_gate_passed = self.commercial_gate_passed(
                commercial_report, minimum_commercial_score
            )
            drafts.write(
                project_id,
                task_id,
                "commercial-report.json",
                commercial_report.model_dump_json(indent=2),
            )
        if memory_candidates is not None:
            drafts.write(
                project_id,
                task_id,
                "memory-candidates.json",
                memory_candidates.model_dump_json(indent=2),
            )
        if audit_reports is not None:
            drafts.write(
                project_id,
                task_id,
                "audit-reports.json",
                json.dumps(audit_reports, ensure_ascii=False, indent=2),
            )
        drafts.write(
            project_id,
            task_id,
            "run.json",
            json.dumps(
                {
                    "project_id": project_id,
                    "chapter_id": chapter_id,
                    "volume_id": volume_id,
                    "commercial_gate_passed": commercial_gate_passed,
                    "minimum_commercial_score": minimum_commercial_score,
                    "agent_runs": getattr(self.runner, "run_traces", lambda: [])(),
                }
            ),
        )
        return service.await_approval(task_id)

    def _require_prerequisites(self, project_id: str, volume_id: str) -> None:
        project = self.workspace.project_path(project_id)
        if (
            not (project / "canon/outline.md").is_file()
            or not (project / "canon/volumes" / f"{volume_id}.md").is_file()
        ):
            raise WorkflowGateError("approved book outline and volume are required")

    def approve(
        self,
        project_id: str,
        task_id: str,
        chapter_id: str,
        volume_id: str = "1",
        commercial_override_reason: str | None = None,
        accepted_memory_ids: list[str] | None = None,
    ) -> Task:
        service = TaskService(TasksRepository(DatabaseRepository(self.workspace), project_id))
        drafts = DraftRepository(self.workspace)
        manifest = json.loads(drafts.read(project_id, task_id, "run.json"))
        if manifest.get("commercial_gate_passed") is False:
            if commercial_override_reason is None or not commercial_override_reason.strip():
                raise CommercialGateError("commercial quality threshold is not met")
            drafts.write(
                project_id,
                task_id,
                "commercial-override.txt",
                commercial_override_reason.strip(),
            )
        service.approve(task_id)
        try:
            if manifest["project_id"] != project_id or manifest["chapter_id"] != chapter_id:
                raise WorkflowGateError("chapter approval does not match its run manifest")
            stored_volume_id = str(manifest["volume_id"])
            content = drafts.read(project_id, task_id, "chapter.md")
            accepted = set(accepted_memory_ids or [])
            candidates = self.read_memory_candidates(project_id, task_id)
            known = {candidate.stable_id for candidate in candidates}
            if not accepted <= known:
                raise WorkflowGateError("accepted memory candidate does not exist")
            selected = [candidate for candidate in candidates if candidate.stable_id in accepted]
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
                    *MemoryService(self.workspace).summary_writes_for_project(
                        project_id, chapter_id, stored_volume_id, content
                    ),
                    *MemoryService(self.workspace).candidate_writes(
                        project_id, chapter_id, content, selected
                    ),
                ],
                revisions.current_revision(project_id),
            )
            DatabaseRepository(self.workspace).rebuild(project_id)
        except Exception:
            service.fail(task_id)
            raise
        return service.complete(task_id)

    def read_memory_candidates(self, project_id: str, task_id: str) -> list[MemoryCandidate]:
        drafts = DraftRepository(self.workspace)
        if "memory-candidates.json" not in drafts.list_files(project_id, task_id):
            return []
        try:
            return MemoryCuration.model_validate_json(
                drafts.read(project_id, task_id, "memory-candidates.json")
            ).updates
        except ValueError as error:
            raise WorkflowGateError("stored memory candidates are invalid") from error

    def read_commercial_report(self, project_id: str, task_id: str) -> CommercialReport | None:
        drafts = DraftRepository(self.workspace)
        if "commercial-report.json" not in drafts.list_files(project_id, task_id):
            return None
        try:
            return CommercialReport.model_validate_json(
                drafts.read(project_id, task_id, "commercial-report.json")
            )
        except ValueError as error:
            raise WorkflowGateError("stored commercial report is invalid") from error

    def store_commercial_report(
        self,
        project_id: str,
        task_id: str,
        chapter_id: str,
        report: CommercialReport,
        minimum_commercial_score: int,
    ) -> bool:
        drafts = DraftRepository(self.workspace)
        manifest = json.loads(drafts.read(project_id, task_id, "run.json"))
        if manifest["project_id"] != project_id or manifest["chapter_id"] != chapter_id:
            raise WorkflowGateError("commercial report does not match its run manifest")
        passed = self.commercial_gate_passed(report, minimum_commercial_score)
        manifest["commercial_gate_passed"] = passed
        manifest["minimum_commercial_score"] = minimum_commercial_score
        drafts.write(
            project_id,
            task_id,
            "commercial-report.json",
            report.model_dump_json(indent=2),
        )
        drafts.write(project_id, task_id, "run.json", json.dumps(manifest))
        return passed

    @staticmethod
    def commercial_gate_passed(report: CommercialReport, minimum_commercial_score: int) -> bool:
        return report.total_score >= minimum_commercial_score and not any(
            issue.severity == "error" for issue in report.issues
        )

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
        commercial: Sequence[CommercialIssue] = (),
    ) -> list[ContinuityIssue | StyleIssue | CommercialIssue]:
        issues: list[ContinuityIssue | StyleIssue | CommercialIssue] = [
            *continuity,
            *style,
            *commercial,
        ]
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
    def validate_memory_candidates(draft: str, candidates: list[MemoryCandidate]) -> None:
        ids = [candidate.stable_id for candidate in candidates]
        if len(ids) != len(set(ids)):
            raise WorkflowGateError("memory candidate ids must be unique")
        for candidate in candidates:
            start, end = candidate.citation.character_range()
            if end > len(draft) or draft[start:end] != candidate.citation.quote:
                raise WorkflowGateError("memory candidate citation must exactly match the draft")

    @staticmethod
    def normalize_audit_citations(draft: str, issues: Sequence[AuditIssueT]) -> list[AuditIssueT]:
        normalized: list[AuditIssueT] = []
        for issue in issues:
            quote = issue.citation.quote
            start = draft.find(quote)
            if start < 0 or draft.find(quote, start + 1) >= 0:
                raise WorkflowGateError(
                    "chapter issue quote must uniquely match the original draft"
                )
            citation = issue.citation.model_copy(
                update={"location": f"chars:{start}-{start + len(quote)}"}
            )
            normalized.append(issue.model_copy(update={"citation": citation}))
        return normalized

    @classmethod
    def normalize_commercial_report(cls, draft: str, report: CommercialReport) -> CommercialReport:
        return report.model_copy(
            update={"issues": cls.normalize_audit_citations(draft, report.issues)}
        )

    @staticmethod
    def apply_revisions(
        draft: str,
        issues: Sequence[ContinuityIssue | StyleIssue | CommercialIssue],
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
