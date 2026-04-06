"""Data models for background ingestion."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


SOURCE_AUTHOR_SUBMISSION = "author_submission"
SOURCE_APPROVED_SUBMISSION = "approved_submission"

TASK_STATUS_PENDING = "pending"
TASK_STATUS_PROCESSING = "processing"
TASK_STATUS_COMPLETED = "completed"
TASK_STATUS_FAILED = "failed"

DEFAULT_AUTHOR_STATE = "approved"
DEFAULT_OPENALEX_STATE = "article"


def _clean_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _clean_string_list(values: Any) -> list[str]:
    if not values:
        return []
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = _clean_string(value)
        if not item or item in seen:
            continue
        seen.add(item)
        cleaned.append(item)
    return cleaned


def _clean_year(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@dataclass(slots=True)
class AuthorSubmission:
    identifier: str | None = None
    title: str = ""
    abstract: str = ""
    year: int | None = None
    best_oa_location: str | None = None
    referenced_works: list[str] = field(default_factory=list)
    related_works: list[str] = field(default_factory=list)
    state: str = DEFAULT_AUTHOR_STATE
    created_by_user_id: int | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "identifier": _clean_string(self.identifier),
            "title": self.title.strip(),
            "abstract": self.abstract.strip(),
            "year": self.year,
            "best_oa_location": _clean_string(self.best_oa_location),
            "referenced_works": list(self.referenced_works),
            "related_works": list(self.related_works),
            "state": _clean_string(self.state) or DEFAULT_AUTHOR_STATE,
            "created_by_user_id": self.created_by_user_id,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any] | None) -> "AuthorSubmission":
        payload = payload or {}
        return cls(
            identifier=_clean_string(payload.get("identifier")),
            title=str(payload.get("title") or "").strip(),
            abstract=str(payload.get("abstract") or "").strip(),
            year=_clean_year(payload.get("year")),
            best_oa_location=_clean_string(payload.get("best_oa_location")),
            referenced_works=_clean_string_list(payload.get("referenced_works")),
            related_works=_clean_string_list(payload.get("related_works")),
            state=_clean_string(payload.get("state")) or DEFAULT_AUTHOR_STATE,
            created_by_user_id=_clean_year(payload.get("created_by_user_id")),
        )


@dataclass(slots=True)
class OpenAlexPaper:
    identifier: str
    title: str
    abstract: str
    year: int | None = None
    best_oa_location: str | None = None
    doi: str | None = None
    publication_date: datetime | None = None
    authors: list[dict[str, Any]] = field(default_factory=list)
    institutions: list[dict[str, Any]] = field(default_factory=list)
    locations: list[dict[str, Any]] = field(default_factory=list)
    referenced_works: list[str] = field(default_factory=list)
    related_works: list[str] = field(default_factory=list)
    state: str = DEFAULT_OPENALEX_STATE


@dataclass(slots=True)
class StoredPaper:
    paper_id: int
    title: str
    abstract: str
    year: int | None = None
    best_oa_location: str | None = None
    state: str | None = None

    @property
    def text(self) -> str:
        parts = [self.title.strip(), self.abstract.strip()]
        return "\n\n".join(part for part in parts if part)


@dataclass(slots=True)
class IngestionDelta:
    stored_papers: list[StoredPaper]
    seed_paper_ids: set[int] = field(default_factory=set)


@dataclass(slots=True)
class IngestionTask:
    task_id: int
    source: str
    status: str
    payload: dict[str, Any]
    attempts: int
    max_attempts: int
    priority: int
    scheduled_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    last_error: str | None = None
    result: dict[str, Any] | None = None


__all__ = [
    "AuthorSubmission",
    "DEFAULT_AUTHOR_STATE",
    "DEFAULT_OPENALEX_STATE",
    "IngestionDelta",
    "IngestionTask",
    "OpenAlexPaper",
    "SOURCE_AUTHOR_SUBMISSION",
    "SOURCE_APPROVED_SUBMISSION",
    "StoredPaper",
    "TASK_STATUS_COMPLETED",
    "TASK_STATUS_FAILED",
    "TASK_STATUS_PENDING",
    "TASK_STATUS_PROCESSING",
]
