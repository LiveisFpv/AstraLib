"""Repository for accessing paper metadata from Postgres."""

from __future__ import annotations

from typing import Any, Iterable, List, Optional

import psycopg
from psycopg.rows import dict_row

from src.config.config import DATABASE_SETTINGS


class PaperRepository:
    def __init__(self, *, dsn: str | None = None) -> None:
        self.dsn = dsn or DATABASE_SETTINGS.psycopg_dsn()

    def fetch_ordered(self, identifiers: Iterable[Any]) -> List[Optional[dict]]:
        ids_list = list(identifiers)
        if not ids_list:
            return []

        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            resolved = self._resolve_identifiers(conn, ids_list)
            valid = [(idx, pid) for idx, pid in enumerate(resolved) if pid is not None]
            if not valid:
                return [None] * len(ids_list)

            ordered_ids = [int(pid) for _, pid in valid]

            query = """
                WITH input AS (
                    SELECT id, ord
                    FROM unnest(%s::int[]) WITH ORDINALITY AS t(id, ord)
                ),
                base AS (
                    SELECT i.ord,
                           p.paper_id,
                           p.title,
                           p.abstract,
                           p.year
                    FROM input i
                    JOIN papers p ON p.paper_id = i.id
                ),
                best_location AS (
                    SELECT
                        l.paper_id,
                        MAX(CASE WHEN l.link_type = 'best_oa_landing' THEN l.url END) AS best_oa_landing,
                        MAX(CASE WHEN l.link_type = 'best_oa_pdf' THEN l.url END) AS best_oa_pdf,
                        MAX(CASE WHEN l.link_type = 'primary_landing' THEN l.url END) AS primary_landing,
                        MAX(CASE WHEN l.link_type = 'primary_pdf' THEN l.url END) AS primary_pdf
                    FROM locations l
                    WHERE l.paper_id = ANY(%s::int[])
                    GROUP BY l.paper_id
                ),
                referenced AS (
                    SELECT
                        ce.src_paper_id AS paper_id,
                        array_agg(
                            DISTINCT CASE
                                WHEN pi.identifier ~ '(^|/)W[0-9]+$'
                                    THEN 'https://openalex.org/' || substring(pi.identifier FROM 'W[0-9]+$')
                                ELSE pi.identifier
                            END
                            ORDER BY CASE
                                WHEN pi.identifier ~ '(^|/)W[0-9]+$'
                                    THEN 'https://openalex.org/' || substring(pi.identifier FROM 'W[0-9]+$')
                                ELSE pi.identifier
                            END
                        ) AS refs
                    FROM citation_edges ce
                    JOIN paper_identifiers pi ON pi.paper_id = ce.dst_paper_id
                    JOIN identifier_types it ON it.identifier_type_id = pi.identifier_type_id
                    WHERE it.name = 'openalex'
                      AND ce.src_paper_id = ANY(%s::int[])
                    GROUP BY ce.src_paper_id
                ),
                related AS (
                    SELECT
                        pr.src_paper_id AS paper_id,
                        array_agg(
                            DISTINCT CASE
                                WHEN pi.identifier ~ '(^|/)W[0-9]+$'
                                    THEN 'https://openalex.org/' || substring(pi.identifier FROM 'W[0-9]+$')
                                ELSE pi.identifier
                            END
                            ORDER BY CASE
                                WHEN pi.identifier ~ '(^|/)W[0-9]+$'
                                    THEN 'https://openalex.org/' || substring(pi.identifier FROM 'W[0-9]+$')
                                ELSE pi.identifier
                            END
                        ) AS rels
                    FROM paper_relations pr
                    JOIN paper_relations rev
                        ON rev.src_paper_id = pr.dst_paper_id
                       AND rev.dst_paper_id = pr.src_paper_id
                    JOIN paper_identifiers pi ON pi.paper_id = pr.dst_paper_id
                    JOIN identifier_types it ON it.identifier_type_id = pi.identifier_type_id
                    WHERE it.name = 'openalex'
                      AND pr.src_paper_id = ANY(%s::int[])
                    GROUP BY pr.src_paper_id
                ),
                cited AS (
                    SELECT
                        ce.dst_paper_id AS paper_id,
                        COUNT(*) AS cited_by
                    FROM citation_edges ce
                    WHERE ce.dst_paper_id = ANY(%s::int[])
                    GROUP BY ce.dst_paper_id
                ),
                authors AS (
                    SELECT
                        pa.paper_id,
                        array_agg(
                            CONCAT_WS(
                                ' ',
                                NULLIF(a.first_name, ''),
                                NULLIF(a.middle_name, ''),
                                NULLIF(a.last_name, '')
                            )
                            ORDER BY pa.author_order NULLS LAST, a.author_id
                        ) AS names
                    FROM paper_authors pa
                    JOIN authors a ON a.author_id = pa.author_id
                    WHERE pa.paper_id = ANY(%s::int[])
                    GROUP BY pa.paper_id
                ),
                institutions AS (
                    SELECT
                        pi.paper_id,
                        array_agg(DISTINCT inst.name ORDER BY inst.name) AS names
                    FROM paper_institutions pi
                    JOIN institutions inst ON inst.institution_id = pi.institution_id
                    WHERE pi.paper_id = ANY(%s::int[])
                    GROUP BY pi.paper_id
                ),
                identifiers AS (
                    SELECT
                        normalized.paper_id,
                        jsonb_agg(
                            jsonb_build_object('type', normalized.type, 'value', normalized.value)
                            ORDER BY normalized.type, normalized.value
                        ) AS items
                    FROM (
                        SELECT DISTINCT
                            pi.paper_id,
                            it.name AS type,
                            CASE
                                WHEN it.name = 'openalex' AND pi.identifier ~ '(^|/)W[0-9]+$'
                                    THEN 'https://openalex.org/' || substring(pi.identifier FROM 'W[0-9]+$')
                                ELSE pi.identifier
                            END AS value
                        FROM paper_identifiers pi
                        JOIN identifier_types it ON it.identifier_type_id = pi.identifier_type_id
                        WHERE pi.paper_id = ANY(%s::int[])
                    ) normalized
                    GROUP BY normalized.paper_id
                )
                SELECT
                    b.ord,
                    b.paper_id,
                    b.title,
                    b.abstract,
                    b.year,
                    COALESCE(best.best_oa_landing, best.best_oa_pdf, best.primary_landing, best.primary_pdf) AS best_oa_location,
                    COALESCE(referenced.refs, ARRAY[]::text[]) AS referenced_works,
                    COALESCE(related.rels, ARRAY[]::text[]) AS related_works,
                    COALESCE(cited.cited_by, 0) AS cited_by_count,
                    COALESCE(authors.names, ARRAY[]::text[]) AS authors,
                    COALESCE(institutions.names, ARRAY[]::text[]) AS institutions,
                    COALESCE(identifiers.items, '[]'::jsonb) AS identifiers
                FROM base b
                LEFT JOIN best_location best ON best.paper_id = b.paper_id
                LEFT JOIN referenced ON referenced.paper_id = b.paper_id
                LEFT JOIN related ON related.paper_id = b.paper_id
                LEFT JOIN cited ON cited.paper_id = b.paper_id
                LEFT JOIN authors ON authors.paper_id = b.paper_id
                LEFT JOIN institutions ON institutions.paper_id = b.paper_id
                LEFT JOIN identifiers ON identifiers.paper_id = b.paper_id
                ORDER BY b.ord
            """

            with conn.cursor() as cur:
                cur.execute(
                    query,
                    (
                        ordered_ids,
                        ordered_ids,
                        ordered_ids,
                        ordered_ids,
                        ordered_ids,
                        ordered_ids,
                        ordered_ids,
                        ordered_ids,
                    ),
                )
                rows = cur.fetchall()

        row_by_id = {row["paper_id"]: row for row in rows}
        results: List[Optional[dict]] = [None] * len(ids_list)
        for idx, paper_id in valid:
            results[idx] = row_by_id.get(paper_id)
        return results

    def _resolve_identifiers(self, conn: psycopg.Connection, identifiers: List[Any]) -> List[Optional[int]]:
        resolved: List[Optional[int]] = []
        openalex_values: List[str] = []
        openalex_positions: dict[str, List[int]] = {}

        for pos, raw in enumerate(identifiers):
            if raw is None:
                resolved.append(None)
                continue
            try:
                resolved.append(int(raw))
                continue
            except (TypeError, ValueError):
                pass

            text = str(raw).strip()
            if not text:
                resolved.append(None)
                continue
            openalex_values.append(text)
            openalex_positions.setdefault(text, []).append(pos)
            resolved.append(None)

        if not openalex_values:
            return resolved

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT pi.identifier, pi.paper_id
                FROM paper_identifiers pi
                JOIN identifier_types it ON it.identifier_type_id = pi.identifier_type_id
                WHERE it.name = 'openalex' AND pi.identifier = ANY(%s)
                """,
                (openalex_values,),
            )
            mapping = {row["identifier"]: row["paper_id"] for row in cur.fetchall()}

        for value, positions in openalex_positions.items():
            paper_id = mapping.get(value)
            if paper_id is None:
                continue
            for pos in positions:
                resolved[pos] = paper_id

        return resolved


__all__ = ["PaperRepository"]
