"""Helpers for shaping runtime trace payloads outside the main runtime loop."""

from __future__ import annotations

from typing import Any

from app.orchestration.limits import OrchestrationLimitTracker
from app.orchestration.models import OrchestrationResult, sanitize_metadata


def build_started_trace_payload(
    *,
    limits: OrchestrationLimitTracker,
    state_version: int | None,
) -> dict[str, Any]:
    return sanitize_metadata(
        {
            "limits": limits.as_dict(),
            "state_version": state_version,
        }
    )


def build_selected_trace_payload(*, strategy_source: str) -> dict[str, Any]:
    return sanitize_metadata({"strategy_source": strategy_source})


def build_fallback_trace_payload(
    *,
    failed_strategy: str,
    fallback_strategy: str,
    reason: str,
    error_code: str,
    retryable: bool,
) -> dict[str, Any]:
    return sanitize_metadata(
        {
            "failed_strategy": failed_strategy,
            "fallback_strategy": fallback_strategy,
            "fallback_reason": reason,
            "failed_error_code": error_code,
            "retryable": retryable,
        }
    )


def build_completed_trace_payload(result: OrchestrationResult) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "finish_reason": result.finish_reason,
        "tool_call_count": len(result.tool_calls),
        "memory_update_count": len(result.memory_updates),
        "fallback_used": bool(result.metadata.get("fallback_used", False)),
    }
    for key in (
        "conversation_history_enabled",
        "conversation_history_turn_count",
        "conversation_history_truncated",
        "session_summary_used",
        "current_turn_deduped",
    ):
        value = result.metadata.get(key)
        if value is not None:
            payload[key] = value
    return sanitize_metadata(payload)


def build_failure_trace_payload() -> dict[str, Any]:
    return {}