"""Safe history projection helpers for session workflow state."""

from __future__ import annotations

from copy import deepcopy
from collections.abc import Iterable
from collections.abc import Mapping

from app.config.view import SessionHistorySettings
from app.contracts.state import WorkflowStateDocument
from app.session.models import SessionHistoryMessage, SessionHistoryResult

_VISIBLE_ROLES = frozenset({"user", "assistant"})
_SAFE_HISTORY_METADATA_KEYS = frozenset(
    {
        "artifact_delivery_mode",
        "artifact_replay_reason",
        "artifact_replay_status",
        "mode",
        "trace_fragment",
        "trace_id",
        "transport",
        "usecase",
    }
)
_MAX_HISTORY_VISUALIZATIONS = 8
_MAX_HISTORY_WARNINGS = 8
_MAX_HISTORY_ARTIFACT_ROWS = 5000
_MAX_HISTORY_ARTIFACT_ROW_FIELDS = 32
_SCALAR_MISSING = object()


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
    raw_metadata = value.get("metadata")
    raw_metadata_mapping = raw_metadata if isinstance(raw_metadata, Mapping) else None
    projected_artifacts = _project_history_artifacts(value.get("artifacts"))
    if not projected_artifacts and raw_metadata_mapping is not None:
        projected_artifacts = _project_history_artifacts(raw_metadata_mapping.get("visualizations"))
    projected_metadata: dict[str, object] = {}
    if settings.include_metadata:
        projected_metadata["message_chars"] = len(content)
        if truncated:
            projected_metadata["content_truncated"] = True
        if raw_metadata_mapping is not None:
            projected_metadata.update(project_safe_message_metadata(raw_metadata_mapping))
        if session_usecase is not None and "usecase" not in projected_metadata and "mode" not in projected_metadata:
            projected_metadata["usecase"] = session_usecase
        if projected_artifacts:
            projected_metadata["visualizations"] = deepcopy(projected_artifacts)

    created_at = value.get("created_at")
    resolved_created_at = created_at if isinstance(created_at, str) else None
    return SessionHistoryMessage(
        role=normalized_role,
        content=projected_content,
        created_at=resolved_created_at,
        artifacts=projected_artifacts,
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


def project_safe_message_metadata(metadata: Mapping[str, object]) -> dict[str, object]:
    projected: dict[str, object] = {}
    for key in _SAFE_HISTORY_METADATA_KEYS:
        value = _optional_text(metadata.get(key))
        if value is not None:
            projected[key] = value
    artifact_count = _optional_non_negative_int(metadata.get("artifact_count"))
    if artifact_count is not None:
        projected["artifact_count"] = artifact_count
    visualizations = _project_history_artifacts(metadata.get("visualizations"))
    if visualizations:
        projected["visualizations"] = visualizations
    return projected


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _optional_non_negative_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value < 0:
        return None
    return value


def _project_history_artifacts(value: object) -> list[dict[str, object]]:
    if not isinstance(value, Iterable) or isinstance(value, str | bytes | bytearray):
        return []

    projected: list[dict[str, object]] = []
    for item in list(value)[:_MAX_HISTORY_VISUALIZATIONS]:
        if not isinstance(item, Mapping):
            continue

        artifact_id = _optional_text(item.get("artifact_id"))
        chart_type = _optional_text(item.get("chart_type"))
        title = _optional_text(item.get("title"))
        renderer = _optional_text(item.get("renderer"))
        spec_version = _optional_text(item.get("spec_version"))
        data_mode = _optional_text(item.get("data_mode"))
        data_ref = _optional_text(item.get("data_ref"))
        data: list[dict[str, object]] | None = None
        if (
            artifact_id is None
            or chart_type is None
            or title is None
            or renderer is None
            or spec_version is None
        ):
            continue

        if data_mode == "reference":
            if data_ref is None:
                continue
        elif data_mode == "inline":
            data = _project_data_rows(item.get("data"))
            if data is None:
                continue
        else:
            continue

        descriptor: dict[str, object] = {
            "artifact_id": artifact_id,
            "type": _optional_text(item.get("type")) or "chart",
            "chart_type": chart_type,
            "title": title,
            "description": _optional_text(item.get("description")) or "",
            "renderer": renderer,
            "spec_version": spec_version,
            "data_mode": data_mode,
            "data": data,
            "data_ref": data_ref,
            "encoding": _project_string_mapping(item.get("encoding")),
            "options": _project_scalar_mapping(item.get("options")),
            "warnings": _project_string_list(item.get("warnings"), limit=_MAX_HISTORY_WARNINGS),
            "metadata": _project_scalar_mapping(item.get("metadata")),
        }
        if descriptor["encoding"]:
            projected.append(descriptor)

    return projected


def _project_data_rows(value: object) -> list[dict[str, object]] | None:
    if not isinstance(value, list):
        return None

    projected: list[dict[str, object]] = []
    for row in value[:_MAX_HISTORY_ARTIFACT_ROWS]:
        if not isinstance(row, Mapping):
            continue
        projected_row: dict[str, object] = {}
        for raw_key, raw_value in list(row.items())[:_MAX_HISTORY_ARTIFACT_ROW_FIELDS]:
            key = _optional_text(raw_key)
            if key is None:
                continue
            scalar_value = _project_scalar_value(raw_value)
            if scalar_value is _SCALAR_MISSING:
                continue
            projected_row[key] = scalar_value
        projected.append(projected_row)
    return projected


def _project_scalar_value(value: object) -> object:
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        text = _optional_text(value)
        if text is not None:
            return text
    return _SCALAR_MISSING


def _project_string_mapping(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}

    projected: dict[str, object] = {}
    for raw_key, raw_value in list(value.items())[:16]:
        key = _optional_text(raw_key)
        if key is None:
            continue
        if isinstance(raw_value, str):
            text = _optional_text(raw_value)
            if text is not None:
                projected[key] = text
            continue
        if isinstance(raw_value, list):
            values = _project_string_list(raw_value, limit=12)
            if values:
                projected[key] = values
    return projected


def _project_scalar_mapping(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}

    projected: dict[str, object] = {}
    for raw_key, raw_value in list(value.items())[:16]:
        key = _optional_text(raw_key)
        if key is None:
            continue
        if isinstance(raw_value, str):
            text = _optional_text(raw_value)
            if text is not None:
                projected[key] = text
        elif isinstance(raw_value, bool | int | float) or raw_value is None:
            projected[key] = raw_value
    return projected


def _project_string_list(value: object, *, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []

    projected: list[str] = []
    for item in value[:limit]:
        text = _optional_text(item)
        if text is not None:
            projected.append(text)
    return projected