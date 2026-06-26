"""Session boundary models used by API routes and service implementations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

SessionStreamEventType = Literal[
    "response.started",
    "response.delta",
    "response.metadata",
    "response.completed",
    "response.error",
    "heartbeat",
]


@dataclass(frozen=True, slots=True)
class SessionChatResult:
    """Stable session-service result for one chat request."""

    answer: str
    session_id: str
    trace_id: str
    agent_name: str | None = None
    strategy_name: str | None = None
    llm_profile: str | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    memory_updates: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SessionResetResult:
    """Stable session-service result for one session reset."""

    session_id: str
    trace_id: str
    reset: bool
    message: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SessionStreamEvent:
    """Stable session-service event used by SSE route mapping."""

    event_type: SessionStreamEventType
    trace_id: str
    session_id: str
    data: dict[str, Any] = field(default_factory=dict)
