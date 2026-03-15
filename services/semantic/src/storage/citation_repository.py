"""Repository for citation graph mutations and neighborhood queries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Iterator, Sequence

import psycopg
from psycopg import Connection
from psycopg.rows import dict_row

from src.config.config import DATABASE_SETTINGS


@dataclass(slots=True)
class CitationSyncResult:
    seed_paper_ids: set[int]
    resolved_pending_sources: set[int]


class CitationRepository:
    def __init__(self, *, dsn: str | None = None) -> None:
        self.dsn = dsn or DATABASE_SETTINGS.psycopg_dsn()

    def backfill_legacy_citations(self, conn: Connection) -> int:
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH inserted AS (
                    INSERT INTO citation_edges (src_paper_id, dst_paper_id)
                    SELECT pr.src_paper_id, pr.dst_paper_id
                    FROM paper_relations pr
                    WHERE NOT EXISTS (
                        SELECT 1
                        FROM paper_relations rev
                        WHERE rev.src_paper_id = pr.dst_paper_id
                          AND rev.dst_paper_id = pr.src_paper_id
                    )
                    ON CONFLICT DO NOTHING
                    RETURNING 1
                )
                SELECT COUNT(*) AS inserted_count
                FROM inserted
                """
            )
            row = cur.fetchone()
            inserted_count = int(row["inserted_count"] or 0) if row else 0
            cur.execute(
                """
                DELETE FROM paper_relations pr
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM paper_relations rev
                    WHERE rev.src_paper_id = pr.dst_paper_id
                      AND rev.dst_paper_id = pr.src_paper_id
                )
                """
            )
        return inserted_count

    def replace_outgoing_citations(
        self,
        conn: Connection,
        *,
        src_paper_id: int,
        resolved_dest_ids: Iterable[int],
        pending_identifiers: Iterable[tuple[int, str]],
    ) -> CitationSyncResult:
        desired_dest_ids = {
            int(dst)
            for dst in resolved_dest_ids
            if dst is not None and int(dst) != int(src_paper_id)
        }
        desired_pending = {
            (int(identifier_type_id), str(identifier).strip())
            for identifier_type_id, identifier in pending_identifiers
            if str(identifier).strip()
        }

        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT dst_paper_id
                FROM citation_edges
                WHERE src_paper_id = %s
                """,
                (src_paper_id,),
            )
            current_dest_ids = {int(row["dst_paper_id"]) for row in cur.fetchall()}

            cur.execute(
                """
                SELECT identifier_type_id, identifier
                FROM pending_citation_edges
                WHERE src_paper_id = %s
                """,
                (src_paper_id,),
            )
            current_pending = {
                (int(row["identifier_type_id"]), str(row["identifier"]))
                for row in cur.fetchall()
            }

        to_add = sorted(desired_dest_ids - current_dest_ids)
        to_remove = sorted(current_dest_ids - desired_dest_ids)
        pending_to_add = sorted(desired_pending - current_pending)
        pending_to_remove = sorted(current_pending - desired_pending)

        if to_add:
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO citation_edges (src_paper_id, dst_paper_id)
                    VALUES (%s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    [(src_paper_id, dst_paper_id) for dst_paper_id in to_add],
                )

        if to_remove:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM citation_edges
                    WHERE src_paper_id = %s
                      AND dst_paper_id = ANY(%s::int[])
                    """,
                    (src_paper_id, to_remove),
                )

        if pending_to_add:
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO pending_citation_edges (src_paper_id, identifier_type_id, identifier)
                    VALUES (%s, %s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    [
                        (src_paper_id, identifier_type_id, identifier)
                        for identifier_type_id, identifier in pending_to_add
                    ],
                )

        if pending_to_remove:
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    DELETE FROM pending_citation_edges
                    WHERE src_paper_id = %s
                      AND identifier_type_id = %s
                      AND identifier = %s
                    """,
                    [
                        (src_paper_id, identifier_type_id, identifier)
                        for identifier_type_id, identifier in pending_to_remove
                    ],
                )

        return CitationSyncResult(
            seed_paper_ids={int(src_paper_id), *current_dest_ids, *desired_dest_ids},
            resolved_pending_sources=set(),
        )

    def resolve_pending_for_identifiers(
        self,
        conn: Connection,
        *,
        paper_id: int,
        identifier_type_id: int,
        identifiers: Iterable[str],
    ) -> set[int]:
        cleaned = [str(identifier).strip() for identifier in identifiers if str(identifier).strip()]
        if not cleaned:
            return set()

        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT src_paper_id, identifier
                FROM pending_citation_edges
                WHERE identifier_type_id = %s
                  AND identifier = ANY(%s)
                """,
                (identifier_type_id, cleaned),
            )
            rows = cur.fetchall()

        source_ids = {
            int(row["src_paper_id"])
            for row in rows
            if int(row["src_paper_id"]) != int(paper_id)
        }
        if not source_ids:
            return set()

        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO citation_edges (src_paper_id, dst_paper_id)
                VALUES (%s, %s)
                ON CONFLICT DO NOTHING
                """,
                [(src_paper_id, paper_id) for src_paper_id in sorted(source_ids)],
            )
            cur.execute(
                """
                DELETE FROM pending_citation_edges
                WHERE identifier_type_id = %s
                  AND identifier = ANY(%s)
                """,
                (identifier_type_id, cleaned),
            )

        return source_ids

    def sync_related_edges(
        self,
        conn: Connection,
        *,
        src_paper_id: int,
        related_dest_ids: Iterable[int],
    ) -> None:
        desired_dest_ids = {
            int(dst)
            for dst in related_dest_ids
            if dst is not None and int(dst) != int(src_paper_id)
        }

        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT pr.dst_paper_id
                FROM paper_relations pr
                JOIN paper_relations rev
                  ON rev.src_paper_id = pr.dst_paper_id
                 AND rev.dst_paper_id = pr.src_paper_id
                WHERE pr.src_paper_id = %s
                """,
                (src_paper_id,),
            )
            current_dest_ids = {int(row["dst_paper_id"]) for row in cur.fetchall()}

        to_add = sorted(desired_dest_ids - current_dest_ids)
        to_remove = sorted(current_dest_ids - desired_dest_ids)

        if to_add:
            with conn.cursor() as cur:
                values = []
                for dst_paper_id in to_add:
                    values.append((src_paper_id, dst_paper_id))
                    values.append((dst_paper_id, src_paper_id))
                cur.executemany(
                    """
                    INSERT INTO paper_relations (src_paper_id, dst_paper_id)
                    VALUES (%s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    values,
                )

        if to_remove:
            with conn.cursor() as cur:
                values = []
                for dst_paper_id in to_remove:
                    values.append((src_paper_id, dst_paper_id))
                    values.append((dst_paper_id, src_paper_id))
                cur.executemany(
                    """
                    DELETE FROM paper_relations
                    WHERE src_paper_id = %s
                      AND dst_paper_id = %s
                    """,
                    values,
                )

    def fetch_successors_map(
        self,
        paper_ids: Iterable[int],
        *,
        conn: Connection | None = None,
    ) -> dict[int, list[int]]:
        return self._fetch_neighbor_map(
            paper_ids,
            source_column="src_paper_id",
            target_column="dst_paper_id",
            conn=conn,
        )

    def fetch_predecessors_map(
        self,
        paper_ids: Iterable[int],
        *,
        conn: Connection | None = None,
    ) -> dict[int, list[int]]:
        return self._fetch_neighbor_map(
            paper_ids,
            source_column="dst_paper_id",
            target_column="src_paper_id",
            conn=conn,
        )

    def iter_edges(self, *, batch_size: int = 100_000) -> Iterator[list[tuple[int, int]]]:
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            with conn.cursor(name="citation_edges_stream") as cur:
                cur.itersize = batch_size
                cur.execute(
                    """
                    SELECT src_paper_id, dst_paper_id
                    FROM citation_edges
                    ORDER BY src_paper_id, dst_paper_id
                    """
                )
                while True:
                    rows = cur.fetchmany(batch_size)
                    if not rows:
                        break
                    yield [
                        (int(row["src_paper_id"]), int(row["dst_paper_id"]))
                        for row in rows
                    ]

    def fetch_outgoing_destinations(
        self,
        conn: Connection,
        *,
        src_paper_ids: Sequence[int],
    ) -> dict[int, set[int]]:
        if not src_paper_ids:
            return {}

        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT src_paper_id, dst_paper_id
                FROM citation_edges
                WHERE src_paper_id = ANY(%s::int[])
                """,
                (list(src_paper_ids),),
            )
            result: dict[int, set[int]] = {int(src): set() for src in src_paper_ids}
            for row in cur.fetchall():
                result.setdefault(int(row["src_paper_id"]), set()).add(int(row["dst_paper_id"]))
            return result

    def _fetch_neighbor_map(
        self,
        paper_ids: Iterable[int],
        *,
        source_column: str,
        target_column: str,
        conn: Connection | None,
    ) -> dict[int, list[int]]:
        normalized_ids = sorted({int(paper_id) for paper_id in paper_ids if paper_id is not None})
        if not normalized_ids:
            return {}

        owns_connection = conn is None
        if owns_connection:
            conn = psycopg.connect(self.dsn, row_factory=dict_row)

        try:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    f"""
                    SELECT {source_column} AS source_id, {target_column} AS target_id
                    FROM citation_edges
                    WHERE {source_column} = ANY(%s::int[])
                    ORDER BY {source_column}, {target_column}
                    """,
                    (normalized_ids,),
                )
                result: dict[int, list[int]] = {paper_id: [] for paper_id in normalized_ids}
                for row in cur.fetchall():
                    result[int(row["source_id"])].append(int(row["target_id"]))
                return result
        finally:
            if owns_connection and conn is not None:
                conn.close()


__all__ = ["CitationRepository", "CitationSyncResult"]
