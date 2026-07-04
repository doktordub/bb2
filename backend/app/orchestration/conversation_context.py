"""Helpers for projecting prompt-safe conversation continuity from workflow state."""

from __future__ import annotations

from dataclasses import dataclass

from app.config.view import ConversationContextSettings
from app.contracts.state import WorkflowStateDocument
from app.contracts.context import OrchestrationContext
from app.memory.redaction import truncate_text
from app.orchestration.models import ConversationMessage
from app.orchestration.state_delta import WorkflowStateSnapshot, workflow_state_snapshot_from_document
from app.session.history import normalize_visible_history_role


_SESSION_SUMMARY_METADATA_KEY = "session_summary"
_SUMMARY_ROLE_LABELS = {
    "user": "User",
    "assistant": "Assistant",
}


@dataclass(frozen=True, slots=True)
class ConversationContextWindow:
    """Bounded prior-turn window safe to inject into prompt history."""

    enabled: bool
    messages: tuple[ConversationMessage, ...] = ()
    session_summary: str | None = None
    session_summary_used: bool = False
    truncated: bool = False
    current_turn_deduped: bool = False
    visible_message_count: int = 0


def build_conversation_context_window(
    context: OrchestrationContext,
) -> ConversationContextWindow:
    """Project one prompt-ready continuity window from orchestration context."""

    settings = _resolve_conversation_context_settings(context)
    return project_conversation_context_window(
        state=context.state,
        settings=settings,
        current_request_id=_current_request_id(context),
    )


def project_conversation_context_window(
    *,
    state: WorkflowStateSnapshot | None,
    settings: ConversationContextSettings,
    current_request_id: str | None,
) -> ConversationContextWindow:
    """Project bounded continuity messages from one workflow-state snapshot."""

    if not settings.enabled:
        return ConversationContextWindow(enabled=False)
    if state is None:
        return ConversationContextWindow(enabled=True)

    visible_messages = _project_visible_messages(
        state.messages,
        settings=settings,
        current_request_id=current_request_id,
    )
    current_turn_deduped = len(visible_messages) != len(state.messages)
    bounded_messages, truncated = _apply_limits(
        visible_messages,
        max_messages=settings.max_messages,
        max_chars=settings.max_chars,
    )
    session_summary = _resolve_session_summary(
        state,
        settings=settings,
        visible_message_count=len(visible_messages),
        truncated=truncated,
    )

    return ConversationContextWindow(
        enabled=True,
        messages=tuple(bounded_messages),
        session_summary=session_summary,
        session_summary_used=session_summary is not None,
        truncated=truncated,
        current_turn_deduped=current_turn_deduped,
        visible_message_count=len(visible_messages),
    )


def refresh_session_summary_metadata(
    state: WorkflowStateDocument,
    *,
    settings: ConversationContextSettings,
    updated_at: str | None,
) -> WorkflowStateDocument:
    """Refresh the persisted deterministic session summary on one workflow state."""

    if not settings.enabled:
        _remove_session_summary_metadata(state)
        return state

    snapshot = workflow_state_snapshot_from_document(
        session_id=_state_session_id(state),
        state=state,
    )
    visible_messages = _project_visible_messages(
        snapshot.messages,
        settings=settings,
        current_request_id=None,
    )
    bounded_messages, truncated = _apply_limits(
        visible_messages,
        max_messages=settings.max_messages,
        max_chars=settings.max_chars,
    )
    if not _should_use_session_summary(
        settings,
        visible_message_count=len(visible_messages),
        truncated=truncated,
    ):
        _remove_session_summary_metadata(state)
        return state

    summary_source = visible_messages[: max(0, len(visible_messages) - len(bounded_messages))]
    summary_text = _build_session_summary_text(
        summary_source,
        max_chars=settings.summary_max_chars,
    )
    if summary_text is None:
        _remove_session_summary_metadata(state)
        return state

    metadata = state.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
        state["metadata"] = metadata
    metadata[_SESSION_SUMMARY_METADATA_KEY] = {
        "text": summary_text,
        "summary_message_count": len(summary_source),
        "visible_message_count": len(visible_messages),
        "updated_at": updated_at,
        "mode": "deterministic_rollup",
    }
    return state


