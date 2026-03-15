"""OpenAlex client for periodic incremental top-up."""

from __future__ import annotations

import math
import time

import requests

from src.parser.load_openalex_to_db import (
    clean_text,
    extract_authors,
    extract_institutions,
    extract_locations,
    extract_relations,
    parse_publication_date,
)
from src.parser.openalex_csv_parser import SELECT_FIELDS, flatten_work
from src.services.ingestion.models import DEFAULT_OPENALEX_STATE, OpenAlexPaper
from src.services.ingestion.settings import IngestionSettings


API_URL = "https://api.openalex.org/works"


class OpenAlexClient:
    def __init__(self, settings: IngestionSettings) -> None:
        self.settings = settings
        self.session = requests.Session()

        agent_email = settings.openalex_email or "noreply@example.com"
        self.headers = {"User-Agent": f"ALibIngestion/1.0 (+mailto:{agent_email})"}

    def fetch_latest(self, *, limit: int | None = None) -> list[OpenAlexPaper]:
        if not self.settings.openalex_email:
            raise RuntimeError("OPENALEX_EMAIL must be set for OpenAlex ingestion")

        requested_limit = limit or self.settings.openalex_limit
        if requested_limit <= 0:
            return []

        per_language_limit = max(
            1,
            math.ceil(requested_limit / max(1, len(self.settings.openalex_languages))),
        )
        papers_by_id: dict[str, OpenAlexPaper] = {}

        for language in self.settings.openalex_languages:
            for paper in self._fetch_language_latest(language=language, limit=per_language_limit):
                papers_by_id.setdefault(paper.identifier, paper)

        papers = list(papers_by_id.values())
        papers.sort(
            key=lambda item: item.publication_date.timestamp() if item.publication_date is not None else float("-inf"),
            reverse=True,
        )
        return papers[:requested_limit]

    def _fetch_language_latest(self, *, language: str, limit: int) -> list[OpenAlexPaper]:
        remaining = limit
        page = 1
        papers: list[OpenAlexPaper] = []

        while remaining > 0:
            per_page = min(remaining, 200)
            payload = self._request_page(language=language, page=page, per_page=per_page)
            results = payload.get("results") or []
            if not results:
                break

            for item in results:
                paper = self._to_paper(item)
                if paper is None:
                    continue
                papers.append(paper)
                remaining -= 1
                if remaining <= 0:
                    break

            page += 1
            if len(results) < per_page:
                break

        return papers

    def _request_page(self, *, language: str, page: int, per_page: int) -> dict:
        params = {
            "filter": f"language:{language},type:article,is_paratext:false,is_retracted:false",
            "sort": "publication_date:desc",
            "page": page,
            "per-page": per_page,
            "select": SELECT_FIELDS,
            "mailto": self.settings.openalex_email,
        }

        for attempt in range(3):
            response = self.session.get(
                API_URL,
                params=params,
                headers=self.headers,
                timeout=self.settings.openalex_timeout_seconds,
            )
            if response.status_code == 429 and attempt < 2:
                retry_after = int(response.headers.get("Retry-After", "2"))
                time.sleep(max(2, retry_after))
                continue
            response.raise_for_status()
            return response.json()

        raise RuntimeError("OpenAlex request retry budget exhausted")

    def _to_paper(self, work: dict) -> OpenAlexPaper | None:
        flattened = flatten_work(work)
        identifier = clean_text(flattened.get("id"))
        title = clean_text(flattened.get("title")) or ""
        abstract = clean_text(flattened.get("abstract_text")) or ""
        if not identifier or (not title and not abstract):
            return None

        referenced_works, related_works = extract_relations(flattened)
        best_oa_location = (
            clean_text(flattened.get("best_oa_loc_landing_page_url"))
            or clean_text(flattened.get("best_oa_loc_pdf_url"))
            or clean_text(flattened.get("primary_loc_landing_page_url"))
            or clean_text(flattened.get("primary_loc_pdf_url"))
        )

        year = flattened.get("publication_year")
        try:
            year_value = int(year) if year not in (None, "") else None
        except (TypeError, ValueError):
            year_value = None

        return OpenAlexPaper(
            identifier=identifier,
            title=title,
            abstract=abstract,
            year=year_value,
            best_oa_location=best_oa_location,
            doi=clean_text(flattened.get("doi")),
            publication_date=parse_publication_date(flattened.get("publication_date")),
            authors=list(extract_authors(flattened)),
            institutions=list(extract_institutions(flattened)),
            locations=list(extract_locations(flattened)),
            referenced_works=list(referenced_works),
            related_works=list(related_works),
            state=DEFAULT_OPENALEX_STATE,
        )

    def close(self) -> None:
        self.session.close()


__all__ = ["OpenAlexClient"]
