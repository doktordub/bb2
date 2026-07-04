"""Safe history projection helpers for session workflow state."""

from __future__ import annotations

from collections.abc import Mapping

from app.config.view import SessionHistorySettings
from app.contracts.state import WorkflowStateDocument
from app.session.models import SessionHistoryMessage, SessionHistoryResult

_VISIBLE_ROLES = frozenset({"user", "assistant"})
_SAFE_HISTORY_METADATA_KEYS = frozenset({"mode", "trace_fragment", "trace_id", "transport", "usecase"})


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
    state_metadata = state.get("metadata") if isinstance(state, dict) else None
    session_usecase = _optional_text(state_metadata.get("usecase")) if isinstance(state_metadata, Mapping) else None
    projected_messages: list[SessionHistoryMessage] = []
    if isinstance(messages_value, list):
        for item in messages_value:
            projected = _project_message(item, settings=settings, session_usecase=session_usecase)
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
    session_usecase: str | None = None,
) -> SessionHistoryMessage | None:
    if not isinstance(value, dict):
        return None

    normalized_role = normalize_visible_history_role(
        value.get("role"),
        include_system_messages=settings.include_system_messages,
        include_tool_summaries=settings.include_tool_summaries,
    )
    if normalized_role is None:
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
        raw_metadata = value.get("metadata")
        if isinstance(raw_metadata, Mapping):
            projected_metadata.update(project_safe_message_metadata(raw_metadata))
        if session_usecase is not None and "usecase" not in projected_metadata and "mode" not in projected_metadata:
            projected_metadata["usecase"] = session_usecase

    created_at = value.get("created_at")
    resolved_created_at = created_at if isinstance(created_at, str) else None
    return SessionHistoryMessage(
        role=normalized_role,
        content=projected_content,
        created_at=resolved_created_at,
        metadata=projected_metadata,
    )


def normalize_visible_history_role(
    role: object,
    *,
    include_system_messages: bool,
    include_tool_summaries: bool,
) -> str | None:
    if not isinstance(role, str):
        return None

    normalized_role = role.strip().lower()
    if normalized_role == "system":
        return normalized_role if include_system_messages else None
    if normalized_role == "tool":
        return normalized_role if include_tool_summaries else None
    if normalized_role in _VISIBLE_ROLES:
        return normalized_role
    return None


def project_safe_message_metadata(metadata: Mapping[str, object]) -> dict[str, str]:
    projected: dict[str, str] = {}
    for key in _SAFE_HISTORY_METADATA_KEYS:
        value = _optional_text(metadata.get(key))
        if value is not None:
            projected[key] = value
    return projected


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None