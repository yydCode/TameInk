import json
import sqlite3
from datetime import UTC, datetime
from typing import cast

from app.domain.creation import (
    ArtifactKind,
    ArtifactStatus,
    AuthorDecision,
    CandidateArtifactRecord,
    DecisionAction,
    DecisionEffect,
    FormalLayer,
    TransientLayer,
)
from app.domain.errors import (
    ArtifactDecisionError,
    ArtifactNotFoundError,
    InvalidArtifactTransitionError,
)
from app.repositories.database import DatabaseRepository

_SYSTEM_TRANSITIONS: frozenset[tuple[ArtifactStatus, ArtifactStatus]] = frozenset(
    {
        ("candidate", "needs_decision"),
        ("candidate", "conflict"),
        ("candidate", "ready"),
        ("ready", "awaiting_approval"),
    }
)


class ArtifactsRepository:
    def __init__(self, database: DatabaseRepository, project_id: str) -> None:
        self.database = database
        self.project_id = project_id

    def create(self, artifact: CandidateArtifactRecord) -> CandidateArtifactRecord:
        if artifact.project_id != self.project_id:
            raise ValueError("artifact project does not match repository project")
        if artifact.status != "candidate":
            raise InvalidArtifactTransitionError("new artifact must start as candidate")
        with self.database.connect(self.project_id) as connection:
            connection.execute(
                """INSERT INTO creative_artifacts(
                    id, project_id, task_id, kind, source_layer, status, payload_path,
                    accepted_layer, formal_path, accepted_decision_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    artifact.id,
                    artifact.project_id,
                    artifact.task_id,
                    artifact.kind,
                    artifact.source_layer,
                    artifact.status,
                    artifact.payload_path,
                    artifact.accepted_layer,
                    artifact.formal_path,
                    artifact.accepted_decision_id,
                    artifact.created_at.isoformat(),
                    artifact.updated_at.isoformat(),
                ),
            )
        return artifact

    def get(self, artifact_id: str) -> CandidateArtifactRecord:
        with self.database.connect(self.project_id) as connection:
            row = connection.execute(
                f"""SELECT {self._artifact_columns()} FROM creative_artifacts
                WHERE id = ? AND project_id = ?""",
                (artifact_id, self.project_id),
            ).fetchone()
        if row is None:
            raise ArtifactNotFoundError(artifact_id)
        return self._artifact(row)

    def list_by_status(self, status: ArtifactStatus) -> list[CandidateArtifactRecord]:
        with self.database.connect(self.project_id) as connection:
            rows = connection.execute(
                f"""SELECT {self._artifact_columns()} FROM creative_artifacts
                WHERE project_id = ? AND status = ? ORDER BY created_at, id""",
                (self.project_id, status),
            ).fetchall()
        return [self._artifact(row) for row in rows]

    def list_all(self) -> list[CandidateArtifactRecord]:
        with self.database.connect(self.project_id) as connection:
            rows = connection.execute(
                f"""SELECT {self._artifact_columns()} FROM creative_artifacts
                WHERE project_id = ? ORDER BY created_at, id""",
                (self.project_id,),
            ).fetchall()
        return [self._artifact(row) for row in rows]

    def transition(
        self,
        artifact_id: str,
        expected_status: ArtifactStatus,
        status: ArtifactStatus,
    ) -> CandidateArtifactRecord:
        if (expected_status, status) not in _SYSTEM_TRANSITIONS:
            raise InvalidArtifactTransitionError(f"{expected_status} -> {status}")
        connection = self.database.connect(self.project_id)
        try:
            connection.isolation_level = None
            connection.execute("BEGIN IMMEDIATE")
            self._assert_expected_status(connection, artifact_id, expected_status)
            updated_at = datetime.now(UTC)
            connection.execute(
                """UPDATE creative_artifacts SET status = ?, updated_at = ?
                WHERE id = ? AND project_id = ?""",
                (status, updated_at.isoformat(), artifact_id, self.project_id),
            )
            connection.commit()
        except sqlite3.IntegrityError as error:
            connection.rollback()
            raise InvalidArtifactTransitionError(str(error)) from error
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return self.get(artifact_id)

    def decide(self, decision: AuthorDecision) -> CandidateArtifactRecord:
        if decision.project_id != self.project_id:
            raise ValueError("decision project does not match repository project")
        target_status = self._decision_target(decision.action)
        connection = self.database.connect(self.project_id)
        try:
            connection.isolation_level = None
            connection.execute("BEGIN IMMEDIATE")
            artifact = self._assert_expected_status(
                connection, decision.artifact_id, decision.expected_status
            )
            self._validate_decision_for_artifact(artifact, decision)
            connection.execute(
                """INSERT INTO artifact_decisions(
                    id, artifact_id, project_id, expected_status, action, rationale,
                    effects, target_layer, formal_path, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    decision.id,
                    decision.artifact_id,
                    decision.project_id,
                    decision.expected_status,
                    decision.action,
                    decision.rationale,
                    json.dumps(
                        [effect.model_dump(mode="json") for effect in decision.effects],
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    decision.target_layer,
                    decision.formal_path,
                    decision.created_at.isoformat(),
                ),
            )
            accepted = target_status == "accepted"
            connection.execute(
                """UPDATE creative_artifacts SET
                    status = ?, accepted_layer = ?, formal_path = ?,
                    accepted_decision_id = ?, updated_at = ?
                WHERE id = ? AND project_id = ?""",
                (
                    target_status,
                    decision.target_layer if accepted else None,
                    decision.formal_path if accepted else None,
                    decision.id if accepted else None,
                    datetime.now(UTC).isoformat(),
                    decision.artifact_id,
                    self.project_id,
                ),
            )
            connection.commit()
        except sqlite3.IntegrityError as error:
            connection.rollback()
            raise ArtifactDecisionError(str(error)) from error
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return self.get(decision.artifact_id)

    def decisions(self, artifact_id: str) -> list[AuthorDecision]:
        self.get(artifact_id)
        with self.database.connect(self.project_id) as connection:
            rows = connection.execute(
                """SELECT id, project_id, artifact_id, expected_status, action, rationale,
                effects, target_layer, formal_path, created_at FROM artifact_decisions
                WHERE artifact_id = ? AND project_id = ? ORDER BY created_at, id""",
                (artifact_id, self.project_id),
            ).fetchall()
        return [
            AuthorDecision(
                id=str(row[0]),
                project_id=str(row[1]),
                artifact_id=str(row[2]),
                expected_status=cast(ArtifactStatus, str(row[3])),
                action=cast(DecisionAction, str(row[4])),
                rationale=None if row[5] is None else str(row[5]),
                effects=[
                    DecisionEffect.model_validate(item) for item in json.loads(str(row[6]))
                ],
                target_layer=(
                    None if row[7] is None else cast(FormalLayer, str(row[7]))
                ),
                formal_path=None if row[8] is None else str(row[8]),
                created_at=datetime.fromisoformat(str(row[9])),
            )
            for row in rows
        ]

    def _assert_expected_status(
        self, connection: sqlite3.Connection, artifact_id: str, expected_status: ArtifactStatus
    ) -> CandidateArtifactRecord:
        row = connection.execute(
            f"""SELECT {self._artifact_columns()} FROM creative_artifacts
            WHERE id = ? AND project_id = ?""",
            (artifact_id, self.project_id),
        ).fetchone()
        if row is None:
            raise ArtifactNotFoundError(artifact_id)
        artifact = self._artifact(row)
        if artifact.status != expected_status:
            raise InvalidArtifactTransitionError("artifact status changed concurrently")
        return artifact

    @staticmethod
    def _decision_target(action: DecisionAction) -> ArtifactStatus:
        if action in {"accept", "mix"}:
            return "accepted"
        if action == "reject":
            return "rejected"
        return "candidate"

    @staticmethod
    def _validate_decision_for_artifact(
        artifact: CandidateArtifactRecord, decision: AuthorDecision
    ) -> None:
        if decision.action in {"accept", "mix"}:
            if artifact.status != "awaiting_approval":
                raise ArtifactDecisionError("only awaiting artifacts can be accepted")
            if artifact.source_layer != "candidate":
                raise ArtifactDecisionError("hypotheses cannot be promoted directly")
            if decision.formal_path is None or not ArtifactsRepository._target_matches_kind(
                artifact.kind, decision.formal_path
            ):
                raise ArtifactDecisionError("formal target does not match artifact kind")
        elif decision.action == "reject":
            if artifact.status in {"accepted", "rejected"}:
                raise ArtifactDecisionError("terminal artifact cannot be rejected")
        elif artifact.status not in {
            "needs_decision",
            "conflict",
            "ready",
            "awaiting_approval",
        }:
            raise ArtifactDecisionError(
                "revision decision requires a blocked or reviewable artifact"
            )

    @staticmethod
    def _target_matches_kind(kind: ArtifactKind, formal_path: str) -> bool:
        exact = {
            "reader_contract": "commitments/reader-contract.yaml",
            "story_engine": "commitments/story-engine.yaml",
            "ending_plan": "commitments/ending-plan.yaml",
        }
        if kind in exact:
            return formal_path == exact[kind]
        prefixes = {
            "character_state": ("canon/characters/",),
            "expectation": ("commitments/expectations/",),
            "story_card": ("commitments/story-cards/",),
            "chapter_plan": ("commitments/story-cards/",),
            "chapter_draft": ("canon/chapters/",),
            "actual_event": ("canon/actual-events/",),
            "memory_proposal": ("canon/characters/", "canon/actual-events/", "memory/"),
            "evidence_finding": (),
        }
        return formal_path.startswith(prefixes[kind])

    @staticmethod
    def _artifact(row: tuple[object, ...]) -> CandidateArtifactRecord:
        return CandidateArtifactRecord(
            id=str(row[0]),
            project_id=str(row[1]),
            task_id=str(row[2]),
            kind=cast(ArtifactKind, str(row[3])),
            source_layer=cast(TransientLayer, str(row[4])),
            status=cast(ArtifactStatus, str(row[5])),
            payload_path=str(row[6]),
            accepted_layer=(
                None if row[7] is None else cast(FormalLayer, str(row[7]))
            ),
            formal_path=None if row[8] is None else str(row[8]),
            accepted_decision_id=None if row[9] is None else str(row[9]),
            created_at=datetime.fromisoformat(str(row[10])),
            updated_at=datetime.fromisoformat(str(row[11])),
        )

    @staticmethod
    def _artifact_columns() -> str:
        return """id, project_id, task_id, kind, source_layer, status, payload_path,
        accepted_layer, formal_path, accepted_decision_id, created_at, updated_at"""
