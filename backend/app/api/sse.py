"""Helpers for mapping session stream events onto the public SSE contract."""

from __future__ import annotations

import json
from typing import Any

from app.api.versioning import API_SCHEMA_VERSION
from app.config.view import ApiSseSettings
from app.session.models import SessionStreamEvent

_SAFE_METADATA_KEYS = frozenset(
    {
        "agent_name",
        "strategy_name",
        "llm_profile",
        "usecase",
        "tool_call_count",
        "memory_result_count",
    }
)


def encode_sse(event: str, data: dict[str, Any], event_id: str | None = None) -> str:
    """Encode one SSE event payload."""

    lines: list[str] = []
    if event_id:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    lines.append(f"data: {payload}")
    return "\n".join(lines) + "\n\n"


def encode_session_stream_event(
    event: SessionStreamEvent,
    *,
    settings: ApiSseSettings,
) -> str | None:
    """Normalize one session stream event into a public SSE frame."""

    if event.event_type == "response.started":
        return encode_sse(
            event.event_type,
            _started_payload(event=event, include_trace_id=settings.send_trace_id_event),
        )

    if event.event_type == "response.delta":
        text = _as_text(event.data.get("text") or event.data.get("delta"))
        if text is None:
            return None
        return encode_sse(event.event_type, {"text": text})

    if event.event_type == "response.metadata":
        if not settings.send_metadata_events:
            return None
        payload = {
            key: value
            for key, value in event.data.items()
            if key in _SAFE_METADATA_KEYS and value is not None
        }
        return encode_sse(event.event_type, payload)

    if event.event_type == "response.completed":
        payload: dict[str, Any] = {
            "session_id": event.session_id,
            "finish_reason": _as_text(event.data.get("finish_reason")) or "stop",
        }
        duration_ms = event.data.get("duration_ms")
        if isinstance(duration_ms, int | float):
            payload["duration_ms"] = duration_ms
        if settings.send_trace_id_event:
            payload["trace_id"] = event.trace_id
        return encode_sse(event.event_type, payload)

    if event.event_type == "response.error":
        return encode_sse(
            event.event_type,
            _error_payload(event=event),
        )

    if event.event_type == "heartbeat":
        payload: dict[str, Any] = {}
        if settings.send_trace_id_event:
            payload["trace_id"] = event.trace_id
        return encode_sse(event.event_type, payload)

    return None


def encode_stream_error(
    *,
    trace_id: str,
    session_id: str | None,
    code: str,
    message: str,
    retryable: bool,
) -> str:
    """Encode a stable public stream error frame."""

    data: dict[str, Any] = {
        "trace_id": trace_id,
        "error": {
            "code": code,
            "message": message,
            "retryable": retryable,
        },
    }
    if session_id:
        data["session_id"] = session_id
    return encode_sse("response.error", data)


def encode_heartbeat(*, trace_id: str, settings: ApiSseSettings) -> str:
    """Encode a heartbeat frame using the configured trace visibility rule."""

    payload: dict[str, Any] = {}
    if settings.send_trace_id_event:
        payload["trace_id"] = trace_id
    return encode_sse("heartbeat", payload)


def encode_completed(
    *,
    trace_id: str,
    session_id: str,
    duration_ms: int,
    settings: ApiSseSettings,
) -> str:
    """Encode a fallback completed frame when the service stream stops cleanly."""

    payload: dict[str, Any] = {
        "session_id": session_id,
        "finish_reason": "stop",
        "duration_ms": duration_ms,
    }
    if settings.send_trace_id_event:
        payload["trace_id"] = trace_id
    return encode_sse("response.completed", payload)


def _started_payload(
    *,
    event: SessionStreamEvent,
    include_trace_id: bool,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": API_SCHEMA_VERSION,
        "session_id": event.session_id,
    }
    if include_trace_id:
        payload["trace_id"] = event.trace_id
    return payload


def _error_payload(event: SessionStreamEvent) -> dict[str, Any]:
    error = event.data.get("error")
    if isinstance(error, dict):
        code = _as_text(error.get("code")) or "backend_error"
        message = _as_text(error.get("message")) or "The request failed."
        retryable = bool(error.get("retryable", False))
    else:
        code = _as_text(event.data.get("code")) or "backend_error"
        message = _as_text(event.data.get("message")) or "The request failed."
        retryable = bool(event.data.get("retryable", False))

    payload: dict[str, Any] = {
        "trace_id": event.trace_id,
        "session_id": event.session_id,
        "error": {
            "code": code,
            "message": message,
            "retryable": retryable,
        },
    }
    return payload


def _as_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized:
        return None
    return normalized