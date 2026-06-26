"""API identity and request-context security helpers."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256


@dataclass(frozen=True, slots=True)
class ApiIdentity:
    """Synthetic local identity for the V1 API boundary."""

    user_id: str
    user_id_hash: str
    auth_mode: str = "local"


def build_local_identity(*, user_id: str = "local_user") -> ApiIdentity:
    """Return the default synthetic identity used before real auth exists."""

    normalized = user_id.strip() or "anonymous"
    return ApiIdentity(
        user_id=normalized,
        user_id_hash=_hash_identifier(normalized),
    )


def _hash_identifier(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()
