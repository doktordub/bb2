"""Trace event recording primitives for the MCP server."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import Lock
from typing import Any, Protocol

from app.observability.context import TraceContext, get_trace_context
from app.security.redaction import Redactor, TRUNCATED_SUFFIX


class TraceRecorder(Protocol):
    """Minimal recorder interface used by runtime observability wrappers."""

    @property
    def mode_name(self) -> str:
        ...

    def record_event(self, event_name: str, payload: Any | None = None) -> None:
        ...


@dataclass(frozen=True, slots=True)
class TraceEvent:
    """Stored trace event payload for local diagnostics and tests."""

    event_name: str
    timestamp: str
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class NoopTraceRecorder:
    """Recorder used when no local trace storage is required."""

    mode_name: str = "noop"

    def record_event(self, event_name: str, payload: Any | None = None) -> None:
        del event_name, payload
        return None


@dataclass(slots=True)
class InMemoryTraceRecorder:
    """Thread-safe trace recorder that stores sanitized events in memory."""

    redactor: Redactor
    max_events: int = 1000
    mode_name: str = field(default="in-memory", init=False)
    _events: deque[TraceEvent] = field(default_factory=deque, init=False, repr=False)
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)

    @property
    def events(self) -> tuple[TraceEvent, ...]:
        with self._lock:
            return tuple(self._events)

    def record_event(self, event_name: str, payload: Any | None = None) -> None:
        try:
            sanitized_payload = self._sanitize_payload(payload)
            event = TraceEvent(
                event_name=event_name,
                timestamp=datetime.now(UTC).isoformat(),
                payload=sanitized_payload,
            )
        except Exception:
            return None

        with self._lock:
            if len(self._events) >= self.max_events:
                self._events.popleft()
            self._events.append(event)

    def _sanitize_payload(self, payload: Any | None) -> dict[str, Any]:
        sanitized = self.redactor.sanitize(payload if payload is not None else {})
        if not isinstance(sanitized, dict):
            sanitized_payload: dict[str, Any] = {"value": sanitized}
        else:
            sanitized_payload = dict(sanitized)

        trace_context = get_trace_context()
        if trace_context is not None:
            for key, value in _trace_context_payload(trace_context).items():
                sanitized_payload.setdefault(key, value)

        sanitized_payload.setdefault("truncated", _contains_truncation(sanitized_payload))
        return sanitized_payload


def _trace_context_payload(context: TraceContext) -> dict[str, str]:
    payload = {"trace_id": context.trace_id}
    if context.request_id is not None:
        payload["request_id"] = context.request_id
    if context.caller_service is not None:
        payload["caller_service"] = context.caller_service
    if context.server_name is not None:
        payload["server_name"] = context.server_name
    if context.tool_name is not None:
        payload["tool_name"] = context.tool_name
    if context.capability_name is not None:
        payload["capability_name"] = context.capability_name
    return payload


def _contains_truncation(value: Any) -> bool:
    if isinstance(value, str):
        return value.endswith(TRUNCATED_SUFFIX)
    if isinstance(value, dict):
        return any(_contains_truncation(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_truncation(item) for item in value)
    return False