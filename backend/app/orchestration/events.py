"""Safe orchestration stream events."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from app.orchestration.errors import OrchestrationError, OrchestrationErrorDetail, error_detail_from_exception
from app.orchestration.models import OrchestrationResult, sanitize_metadata

OrchestrationEventType = Literal[
    "orchestration.started",
    "strategy.selected",
    "response.delta",
    "response.completed",
    "orchestration.completed",
    "orchestration.error",
    "orchestration.cancelled",
]


@dataclass(frozen=True, slots=True)
class OrchestrationStreamEvent:
    """Normalized orchestration stream event safe for session-level mapping."""

    type: OrchestrationEventType
    trace_id: str
    session_id: str
    text: str | None = None
    result: OrchestrationResult | None = None
    error: OrchestrationErrorDetail | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "type", _normalize_identifier(self.type, field_name="type"))
        object.__setattr__(self, "trace_id", _normalize_identifier(self.trace_id, field_name="trace_id"))
        object.__setattr__(self, "session_id", _normalize_identifier(self.session_id, field_name="session_id"))
        object.__setattr__(self, "text", _normalize_optional_delta_text(self.text))
        object.__setattr__(self, "metadata", sanitize_metadata(self.metadata))

    @classmethod
    def started(
        cls,
        *,
        trace_id: str,
        session_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> "OrchestrationStreamEvent":
        return cls(
            type="orchestration.started",
            trace_id=trace_id,
            session_id=session_id,
            metadata=dict(metadata or {}),
        )

    @classmethod
    def strategy_selected(
        cls,
        *,
        trace_id: str,
        session_id: str,
        strategy_name: str,
        usecase: str | None,
        agent_name: str | None = None,
        llm_profile: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "OrchestrationStreamEvent":
        payload = dict(metadata or {})
        payload["strategy_name"] = strategy_name
        if usecase is not None:
            payload["usecase"] = usecase
        if agent_name is not None:
            payload["agent_name"] = agent_name
        if llm_profile is not None:
            payload["llm_profile"] = llm_profile
        return cls(
            type="strategy.selected",
            trace_id=trace_id,
            session_id=session_id,
            metadata=payload,
        )

    @classmethod
    def response_delta(
        cls,
        *,
        trace_id: str,
        session_id: str,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> "OrchestrationStreamEvent":
        return cls(
            type="response.delta",
            trace_id=trace_id,
            session_id=session_id,
            text=text,
            metadata=dict(metadata or {}),
        )

    @classmethod
    def response_completed(
        cls,
        *,
        trace_id: str,
        session_id: str,
        finish_reason: str,
        duration_ms: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "OrchestrationStreamEvent":
        payload = dict(metadata or {})
        payload["finish_reason"] = finish_reason
        if duration_ms is not None:
            payload["duration_ms"] = duration_ms
        return cls(
            type="response.completed",
            trace_id=trace_id,
            session_id=session_id,
            metadata=payload,
        )

    @classmethod
    def completed(
        cls,
        *,
        trace_id: str,
        session_id: str,
        result: OrchestrationResult,
        metadata: dict[str, Any] | None = None,
    ) -> "OrchestrationStreamEvent":
        return cls(
            type="orchestration.completed",
            trace_id=trace_id,
            session_id=session_id,
            result=result,
            metadata=dict(metadata or {}),
        )

    @classmethod
    def error_event(
        cls,
        *,
        trace_id: str,
        session_id: str,
        error: OrchestrationErrorDetail | OrchestrationError | BaseException,
        metadata: dict[str, Any] | None = None,
    ) -> "OrchestrationStreamEvent":
        detail = error.to_detail() if isinstance(error, OrchestrationError) else None
        if detail is None:
            detail = error if isinstance(error, OrchestrationErrorDetail) else error_detail_from_exception(error)
        return cls(
            type="orchestration.error",
            trace_id=trace_id,
            session_id=session_id,
            error=detail,
            metadata=dict(metadata or {}),
        )

    @classmethod
    def cancelled(
        cls,
        *,
        trace_id: str,
        session_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> "OrchestrationStreamEvent":
        return cls(
            type="orchestration.cancelled",
            trace_id=trace_id,
            session_id=session_id,
            metadata=dict(metadata or {}),
        )


def _normalize_identifier(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"Invalid {field_name}.")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"Invalid {field_name}.")
    return normalized


def _normalize_optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _normalize_optional_delta_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    if value == "":
        return None
    return value