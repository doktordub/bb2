"""Helpers for shaping runtime trace payloads outside the main runtime loop."""

from __future__ import annotations

from collections.abc import Mapping
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
    policy_denied: bool = False,
    policy_block_summary: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "failed_strategy": failed_strategy,
        "fallback_strategy": fallback_strategy,
        "fallback_reason": reason,
        "failed_error_code": error_code,
        "retryable": retryable,
    }
    if policy_denied:
        payload["policy_denied"] = True
        payload["policy_block_summary"] = _policy_trace_summary(policy_block_summary)
    return sanitize_metadata(payload)


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


def build_failure_trace_payload(error: BaseException | None = None) -> dict[str, Any]:
    if error is None:
        return {}

    raw_metadata = getattr(error, "metadata", None)
    metadata = raw_metadata if isinstance(raw_metadata, Mapping) else {}
    source_error_code = _read_optional_text(getattr(error, "code", None)) or _read_optional_text(metadata.get("source_error_code"))
    policy_denied = bool(metadata.get("policy_denied", False))
    if not policy_denied and source_error_code is not None and source_error_code.endswith("_policy_denied"):
        policy_denied = True

    policy_block_summary = _read_optional_text(metadata.get("policy_block_summary"))
    if policy_denied and policy_block_summary is None:
        message = _read_optional_text(getattr(error, "message", None)) or _read_optional_text(str(error))
        policy_block_summary = _policy_trace_summary(message)

    payload: dict[str, Any] = {}
    if source_error_code is not None:
        payload["source_error_code"] = source_error_code
    if policy_denied:
        payload["policy_denied"] = True
        payload["policy_block_summary"] = policy_block_summary or "Blocked by policy."
    return sanitize_metadata(payload)


def _policy_trace_summary(summary: str | None) -> str:
    normalized = _read_optional_text(summary)
    if normalized is None:
        return "Blocked by policy."
    if "policy" in normalized.casefold():
        return normalized
    return f"Blocked by policy. {normalized}"


def _read_optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None