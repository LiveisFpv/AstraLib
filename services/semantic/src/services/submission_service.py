from __future__ import annotations

from typing import Iterable, Protocol, Sequence

from src.domain.models.submission import (
    SUBMISSION_STATUS_APPROVED,
    SUBMISSION_STATUS_DRAFT,
    SUBMISSION_STATUS_PENDING,
    SUBMISSION_STATUS_REJECTED,
    SubmissionModel,
)


ALLOWED_SUBMISSION_STATUSES = {
    SUBMISSION_STATUS_DRAFT,
    SUBMISSION_STATUS_PENDING,
    SUBMISSION_STATUS_APPROVED,
    SUBMISSION_STATUS_REJECTED,
}
EDITABLE_AUTHOR_STATUSES = {SUBMISSION_STATUS_DRAFT, SUBMISSION_STATUS_REJECTED}
DEFAULT_AUTHOR_STATUSES = (
    SUBMISSION_STATUS_DRAFT,
    SUBMISSION_STATUS_PENDING,
    SUBMISSION_STATUS_APPROVED,
    SUBMISSION_STATUS_REJECTED,
)
DEFAULT_MODERATION_STATUSES = (SUBMISSION_STATUS_PENDING,)
MODERATION_ACTION_APPROVE = "approve"
MODERATION_ACTION_REJECT = "reject"
DEFAULT_LIST_LIMIT = 20
MAX_LIST_LIMIT = 100


class SubmissionError(RuntimeError):
    pass


class SubmissionNotFoundError(SubmissionError):
    pass


class SubmissionPermissionError(SubmissionError):
    pass


class SubmissionValidationError(SubmissionError):
    pass


class SubmissionStateError(SubmissionError):
    pass


class SubmissionRepositoryProtocol(Protocol):
    def create_submission(self, **kwargs) -> SubmissionModel: ...
    def update_author_submission(self, **kwargs) -> SubmissionModel: ...
    def delete_author_submission(self, **kwargs) -> bool: ...
    def submit_author_submission(self, **kwargs) -> SubmissionModel: ...
    def update_moderation_submission(self, **kwargs) -> SubmissionModel: ...
    def reject_submission(self, **kwargs) -> SubmissionModel: ...
    def approve_submission_and_enqueue(self, **kwargs) -> tuple[SubmissionModel, int]: ...
    def get_submission(self, submission_id: int) -> SubmissionModel: ...
    def get_author_submission(self, **kwargs) -> SubmissionModel | None: ...
    def find_latest_submission_by_source_identifier(self, **kwargs) -> SubmissionModel | None: ...
    def list_author_submissions(self, **kwargs) -> tuple[list[SubmissionModel], int]: ...
    def list_moderation_submissions(self, **kwargs) -> tuple[list[SubmissionModel], int]: ...


class UserEnsurerProtocol(Protocol):
    def ensure_user(self, user_id: int): ...


