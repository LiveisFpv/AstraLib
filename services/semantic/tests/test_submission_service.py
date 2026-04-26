from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from src.domain.models.submission import SubmissionModel  # noqa: E402
from src.domain.models.submission import (  # noqa: E402
    SUBMISSION_STATUS_APPROVED,
    SUBMISSION_STATUS_DRAFT,
    SUBMISSION_STATUS_PENDING,
    SUBMISSION_STATUS_REJECTED,
)
from src.services.submission_service import (  # noqa: E402
    SubmissionPermissionError,
    SubmissionService,
    SubmissionStateError,
)


class FakeSubmissionRepository:
    def __init__(self) -> None:
        self.submissions: dict[int, SubmissionModel] = {}
        self.next_submission_id = 1
        self.next_task_id = 1000
        self.enqueued_submission_ids: list[int] = []

    def create_submission(
        self,
        *,
        created_by_user_id: int,
        source_identifier: str | None,
        title: str,
        abstract: str,
        year: int | None,
        best_oa_location: str | None,
        referenced_works,
        related_works,
    ) -> SubmissionModel:
        submission = SubmissionModel(
            submission_id=self.next_submission_id,
            created_by_user_id=created_by_user_id,
            source_identifier=source_identifier,
            title=title,
            abstract=abstract,
            year=year,
            best_oa_location=best_oa_location,
            status=SUBMISSION_STATUS_DRAFT,
            referenced_works=list(referenced_works),
            related_works=list(related_works),
        )
        self.submissions[submission.submission_id] = submission
        self.next_submission_id += 1
        return submission

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
        referenced_works,
        related_works,
    ) -> SubmissionModel:
        submission = self.submissions[submission_id]
        assert submission.created_by_user_id == created_by_user_id
        updated = replace(
            submission,
            source_identifier=source_identifier,
            title=title,
            abstract=abstract,
            year=year,
            best_oa_location=best_oa_location,
            referenced_works=list(referenced_works),
            related_works=list(related_works),
        )
        self.submissions[submission_id] = updated
        return updated

    def delete_author_submission(self, *, created_by_user_id: int, submission_id: int) -> bool:
        submission = self.submissions.get(submission_id)
        if submission is None or submission.created_by_user_id != created_by_user_id:
            return False
        del self.submissions[submission_id]
        return True

    def submit_author_submission(self, *, created_by_user_id: int, submission_id: int) -> SubmissionModel:
        submission = self.submissions[submission_id]
        assert submission.created_by_user_id == created_by_user_id
        updated = replace(
            submission,
            status=SUBMISSION_STATUS_PENDING,
            approved_paper_id=None,
            moderated_by_user_id=None,
            moderation_comment=None,
            moderated_at=None,
        )
        self.submissions[submission_id] = updated
        return updated

    def update_moderation_submission(
        self,
        *,
        submission_id: int,
        source_identifier: str | None,
        title: str,
        abstract: str,
        year: int | None,
        best_oa_location: str | None,
        referenced_works,
        related_works,
    ) -> SubmissionModel:
        submission = self.submissions[submission_id]
        updated = replace(
            submission,
            source_identifier=source_identifier,
            title=title,
            abstract=abstract,
            year=year,
            best_oa_location=best_oa_location,
            referenced_works=list(referenced_works),
            related_works=list(related_works),
        )
        self.submissions[submission_id] = updated
        return updated

    def reject_submission(self, *, submission_id: int, moderated_by_user_id: int, moderation_comment: str | None):
        submission = self.submissions[submission_id]
        updated = replace(
            submission,
            status=SUBMISSION_STATUS_REJECTED,
            moderated_by_user_id=moderated_by_user_id,
            moderation_comment=moderation_comment,
        )
        self.submissions[submission_id] = updated
        return updated

    def approve_submission_and_enqueue(
        self,
        *,
        submission_id: int,
        moderated_by_user_id: int,
        moderation_comment: str | None,
        max_attempts: int,
    ):
        submission = self.submissions[submission_id]
        updated = replace(
            submission,
            status=SUBMISSION_STATUS_APPROVED,
            moderated_by_user_id=moderated_by_user_id,
            moderation_comment=moderation_comment,
        )
        self.submissions[submission_id] = updated
        task_id = self.next_task_id
        self.next_task_id += 1
        self.enqueued_submission_ids.append(submission_id)
        return updated, task_id

    def get_submission(self, submission_id: int) -> SubmissionModel:
        if submission_id not in self.submissions:
            raise RuntimeError("submission not found")
        return self.submissions[submission_id]

    def get_author_submission(self, *, created_by_user_id: int, submission_id: int) -> SubmissionModel | None:
        submission = self.submissions.get(submission_id)
        if submission is None or submission.created_by_user_id != created_by_user_id:
            return None
        return submission

    def find_latest_submission_by_source_identifier(
        self,
        *,
        created_by_user_id: int,
        source_identifier: str,
    ) -> SubmissionModel | None:
        matches = [
            submission
            for submission in self.submissions.values()
            if submission.created_by_user_id == created_by_user_id
            and submission.source_identifier == source_identifier
        ]
        if not matches:
            return None
        return max(matches, key=lambda item: item.submission_id)

    def list_author_submissions(self, *, created_by_user_id: int, statuses, limit: int, offset: int):
        matches = [
            submission
            for submission in self.submissions.values()
            if submission.created_by_user_id == created_by_user_id and submission.status in statuses
        ]
        ordered = sorted(matches, key=lambda item: item.submission_id, reverse=True)
        return ordered[offset : offset + limit], len(matches)

    def list_moderation_submissions(self, *, statuses, limit: int, offset: int):
        matches = [
            submission for submission in self.submissions.values() if submission.status in statuses
        ]
        ordered = sorted(matches, key=lambda item: item.submission_id, reverse=True)
        return ordered[offset : offset + limit], len(matches)


