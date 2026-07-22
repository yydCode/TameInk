import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from app.domain.creation import AuthorDecision, CandidateArtifactRecord
from app.domain.errors import ArtifactDecisionError, InvalidArtifactTransitionError
from app.domain.task import Task, TaskKind, TaskStatus
from app.repositories.artifacts import ArtifactsRepository
from app.repositories.database import DatabaseRepository
from app.repositories.tasks import TasksRepository
from app.repositories.workspace import WorkspaceRepository


def setup(tmp_path: Path) -> tuple[ArtifactsRepository, str]:
    workspace = WorkspaceRepository(tmp_path)
    workspace.create_project("story-01")
    database = DatabaseRepository(workspace)
    database.initialize("story-01")
    task_id = str(uuid4())
    now = datetime.now(UTC)
    TasksRepository(database, "story-01").create(
        Task(
            id=task_id,
            project_id="story-01",
            kind=TaskKind.WRITE,
            status=TaskStatus.PENDING,
            created_at=now,
            updated_at=now,
        ),
        "task.created",
    )
    return ArtifactsRepository(database, "story-01"), task_id


def candidate(task_id: str, *, source_layer: str = "candidate") -> CandidateArtifactRecord:
    now = datetime.now(UTC)
    return CandidateArtifactRecord.model_validate(
        {
            "id": str(uuid4()),
            "project_id": "story-01",
            "task_id": task_id,
            "kind": "story_card",
            "source_layer": source_layer,
            "status": "candidate",
            "payload_path": "story-card.json",
            "created_at": now,
            "updated_at": now,
        }
    )


def decision(
    artifact: CandidateArtifactRecord,
    action: str,
    *,
    target_layer: str | None = None,
    formal_path: str | None = None,
) -> AuthorDecision:
    return AuthorDecision.model_validate(
        {
            "id": str(uuid4()),
            "project_id": artifact.project_id,
            "artifact_id": artifact.id,
            "expected_status": artifact.status,
            "action": action,
            "rationale": "作者明确决定",
            "effects": [],
            "target_layer": target_layer,
            "formal_path": formal_path,
            "created_at": datetime.now(UTC),
        }
    )


def test_candidate_requires_ready_and_approval_before_author_can_accept(tmp_path: Path) -> None:
    repository, task_id = setup(tmp_path)
    artifact = repository.create(candidate(task_id))
    artifact = repository.transition(artifact.id, "candidate", "ready")
    artifact = repository.transition(artifact.id, "ready", "awaiting_approval")

    accepted = repository.decide(
        decision(
            artifact,
            "accept",
            target_layer="commitment",
            formal_path="commitments/story-cards/card-01.yaml",
        )
    )

    assert accepted.status == "accepted"
    assert accepted.accepted_layer == "commitment"
    assert accepted.formal_path == "commitments/story-cards/card-01.yaml"
    assert [item.action for item in repository.decisions(artifact.id)] == ["accept"]


def test_repository_rejects_direct_acceptance_without_review_state(tmp_path: Path) -> None:
    repository, task_id = setup(tmp_path)
    artifact = repository.create(candidate(task_id))

    with pytest.raises(ArtifactDecisionError, match="awaiting"):
        repository.decide(
            decision(
                artifact,
                "accept",
                target_layer="commitment",
                formal_path="commitments/story-cards/card-01.yaml",
            )
        )

    assert repository.get(artifact.id).status == "candidate"
    assert repository.decisions(artifact.id) == []


def test_hypothesis_cannot_be_promoted_directly(tmp_path: Path) -> None:
    repository, task_id = setup(tmp_path)
    artifact = repository.create(candidate(task_id, source_layer="hypothesis"))
    artifact = repository.transition(artifact.id, "candidate", "ready")
    artifact = repository.transition(artifact.id, "ready", "awaiting_approval")

    with pytest.raises(ArtifactDecisionError, match="hypotheses"):
        repository.decide(
            decision(
                artifact,
                "accept",
                target_layer="canon",
                formal_path="canon/characters/hero.yaml",
            )
        )

    assert repository.get(artifact.id).status == "awaiting_approval"
    assert repository.decisions(artifact.id) == []


