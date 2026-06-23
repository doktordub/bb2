"""Normalized agent and orchestration result contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

StreamEventType = Literal[
    "message_started",
    "content_delta",
    "tool_call_summary",
    "agent_summary",
    "trace_summary",
    "message_completed",
    "error",
]


@dataclass(slots=True)
class AgentResult:
    """Normalized output returned by an agent plugin."""

    answer: str
    agent_name: str
    confidence: float | None = None
    llm_profile: str | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    memory_updates: list[dict[str, Any]] = field(default_factory=list)
    handoff_to: str | None = None
    citations: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class OrchestrationResult:
    """Normalized output returned by orchestration to the API/session layer."""

    answer: str
    session_id: str
    trace_id: str | None = None
    agent_name: str | None = None
    strategy_name: str | None = None
    llm_profile: str | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    memory_updates: list[dict[str, Any]] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class StreamEvent:
    """Normalized streaming event shape for future SSE support."""

    event_type: StreamEventType
    data: dict[str, Any] = field(default_factory=dict)