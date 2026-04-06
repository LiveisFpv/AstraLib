from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Protocol


USER_ID_HEADER = "x-user-id"
USER_ROLE_HEADER = "x-user-role"
ROLE_MODERATOR = "moderator"


class UserEnsurer(Protocol):
    def ensure_user(self, user_id: int): ...


class AuthenticationError(RuntimeError):
    pass


class AuthorizationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RequestAuthContext:
    user_id: int
    roles: frozenset[str]

    def require_role(self, role: str) -> None:
        if role not in self.roles:
            raise AuthorizationError(f"missing required role: {role}")


def extract_auth_context(
    context: Any,
    *,
    user_service: UserEnsurer,
) -> RequestAuthContext:
    metadata = context.invocation_metadata() or ()
    values = _metadata_to_dict(metadata)

    raw_user_id = values.get(USER_ID_HEADER, [])
    if not raw_user_id:
        raise AuthenticationError(f"missing {USER_ID_HEADER} metadata")

    try:
        user_id = int(raw_user_id[0].strip())
    except (TypeError, ValueError) as exc:
        raise AuthenticationError(f"invalid {USER_ID_HEADER} metadata") from exc

    roles = frozenset(_parse_roles(values.get(USER_ROLE_HEADER, [])))
    user_service.ensure_user(user_id)
    return RequestAuthContext(user_id=user_id, roles=roles)


def _metadata_to_dict(metadata: Iterable[object]) -> dict[str, list[str]]:
    values: dict[str, list[str]] = {}
    for item in metadata:
        key = getattr(item, "key", None)
        value = getattr(item, "value", None)
        if key is None and isinstance(item, tuple) and len(item) == 2:
            key, value = item
        if key is None or value is None:
            continue
        normalized_key = str(key).strip().lower()
        if not normalized_key:
            continue
        values.setdefault(normalized_key, []).append(str(value))
    return values


def _parse_roles(values: Iterable[str]) -> list[str]:
    roles: list[str] = []
    seen: set[str] = set()
    for value in values:
        for role in str(value).split(","):
            normalized = role.strip().lower()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            roles.append(normalized)
    return roles


__all__ = [
    "AuthenticationError",
    "AuthorizationError",
    "ROLE_MODERATOR",
    "RequestAuthContext",
    "extract_auth_context",
]