class FakeUserService:
    def __init__(self) -> None:
        self.ensured_user_ids: list[int] = []

    def ensure_user(self, user_id: int):
        self.ensured_user_ids.append(user_id)
        return {"id": user_id}


def make_service() -> tuple[SubmissionService, FakeSubmissionRepository]:
    repository = FakeSubmissionRepository()
    return SubmissionService(repository, task_max_attempts=3), repository


def seed_submission(
    repository: FakeSubmissionRepository,
    *,
    submission_id: int,
    created_by_user_id: int,
    source_identifier: str | None,
    title: str,
    abstract: str,
    status: str,
) -> SubmissionModel:
    submission = SubmissionModel(
        submission_id=submission_id,
        created_by_user_id=created_by_user_id,
        source_identifier=source_identifier,
        title=title,
        abstract=abstract,
        status=status,
    )
    repository.submissions[submission_id] = submission
    repository.next_submission_id = max(repository.next_submission_id, submission_id + 1)
    return submission


def test_create_submission_ensures_user_before_insert() -> None:
    repository = FakeSubmissionRepository()
    user_service = FakeUserService()
    service = SubmissionService(repository, task_max_attempts=3, user_service=user_service)

    submission = service.create_my_submission(
        user_id=10,
        source_identifier="W1",
        title="title",
        abstract="abstract",
        year=None,
        best_oa_location=None,
        referenced_works=[],
        related_works=[],
    )

    assert user_service.ensured_user_ids == [10]
    assert submission.created_by_user_id == 10


def test_author_cannot_update_approved_submission() -> None:
    service, repository = make_service()
    seed_submission(
        repository,
        submission_id=1,
        created_by_user_id=10,
        source_identifier="W1",
        title="title",
        abstract="abstract",
        status=SUBMISSION_STATUS_APPROVED,
    )

    with pytest.raises(SubmissionStateError, match="cannot be updated by author"):
        service.update_my_submission(
            user_id=10,
            submission_id=1,
            source_identifier="W1",
            title="new title",
            abstract="new abstract",
            year=None,
            best_oa_location=None,
            referenced_works=[],
            related_works=[],
        )