class SubmissionService:
    def __init__(
        self,
        repository: SubmissionRepositoryProtocol,
        *,
        task_max_attempts: int,
        user_service: UserEnsurerProtocol | None = None,
    ) -> None:
        self.repository = repository
        self.task_max_attempts = max(1, int(task_max_attempts))
        self.user_service = user_service

    def create_my_submission(
        self,
        *,
        user_id: int,
        source_identifier: str | None,
        title: str,
        abstract: str,
        year: int | None,
        best_oa_location: str | None,
        referenced_works: Sequence[str],
        related_works: Sequence[str],
    ) -> SubmissionModel:
        normalized_user_id = int(user_id)
        self._ensure_user(normalized_user_id)
        return self.repository.create_submission(
            created_by_user_id=normalized_user_id,
            source_identifier=_clean_text(source_identifier),
            title=_clean_text(title) or "",
            abstract=_clean_text(abstract) or "",
            year=_clean_year(year),
            best_oa_location=_clean_text(best_oa_location),
            referenced_works=_clean_identifier_list(referenced_works),
            related_works=_clean_identifier_list(related_works),
        )

    def update_my_submission(
        self,
        *,
        user_id: int,
        submission_id: int,
        source_identifier: str | None,
        title: str,
        abstract: str,
        year: int | None,
        best_oa_location: str | None,
        referenced_works: Sequence[str],
        related_works: Sequence[str],
    ) -> SubmissionModel:
        submission = self._get_author_owned_submission(user_id=user_id, submission_id=submission_id)
        self._require_author_editable(submission, action="update")
        return self.repository.update_author_submission(
            created_by_user_id=int(user_id),
            submission_id=int(submission_id),
            source_identifier=_clean_text(source_identifier),
            title=_clean_text(title) or "",
            abstract=_clean_text(abstract) or "",
            year=_clean_year(year),
            best_oa_location=_clean_text(best_oa_location),
            referenced_works=_clean_identifier_list(referenced_works),
            related_works=_clean_identifier_list(related_works),
        )

    def delete_my_submission(self, *, user_id: int, submission_id: int) -> None:
        submission = self._get_author_owned_submission(user_id=user_id, submission_id=submission_id)
        self._require_author_editable(submission, action="delete")
        deleted = self.repository.delete_author_submission(
            created_by_user_id=int(user_id),
            submission_id=int(submission_id),
        )
        if not deleted:
            raise SubmissionNotFoundError("submission not found")

    def get_my_submission(self, *, user_id: int, submission_id: int) -> SubmissionModel:
        return self._get_author_owned_submission(user_id=user_id, submission_id=submission_id)

    def list_my_submissions(
        self,
        *,
        user_id: int,
        statuses: Sequence[str],
        limit: int,
        offset: int,
    ) -> tuple[list[SubmissionModel], int, int, int]:
        normalized_statuses = _normalize_statuses(statuses, default=DEFAULT_AUTHOR_STATUSES)
        normalized_limit = _normalize_limit(limit)
        normalized_offset = _normalize_offset(offset)
        items, total = self.repository.list_author_submissions(
            created_by_user_id=int(user_id),
            statuses=normalized_statuses,
            limit=normalized_limit,
            offset=normalized_offset,
        )
        return items, total, normalized_limit, normalized_offset

    def submit_my_submission(self, *, user_id: int, submission_id: int) -> SubmissionModel:
        submission = self._get_author_owned_submission(user_id=user_id, submission_id=submission_id)
        if submission.status not in EDITABLE_AUTHOR_STATUSES:
            raise SubmissionStateError(
                f"submission in status '{submission.status}' cannot be submitted by author"
            )
        self._validate_publishable_content(submission)
        return self.repository.submit_author_submission(
            created_by_user_id=int(user_id),
            submission_id=int(submission_id),
        )

    def list_moderation_queue(
        self,
        *,
        statuses: Sequence[str],
        limit: int,
        offset: int,
    ) -> tuple[list[SubmissionModel], int, int, int]:
        normalized_statuses = _normalize_statuses(statuses, default=DEFAULT_MODERATION_STATUSES)
        normalized_limit = _normalize_limit(limit)
        normalized_offset = _normalize_offset(offset)
        items, total = self.repository.list_moderation_submissions(
            statuses=normalized_statuses,
            limit=normalized_limit,
            offset=normalized_offset,
        )
        return items, total, normalized_limit, normalized_offset

    def get_moderation_submission(self, *, submission_id: int) -> SubmissionModel:
        return self._get_submission(submission_id)

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
        submission = self._get_submission(submission_id)
        if submission.status != SUBMISSION_STATUS_PENDING:
            raise SubmissionStateError("only pending submissions can be updated by moderator")
        return self.repository.update_moderation_submission(
            submission_id=int(submission_id),
            source_identifier=_clean_text(source_identifier),
            title=_clean_text(title) or "",
            abstract=_clean_text(abstract) or "",
            year=_clean_year(year),
            best_oa_location=_clean_text(best_oa_location),
            referenced_works=_clean_identifier_list(referenced_works),
            related_works=_clean_identifier_list(related_works),
        )

    def moderate_submission(
        self,
        *,
        submission_id: int,
        moderator_user_id: int,
        action: str,
        comment: str | None,
    ) -> SubmissionModel:
        submission = self._get_submission(submission_id)
        if submission.status != SUBMISSION_STATUS_PENDING:
            raise SubmissionStateError("only pending submissions can be moderated")

        normalized_action = str(action or "").strip().lower()
        if normalized_action not in {MODERATION_ACTION_REJECT, MODERATION_ACTION_APPROVE}:
            raise SubmissionValidationError("moderation action must be 'approve' or 'reject'")

        normalized_moderator_user_id = int(moderator_user_id)
        self._ensure_user(normalized_moderator_user_id)
        if normalized_action == MODERATION_ACTION_REJECT:
            return self.repository.reject_submission(
                submission_id=int(submission_id),
                moderated_by_user_id=normalized_moderator_user_id,
                moderation_comment=_clean_text(comment),
            )

        self._validate_publishable_content(submission)
        approved_submission, _task_id = self.repository.approve_submission_and_enqueue(
            submission_id=int(submission_id),
            moderated_by_user_id=normalized_moderator_user_id,
            moderation_comment=_clean_text(comment),
            max_attempts=self.task_max_attempts,
        )
        return approved_submission

    def create_or_submit_compat_submission(
        self,
        *,
        user_id: int,
        source_identifier: str | None,
        title: str,
        abstract: str,
        year: int | None,
        best_oa_location: str | None,
        referenced_works: Sequence[str],
        related_works: Sequence[str],
    ) -> SubmissionModel:
        cleaned_identifier = _clean_text(source_identifier)
        if cleaned_identifier:
            existing = self.repository.find_latest_submission_by_source_identifier(
                created_by_user_id=int(user_id),
                source_identifier=cleaned_identifier,
            )
            if existing is not None:
                if existing.status in EDITABLE_AUTHOR_STATUSES:
                    updated = self.update_my_submission(
                        user_id=int(user_id),
                        submission_id=existing.submission_id,
                        source_identifier=cleaned_identifier,
                        title=title,
                        abstract=abstract,
                        year=year,
                        best_oa_location=best_oa_location,
                        referenced_works=referenced_works,
                        related_works=related_works,
                    )
                    return self.submit_my_submission(
                        user_id=int(user_id),
                        submission_id=updated.submission_id,
                    )
                raise SubmissionStateError(
                    f"submission for source identifier '{cleaned_identifier}' already exists in status '{existing.status}'"
                )

        created = self.create_my_submission(
            user_id=int(user_id),
            source_identifier=cleaned_identifier,
            title=title,
            abstract=abstract,
            year=year,
            best_oa_location=best_oa_location,
            referenced_works=referenced_works,
            related_works=related_works,
        )
        return self.submit_my_submission(user_id=int(user_id), submission_id=created.submission_id)

    def _get_submission(self, submission_id: int) -> SubmissionModel:
        try:
            return self.repository.get_submission(int(submission_id))
        except RuntimeError as exc:
            raise SubmissionNotFoundError(str(exc)) from exc

    def _get_author_owned_submission(self, *, user_id: int, submission_id: int) -> SubmissionModel:
        submission = self.repository.get_author_submission(
            created_by_user_id=int(user_id),
            submission_id=int(submission_id),
        )
        if submission is not None:
            return submission

        try:
            existing = self.repository.get_submission(int(submission_id))
        except RuntimeError as exc:
            raise SubmissionNotFoundError(str(exc)) from exc
        raise SubmissionPermissionError(
            f"user {int(user_id)} is not allowed to access submission {int(submission_id)} owned by user {existing.created_by_user_id}"
        )

    def _ensure_user(self, user_id: int) -> None:
        if self.user_service is not None:
            self.user_service.ensure_user(user_id)

    @staticmethod
    def _require_author_editable(submission: SubmissionModel, *, action: str) -> None:
        if submission.status not in EDITABLE_AUTHOR_STATUSES:
            raise SubmissionStateError(
                f"submission in status '{submission.status}' cannot be {action}d by author"
            )

    @staticmethod
    def _validate_publishable_content(submission: SubmissionModel) -> None:
        if not _clean_text(submission.title) and not _clean_text(submission.abstract):
            raise SubmissionValidationError("submission must contain title or abstract")


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _clean_identifier_list(values: Iterable[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        identifier = _clean_text(value)
        if not identifier or identifier in seen:
            continue
        seen.add(identifier)
        cleaned.append(identifier)
    return cleaned


def _clean_year(value: int | str | None) -> int | None:
    if value in (None, ""):
        return None
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise SubmissionValidationError("year must be an integer") from exc
    if normalized < 0 or normalized > 9999:
        raise SubmissionValidationError("year must be between 0 and 9999")
    return normalized


def _normalize_statuses(values: Sequence[str], *, default: Sequence[str]) -> list[str]:
    if not values:
        return list(default)
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        status = str(value or "").strip().lower()
        if not status:
            continue
        if status not in ALLOWED_SUBMISSION_STATUSES:
            raise SubmissionValidationError(f"unsupported submission status: {status}")
        if status in seen:
            continue
        seen.add(status)
        normalized.append(status)
    return normalized or list(default)


def _normalize_limit(value: int) -> int:
    try:
        limit = int(value)
    except (TypeError, ValueError):
        return DEFAULT_LIST_LIMIT
    if limit <= 0:
        return DEFAULT_LIST_LIMIT
    return min(limit, MAX_LIST_LIMIT)


def _normalize_offset(value: int) -> int:
    try:
        offset = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, offset)


__all__ = [
    "MODERATION_ACTION_APPROVE",
    "MODERATION_ACTION_REJECT",
    "SubmissionError",
    "SubmissionNotFoundError",
    "SubmissionPermissionError",
    "SubmissionService",
    "SubmissionStateError",
    "SubmissionValidationError",
]
