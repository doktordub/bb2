"""Session identifier generation and validation helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Pattern, Protocol
from uuid import uuid4

from app.session.errors import InvalidSessionIdError, SessionIdRequiredError

DEFAULT_SESSION_ID_PATTERN = r"^[A-Za-z0-9_.:-]{3,128}$"


class SessionIdProvider(Protocol):
    """Provides new stable session identifiers."""

    def new_session_id(self) -> str:
        ...


@dataclass(frozen=True, slots=True)
class PrefixedUuidSessionIdProvider:
    """Generate prefixed UUID-backed session identifiers."""

    prefix: str = "session"

    def new_session_id(self) -> str:
        return f"{self.prefix}_{uuid4().hex[:12]}"


def normalize_session_id(
    session_id: object,
    *,
    allowed_pattern: str | Pattern[str] = DEFAULT_SESSION_ID_PATTERN,
    max_length: int = 128,
) -> str:
    """Validate and normalize a session identifier."""

    if not isinstance(session_id, str):
        raise InvalidSessionIdError()

    normalized = session_id.strip()
    if not normalized or len(normalized) > max_length:
        raise InvalidSessionIdError()

    pattern = _compile_pattern(allowed_pattern)
    if not pattern.fullmatch(normalized):
        raise InvalidSessionIdError()

    return normalized


def resolve_session_id(
    session_id: str | None,
    *,
    generate_when_missing: bool,
    id_provider: SessionIdProvider,
    allowed_pattern: str | Pattern[str] = DEFAULT_SESSION_ID_PATTERN,
    max_length: int = 128,
) -> str:
    """Resolve a caller-provided or generated session identifier."""

    if session_id is None:
        if not generate_when_missing:
            raise SessionIdRequiredError()
        return normalize_session_id(
            id_provider.new_session_id(),
            allowed_pattern=allowed_pattern,
            max_length=max_length,
        )

    return normalize_session_id(
        session_id,
        allowed_pattern=allowed_pattern,
        max_length=max_length,
    )


def _compile_pattern(value: str | Pattern[str]) -> Pattern[str]:
    if isinstance(value, re.Pattern):
        return value
    return re.compile(value)