from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

SUBMISSION_STATUS_DRAFT = "draft"
SUBMISSION_STATUS_PENDING = "pending"
SUBMISSION_STATUS_APPROVED = "approved"
SUBMISSION_STATUS_REJECTED = "rejected"


@dataclass(slots=True)
class SubmissionModel:
    submission_id: int
    created_by_user_id: int
    source_identifier: str | None = None
    title: str = ""
    abstract: str = ""
    year: int | None = None
    best_oa_location: str | None = None
    status: str = "draft"
    referenced_works: list[str] = field(default_factory=list)
    related_works: list[str] = field(default_factory=list)
    moderated_by_user_id: int | None = None
    moderation_comment: str | None = None
    approved_paper_id: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    submitted_at: datetime | None = None
    moderated_at: datetime | None = None

__all__ = [
    "SUBMISSION_STATUS_APPROVED",
    "SUBMISSION_STATUS_DRAFT",
    "SUBMISSION_STATUS_PENDING",
    "SUBMISSION_STATUS_REJECTED",
    "SubmissionModel",
]
