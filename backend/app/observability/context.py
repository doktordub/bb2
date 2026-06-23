"""Async-safe trace context helpers."""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class TraceContext:
    """Request-scoped observability context available to logs and trace events."""

    trace_id: str
    session_id: str | None = None
    user_id: str | None = None
    usecase: str | None = None
    request_id: str | None = None
    component: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


_current_trace_context: ContextVar[TraceContext | None] = ContextVar(
    "current_trace_context",
    default=None,
)


def get_trace_context() -> TraceContext | None:
    """Return the active trace context for the current async task."""

    return _current_trace_context.get()


def get_trace_id() -> str | None:
    """Return the active trace ID for the current async task."""

    context = get_trace_context()
    return None if context is None else context.trace_id


def set_trace_context(context: TraceContext) -> Token[TraceContext | None]:
    """Activate a trace context and return the token required to restore the prior state."""

    return _current_trace_context.set(context)


def bind_trace_context(
    *,
    trace_id: str,
    session_id: str | None = None,
    user_id: str | None = None,
    usecase: str | None = None,
    request_id: str | None = None,
    component: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Token[TraceContext | None]:
    """Build and activate a trace context from keyword arguments."""

    return set_trace_context(
        TraceContext(
            trace_id=trace_id,
            session_id=session_id,
            user_id=user_id,
            usecase=usecase,
            request_id=request_id,
            component=component,
            metadata=dict(metadata or {}),
        )
    )


def reset_trace_context(token: Token[TraceContext | None]) -> None:
    """Restore the previous trace context after a scoped activation."""

    _current_trace_context.reset(token)