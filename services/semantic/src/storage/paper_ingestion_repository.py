"""Incremental paper ingestion helpers for author submissions and OpenAlex."""

from __future__ import annotations

import re
from typing import Iterable

from src.db.connection import transaction
from src.parser.load_openalex_to_db import (
    LoaderContext,
    RowData,
    clean_text,
    ensure_identifier_type,
    find_paper_by_identifier,
    link_identifier,
    normalize_openalex_id,
    process_batch,
    upsert_paper,
)
from src.services.ingestion.models import (
    DEFAULT_AUTHOR_STATE,
    DEFAULT_OPENALEX_STATE,
    AuthorSubmission,
    IngestionDelta,
    OpenAlexPaper,
    StoredPaper,
)
from src.storage.citation_repository import CitationRepository


OPENALEX_ENTITY_RE = re.compile(r"^[WAISCF]\d+$", re.IGNORECASE)
SUBMISSION_IDENTIFIER_TYPE = "submission"


class PaperIngestionRepository:
    def __init__(self, *, citation_repository: CitationRepository | None = None) -> None:
        self.citation_repository = citation_repository or CitationRepository()

    def upsert_author_submission(self, submission: AuthorSubmission) -> IngestionDelta:
        title = (submission.title or "").strip()
        abstract = (submission.abstract or "").strip()
        if not title and not abstract:
            raise ValueError("submission must contain title or abstract")

        with transaction() as conn:
            context = LoaderContext(conn)
            submission_type_id = ensure_identifier_type(conn, SUBMISSION_IDENTIFIER_TYPE)

            identifier = clean_text(submission.identifier)
            paper_id = self._resolve_author_paper_id(
                conn,
                context,
                submission_type_id=submission_type_id,
                identifier=identifier,
            )

            state = clean_text(submission.state) or DEFAULT_AUTHOR_STATE
            paper_id = upsert_paper(
                conn,
                paper_id=paper_id,
                title=title or None,
                abstract=abstract or None,
                year=submission.year,
                type_value=state,
                created_at=None,
            )

            seed_paper_ids: set[int] = {int(paper_id)}
            if identifier:
                identifier_type_id, aliases = self._identifier_spec(
                    identifier,
                    openalex_type_id=context.openalex_type_id,
                    submission_type_id=submission_type_id,
                )
                for alias in aliases:
                    link_identifier(conn, paper_id, identifier_type_id, alias)
                if identifier_type_id == context.openalex_type_id:
                    context.register_paper_identifiers(paper_id, aliases)
                seed_paper_ids.update(
                    self.citation_repository.resolve_pending_for_identifiers(
                        conn,
                        paper_id=paper_id,
                        identifier_type_id=identifier_type_id,
                        identifiers=aliases,
                    )
                )

            self._ensure_best_location(conn, paper_id, submission.best_oa_location)

            resolved_citations, pending_citations = self._resolve_reference_targets(
                conn,
                context,
                submission_type_id=submission_type_id,
                identifiers=submission.referenced_works,
            )
            citation_sync = self.citation_repository.replace_outgoing_citations(
                conn,
                src_paper_id=paper_id,
                resolved_dest_ids=resolved_citations,
                pending_identifiers=pending_citations,
            )
            seed_paper_ids.update(citation_sync.seed_paper_ids)
            seed_paper_ids.update(citation_sync.resolved_pending_sources)

            resolved_related_ids = self._resolve_related_targets(
                conn,
                context,
                submission_type_id=submission_type_id,
                identifiers=submission.related_works,
            )
            self.citation_repository.sync_related_edges(
                conn,
                src_paper_id=paper_id,
                related_dest_ids=resolved_related_ids,
            )

            stored = StoredPaper(
                paper_id=paper_id,
                title=title,
                abstract=abstract,
                year=submission.year,
                best_oa_location=clean_text(submission.best_oa_location),
                state=state,
            )
            return IngestionDelta(stored_papers=[stored], seed_paper_ids=seed_paper_ids)

    def upsert_openalex_batch(self, papers: Iterable[OpenAlexPaper]) -> IngestionDelta:
        entries = [paper for paper in papers if (paper.title or "").strip() or (paper.abstract or "").strip()]
        if not entries:
            return IngestionDelta(stored_papers=[], seed_paper_ids=set())

        with transaction() as conn:
            rows: list[RowData] = []
            for paper in entries:
                locations = list(paper.locations)
                if paper.best_oa_location and not any(
                    clean_text(location.get("url")) == clean_text(paper.best_oa_location)
                    for location in locations
                ):
                    locations.append(
                        {
                            "url": clean_text(paper.best_oa_location),
                            "link_type": "best_oa_landing",
                            "version": "open_access",
                        }
                    )

                rows.append(
                    RowData(
                        identifier_aliases=self._build_openalex_aliases(paper.identifier),
                        title=clean_text(paper.title),
                        abstract=clean_text(paper.abstract),
                        year=paper.year,
                        type_value=clean_text(paper.state) or DEFAULT_OPENALEX_STATE,
                        created_at=paper.publication_date,
                        doi=clean_text(paper.doi.lower() if paper.doi else None),
                        authors=list(paper.authors),
                        institutions=list(paper.institutions),
                        locations=locations,
                        referenced_ids=list(paper.referenced_works),
                        related_ids=list(paper.related_works),
                    )
                )

            process_batch(LoaderContext(conn), rows)

            stored: list[StoredPaper] = []
            seed_paper_ids: set[int] = set()
            for row in rows:
                if row.paper_id is None:
                    continue
                stored.append(
                    StoredPaper(
                        paper_id=int(row.paper_id),
                        title=row.title or "",
                        abstract=row.abstract or "",
                        year=row.year,
                        best_oa_location=self._best_location_from_row(row),
                        state=row.type_value or DEFAULT_OPENALEX_STATE,
                    )
                )
                seed_paper_ids.update(int(paper_id) for paper_id in row.seed_paper_ids)
            return IngestionDelta(stored_papers=stored, seed_paper_ids=seed_paper_ids)

    def _resolve_author_paper_id(
        self,
        conn,
        context: LoaderContext,
        *,
        submission_type_id: int,
        identifier: str | None,
    ) -> int | None:
        if not identifier:
            return None
        if self._looks_like_openalex_identifier(identifier):
            return context.lookup_paper_id(self._build_openalex_aliases(identifier))
        return find_paper_by_identifier(conn, submission_type_id, identifier)

    def _resolve_reference_targets(
        self,
        conn,
        context: LoaderContext,
        *,
        submission_type_id: int,
        identifiers: Iterable[str],
    ) -> tuple[set[int], set[tuple[int, str]]]:
        resolved_dest_ids: set[int] = set()
        pending_identifiers: set[tuple[int, str]] = set()

        for raw_identifier in identifiers:
            identifier = clean_text(raw_identifier)
            if not identifier:
                continue

            identifier_type_id, aliases = self._identifier_spec(
                identifier,
                openalex_type_id=context.openalex_type_id,
                submission_type_id=submission_type_id,
            )
            dest_paper_id = self._resolve_target_paper_id(
                conn,
                context,
                identifier_type_id=identifier_type_id,
                aliases=aliases,
                submission_type_id=submission_type_id,
            )
            if dest_paper_id is not None:
                resolved_dest_ids.add(int(dest_paper_id))
            else:
                for alias in aliases:
                    pending_identifiers.add((identifier_type_id, alias))

        return resolved_dest_ids, pending_identifiers

    def _resolve_related_targets(
        self,
        conn,
        context: LoaderContext,
        *,
        submission_type_id: int,
        identifiers: Iterable[str],
    ) -> set[int]:
        related_dest_ids: set[int] = set()
        for raw_identifier in identifiers:
            identifier = clean_text(raw_identifier)
            if not identifier:
                continue
            identifier_type_id, aliases = self._identifier_spec(
                identifier,
                openalex_type_id=context.openalex_type_id,
                submission_type_id=submission_type_id,
            )
            dest_paper_id = self._resolve_target_paper_id(
                conn,
                context,
                identifier_type_id=identifier_type_id,
                aliases=aliases,
                submission_type_id=submission_type_id,
            )
            if dest_paper_id is not None:
                related_dest_ids.add(int(dest_paper_id))
        return related_dest_ids

    def _resolve_target_paper_id(
        self,
        conn,
        context: LoaderContext,
        *,
        identifier_type_id: int,
        aliases: list[str],
        submission_type_id: int,
    ) -> int | None:
        if identifier_type_id == context.openalex_type_id:
            return context.lookup_paper_id(aliases)
        if identifier_type_id == submission_type_id and aliases:
            return find_paper_by_identifier(conn, identifier_type_id, aliases[0])
        return None

    def _ensure_best_location(self, conn, paper_id: int, best_oa_location: str | None) -> None:
        url = clean_text(best_oa_location)
        if not url:
            return
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO locations (paper_id, url, link_type, version)
                SELECT %s, %s, %s, %s
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM locations
                    WHERE paper_id = %s
                      AND url = %s
                      AND COALESCE(link_type, '') = %s
                      AND COALESCE(version, '') = %s
                )
                """,
                (
                    paper_id,
                    url,
                    "best_oa_landing",
                    "submitted",
                    paper_id,
                    url,
                    "best_oa_landing",
                    "submitted",
                ),
            )

    @staticmethod
    def _looks_like_openalex_identifier(value: str) -> bool:
        normalized = normalize_openalex_id(value)
        if not normalized:
            return False
        return bool(OPENALEX_ENTITY_RE.match(normalized))

    @staticmethod
    def _build_openalex_aliases(value: str | None) -> list[str]:
        cleaned = clean_text(value)
        if not cleaned:
            return []
        aliases: list[str] = []
        normalized = normalize_openalex_id(cleaned)
        if normalized:
            aliases.append(normalized)
        aliases.append(cleaned)
        return list(dict.fromkeys(alias for alias in aliases if alias))

    @classmethod
    def _identifier_spec(
        cls,
        value: str,
        *,
        openalex_type_id: int,
        submission_type_id: int,
    ) -> tuple[int, list[str]]:
        if cls._looks_like_openalex_identifier(value):
            return openalex_type_id, cls._build_openalex_aliases(value)
        cleaned = clean_text(value)
        return submission_type_id, [cleaned] if cleaned else []

    @staticmethod
    def _best_location_from_row(row: RowData) -> str | None:
        for location in row.locations:
            url = clean_text(location.get("url"))
            if url:
                return url
        return None


__all__ = ["PaperIngestionRepository"]
