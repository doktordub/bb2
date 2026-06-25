"""Trace store contracts and event constants."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
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

TERMINAL_TRACE_STATUSES = frozenset(
    {
        "completed",
        "failed",
        "cancelled",
        "skipped",
        "degraded",
    }
)
_ERROR_SEVERITIES = frozenset({"error", "critical"})
_SEVERITY_ORDER = {
    "debug": 10,
    "info": 20,
    "warning": 30,
    "error": 40,
    "critical": 50,
}


@dataclass(frozen=True, slots=True)
class TraceEvent:
    """Operational trace event recorded during orchestration."""

    trace_id: str
    session_id: str
    event_type: str
    component: str
    timestamp: datetime
    event_name: str | None = None
    status: str = "completed"
    severity: str = "info"
    event_id: str | None = None
    parent_event_id: str | None = None
    parent_trace_id: str | None = None
    session_id_hash: str | None = None
    user_id: str | None = None
    user_id_hash: str | None = None
    usecase: str | None = None
    agent_name: str | None = None
    strategy_name: str | None = None
    llm_profile: str | None = None
    provider: str | None = None
    model: str | None = None
    tool_name: str | None = None
    duration_ms: float | None = None
    error_type: str | None = None
    error_code: str | None = None
    retryable: bool | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.event_name is None:
            object.__setattr__(self, "event_name", self.event_type)
        object.__setattr__(self, "payload", dict(self.payload))

    @property
    def resolved_event_name(self) -> str:
        return self.event_name or self.event_type


@dataclass(frozen=True, slots=True)
class TraceSummary:
    """Safe trace summary for search results and read-model headers."""

    trace_id: str
    parent_trace_id: str | None = None
    session_id_hash: str | None = None
    user_id_hash: str | None = None
    usecase: str | None = None
    operation: str | None = None
    route_template: str | None = None
    status: str | None = None
    severity: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    last_event_at: datetime | None = None
    duration_ms: float | None = None
    event_count: int = 0
    error_count: int = 0
    event_name: str | None = None
    event_type: str | None = None
    agent_name: str | None = None
    strategy_name: str | None = None
    llm_profile: str | None = None
    provider: str | None = None
    model: str | None = None
    tool_name: str | None = None
    error_type: str | None = None
    error_code: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", dict(self.metadata))

    @classmethod
    def from_events(
        cls,
        *,
        trace_id: str,
        events: Sequence[TraceEvent],
    ) -> "TraceSummary":
        ordered_events = tuple(events)
        if not ordered_events:
            return cls(trace_id=trace_id)

        first_event = ordered_events[0]
        last_event = ordered_events[-1]

        return cls(
            trace_id=trace_id,
            parent_trace_id=_last_non_none(ordered_events, "parent_trace_id"),
            session_id_hash=_last_non_none(ordered_events, "session_id_hash"),
            user_id_hash=_last_non_none(ordered_events, "user_id_hash"),
            usecase=_last_non_none(ordered_events, "usecase"),
            operation=_last_payload_str(ordered_events, "operation"),
            route_template=_last_payload_str(ordered_events, "route_template"),
            status=last_event.status,
            severity=_highest_severity(ordered_events),
            started_at=first_event.timestamp,
            ended_at=(
                last_event.timestamp
                if last_event.status in TERMINAL_TRACE_STATUSES
                else None
            ),
            last_event_at=last_event.timestamp,
            duration_ms=_resolve_duration_ms(first_event, last_event),
            event_count=len(ordered_events),
            error_count=sum(1 for event in ordered_events if _is_error_event(event)),
            event_name=last_event.resolved_event_name,
            event_type=last_event.event_type,
            agent_name=_last_non_none(ordered_events, "agent_name"),
            strategy_name=_last_non_none(ordered_events, "strategy_name"),
            llm_profile=_last_non_none(ordered_events, "llm_profile"),
            provider=_last_non_none(ordered_events, "provider"),
            model=_last_non_none(ordered_events, "model"),
            tool_name=_last_non_none(ordered_events, "tool_name"),
            error_type=_last_non_none(ordered_events, "error_type"),
            error_code=_last_non_none(ordered_events, "error_code"),
            metadata=_last_payload_mapping(ordered_events, "metadata"),
        )


@dataclass(frozen=True, slots=True)
class TraceReadModel(TraceSummary):
    """Trace summary plus ordered events for one trace lookup."""

    events: tuple[TraceEvent, ...] = field(default_factory=tuple)
    found: bool = True

    def __post_init__(self) -> None:
        TraceSummary.__post_init__(self)
        object.__setattr__(self, "events", tuple(self.events))

    @classmethod
    def from_events(
        cls,
        *,
        trace_id: str,
        events: Sequence[TraceEvent],
        total_events: Sequence[TraceEvent] | None = None,
    ) -> "TraceReadModel":
        all_events = tuple(total_events) if total_events is not None else tuple(events)
        summary = TraceSummary.from_events(trace_id=trace_id, events=all_events)
        return cls.from_summary(summary, events=events, found=bool(all_events))

    @classmethod
    def from_summary(
        cls,
        summary: TraceSummary,
        *,
        events: Sequence[TraceEvent],
        found: bool = True,
    ) -> "TraceReadModel":
        return cls(
            trace_id=summary.trace_id,
            parent_trace_id=summary.parent_trace_id,
            session_id_hash=summary.session_id_hash,
            user_id_hash=summary.user_id_hash,
            usecase=summary.usecase,
            operation=summary.operation,
            route_template=summary.route_template,
            status=summary.status,
            severity=summary.severity,
            started_at=summary.started_at,
            ended_at=summary.ended_at,
            last_event_at=summary.last_event_at,
            duration_ms=summary.duration_ms,
            event_count=summary.event_count,
            error_count=summary.error_count,
            event_name=summary.event_name,
            event_type=summary.event_type,
            agent_name=summary.agent_name,
            strategy_name=summary.strategy_name,
            llm_profile=summary.llm_profile,
            provider=summary.provider,
            model=summary.model,
            tool_name=summary.tool_name,
            error_type=summary.error_type,
            error_code=summary.error_code,
            metadata=dict(summary.metadata),
            events=tuple(events),
            found=found,
        )

    @classmethod
    def not_found(cls, *, trace_id: str) -> "TraceReadModel":
        return cls(trace_id=trace_id, found=False)


@dataclass(frozen=True, slots=True)
class TraceSearchFilters:
    """Safe, bounded search filters for trace-summary queries."""

    started_after: datetime | None = None
    started_before: datetime | None = None
    status: str | None = None
    severity: str | None = None
    usecase: str | None = None
    session_id_hash: str | None = None
    user_id_hash: str | None = None
    event_name: str | None = None
    event_type: str | None = None
    agent_name: str | None = None
    strategy_name: str | None = None
    llm_profile: str | None = None
    tool_name: str | None = None
    error_type: str | None = None
    errors_only: bool = False
    limit: int = 100

    def __post_init__(self) -> None:
        if self.limit < 1:
            raise ValueError("Trace search limit must be at least 1.")

    def matches(
        self,
        *,
        summary: TraceSummary,
        events: Sequence[TraceEvent],
    ) -> bool:
        if self.started_after is not None:
            if summary.started_at is None or summary.started_at < self.started_after:
                return False

        if self.started_before is not None:
            if summary.started_at is None or summary.started_at >= self.started_before:
                return False

        if self.status is not None and summary.status != self.status:
            return False

        if self.severity is not None and summary.severity != self.severity:
            return False

        if self.usecase is not None and summary.usecase != self.usecase:
            return False

        if self.session_id_hash is not None and summary.session_id_hash != self.session_id_hash:
            return False

        if self.user_id_hash is not None and summary.user_id_hash != self.user_id_hash:
            return False

        if self.agent_name is not None and summary.agent_name != self.agent_name:
            return False

        if self.strategy_name is not None and summary.strategy_name != self.strategy_name:
            return False

        if self.llm_profile is not None and summary.llm_profile != self.llm_profile:
            return False

        if self.tool_name is not None and summary.tool_name != self.tool_name:
            return False

        if self.error_type is not None and summary.error_type != self.error_type:
            return False

        if self.errors_only and summary.error_count < 1:
            return False

        if self.event_name is not None and not any(
            event.resolved_event_name == self.event_name for event in events
        ):
            return False

        if self.event_type is not None and not any(
            event.event_type == self.event_type for event in events
        ):
            return False

        return True


class TraceStore(Protocol):
    """Operational trace persistence contract."""

    async def record_event(self, event: TraceEvent) -> None:
        ...

    async def record_events(self, events: Sequence[TraceEvent]) -> None:
        ...

    async def read_trace(
        self,
        *,
        trace_id: str,
        limit: int | None = None,
    ) -> TraceReadModel:
        ...

    async def search_traces(
        self,
        *,
        filters: TraceSearchFilters,
    ) -> list[TraceSummary]:
        ...

    async def health(self) -> dict[str, Any]:
        ...


def _last_non_none(events: Sequence[TraceEvent], attribute: str) -> Any:
    for event in reversed(events):
        value = getattr(event, attribute)
        if value is not None:
            return value
    return None


def _last_payload_str(events: Sequence[TraceEvent], key: str) -> str | None:
    for event in reversed(events):
        value = event.payload.get(key)
        if isinstance(value, str) and value.strip() != "":
            return value.strip()
    return None


def _last_payload_mapping(events: Sequence[TraceEvent], key: str) -> Mapping[str, Any]:
    for event in reversed(events):
        value = event.payload.get(key)
        if isinstance(value, Mapping):
            return {str(item_key): item_value for item_key, item_value in value.items()}
    return {}


def _resolve_duration_ms(
    first_event: TraceEvent,
    last_event: TraceEvent,
) -> float | None:
    if last_event.duration_ms is not None:
        return last_event.duration_ms
    return max((last_event.timestamp - first_event.timestamp).total_seconds() * 1000.0, 0.0)


def _highest_severity(events: Sequence[TraceEvent]) -> str | None:
    highest: str | None = None
    highest_rank = -1
    for event in events:
        rank = _SEVERITY_ORDER.get(event.severity, _SEVERITY_ORDER["info"])
        if rank > highest_rank:
            highest = event.severity
            highest_rank = rank
    return highest


def _is_error_event(event: TraceEvent) -> bool:
    return (
        event.status == "failed"
        or event.severity in _ERROR_SEVERITIES
        or event.error_type is not None
        or event.error_code is not None
        or event.resolved_event_name == ERROR_OCCURRED
    )