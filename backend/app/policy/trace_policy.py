"""Typed trace exposure policy helpers and evaluators."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from app.contracts.context import OrchestrationContext
from app.contracts.policy import (
    PolicyActor,
    PolicyDecision,
    PolicyEvaluationContext,
    PolicyRequest,
)
from app.policy.settings import PolicyProfileSettings

_RAW_DENIED_CATEGORIES = frozenset(
    {
        "raw_prompt",
        "raw_completion",
        "raw_tool_payload",
        "raw_memory_record",
        "raw_workflow_state",
        "provider_response",
        "mcp_payload",
        "stack_trace",
        "hidden_scratchpad",
    }
)
_STACK_TRACE_FIELDS = frozenset({"stack_trace", "traceback"})


def build_trace_policy_request(
    *,
    trace_id: str | None,
    session_id: str | None,
    user_id: str | None,
    usecase_name: str | None,
    event_name: str,
    component: str,
    payload: Mapping[str, Any] | None,
    payload_category: str = "safe_summary",
) -> PolicyRequest:
    """Build a normalized policy request for one trace payload emission."""

    actor = PolicyActor(
        actor_type="user" if user_id else "anonymous",
        actor_id=user_id,
        user_id=user_id,
        session_id=session_id,
    )
    field_names = _field_names(payload)
    metadata = {
        "event_name": event_name,
        "payload_category": payload_category,
        "field_names": field_names,
    }
    evaluation = PolicyEvaluationContext(
        trace_id=trace_id,
        usecase_name=usecase_name,
        exposure_level="summary",
        tags=("trace", component),
        metadata=dict(metadata),
    )
    return PolicyRequest(
        action="trace.emit",
        component=component,
        resource=event_name,
        scope={
            "user_id": user_id,
            "session_id": session_id,
            "usecase_name": usecase_name,
        },
        metadata=metadata,
        actor=actor,
        evaluation=evaluation,
    )


async def evaluate_trace_request(
    request: PolicyRequest,
    context: OrchestrationContext,
    profile: PolicyProfileSettings,
) -> PolicyDecision | None:
    """Evaluate whether a trace payload category can be emitted."""

    _ = context
    payload_category = _optional_text(request.metadata.get("payload_category")) or "safe_summary"
    field_names = _read_field_names(request.metadata.get("field_names"))

    if not profile.trace.allow_trace:
        return PolicyDecision.deny(
            reason="Trace emission is disabled by policy.",
            reason_code="policy.trace.disabled",
            metadata={"resource": request.resource, "payload_category": payload_category},
        )
    if payload_category in _RAW_DENIED_CATEGORIES and not profile.trace.expose_raw_payloads:
        return PolicyDecision.deny(
            reason="Raw trace payloads are denied by policy.",
            reason_code="policy.trace.raw_payload_denied",
            metadata={"resource": request.resource, "payload_category": payload_category},
        )
    if payload_category == "raw_prompt" and not profile.llm.allow_prompt_trace:
        return PolicyDecision.deny(
            reason="Prompt trace payloads are denied by policy.",
            reason_code="policy.trace.prompt_denied",
            metadata={"resource": request.resource, "payload_category": payload_category},
        )
    if payload_category == "raw_completion" and not profile.llm.allow_completion_trace:
        return PolicyDecision.deny(
            reason="Completion trace payloads are denied by policy.",
            reason_code="policy.trace.completion_denied",
            metadata={"resource": request.resource, "payload_category": payload_category},
        )
    if _STACK_TRACE_FIELDS.intersection(field_names):
        return PolicyDecision.deny(
            reason="Stack traces are denied by policy.",
            reason_code="policy.trace.stack_trace_denied",
            metadata={"resource": request.resource, "payload_category": payload_category},
        )

    return PolicyDecision.allow(
        reason_code="policy.trace.allowed",
        metadata={"resource": request.resource, "payload_category": payload_category},
    )


def infer_trace_payload_category(payload: Mapping[str, Any] | None) -> str:
    """Infer a conservative trace payload category from a candidate payload."""

    if not payload:
        return "safe_summary"
    field_names = set(_field_names(payload))
    if {"prompt", "prompts", "messages", "system_prompt"}.intersection(field_names):
        return "raw_prompt"
    if {"completion", "content", "response_text", "provider_response"}.intersection(field_names):
        return "raw_completion"
    if {"tool_arguments", "tool_result", "tool_payload"}.intersection(field_names):
        return "raw_tool_payload"
    if {"memory_record", "memory_text", "memory_results"}.intersection(field_names):
        return "raw_memory_record"
    if {"workflow_state", "state_document"}.intersection(field_names):
        return "raw_workflow_state"
    if _STACK_TRACE_FIELDS.intersection(field_names):
        return "stack_trace"
    return "safe_summary"


def _field_names(payload: Mapping[str, Any] | None) -> tuple[str, ...]:
    if not payload:
        return ()
    return tuple(sorted(str(key) for key in payload.keys()))


def _read_field_names(value: object) -> tuple[str, ...]:
    if not isinstance(value, Iterable) or isinstance(value, str | bytes | bytearray):
        return ()
    result: list[str] = []
    for item in value:
        text = _optional_text(item)
        if text is not None and text not in result:
            result.append(text)
    return tuple(result)


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None