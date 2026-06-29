"""Typed stream exposure policy helpers and evaluators."""

from __future__ import annotations

from collections.abc import Iterable

from app.contracts.context import OrchestrationContext
from app.contracts.policy import (
    PolicyActor,
    PolicyDecision,
    PolicyEvaluationContext,
    PolicyRequest,
)
from app.session.models import SessionStreamEvent
from app.policy.settings import PolicyProfileSettings

_ALLOWED_EVENT_TYPES = frozenset(
    {
        "response.started",
        "response.delta",
        "response.metadata",
        "response.completed",
        "response.error",
        "heartbeat",
    }
)
_INTERNAL_ONLY_EVENT_TYPES = frozenset({"strategy.started", "strategy.completed", "agent.started", "agent.completed"})
_RAW_DENIED_CATEGORIES = frozenset(
    {
        "raw_provider_chunk",
        "raw_prompt",
        "raw_tool_payload",
        "raw_memory_record",
        "raw_workflow_state",
        "stack_trace",
        "hidden_scratchpad",
    }
)


def build_stream_policy_request(
    *,
    event: SessionStreamEvent,
    payload_category: str,
) -> PolicyRequest:
    """Build a normalized policy request for one SSE event emission."""

    metadata = {
        "event_type": event.event_type,
        "payload_category": payload_category,
        "field_names": tuple(sorted(str(key) for key in event.data.keys())),
    }
    actor = PolicyActor(actor_type="anonymous", session_id=event.session_id)
    evaluation = PolicyEvaluationContext(
        trace_id=event.trace_id,
        exposure_level="summary",
        tags=("stream", event.event_type),
        metadata=dict(metadata),
    )
    return PolicyRequest(
        action="stream.emit",
        component="api.sse",
        resource=event.event_type,
        scope={"session_id": event.session_id},
        metadata=metadata,
        actor=actor,
        evaluation=evaluation,
    )


async def evaluate_stream_request(
    request: PolicyRequest,
    context: OrchestrationContext,
    profile: PolicyProfileSettings,
) -> PolicyDecision | None:
    """Evaluate whether a stream event payload is safe to emit."""

    _ = context
    event_type = _optional_text(request.resource) or _optional_text(request.metadata.get("event_type"))
    payload_category = _optional_text(request.metadata.get("payload_category")) or "safe_summary"
    field_names = _read_field_names(request.metadata.get("field_names"))

    if not profile.stream.allow_stream_events:
        return PolicyDecision.deny(
            reason="Stream events are disabled by policy.",
            reason_code="policy.stream.disabled",
            metadata={"resource": event_type, "payload_category": payload_category},
        )
    if event_type is None or event_type not in _ALLOWED_EVENT_TYPES:
        return PolicyDecision.deny(
            reason="Stream event type is not allowed by policy.",
            reason_code="policy.stream.event_denied",
            metadata={"resource": event_type, "payload_category": payload_category},
        )
    if event_type in _INTERNAL_ONLY_EVENT_TYPES and not profile.stream.expose_internal_events:
        return PolicyDecision.deny(
            reason="Internal stream events are denied by policy.",
            reason_code="policy.stream.internal_event_denied",
            metadata={"resource": event_type, "payload_category": payload_category},
        )
    if payload_category in _RAW_DENIED_CATEGORIES:
        return PolicyDecision.deny(
            reason="Raw stream payloads are denied by policy.",
            reason_code="policy.stream.raw_payload_denied",
            metadata={"resource": event_type, "payload_category": payload_category},
        )
    if event_type == "response.delta" and payload_category == "raw_provider_chunk" and not profile.stream.expose_raw_deltas:
        return PolicyDecision.deny(
            reason="Raw stream deltas are denied by policy.",
            reason_code="policy.stream.raw_delta_denied",
            metadata={"resource": event_type, "payload_category": payload_category},
        )
    if "stack_trace" in field_names or "traceback" in field_names:
        return PolicyDecision.deny(
            reason="Stack traces are denied in stream payloads.",
            reason_code="policy.stream.stack_trace_denied",
            metadata={"resource": event_type, "payload_category": payload_category},
        )

    return PolicyDecision.allow(
        reason_code="policy.stream.allowed",
        metadata={"resource": event_type, "payload_category": payload_category},
    )


def infer_stream_payload_category(event: SessionStreamEvent) -> str:
    """Infer a conservative SSE payload category from a normalized stream event."""

    field_names = set(str(key) for key in event.data.keys())
    if event.event_type == "response.delta" and "provider_chunk" in field_names:
        return "raw_provider_chunk"
    if {"prompt", "messages", "system_prompt"}.intersection(field_names):
        return "raw_prompt"
    if {"tool_arguments", "tool_result", "tool_payload"}.intersection(field_names):
        return "raw_tool_payload"
    if {"memory_record", "memory_results", "memory_text"}.intersection(field_names):
        return "raw_memory_record"
    if {"workflow_state", "state_document"}.intersection(field_names):
        return "raw_workflow_state"
    if {"stack_trace", "traceback"}.intersection(field_names):
        return "stack_trace"
    return "safe_summary"


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