def test_artifact_kind_cannot_be_promoted_to_an_unrelated_formal_path(tmp_path: Path) -> None:
    repository, task_id = setup(tmp_path)
    artifact = repository.create(candidate(task_id))
    artifact = repository.transition(artifact.id, "candidate", "ready")
    artifact = repository.transition(artifact.id, "ready", "awaiting_approval")

    wrong_decision = decision(
        artifact,
        "accept",
        target_layer="canon",
        formal_path="canon/characters/hero.yaml",
    )
    with pytest.raises(ArtifactDecisionError, match="does not match"):
        repository.decide(wrong_decision)

    with pytest.raises(sqlite3.IntegrityError):
        with repository.database.connect("story-01") as connection:
            connection.execute(
                """INSERT INTO artifact_decisions(
                    id, artifact_id, project_id, expected_status, action, rationale,
                    effects, target_layer, formal_path, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    wrong_decision.id,
                    wrong_decision.artifact_id,
                    wrong_decision.project_id,
                    wrong_decision.expected_status,
                    wrong_decision.action,
                    wrong_decision.rationale,
                    "[]",
                    wrong_decision.target_layer,
                    wrong_decision.formal_path,
                    wrong_decision.created_at.isoformat(),
                ),
            )
            connection.execute(
                """UPDATE creative_artifacts SET status = 'accepted', accepted_layer = 'canon',
                formal_path = ?, accepted_decision_id = ? WHERE id = ?""",
                (
                    wrong_decision.formal_path,
                    wrong_decision.id,
                    artifact.id,
                ),
            )

    assert repository.get(artifact.id).status == "awaiting_approval"
    assert repository.decisions(artifact.id) == []


def test_author_can_revise_blocked_artifact_and_decision_is_immutable(tmp_path: Path) -> None:
    repository, task_id = setup(tmp_path)
    artifact = repository.create(candidate(task_id))
    artifact = repository.transition(artifact.id, "candidate", "needs_decision")
    revised = repository.decide(decision(artifact, "revise"))
    stored = repository.decisions(artifact.id)[0]

    assert revised.status == "candidate"
    assert stored.action == "revise"
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        with repository.database.connect("story-01") as connection:
            connection.execute(
                "UPDATE artifact_decisions SET rationale = 'changed' WHERE id = ?",
                (stored.id,),
            )


def test_database_guards_identity_and_promotion_outside_repository(tmp_path: Path) -> None:
    repository, task_id = setup(tmp_path)
    artifact = repository.create(candidate(task_id))

    with pytest.raises(sqlite3.IntegrityError, match="identity"):
        with repository.database.connect("story-01") as connection:
            connection.execute(
                "UPDATE creative_artifacts SET payload_path = 'other.json' WHERE id = ?",
                (artifact.id,),
            )

    with pytest.raises(sqlite3.IntegrityError):
        with repository.database.connect("story-01") as connection:
            connection.execute(
                """UPDATE creative_artifacts SET status = 'accepted',
                accepted_layer = 'commitment', formal_path = ?, accepted_decision_id = ?
                WHERE id = ?""",
                (
                    "commitments/story-cards/card-01.yaml",
                    str(uuid4()),
                    artifact.id,
                ),
            )


def test_stale_decision_rolls_back_without_append(tmp_path: Path) -> None:
    repository, task_id = setup(tmp_path)
    artifact = repository.create(candidate(task_id))
    stale = decision(artifact, "reject")
    repository.transition(artifact.id, "candidate", "ready")

    with pytest.raises(InvalidArtifactTransitionError, match="concurrently"):
        repository.decide(stale)

    with repository.database.connect("story-01") as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM artifact_decisions WHERE artifact_id = ?", (artifact.id,)
        ).fetchone()[0]
    assert count == 0


def test_decision_effects_round_trip_as_structured_json(tmp_path: Path) -> None:
    repository, task_id = setup(tmp_path)
    artifact = repository.create(candidate(task_id))
    rejected = AuthorDecision.model_validate(
        {
            **decision(artifact, "reject").model_dump(),
            "effects": [
                {
                    "record_kind": "story_card",
                    "record_id": "card-01",
                    "description": "候选作废，不影响正式承诺",
                }
            ],
        }
    )
    repository.decide(rejected)

    stored = repository.decisions(artifact.id)[0]
    assert stored.effects[0].record_id == "card-01"
    with repository.database.connect("story-01") as connection:
        raw = connection.execute(
            "SELECT effects FROM artifact_decisions WHERE id = ?", (stored.id,)
        ).fetchone()[0]
    assert json.loads(raw)[0]["record_kind"] == "story_card"
