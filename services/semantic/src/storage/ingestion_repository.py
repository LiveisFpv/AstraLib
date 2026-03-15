"""Repository for persistent background ingestion tasks."""

from __future__ import annotations

from typing import Any, Iterable

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from src.config.config import DATABASE_SETTINGS
from src.services.ingestion.models import (
    IngestionTask,
    TASK_STATUS_COMPLETED,
    TASK_STATUS_FAILED,
    TASK_STATUS_PENDING,
    TASK_STATUS_PROCESSING,
)


class IngestionRepository:
    def __init__(self, *, dsn: str | None = None) -> None:
        self.dsn = dsn or DATABASE_SETTINGS.psycopg_dsn()

    def enqueue_task(
        self,
        *,
        source: str,
        payload: dict[str, Any],
        priority: int = 0,
        max_attempts: int = 3,
    ) -> IngestionTask:
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO ingestion_tasks (source, status, payload, priority, max_attempts)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (source, TASK_STATUS_PENDING, Jsonb(payload), priority, max_attempts),
                )
                row = cur.fetchone()
            conn.commit()
        return self._row_to_task(row)

    def requeue_stale_tasks(self, *, stale_after_seconds: int) -> int:
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE ingestion_tasks
                    SET status = %s,
                        scheduled_at = NOW(),
                        updated_at = NOW(),
                        last_error = COALESCE(last_error, 'task was re-queued after stale processing lease')
                    WHERE status = %s
                      AND started_at IS NOT NULL
                      AND started_at < NOW() - (%s * INTERVAL '1 second')
                    """,
                    (
                        TASK_STATUS_PENDING,
                        TASK_STATUS_PROCESSING,
                        stale_after_seconds,
                    ),
                )
                updated = cur.rowcount
            conn.commit()
        return updated

    def claim_tasks(self, *, limit: int) -> list[IngestionTask]:
        if limit <= 0:
            return []

        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    WITH picked AS (
                        SELECT task_id
                        FROM ingestion_tasks
                        WHERE status = %s
                          AND scheduled_at <= NOW()
                        ORDER BY priority DESC, created_at ASC
                        FOR UPDATE SKIP LOCKED
                        LIMIT %s
                    )
                    UPDATE ingestion_tasks AS task
                    SET status = %s,
                        attempts = task.attempts + 1,
                        started_at = NOW(),
                        updated_at = NOW(),
                        last_error = NULL
                    FROM picked
                    WHERE task.task_id = picked.task_id
                    RETURNING task.*
                    """,
                    (
                        TASK_STATUS_PENDING,
                        limit,
                        TASK_STATUS_PROCESSING,
                    ),
                )
                rows = cur.fetchall()
            conn.commit()
        return [self._row_to_task(row) for row in rows]

    def mark_completed(self, task_id: int, *, result: dict[str, Any] | None = None) -> None:
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE ingestion_tasks
                    SET status = %s,
                        result = %s,
                        finished_at = NOW(),
                        updated_at = NOW(),
                        last_error = NULL
                    WHERE task_id = %s
                    """,
                    (
                        TASK_STATUS_COMPLETED,
                        Jsonb(result or {}),
                        task_id,
                    ),
                )
            conn.commit()

    def mark_failed(
        self,
        task_id: int,
        *,
        error: str,
        retry_after_seconds: int | None = None,
    ) -> None:
        if retry_after_seconds is None:
            status = TASK_STATUS_FAILED
            query = """
                UPDATE ingestion_tasks
                SET status = %s,
                    last_error = %s,
                    finished_at = NOW(),
                    updated_at = NOW()
                WHERE task_id = %s
            """
            params: Iterable[Any] = (status, error, task_id)
        else:
            status = TASK_STATUS_PENDING
            query = """
                UPDATE ingestion_tasks
                SET status = %s,
                    last_error = %s,
                    scheduled_at = NOW() + (%s * INTERVAL '1 second'),
                    updated_at = NOW()
                WHERE task_id = %s
            """
            params = (status, error, retry_after_seconds, task_id)

        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(query, tuple(params))
            conn.commit()

    @staticmethod
    def _row_to_task(row: dict[str, Any] | None) -> IngestionTask:
        if not row:
            raise RuntimeError("Expected ingestion task row, got nothing")
        return IngestionTask(
            task_id=int(row["task_id"]),
            source=str(row["source"]),
            status=str(row["status"]),
            payload=dict(row.get("payload") or {}),
            attempts=int(row.get("attempts") or 0),
            max_attempts=int(row.get("max_attempts") or 0),
            priority=int(row.get("priority") or 0),
            scheduled_at=row.get("scheduled_at"),
            started_at=row.get("started_at"),
            finished_at=row.get("finished_at"),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
            last_error=row.get("last_error"),
            result=dict(row.get("result") or {}) if row.get("result") is not None else None,
        )


__all__ = ["IngestionRepository"]
