"""Session-level optimistic concurrency helpers."""

from __future__ import annotations

from app.config.view import SessionConcurrencySettings
from app.persistence.errors import WorkflowStateConflictError
from app.session.errors import SessionConflictError


def map_conflict_error(
    *,
    operation: str,
    settings: SessionConcurrencySettings,
    error: WorkflowStateConflictError,
) -> SessionConflictError:
    """Map workflow-state optimistic conflicts to the session boundary."""

    _ = error
    policy = settings.conflict_policy.strip().lower()
    if policy != "reject":
        return SessionConflictError(
            f"The session {operation} conflicted with the current session state."
        )

    messages = {
        "chat": "The session changed before the chat response could be saved.",
        "stream": "The session changed before the stream could be finalized.",
        "reset": "The session changed during reset.",
    }
    return SessionConflictError(messages.get(operation, SessionConflictError.default_message))