"""Trace store contracts and event constants."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

REQUEST_RECEIVED = "request_received"
CONTEXT_CREATED = "context_created"
WORKFLOW_STATE_LOADED = "workflow_state_loaded"
MEMORY_SEARCH_STARTED = "memory_search_started"
MEMORY_SEARCH_COMPLETED = "memory_search_completed"
LLM_CALL_STARTED = "llm_call_started"
LLM_CALL_COMPLETED = "llm_call_completed"
LLM_CALL_FAILED = "llm_call_failed"
LLM_FALLBACK_SELECTED = "llm_fallback_selected"
STRATEGY_SELECTED = "strategy_selected"
AGENT_SELECTED = "agent_selected"
AGENT_STARTED = "agent_started"
AGENT_COMPLETED = "agent_completed"
TOOL_CALL_STARTED = "tool_call_started"
TOOL_CALL_COMPLETED = "tool_call_completed"
TOOL_CALL_FAILED = "tool_call_failed"
WORKFLOW_STATE_SAVED = "workflow_state_saved"
RESPONSE_RETURNED = "response_returned"
ERROR_OCCURRED = "error_occurred"
MINIMUM_TRACE_EVENT_TYPES = (
    REQUEST_RECEIVED,
    CONTEXT_CREATED,
    WORKFLOW_STATE_LOADED,
    MEMORY_SEARCH_STARTED,
    MEMORY_SEARCH_COMPLETED,
    LLM_CALL_STARTED,
    LLM_CALL_COMPLETED,
    LLM_CALL_FAILED,
    LLM_FALLBACK_SELECTED,
    STRATEGY_SELECTED,
    AGENT_SELECTED,
    AGENT_STARTED,
    AGENT_COMPLETED,
    TOOL_CALL_STARTED,
    TOOL_CALL_COMPLETED,
    TOOL_CALL_FAILED,
    WORKFLOW_STATE_SAVED,
    RESPONSE_RETURNED,
    ERROR_OCCURRED,
)


@dataclass(slots=True)
class TraceEvent:
    """Operational trace event recorded during orchestration."""

    trace_id: str
    session_id: str
    event_type: str
    component: str
    timestamp: datetime
    user_id: str | None = None
    usecase: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


class TraceStore(Protocol):
    """Operational trace persistence contract."""

    async def record_event(self, event: TraceEvent) -> None:
        ...

    async def health(self) -> dict[str, Any]:
        ...