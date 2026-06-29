"""Safe history projection helpers for session workflow state."""

from __future__ import annotations

from app.config.view import SessionHistorySettings
from app.contracts.state import WorkflowStateDocument
from app.session.models import SessionHistoryMessage, SessionHistoryResult

_VISIBLE_ROLES = frozenset({"user", "assistant"})


def project_session_history(
    *,
    trace_id: str,
    session_id: str,
    state: WorkflowStateDocument,
    limit: int,
    settings: SessionHistorySettings,
) -> SessionHistoryResult:
    """Return a bounded, safe history projection from workflow state."""

    messages_value = state.get("conversation", {}).get("messages", [])
    projected_messages: list[SessionHistoryMessage] = []
    if isinstance(messages_value, list):
        for item in messages_value:
            projected = _project_message(item, settings=settings)
            if projected is not None:
                projected_messages.append(projected)

    bounded_messages = projected_messages[-limit:]
    return SessionHistoryResult(
        trace_id=trace_id,
        session_id=session_id,
        messages=bounded_messages,
        truncated=len(projected_messages) > len(bounded_messages),
        metadata={
            "limit": limit,
            "returned_count": len(bounded_messages),
        },
    )


def _project_message(
    value: object,
    *,
    settings: SessionHistorySettings,
) -> SessionHistoryMessage | None:
    if not isinstance(value, dict):
        return None

    role = value.get("role")
    if not isinstance(role, str):
        return None

    normalized_role = role.strip().lower()
    if normalized_role == "system" and not settings.include_system_messages:
        return None
    if normalized_role == "tool" and not settings.include_tool_summaries:
        return None
    if normalized_role not in _VISIBLE_ROLES and normalized_role != "system":
        if normalized_role != "tool":
            return None

    content = value.get("content")
    if not isinstance(content, str):
        return None

    truncated = len(content) > settings.max_message_chars
    projected_content = content[: settings.max_message_chars]
    projected_metadata: dict[str, object] = {}
    if settings.include_metadata:
        projected_metadata["message_chars"] = len(content)
        if truncated:
            projected_metadata["content_truncated"] = True

    created_at = value.get("created_at")
    resolved_created_at = created_at if isinstance(created_at, str) else None
    return SessionHistoryMessage(
        role=normalized_role,
        content=projected_content,
        created_at=resolved_created_at,
        metadata=projected_metadata,
    )