def test_submit_rejected_submission_transitions_back_to_pending() -> None:
    service, repository = make_service()
    seed_submission(
        repository,
        submission_id=1,
        created_by_user_id=10,
        source_identifier="W1",
        title="title",
        abstract="abstract",
        status=SUBMISSION_STATUS_REJECTED,
    )

    submission = service.submit_my_submission(user_id=10, submission_id=1)

    assert submission.status == SUBMISSION_STATUS_PENDING
    assert repository.submissions[1].status == SUBMISSION_STATUS_PENDING


def test_author_cannot_access_foreign_submission() -> None:
    service, repository = make_service()
    seed_submission(
        repository,
        submission_id=7,
        created_by_user_id=99,
        source_identifier="W7",
        title="title",
        abstract="abstract",
        status=SUBMISSION_STATUS_DRAFT,
    )

    with pytest.raises(SubmissionPermissionError, match="not allowed to access submission 7"):
        service.get_my_submission(user_id=10, submission_id=7)


def test_moderator_cannot_approve_already_decided_submission() -> None:
    service, repository = make_service()
    seed_submission(
        repository,
        submission_id=3,
        created_by_user_id=10,
        source_identifier="W3",
        title="title",
        abstract="abstract",
        status=SUBMISSION_STATUS_APPROVED,
    )

    with pytest.raises(SubmissionStateError, match="only pending submissions can be moderated"):
        service.moderate_submission(
            submission_id=3,
            moderator_user_id=500,
            action="approve",
            comment="ok",
        )


def test_moderation_ensures_moderator_user_before_update() -> None:
    repository = FakeSubmissionRepository()
    user_service = FakeUserService()
    service = SubmissionService(repository, task_max_attempts=3, user_service=user_service)
    seed_submission(
        repository,
        submission_id=3,
        created_by_user_id=10,
        source_identifier="W3",
        title="title",
        abstract="abstract",
        status=SUBMISSION_STATUS_PENDING,
    )

    submission = service.moderate_submission(
        submission_id=3,
        moderator_user_id=500,
        action="reject",
        comment="not enough data",
    )

    assert user_service.ensured_user_ids == [500]
    assert submission.moderated_by_user_id == 500


def test_compatibility_wrapper_updates_latest_editable_submission_and_submits() -> None:
    service, repository = make_service()
    seed_submission(
        repository,
        submission_id=5,
        created_by_user_id=10,
        source_identifier="W5",
        title="old title",
        abstract="old abstract",
        status=SUBMISSION_STATUS_REJECTED,
    )

    submission = service.create_or_submit_compat_submission(
        user_id=10,
        source_identifier="W5",
        title="new title",
        abstract="new abstract",
        year=2024,
        best_oa_location="https://example.org",
        referenced_works=["W10"],
        related_works=["W11"],
    )

    assert submission.submission_id == 5
    assert submission.status == SUBMISSION_STATUS_PENDING
    assert submission.title == "new title"
    assert repository.submissions[5].related_works == ["W11"]


def test_compatibility_wrapper_rejects_pending_duplicate_source_identifier() -> None:
    service, repository = make_service()
    seed_submission(
        repository,
        submission_id=6,
        created_by_user_id=10,
        source_identifier="W6",
        title="title",
        abstract="abstract",
        status=SUBMISSION_STATUS_PENDING,
    )

    with pytest.raises(SubmissionStateError, match="already exists in status 'pending'"):
        service.create_or_submit_compat_submission(
            user_id=10,
            source_identifier="W6",
            title="title",
            abstract="abstract",
            year=None,
            best_oa_location=None,
            referenced_works=[],
            related_works=[],
        )
