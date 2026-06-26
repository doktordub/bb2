"""Known session boundary errors surfaced to the API layer."""

from __future__ import annotations

from app.contracts.errors import BackendError


class SessionError(BackendError):
    """Base exception for session-service failures."""


class SessionNotFoundError(SessionError):
    """Requested session could not be found."""


class SessionConflictError(SessionError):
    """Session lifecycle or concurrency conflict occurred."""


class UnknownUseCaseError(SessionError):
    """Caller requested an unavailable use case."""
