import json
import sqlite3
from datetime import UTC, datetime
from typing import Any

from app.domain.diagnostics import TaskDiagnosticLog, TaskLogLevel
from app.domain.errors import (
    ActiveTaskConflictError,
    InvalidTaskTransitionError,
    TaskNotFoundError,
)
from app.domain.task import Task, TaskEvent, TaskKind, TaskPurpose, TaskStatus
from app.repositories.database import DatabaseRepository


class TasksRepository:
    def __init__(self, database: DatabaseRepository, project_id: str) -> None:
        self.database = database
        self.project_id = project_id

    def create(self, task: Task, event_type: str) -> Task:
        if task.project_id != self.project_id:
            raise ValueError("task project does not match repository project")
        connection = self.database.connect(self.project_id)
        try:
            connection.isolation_level = None
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """INSERT INTO tasks(
                    id, project_id, kind, purpose, status, subject_id, volume_id, chapter_id,
                    parent_task_id, retry_of_task_id, cancel_requested_at, error_code,
                    error_message, started_at, finished_at, duration_ms, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    task.id,
                    task.project_id,
                    task.kind.value,
                    task.purpose.value,
                    task.status.value,
                    task.subject_id,
                    task.volume_id,
                    task.chapter_id,
                    task.parent_task_id,
                    task.retry_of_task_id,
                    self._timestamp(task.cancel_requested_at),
                    task.error_code,
                    task.error_message,
                    self._timestamp(task.started_at),
                    self._timestamp(task.finished_at),
                    task.duration_ms,
                    task.created_at.isoformat(),
                    task.updated_at.isoformat(),
                ),
            )
            self._insert_event(connection, task.id, 1, event_type, {})
            connection.commit()
        except sqlite3.IntegrityError as error:
            connection.rollback()
            if "tasks.project_id" in str(error):
                raise ActiveTaskConflictError(self.project_id) from error
            raise
        finally:
            connection.close()
        return task

    def get(self, task_id: str) -> Task:
        with self.database.connect(self.project_id) as connection:
            row = connection.execute(
                f"""SELECT {self._task_columns()}
                FROM tasks WHERE id = ?""",
                (task_id,),
            ).fetchone()
        if row is None:
            raise TaskNotFoundError(task_id)
        return self._task(row)

    def transition(
        self,
        task_id: str,
        expected_status: TaskStatus,
        status: TaskStatus,
        event_type: str,
    ) -> Task:
        connection = self.database.connect(self.project_id)
        try:
            connection.isolation_level = None
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT status FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if row is None:
                raise TaskNotFoundError(task_id)
            if TaskStatus(str(row[0])) is not expected_status:
                raise InvalidTaskTransitionError("task status changed concurrently")
            updated_at = datetime.now(UTC)
            started_at = updated_at.isoformat() if status is TaskStatus.RUNNING else None
            finished_at = (
                updated_at.isoformat()
                if status in {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}
                else None
            )
            connection.execute(
                """UPDATE tasks SET status = ?, updated_at = ?,
                    started_at = COALESCE(started_at, ?),
                    finished_at = COALESCE(?, finished_at),
                    duration_ms = CASE
                        WHEN ? IS NOT NULL AND started_at IS NOT NULL
                        THEN MAX(
                            0,
                            CAST((julianday(?) - julianday(started_at)) * 86400000 AS INTEGER)
                        )
                        ELSE duration_ms
                    END
                WHERE id = ?""",
                (
                    status.value,
                    updated_at.isoformat(),
                    started_at,
                    finished_at,
                    finished_at,
                    finished_at,
                    task_id,
                ),
            )
            sequence = self._next_sequence(connection, task_id)
            self._insert_event(connection, task_id, sequence, event_type, {"status": status.value})
            connection.commit()
        except sqlite3.IntegrityError as error:
            connection.rollback()
            if str(error) == "invalid task transition":
                raise InvalidTaskTransitionError(str(error)) from error
            raise
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return self.get(task_id)

    def append_event(self, task_id: str, event_type: str, data: dict[str, Any]) -> TaskEvent:
        connection = self.database.connect(self.project_id)
        try:
            connection.isolation_level = None
            connection.execute("BEGIN IMMEDIATE")
            exists = connection.execute("SELECT 1 FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if exists is None:
                raise TaskNotFoundError(task_id)
            sequence = self._next_sequence(connection, task_id)
            timestamp = self._insert_event(connection, task_id, sequence, event_type, data)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return TaskEvent(
            task_id=task_id,
            project_id=self.project_id,
            sequence=sequence,
            type=event_type,
            timestamp=timestamp,
            data=data,
        )

    def append_log(
        self,
        task_id: str,
        level: TaskLogLevel,
        component: str,
        event: str,
        *,
        agent: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> TaskDiagnosticLog:
        safe_details = _safe_details(details or {})
        connection = self.database.connect(self.project_id)
        try:
            connection.isolation_level = None
            connection.execute("BEGIN IMMEDIATE")
            exists = connection.execute("SELECT 1 FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if exists is None:
                raise TaskNotFoundError(task_id)
            timestamp = datetime.now(UTC)
            cursor = connection.execute(
                """INSERT INTO task_logs(
                    task_id, project_id, timestamp, level, component, event, agent, details
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    task_id,
                    self.project_id,
                    timestamp.isoformat(),
                    level.value,
                    component,
                    event,
                    agent,
                    json.dumps(safe_details, ensure_ascii=False, separators=(",", ":")),
                ),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("task diagnostic log id is missing")
            log_id = int(cursor.lastrowid)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return TaskDiagnosticLog(
            id=log_id,
            task_id=task_id,
            project_id=self.project_id,
            timestamp=timestamp,
            level=level,
            component=component,
            event=event,
            agent=agent,
            details=safe_details,
        )

    def logs(
        self,
        task_id: str,
        *,
        after_id: int = 0,
        limit: int = 100,
        level: TaskLogLevel | None = None,
    ) -> list[TaskDiagnosticLog]:
        query = """SELECT id, task_id, project_id, timestamp, level,
        component, event, agent, details FROM task_logs
        WHERE task_id = ? AND id > ?"""
        parameters: list[object] = [task_id, after_id]
        if level is not None:
            query += " AND level = ?"
            parameters.append(level.value)
        query += " ORDER BY id LIMIT ?"
        parameters.append(limit)
        with self.database.connect(self.project_id) as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [
            TaskDiagnosticLog(
                id=int(row[0]),
                task_id=str(row[1]),
                project_id=str(row[2]),
                timestamp=datetime.fromisoformat(str(row[3])),
                level=TaskLogLevel(str(row[4])),
                component=str(row[5]),
                event=str(row[6]),
                agent=None if row[7] is None else str(row[7]),
                details=_safe_details(json.loads(str(row[8]))),
            )
            for row in rows
        ]

    def request_cancel(self, task_id: str) -> Task:
        connection = self.database.connect(self.project_id)
        try:
            connection.isolation_level = None
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT cancel_requested_at FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
            if row is None:
                raise TaskNotFoundError(task_id)
            if row[0] is None:
                requested_at = datetime.now(UTC)
                connection.execute(
                    "UPDATE tasks SET cancel_requested_at = ?, updated_at = ? WHERE id = ?",
                    (requested_at.isoformat(), requested_at.isoformat(), task_id),
                )
                sequence = self._next_sequence(connection, task_id)
                self._insert_event(
                    connection,
                    task_id,
                    sequence,
                    "task.cancel_requested",
                    {"status": TaskStatus.RUNNING.value},
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return self.get(task_id)

    def record_error(self, task_id: str, code: str, message: str) -> Task:
        connection = self.database.connect(self.project_id)
        try:
            connection.isolation_level = None
            connection.execute("BEGIN IMMEDIATE")
            exists = connection.execute("SELECT 1 FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if exists is None:
                raise TaskNotFoundError(task_id)
            updated_at = datetime.now(UTC)
            connection.execute(
                "UPDATE tasks SET error_code = ?, error_message = ?, updated_at = ? WHERE id = ?",
                (code, message, updated_at.isoformat(), task_id),
            )
            sequence = self._next_sequence(connection, task_id)
            self._insert_event(
                connection,
                task_id,
                sequence,
                "task.error",
                {"error_code": code},
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return self.get(task_id)

    def events(self, task_id: str, after: int = 0) -> list[TaskEvent]:
        with self.database.connect(self.project_id) as connection:
            rows = connection.execute(
                """SELECT task_id, project_id, sequence, type, timestamp, data
                FROM task_events WHERE task_id = ? AND sequence > ? ORDER BY sequence""",
                (task_id, after),
            ).fetchall()
        return [
            TaskEvent(
                task_id=row[0],
                project_id=row[1],
                sequence=row[2],
                type=row[3],
                timestamp=datetime.fromisoformat(row[4]),
                data=json.loads(row[5]),
            )
            for row in rows
        ]

    def list_by_status(self, status: TaskStatus) -> list[Task]:
        with self.database.connect(self.project_id) as connection:
            rows = connection.execute(
                f"""SELECT {self._task_columns()}
                FROM tasks WHERE status = ? ORDER BY created_at, id""",
                (status.value,),
            ).fetchall()
        return [self._task(row) for row in rows]

    def list_all(self) -> list[Task]:
        with self.database.connect(self.project_id) as connection:
            rows = connection.execute(
                f"""SELECT {self._task_columns()}
                FROM tasks ORDER BY created_at DESC, id DESC"""
            ).fetchall()
        return [self._task(row) for row in rows]

    @staticmethod
    def _task(row: tuple[object, ...]) -> Task:
        return Task(
            id=str(row[0]),
            project_id=str(row[1]),
            kind=TaskKind(str(row[2])),
            purpose=TaskPurpose(str(row[3])),
            status=TaskStatus(str(row[4])),
            subject_id=None if row[5] is None else str(row[5]),
            volume_id=None if row[6] is None else str(row[6]),
            chapter_id=None if row[7] is None else str(row[7]),
            parent_task_id=None if row[8] is None else str(row[8]),
            retry_of_task_id=None if row[9] is None else str(row[9]),
            cancel_requested_at=TasksRepository._parse_timestamp(row[10]),
            error_code=None if row[11] is None else str(row[11]),
            error_message=None if row[12] is None else str(row[12]),
            started_at=TasksRepository._parse_timestamp(row[13]),
            finished_at=TasksRepository._parse_timestamp(row[14]),
            duration_ms=None if row[15] is None else int(str(row[15])),
            created_at=datetime.fromisoformat(str(row[16])),
            updated_at=datetime.fromisoformat(str(row[17])),
        )

    @staticmethod
    def _task_columns() -> str:
        return """id, project_id, kind, purpose, status, subject_id, volume_id, chapter_id,
        parent_task_id, retry_of_task_id, cancel_requested_at, error_code, error_message,
        started_at, finished_at, duration_ms, created_at, updated_at"""

    @staticmethod
    def _timestamp(value: datetime | None) -> str | None:
        return None if value is None else value.isoformat()

    @staticmethod
    def _parse_timestamp(value: object) -> datetime | None:
        return None if value is None else datetime.fromisoformat(str(value))

    @staticmethod
    def _next_sequence(connection: sqlite3.Connection, task_id: str) -> int:
        row = connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM task_events WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        return int(row[0])

    def _insert_event(
        self,
        connection: sqlite3.Connection,
        task_id: str,
        sequence: int,
        event_type: str,
        data: dict[str, Any],
    ) -> datetime:
        timestamp = datetime.now(UTC)
        connection.execute(
            """INSERT INTO task_events(task_id, project_id, sequence, type, timestamp, data)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (
                task_id,
                self.project_id,
                sequence,
                event_type,
                timestamp.isoformat(),
                json.dumps(data, ensure_ascii=False, separators=(",", ":")),
            ),
        )
        return timestamp


_SAFE_STRING_FIELDS = {
    "agent",
    "artifact",
    "error_code",
    "error_type",
    "job_kind",
    "model",
    "phase",
    "skill",
    "stage",
    "status",
}
_SAFE_INTEGER_FIELDS = {
    "artifact_count",
    "bytes_written",
    "duration_ms",
    "input_tokens",
    "output_tokens",
    "query_count",
    "retrieved_count",
    "source_count",
    "total_characters",
    "total_tokens",
}
_SAFE_FLOAT_FIELDS = {"input_cost_cny", "output_cost_cny", "total_cost_cny"}
_SAFE_BOOLEAN_FIELDS = {"commercial_gate_passed", "cancel_requested"}
_SAFE_PATH_LIST_FIELDS = {"source_paths"}


def _safe_details(details: dict[str, Any]) -> dict[str, Any]:
    """Keep only a small diagnostics allowlist so text content cannot leak into logs."""

    result: dict[str, Any] = {}
    for key, value in details.items():
        if key in _SAFE_STRING_FIELDS and isinstance(value, str):
            compact = value.strip()
            if compact and "\n" not in compact and len(compact) <= 128:
                result[key] = compact
        elif key in _SAFE_INTEGER_FIELDS and isinstance(value, int) and not isinstance(value, bool):
            if value >= 0:
                result[key] = value
        elif (
            key in _SAFE_FLOAT_FIELDS
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
        ):
            result[key] = round(float(value), 8)
        elif key in _SAFE_BOOLEAN_FIELDS and isinstance(value, bool):
            result[key] = value
        elif key in _SAFE_PATH_LIST_FIELDS and isinstance(value, list):
            paths = [
                item
                for item in value[:32]
                if isinstance(item, str)
                and item.strip() == item
                and 1 <= len(item) <= 256
                and all(character.isalnum() or character in "._-/" for character in item)
            ]
            result[key] = paths
    return result