def _project_visible_messages(
    messages: list[ConversationMessage],
    *,
    settings: ConversationContextSettings,
    current_request_id: str | None,
) -> list[ConversationMessage]:
    visible_messages: list[ConversationMessage] = []
    for message in messages:
        if _is_current_request_user_message(message, current_request_id=current_request_id):
            continue

        projected = _project_visible_message(message, settings=settings)
        if projected is not None:
            visible_messages.append(projected)
    return visible_messages


def _apply_limits(
    messages: list[ConversationMessage],
    *,
    max_messages: int,
    max_chars: int,
) -> tuple[list[ConversationMessage], bool]:
    bounded_messages, truncated_by_count = _apply_message_limit(
        messages,
        max_messages=max_messages,
    )
    bounded_messages, truncated_by_chars = _apply_char_limit(
        bounded_messages,
        max_chars=max_chars,
    )
    return bounded_messages, truncated_by_count or truncated_by_chars


def _project_visible_message(
    message: ConversationMessage,
    *,
    settings: ConversationContextSettings,
) -> ConversationMessage | None:
    role = normalize_visible_history_role(
        message.role,
        include_system_messages=False,
        include_tool_summaries=False,
    )
    if role is None:
        return None
    if role == "assistant" and not settings.include_assistant_messages:
        return None
    return ConversationMessage(
        role=role,
        content=message.content,
        created_at=message.created_at,
        request_id=message.request_id,
        turn_id=message.turn_id,
        trace_id=message.trace_id,
        metadata=dict(message.metadata),
    )


def _apply_message_limit(
    messages: list[ConversationMessage],
    *,
    max_messages: int,
) -> tuple[list[ConversationMessage], bool]:
    if max_messages <= 0:
        return [], bool(messages)
    if len(messages) <= max_messages:
        return list(messages), False
    return list(messages[-max_messages:]), True


def _apply_char_limit(
    messages: list[ConversationMessage],
    *,
    max_chars: int,
) -> tuple[list[ConversationMessage], bool]:
    if max_chars <= 0:
        return [], bool(messages)

    bounded = list(messages)
    total_chars = sum(len(message.content) for message in bounded)
    if total_chars <= max_chars:
        return bounded, False

    while len(bounded) > 1 and total_chars > max_chars:
        total_chars -= len(bounded.pop(0).content)

    if not bounded:
        return [], True
    if total_chars <= max_chars:
        return bounded, True

    tail_message = bounded[-1]
    truncated_content = truncate_text(tail_message.content, max_chars=max_chars)
    if not truncated_content:
        truncated_content = tail_message.content[:max_chars]
    bounded[-1] = ConversationMessage(
        role=tail_message.role,
        content=truncated_content,
        created_at=tail_message.created_at,
        request_id=tail_message.request_id,
        turn_id=tail_message.turn_id,
        trace_id=tail_message.trace_id,
        metadata=dict(tail_message.metadata),
    )
    return bounded, True


def _is_current_request_user_message(
    message: ConversationMessage,
    *,
    current_request_id: str | None,
) -> bool:
    if current_request_id is None:
        return False
    if message.role.strip().lower() != "user":
        return False
    return _message_request_id(message) == current_request_id


def _message_request_id(message: ConversationMessage) -> str | None:
    if message.request_id is not None:
        return message.request_id
    value = message.metadata.get("request_id")
    return value.strip() if isinstance(value, str) and value.strip() else None


def _current_request_id(context: OrchestrationContext) -> str | None:
    runtime_request_id = None if context.runtime is None else _normalize_text(context.runtime.request_id)
    if runtime_request_id is not None:
        return runtime_request_id
    request_metadata = context.request.metadata
    metadata_request_id = _normalize_text(request_metadata.get("request_id"))
    if metadata_request_id is not None:
        return metadata_request_id
    return _normalize_text(context.runtime_metadata.get("request_id"))


