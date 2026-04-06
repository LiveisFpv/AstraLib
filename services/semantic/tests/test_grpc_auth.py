from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from src.http.grpc.auth import (  # noqa: E402
    AuthenticationError,
    extract_auth_context,
)


class FakeUserService:
    def __init__(self) -> None:
        self.ensured_user_ids: list[int] = []

    def ensure_user(self, user_id: int):
        self.ensured_user_ids.append(user_id)
        return {"id": user_id}


class FakeContext:
    def __init__(self, metadata: list[tuple[str, str]]) -> None:
        self._metadata = metadata

    def invocation_metadata(self):
        return tuple(self._metadata)


def test_extract_auth_context_parses_roles_and_upserts_user() -> None:
    user_service = FakeUserService()
    context = FakeContext(
        [
            ("x-user-id", "42"),
            ("x-user-role", "author"),
            ("x-user-role", "moderator, reviewer"),
        ]
    )

    auth = extract_auth_context(context, user_service=user_service)

    assert auth.user_id == 42
    assert auth.roles == frozenset({"author", "moderator", "reviewer"})
    assert user_service.ensured_user_ids == [42]


def test_extract_auth_context_rejects_missing_user_id() -> None:
    user_service = FakeUserService()
    context = FakeContext([("x-user-role", "author")])

    with pytest.raises(AuthenticationError, match="missing x-user-id metadata"):
        extract_auth_context(context, user_service=user_service)

