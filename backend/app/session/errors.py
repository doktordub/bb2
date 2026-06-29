"""Known session boundary errors surfaced to the API layer."""

from __future__ import annotations

from typing import Any

from app.contracts.errors import BackendError


class SessionError(BackendError):
    """Base exception for session-service failures."""

    code = "session_error"
    retryable = False
    default_message = "Session request failed."

    def __init__(
        self,
        message: str | None = None,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        resolved_message = message or self.default_message
        super().__init__(resolved_message)
        self.message = resolved_message
        self.details = dict(details or {})


class InvalidSessionIdError(SessionError):
    """Caller provided a session identifier with an invalid shape."""

    code = "invalid_session_id"
    default_message = "The session ID is invalid."


class SessionIdRequiredError(SessionError):
    """Session ID is required when automatic generation is disabled."""

    code = "session_id_required"
    default_message = "A session ID is required for this request."


class SessionNotFoundError(SessionError):
    """Requested session could not be found."""

    code = "session_not_found"
    default_message = "The requested session was not found."


class SessionConflictError(SessionError):
    """Session lifecycle or concurrency conflict occurred."""

    code = "session_conflict"
    retryable = True
    default_message = "The session request conflicted with the current session state."


class SessionStateUnavailableError(SessionError):
    """Workflow-state backing store is unavailable."""

    code = "workflow_state_unavailable"
    retryable = True
    default_message = "Workflow state is temporarily unavailable."


class SessionResetFailedError(SessionError):
    """Session reset failed due to a backing store problem."""

    code = "session_reset_failed"
    retryable = True
    default_message = "The session could not be reset."


class SessionHistoryDisabledError(SessionError):
    """Session history route is disabled by configuration."""

    code = "session_history_disabled"
    default_message = "Session history is not enabled."


class SessionHistoryUnavailableError(SessionError):
    """Session history could not be retrieved safely."""

    code = "session_history_unavailable"
    retryable = True
    default_message = "Session history is temporarily unavailable."


class SessionListDisabledError(SessionError):
    """Session list route is disabled by configuration."""

    code = "session_list_disabled"
    default_message = "Session listing is not enabled."


class SessionListUnavailableError(SessionError):
    """Session list could not be retrieved safely."""

    code = "session_list_unavailable"
    retryable = True
    default_message = "Session listing is temporarily unavailable."


class SessionDeleteDisabledError(SessionError):
    """Session delete route is disabled by configuration."""

    code = "session_delete_disabled"
    default_message = "Session deletion is not enabled."


class SessionDeleteFailedError(SessionError):
    """Session deletion failed due to a backing store problem."""

    code = "session_delete_failed"
    retryable = True
    default_message = "The session could not be deleted."


class UnknownUseCaseError(SessionError):
    """Caller requested an unavailable use case."""

    code = "unknown_usecase"
    default_message = "The requested use case is not available."
