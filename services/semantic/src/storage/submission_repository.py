from __future__ import annotations

from typing import Iterable, Sequence

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from src.config.config import DATABASE_SETTINGS
from src.domain.models.submission import (
    SUBMISSION_STATUS_APPROVED,
    SUBMISSION_STATUS_DRAFT,
    SUBMISSION_STATUS_PENDING,
    SUBMISSION_STATUS_REJECTED,
    SubmissionModel,
)
from src.services.ingestion.models import (
    AuthorSubmission,
    SOURCE_APPROVED_SUBMISSION,
    TASK_STATUS_PENDING,
)


RELATION_REFERENCED = "referenced"
RELATION_RELATED = "related"
class SubmissionRepository:
    def __init__(self, *, dsn: str | None = None) -> None:
        self.dsn = dsn or DATABASE_SETTINGS.psycopg_dsn()

    def create_submission(
        self,
        *,
        created_by_user_id: int,
        source_identifier: str | None,
        title: str,
        abstract: str,
        year: int | None,
        best_oa_location: str | None,
        referenced_works: Sequence[str],
        related_works: Sequence[str],
    ) -> SubmissionModel:
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO author_submissions (
                        created_by_user_id,
                        source_identifier,
                        title,
                        abstract,
                        year,
                        best_oa_location,
                        status
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING submission_id
                    """,
                    (
                        int(created_by_user_id),
                        _clean_text(source_identifier),
                        _clean_text(title),
                        _clean_text(abstract),
                        year,
                        _clean_text(best_oa_location),
                        SUBMISSION_STATUS_DRAFT,
                    ),
                )
                row = cur.fetchone()
                if not row:
                    raise RuntimeError("Failed to create submission")
                submission_id = int(row["submission_id"])
                self._replace_links(cur, submission_id, RELATION_REFERENCED, referenced_works)
                self._replace_links(cur, submission_id, RELATION_RELATED, related_works)
            conn.commit()
        return self.get_submission(submission_id)

    def update_author_submission(
        self,
        *,
        created_by_user_id: int,
        submission_id: int,
        source_identifier: str | None,
        title: str,
        abstract: str,
        year: int | None,
        best_oa_location: str | None,
        referenced_works: Sequence[str],
        related_works: Sequence[str],
    ) -> SubmissionModel:
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE author_submissions
                    SET source_identifier = %s,
                        title = %s,
                        abstract = %s,
                        year = %s,
                        best_oa_location = %s,
                        updated_at = NOW()
                    WHERE submission_id = %s
                      AND created_by_user_id = %s
                    RETURNING submission_id
                    """,
                    (
                        _clean_text(source_identifier),
                        _clean_text(title),
                        _clean_text(abstract),
                        year,
                        _clean_text(best_oa_location),
                        int(submission_id),
                        int(created_by_user_id),
                    ),
                )
                if cur.fetchone() is None:
                    raise RuntimeError("submission was not updated")
                self._replace_links(cur, int(submission_id), RELATION_REFERENCED, referenced_works)
                self._replace_links(cur, int(submission_id), RELATION_RELATED, related_works)
            conn.commit()
        return self.get_submission(int(submission_id))

    def delete_author_submission(self, *, created_by_user_id: int, submission_id: int) -> bool:
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM author_submissions
                    WHERE submission_id = %s
                      AND created_by_user_id = %s
                    """,
                    (int(submission_id), int(created_by_user_id)),
                )
                deleted = cur.rowcount > 0
            conn.commit()
        return deleted

    def submit_author_submission(self, *, created_by_user_id: int, submission_id: int) -> SubmissionModel:
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE author_submissions
                    SET status = %s,
                        submitted_at = NOW(),
                        updated_at = NOW(),
                        moderated_by_user_id = NULL,
                        moderation_comment = NULL,
                        moderated_at = NULL,
                        approved_paper_id = NULL
                    WHERE submission_id = %s
                      AND created_by_user_id = %s
                    RETURNING submission_id
                    """,
                    (
                        SUBMISSION_STATUS_PENDING,
                        int(submission_id),
                        int(created_by_user_id),
                    ),
                )
                if cur.fetchone() is None:
                    raise RuntimeError("submission was not submitted")
            conn.commit()
        return self.get_submission(int(submission_id))

    def update_moderation_submission(
        self,
        *,
        submission_id: int,
        source_identifier: str | None,
        title: str,
        abstract: str,
        year: int | None,
        best_oa_location: str | None,
        referenced_works: Sequence[str],
        related_works: Sequence[str],
    ) -> SubmissionModel:
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE author_submissions
                    SET source_identifier = %s,
                        title = %s,
                        abstract = %s,
                        year = %s,
                        best_oa_location = %s,
                        updated_at = NOW()
                    WHERE submission_id = %s
                    RETURNING submission_id
                    """,
                    (
                        _clean_text(source_identifier),
                        _clean_text(title),
                        _clean_text(abstract),
                        year,
                        _clean_text(best_oa_location),
                        int(submission_id),
                    ),
                )
                if cur.fetchone() is None:
                    raise RuntimeError("submission was not updated")
                self._replace_links(cur, int(submission_id), RELATION_REFERENCED, referenced_works)
                self._replace_links(cur, int(submission_id), RELATION_RELATED, related_works)
            conn.commit()
        return self.get_submission(int(submission_id))

    def reject_submission(
        self,
        *,
        submission_id: int,
        moderated_by_user_id: int,
        moderation_comment: str | None,
    ) -> SubmissionModel:
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE author_submissions
                    SET status = %s,
                        moderated_by_user_id = %s,
                        moderation_comment = %s,
                        moderated_at = NOW(),
                        updated_at = NOW()
                    WHERE submission_id = %s
                    RETURNING submission_id
                    """,
                    (
                        SUBMISSION_STATUS_REJECTED,
                        int(moderated_by_user_id),
                        _clean_text(moderation_comment),
                        int(submission_id),
                    ),
                )
                if cur.fetchone() is None:
                    raise RuntimeError("submission was not rejected")
            conn.commit()
        return self.get_submission(int(submission_id))

    def approve_submission_and_enqueue(
        self,
        *,
        submission_id: int,
        moderated_by_user_id: int,
        moderation_comment: str | None,
        max_attempts: int,
    ) -> tuple[SubmissionModel, int]:
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE author_submissions
                    SET status = %s,
                        moderated_by_user_id = %s,
                        moderation_comment = %s,
                        moderated_at = NOW(),
                        updated_at = NOW()
                    WHERE submission_id = %s
                    RETURNING submission_id
                    """,
                    (
                        SUBMISSION_STATUS_APPROVED,
                        int(moderated_by_user_id),
                        _clean_text(moderation_comment),
                        int(submission_id),
                    ),
                )
                row = cur.fetchone()
                if not row:
                    raise RuntimeError("submission was not approved")
                cur.execute(
                    """
                    INSERT INTO ingestion_tasks (source, status, payload, max_attempts)
                    VALUES (%s, %s, %s, %s)
                    RETURNING task_id
                    """,
                    (
                        SOURCE_APPROVED_SUBMISSION,
                        TASK_STATUS_PENDING,
                        Jsonb({"submission_id": int(submission_id)}),
                        int(max_attempts),
                    ),
                )
                task_row = cur.fetchone()
                if not task_row:
                    raise RuntimeError("failed to enqueue submission publication")
            conn.commit()
        return self.get_submission(int(submission_id)), int(task_row["task_id"])

    def get_submission(self, submission_id: int) -> SubmissionModel:
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(self._submission_query(where_clause="s.submission_id = %s"), (int(submission_id),))
                row = cur.fetchone()
        if not row:
            raise RuntimeError("submission not found")
        return self._row_to_submission(row)

    def get_author_submission(self, *, created_by_user_id: int, submission_id: int) -> SubmissionModel | None:
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    self._submission_query(where_clause="s.submission_id = %s AND s.created_by_user_id = %s"),
                    (int(submission_id), int(created_by_user_id)),
                )
                row = cur.fetchone()
        return self._row_to_submission(row) if row else None

    def find_latest_submission_by_source_identifier(
        self,
        *,
        created_by_user_id: int,
        source_identifier: str,
    ) -> SubmissionModel | None:
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    self._submission_query(
                        where_clause="s.created_by_user_id = %s AND s.source_identifier = %s",
                        order_clause="ORDER BY s.updated_at DESC, s.submission_id DESC LIMIT 1",
                    ),
                    (int(created_by_user_id), str(source_identifier).strip()),
                )
                row = cur.fetchone()
        return self._row_to_submission(row) if row else None

    def list_author_submissions(
        self,
        *,
        created_by_user_id: int,
        statuses: Sequence[str],
        limit: int,
        offset: int,
    ) -> tuple[list[SubmissionModel], int]:
        where, params = self._list_filter_clause(
            base_clause="s.created_by_user_id = %s",
            base_params=[int(created_by_user_id)],
            statuses=statuses,
        )
        return self._list_submissions(where_clause=where, params=params, limit=limit, offset=offset)

    def list_moderation_submissions(
        self,
        *,
        statuses: Sequence[str],
        limit: int,
        offset: int,
    ) -> tuple[list[SubmissionModel], int]:
        where, params = self._list_filter_clause(
            base_clause="TRUE",
            base_params=[],
            statuses=statuses,
        )
        return self._list_submissions(where_clause=where, params=params, limit=limit, offset=offset)

    def build_author_submission_for_publication(self, submission_id: int) -> AuthorSubmission:
        submission = self.get_submission(int(submission_id))
        if submission.status != SUBMISSION_STATUS_APPROVED:
            raise RuntimeError(
                f"submission {int(submission_id)} is in status '{submission.status}' and cannot be published"
            )
        return AuthorSubmission(
            identifier=submission.source_identifier,
            title=submission.title,
            abstract=submission.abstract,
            year=submission.year,
            best_oa_location=submission.best_oa_location,
            referenced_works=list(submission.referenced_works),
            related_works=list(submission.related_works),
            state="approved",
            created_by_user_id=submission.created_by_user_id,
        )

    def mark_publication_completed(self, *, submission_id: int, approved_paper_id: int) -> SubmissionModel:
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE author_submissions
                    SET approved_paper_id = %s,
                        updated_at = NOW()
                    WHERE submission_id = %s
                    RETURNING submission_id
                    """,
                    (int(approved_paper_id), int(submission_id)),
                )
                if cur.fetchone() is None:
                    raise RuntimeError("failed to persist approved paper id")
            conn.commit()
        return self.get_submission(int(submission_id))

    @staticmethod
    def _replace_links(
        cur: psycopg.Cursor,
        submission_id: int,
        relation_type: str,
        identifiers: Sequence[str],
    ) -> None:
        cleaned = _clean_identifier_list(identifiers)
        cur.execute(
            """
            DELETE FROM author_submission_links
            WHERE submission_id = %s
              AND relation_type = %s
            """,
            (int(submission_id), relation_type),
        )
        if cleaned:
            cur.executemany(
                """
                INSERT INTO author_submission_links (submission_id, relation_type, identifier)
                VALUES (%s, %s, %s)
                """,
                [
                    (int(submission_id), relation_type, identifier)
                    for identifier in cleaned
                ],
            )

    def _list_submissions(
        self,
        *,
        where_clause: str,
        params: Sequence[object],
        limit: int,
        offset: int,
    ) -> tuple[list[SubmissionModel], int]:
        query = self._submission_query(
            where_clause=where_clause,
            order_clause="ORDER BY s.updated_at DESC, s.submission_id DESC LIMIT %s OFFSET %s",
        )
        count_query = f"SELECT COUNT(*) AS total FROM author_submissions s WHERE {where_clause}"

        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(count_query, tuple(params))
                total_row = cur.fetchone()
                total = int(total_row["total"] or 0) if total_row else 0
                cur.execute(query, tuple(params) + (int(limit), int(offset)))
                rows = cur.fetchall()
        return [self._row_to_submission(row) for row in rows], total

    @staticmethod
    def _list_filter_clause(
        *,
        base_clause: str,
        base_params: list[object],
        statuses: Sequence[str],
    ) -> tuple[str, tuple[object, ...]]:
        normalized_statuses = [status for status in dict.fromkeys(str(value).strip() for value in statuses) if status]
        if normalized_statuses:
            return f"{base_clause} AND s.status = ANY(%s::text[])", tuple(base_params + [normalized_statuses])
        return base_clause, tuple(base_params)

    @staticmethod
    def _submission_query(*, where_clause: str, order_clause: str = "") -> str:
        return f"""
            WITH referenced AS (
                SELECT
                    submission_id,
                    array_agg(identifier ORDER BY identifier) AS identifiers
                FROM author_submission_links
                WHERE relation_type = '{RELATION_REFERENCED}'
                GROUP BY submission_id
            ),
            related AS (
                SELECT
                    submission_id,
                    array_agg(identifier ORDER BY identifier) AS identifiers
                FROM author_submission_links
                WHERE relation_type = '{RELATION_RELATED}'
                GROUP BY submission_id
            )
            SELECT
                s.submission_id,
                s.created_by_user_id,
                s.source_identifier,
                s.title,
                s.abstract,
                s.year,
                s.best_oa_location,
                s.status,
                s.moderated_by_user_id,
                s.moderation_comment,
                s.approved_paper_id,
                s.created_at,
                s.updated_at,
                s.submitted_at,
                s.moderated_at,
                COALESCE(referenced.identifiers, ARRAY[]::text[]) AS referenced_works,
                COALESCE(related.identifiers, ARRAY[]::text[]) AS related_works
            FROM author_submissions s
            LEFT JOIN referenced ON referenced.submission_id = s.submission_id
            LEFT JOIN related ON related.submission_id = s.submission_id
            WHERE {where_clause}
            {order_clause}
        """

    @staticmethod
    def _row_to_submission(row: dict | None) -> SubmissionModel:
        if row is None:
            raise RuntimeError("submission row is required")
        return SubmissionModel(
            submission_id=int(row["submission_id"]),
            created_by_user_id=int(row["created_by_user_id"]),
            source_identifier=row.get("source_identifier"),
            title=str(row.get("title") or ""),
            abstract=str(row.get("abstract") or ""),
            year=row.get("year"),
            best_oa_location=row.get("best_oa_location"),
            status=str(row.get("status") or SUBMISSION_STATUS_DRAFT),
            referenced_works=list(row.get("referenced_works") or []),
            related_works=list(row.get("related_works") or []),
            moderated_by_user_id=row.get("moderated_by_user_id"),
            moderation_comment=row.get("moderation_comment"),
            approved_paper_id=row.get("approved_paper_id"),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
            submitted_at=row.get("submitted_at"),
            moderated_at=row.get("moderated_at"),
        )


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _clean_identifier_list(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    cleaned: list[str] = []
    for value in values:
        identifier = _clean_text(value)
        if not identifier or identifier in seen:
            continue
        seen.add(identifier)
        cleaned.append(identifier)
    return cleaned


__all__ = [
    "RELATION_REFERENCED",
    "RELATION_RELATED",
    "SOURCE_APPROVED_SUBMISSION",
    "SUBMISSION_STATUS_APPROVED",
    "SUBMISSION_STATUS_DRAFT",
    "SUBMISSION_STATUS_PENDING",
    "SUBMISSION_STATUS_REJECTED",
    "SubmissionRepository",
]
