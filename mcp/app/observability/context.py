"""Async-safe trace-context helpers for MCP observability."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
import re
from typing import Any
from uuid import uuid4


TRACE_ID_HEADER = "x-trace-id"
TRACE_ID_ALIAS_HEADER = "traceparent"
REQUEST_ID_HEADER = "x-request-id"
REQUEST_ID_ALIAS_HEADER = "x-correlation-id"

_TRACE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{8,128}$")
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_TRACEPARENT_PATTERN = re.compile(
    r"^(?P<version>[A-Fa-f0-9]{2})-"
    r"(?P<trace_id>[A-Fa-f0-9]{32})-"
    r"(?P<parent_id>[A-Fa-f0-9]{16})-"
    r"(?P<flags>[A-Fa-f0-9]{2})$"
)


@dataclass(frozen=True, slots=True)
class TraceContext:
    """Request-scoped trace metadata bound to the active async context."""

    trace_id: str
    request_id: str | None = None
    caller_service: str | None = None
    server_name: str | None = None
    tool_name: str | None = None
    capability_name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


_current_trace_context: ContextVar[TraceContext | None] = ContextVar(
    "mcp_current_trace_context",
    default=None,
)


def new_trace_id() -> str:
    """Return a new MCP-generated trace ID."""

    return f"trace_{uuid4().hex}"


def is_valid_trace_id(value: str | None) -> bool:
    """Return True when the candidate is safe to accept as a trace ID."""

    return _validate_identifier(value, pattern=_TRACE_ID_PATTERN) is not None


def is_valid_request_id(value: str | None) -> bool:
    """Return True when the candidate is safe to accept as a request ID."""

    return _validate_identifier(value, pattern=_REQUEST_ID_PATTERN) is not None


def resolve_incoming_trace_id(headers: Mapping[str, str]) -> str | None:
    """Return the first valid inbound trace identifier."""

    normalized_headers = _normalize_headers(headers)

    trace_id = _validate_identifier(
        normalized_headers.get(TRACE_ID_HEADER),
        pattern=_TRACE_ID_PATTERN,
    )
    if trace_id is not None:
        return trace_id

    return _trace_id_from_traceparent(normalized_headers.get(TRACE_ID_ALIAS_HEADER))


def resolve_incoming_request_id(headers: Mapping[str, str]) -> str | None:
    """Return the first valid inbound request identifier."""

    normalized_headers = _normalize_headers(headers)
    for header_name in (REQUEST_ID_HEADER, REQUEST_ID_ALIAS_HEADER):
        request_id = _validate_identifier(
            normalized_headers.get(header_name),
            pattern=_REQUEST_ID_PATTERN,
        )
        if request_id is not None:
            return request_id
    return None


def build_trace_context(
    *,
    trace_id: str | None,
    request_id: str | None = None,
    caller_service: str | None = None,
    server_name: str | None = None,
    tool_name: str | None = None,
    capability_name: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> TraceContext:
    """Build a validated trace context and generate an ID when needed."""

    resolved_trace_id = _validate_identifier(trace_id, pattern=_TRACE_ID_PATTERN) or new_trace_id()
    resolved_request_id = _validate_identifier(request_id, pattern=_REQUEST_ID_PATTERN)
    return TraceContext(
        trace_id=resolved_trace_id,
        request_id=resolved_request_id,
        caller_service=_normalize_optional_text(caller_service),
        server_name=_normalize_optional_text(server_name),
        tool_name=_normalize_optional_text(tool_name),
        capability_name=_normalize_optional_text(capability_name),
        metadata=dict(metadata or {}),
    )


def build_trace_context_from_headers(
    headers: Mapping[str, str],
    *,
    caller_service: str | None = None,
    server_name: str | None = None,
    tool_name: str | None = None,
    capability_name: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> TraceContext:
    """Create a trace context from inbound headers using safe validation rules."""

    return build_trace_context(
        trace_id=resolve_incoming_trace_id(headers),
        request_id=resolve_incoming_request_id(headers),
        caller_service=caller_service,
        server_name=server_name,
        tool_name=tool_name,
        capability_name=capability_name,
        metadata=metadata,
    )


def get_trace_context() -> TraceContext | None:
    """Return the currently bound trace context for this async task."""

    return _current_trace_context.get()


def get_trace_id() -> str | None:
    """Return the currently bound trace ID, if any."""

    context = get_trace_context()
    return None if context is None else context.trace_id


def set_trace_context(context: TraceContext) -> Token[TraceContext | None]:
    """Bind a trace context to the current async task."""

    return _current_trace_context.set(context)


def reset_trace_context(token: Token[TraceContext | None]) -> None:
    """Restore the previous trace context after a scoped binding."""

    _current_trace_context.reset(token)


def clear_trace_context() -> None:
    """Explicitly clear any active trace context for this async task."""

    _current_trace_context.set(None)


@contextmanager
def trace_context_scope(context: TraceContext) -> Iterator[TraceContext]:
    """Temporarily bind a trace context for the duration of a block."""

    token = set_trace_context(context)
    try:
        yield context
    finally:
        reset_trace_context(token)


def _normalize_headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {
        str(key).strip().lower(): str(value).strip()
        for key, value in headers.items()
        if str(key).strip() and value is not None
    }


def _trace_id_from_traceparent(value: str | None) -> str | None:
    candidate = _normalize_optional_text(value)
    if candidate is None:
        return None

    match = _TRACEPARENT_PATTERN.fullmatch(candidate)
    if match is None:
        return None

    trace_id = match.group("trace_id").lower()
    if set(trace_id) == {"0"}:
        return None
    return trace_id


def _validate_identifier(value: str | None, *, pattern: re.Pattern[str]) -> str | None:
    candidate = _normalize_optional_text(value)
    if candidate is None or not candidate.isascii():
        return None
    if any(character.isspace() or ord(character) < 32 or ord(character) == 127 for character in candidate):
        return None
    if pattern.fullmatch(candidate) is None:
        return None
    return candidate


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None