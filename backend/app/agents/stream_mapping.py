"""Map gateway stream events into safe structured agent events."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.agents.errors import AgentErrorDetail
from app.agents.models import AgentRunResult, AgentStreamEvent
from app.contracts.llm import LLMErrorDetail, LLMStreamEvent
from app.orchestration.models import sanitize_metadata


def map_llm_stream_event(
    agent_name: str,
    event: LLMStreamEvent,
    *,
    metadata: Mapping[str, Any] | None = None,
) -> AgentStreamEvent | None:
    """Translate one LLM gateway event into a structured agent stream event."""

    merged_metadata = _merge_metadata(event=event, metadata=metadata)
    if event.type == "started":
        return AgentStreamEvent(
            type="agent.llm.started",
            agent_name=agent_name,
            metadata=merged_metadata,
        )
    if event.type == "delta":
        return AgentStreamEvent(
            type="agent.llm.delta",
            agent_name=agent_name,
            text=event.text,
            metadata=merged_metadata,
        )
    if event.type == "completed":
        return AgentStreamEvent(
            type="agent.llm.completed",
            agent_name=agent_name,
            metadata=merged_metadata,
        )
    if event.type == "error":
        return build_failed_event(
            agent_name,
            error=_agent_error_from_llm_error(event.error),
            metadata=merged_metadata,
        )
    return None


def build_started_event(
    agent_name: str,
    *,
    metadata: Mapping[str, Any] | None = None,
) -> AgentStreamEvent:
    """Return a safe agent-started event."""

    return AgentStreamEvent.started(agent_name=agent_name, metadata=dict(metadata or {}))


def build_completed_event(
    agent_name: str,
    *,
    result: AgentRunResult,
    metadata: Mapping[str, Any] | None = None,
) -> AgentStreamEvent:
    """Return a safe agent-completed event."""

    return AgentStreamEvent.completed(
        agent_name=agent_name,
        result=result,
        metadata=dict(metadata or {}),
    )


def build_failed_event(
    agent_name: str,
    *,
    error: AgentErrorDetail,
    metadata: Mapping[str, Any] | None = None,
) -> AgentStreamEvent:
    """Return a safe agent-failed event."""

    return AgentStreamEvent.failed(
        agent_name=agent_name,
        error=error,
        metadata=dict(metadata or {}),
    )


def build_cancelled_event(
    agent_name: str,
    *,
    metadata: Mapping[str, Any] | None = None,
) -> AgentStreamEvent:
    """Return a safe agent-cancelled event."""

    return AgentStreamEvent.cancelled(
        agent_name=agent_name,
        metadata=dict(metadata or {}),
    )


def _merge_metadata(
    *,
    event: LLMStreamEvent,
    metadata: Mapping[str, Any] | None,
) -> dict[str, Any]:
    merged: dict[str, Any] = {
        "profile": event.profile,
        "provider": event.provider,
        "model": event.model,
        "finish_reason": event.finish_reason,
    }
    if event.usage is not None:
        merged["usage_counts"] = {
            "input": event.usage.input_tokens,
            "output": event.usage.output_tokens,
            "total": event.usage.total_tokens,
        }
    merged.update(event.metadata)
    if metadata is not None:
        merged.update(metadata)
    return sanitize_metadata(merged)


def _agent_error_from_llm_error(error: LLMErrorDetail | None) -> AgentErrorDetail:
    if error is None:
        return AgentErrorDetail(
            code="agent_llm_error",
            message="The agent LLM request failed.",
            retryable=True,
        )
    return AgentErrorDetail(
        code=error.code or error.type or "agent_llm_error",
        message=error.message or "The agent LLM request failed.",
        retryable=True if error.retryable is None else bool(error.retryable),
        metadata=error.metadata,
    )


__all__ = [
    "build_cancelled_event",
    "build_completed_event",
    "build_failed_event",
    "build_started_event",
    "map_llm_stream_event",
]