def _resolve_conversation_context_settings(
    context: OrchestrationContext,
) -> ConversationContextSettings:
    if context.settings is not None:
        return context.settings.defaults.conversation_context
    return ConversationContextSettings(
        enabled=bool(context.config.get("orchestration.defaults.conversation_context.enabled", False)),
        mode=_read_str(
            context,
            "orchestration.defaults.conversation_context.mode",
            "window",
        ),
        max_messages=_read_int(
            context,
            "orchestration.defaults.conversation_context.max_messages",
            12,
        ),
        max_chars=_read_int(
            context,
            "orchestration.defaults.conversation_context.max_chars",
            12000,
        ),
        include_assistant_messages=bool(
            context.config.get(
                "orchestration.defaults.conversation_context.include_assistant_messages",
                True,
            )
        ),
        summary_threshold_messages=_read_int(
            context,
            "orchestration.defaults.conversation_context.summary_threshold_messages",
            24,
        ),
        summary_max_chars=_read_int(
            context,
            "orchestration.defaults.conversation_context.summary_max_chars",
            2000,
        ),
    )


def _read_int(context: OrchestrationContext, path: str, default: int) -> int:
    value = context.config.get(path, default)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return default


def _read_str(context: OrchestrationContext, path: str, default: str) -> str:
    value = context.config.get(path, default)
    if not isinstance(value, str):
        return default
    normalized = value.strip()
    return normalized or default


def _normalize_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _resolve_session_summary(
    state: WorkflowStateSnapshot,
    *,
    settings: ConversationContextSettings,
    visible_message_count: int,
    truncated: bool,
) -> str | None:
    if not _should_use_session_summary(
        settings,
        visible_message_count=visible_message_count,
        truncated=truncated,
    ):
        return None

    raw_summary = state.metadata.get(_SESSION_SUMMARY_METADATA_KEY)
    if not isinstance(raw_summary, dict):
        return None
    return _normalize_text(raw_summary.get("text"))


def _should_use_session_summary(
    settings: ConversationContextSettings,
    *,
    visible_message_count: int,
    truncated: bool,
) -> bool:
    if visible_message_count <= 0:
        return False
    if truncated:
        return True
    return visible_message_count >= settings.summary_threshold_messages


def _build_session_summary_text(
    messages: list[ConversationMessage],
    *,
    max_chars: int,
) -> str | None:
    if max_chars <= 0 or not messages:
        return None

    lines: list[str] = []
    used_chars = 0
    for message in messages:
        line = _build_session_summary_line(message)
        if line is None:
            continue
        separator = 1 if lines else 0
        projected_total = used_chars + separator + len(line)
        if projected_total <= max_chars:
            lines.append(line)
            used_chars = projected_total
            continue

        remaining_chars = max_chars - used_chars - separator
        if remaining_chars <= 8:
            break
        truncated_line = truncate_text(line, max_chars=remaining_chars) or line[:remaining_chars]
        lines.append(truncated_line)
        break

    if not lines:
        return None
    return "\n".join(lines)


def _build_session_summary_line(message: ConversationMessage) -> str | None:
    role_label = _SUMMARY_ROLE_LABELS.get(message.role.strip().lower())
    if role_label is None:
        return None
    content = _normalize_text(message.content)
    if content is None:
        return None
    return f"- {role_label}: {content}"


def _remove_session_summary_metadata(state: WorkflowStateDocument) -> None:
    metadata = state.get("metadata")
    if isinstance(metadata, dict):
        metadata.pop(_SESSION_SUMMARY_METADATA_KEY, None)


def _state_session_id(state: WorkflowStateDocument) -> str:
    session_id = state.get("session_id") if isinstance(state, dict) else None
    if isinstance(session_id, str) and session_id.strip():
        return session_id
    return "session"


__all__ = [
    "ConversationContextWindow",
    "build_conversation_context_window",
    "project_conversation_context_window",
    "refresh_session_summary_metadata",
]