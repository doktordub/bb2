"""Session boundary models used by API routes and service implementations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from app.contracts.state import WorkflowSessionDeleteResult, WorkflowSessionListResult, WorkflowSessionSummary

SessionStreamEventType = Literal[
    "response.started",
    "response.delta",
    "response.metadata",
    "artifact.started",
    "artifact.completed",
    "artifact.failed",
    "response.completed",
    "response.error",
    "heartbeat",
]


@dataclass(frozen=True, slots=True)
class SessionRequestContext:
    """Session-level request context independent of the HTTP framework."""

    trace_id: str
    request_id: str
    user_id: str
    user_id_hash: str | None
    client_host: str | None
    user_agent: str | None
    path: str | None
    method: str | None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SessionChatRequest:
    """Session-owned chat request DTO."""

    message: str
    session_id: str | None = None
    usecase: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


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
    artifacts: list[dict[str, Any]] = field(default_factory=list)
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
class SessionHistoryMessage:
    """Safe session history projection for one conversation message."""

    role: str
    content: str
    created_at: str | None = None
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SessionHistoryResult:
    """Safe session history projection returned by session services."""

    trace_id: str
    session_id: str
    messages: list[SessionHistoryMessage]
    truncated: bool
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SessionSummary:
    """Safe session summary projected by the session-service boundary."""

    session_id: str
    usecase: str | None
    status: str
    created_at: str | None = None
    updated_at: str | None = None
    last_activity_at: str | None = None
    reset_count: int = 0
    message_count: int = 0

    @classmethod
    def from_workflow_summary(cls, summary: WorkflowSessionSummary) -> SessionSummary:
        return cls(
            session_id=summary.session_id,
            usecase=summary.usecase,
            status=summary.status,
            created_at=summary.created_at.isoformat() if summary.created_at is not None else None,
            updated_at=summary.updated_at.isoformat() if summary.updated_at is not None else None,
            last_activity_at=(
                summary.last_activity_at.isoformat() if summary.last_activity_at is not None else None
            ),
            reset_count=summary.reset_count,
            message_count=summary.message_count,
        )


@dataclass(frozen=True, slots=True)
class SessionListResult:
    """Bounded session admin projection returned by session services."""

    trace_id: str
    sessions: list[SessionSummary]
    limit: int
    has_more: bool
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_workflow_result(
        cls,
        result: WorkflowSessionListResult,
        *,
        trace_id: str,
    ) -> SessionListResult:
        return cls(
            trace_id=trace_id,
            sessions=[SessionSummary.from_workflow_summary(item) for item in result.sessions],
            limit=result.limit,
            has_more=result.has_more,
            metadata={
                "limit": result.limit,
                "returned_count": len(result.sessions),
                "has_more": result.has_more,
            },
        )


@dataclass(frozen=True, slots=True)
class SessionDeleteResult:
    """Delete result returned by the session-service boundary."""

    session_id: str
    trace_id: str
    deleted: bool
    message: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_workflow_result(
        cls,
        result: WorkflowSessionDeleteResult,
        *,
        trace_id: str,
    ) -> SessionDeleteResult:
        return cls(
            session_id=result.session_id,
            trace_id=trace_id,
            deleted=result.deleted,
            message=(
                "Session workflow state was deleted."
                if result.deleted
                else "The requested session was not found."
            ),
            metadata={"deleted": result.deleted},
        )


@dataclass(frozen=True, slots=True)
class SessionStreamEvent:
    """Stable session-service event used by SSE route mapping."""

    event_type: SessionStreamEventType
    trace_id: str
    session_id: str
    data: dict[str, Any] = field(default_factory=dict)
    sequence_no: int | None = None
