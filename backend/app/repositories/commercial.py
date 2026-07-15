from uuid import uuid4

from app.domain.commercial import (
    CommercialMetrics,
    CommercialObservation,
    CommercialObservationInput,
)
from app.repositories.database import DatabaseRepository


class CommercialRepository:
    def __init__(self, database: DatabaseRepository) -> None:
        self.database = database

    def add(
        self, project_id: str, payload: CommercialObservationInput
    ) -> CommercialObservation:
        self.database.initialize(project_id)
        record = CommercialObservation(id=str(uuid4()), **payload.model_dump())
        with self.database.connect(project_id) as connection:
            connection.execute(
                """
                INSERT INTO commercial_observations(
                    id, observed_at, impressions, opens,
                    chapter_one_completions, chapter_three_completions,
                    follows, read_minutes, revenue_cents
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.observed_at,
                    record.impressions,
                    record.opens,
                    record.chapter_one_completions,
                    record.chapter_three_completions,
                    record.follows,
                    record.read_minutes,
                    record.revenue_cents,
                ),
            )
        return record

    def list_all(self, project_id: str) -> list[CommercialObservation]:
        self.database.initialize(project_id)
        with self.database.connect(project_id) as connection:
            rows = connection.execute(
                """
                SELECT id, observed_at, impressions, opens,
                       chapter_one_completions, chapter_three_completions,
                       follows, read_minutes, revenue_cents
                FROM commercial_observations
                ORDER BY observed_at DESC, id DESC
                """
            ).fetchall()
        return [
            CommercialObservation(
                id=str(row[0]),
                observed_at=str(row[1]),
                impressions=int(row[2]),
                opens=int(row[3]),
                chapter_one_completions=int(row[4]),
                chapter_three_completions=int(row[5]),
                follows=int(row[6]),
                read_minutes=int(row[7]),
                revenue_cents=int(row[8]),
            )
            for row in rows
        ]

    def metrics(self, project_id: str) -> CommercialMetrics:
        return CommercialMetrics.from_observations(self.list_all(project_id))
