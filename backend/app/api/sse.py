"""Helpers for mapping session stream events onto the public SSE contract."""

from __future__ import annotations

import json
from typing import Any

from app.api.versioning import API_SCHEMA_VERSION
from app.contracts.config import ConfigurationView
from app.config.view import ApiSseSettings
from app.contracts.policy import PolicyService
from app.policy.context import build_readonly_policy_context
from app.policy.stream_policy import build_stream_policy_request, infer_stream_payload_category
from app.session.mapping import project_public_artifact, resolve_public_artifact_retrieval_endpoint
from app.session.models import SessionStreamEvent

_SAFE_METADATA_KEYS = frozenset(
    {
        "agent_name",
        "strategy_name",
        "llm_profile",
        "usecase",
        "tool_call_count",
        "memory_result_count",
    }
)


def encode_sse(event: str, data: dict[str, Any], event_id: str | None = None) -> str:
    """Encode one SSE event payload."""

    lines: list[str] = []
    if event_id:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    lines.append(f"data: {payload}")
    return "\n".join(lines) + "\n\n"


def encode_session_stream_event(
    event: SessionStreamEvent,
    *,
    settings: ApiSseSettings,
    artifact_retrieval_endpoint: str | None = None,
) -> str | None:
    """Normalize one session stream event into a public SSE frame."""

    if event.event_type == "response.started":
        return encode_sse(
            event.event_type,
            _started_payload(event=event, include_trace_id=settings.send_trace_id_event),
        )

    if event.event_type == "response.delta":
        text = _as_delta_text(event.data.get("text") or event.data.get("delta"))
        if text is None:
            return None
        return encode_sse(event.event_type, {"text": text})

    if event.event_type == "response.metadata":
        if not settings.send_metadata_events:
            return None
        metadata_payload = {
            key: value
            for key, value in event.data.items()
            if key in _SAFE_METADATA_KEYS and value is not None
        }
        return encode_sse(event.event_type, metadata_payload)

    if event.event_type == "artifact.started":
        payload = _artifact_started_payload(event)
        if payload is None:
            return None
        return encode_sse(
            event.event_type,
            payload,
            event_id=_artifact_event_id(event),
        )

    if event.event_type == "artifact.completed":
        payload = _artifact_completed_payload(
            event,
            artifact_retrieval_endpoint=artifact_retrieval_endpoint,
        )
        if payload is None:
            return None
        return encode_sse(
            event.event_type,
            payload,
            event_id=_artifact_event_id(event),
        )

    if event.event_type == "artifact.failed":
        payload = _artifact_failed_payload(event)
        if payload is None:
            return None
        return encode_sse(
            event.event_type,
            payload,
            event_id=_artifact_event_id(event),
        )

    if event.event_type == "response.completed":
        completed_payload: dict[str, Any] = {
            "session_id": event.session_id,
            "finish_reason": _as_text(event.data.get("finish_reason")) or "stop",
        }
        duration_ms = event.data.get("duration_ms")
        if isinstance(duration_ms, int | float):
            completed_payload["duration_ms"] = duration_ms
        if settings.send_trace_id_event:
            completed_payload["trace_id"] = event.trace_id
        return encode_sse(event.event_type, completed_payload)

    if event.event_type == "response.error":
        return encode_sse(
            event.event_type,
            _error_payload(event=event),
        )

    if event.event_type == "heartbeat":
        heartbeat_payload: dict[str, Any] = {}
        if settings.send_trace_id_event:
            heartbeat_payload["trace_id"] = event.trace_id
        return encode_sse(event.event_type, heartbeat_payload)

    return None


def encode_stream_error(
    *,
    trace_id: str,
    session_id: str | None,
    code: str,
    message: str,
    retryable: bool,
) -> str:
    """Encode a stable public stream error frame."""

    data: dict[str, Any] = {
        "trace_id": trace_id,
        "error": {
            "code": code,
            "message": message,
            "retryable": retryable,
        },
    }
    if session_id:
        data["session_id"] = session_id
    return encode_sse("response.error", data)


def encode_heartbeat(*, trace_id: str, settings: ApiSseSettings) -> str:
    """Encode a heartbeat frame using the configured trace visibility rule."""

    payload: dict[str, Any] = {}
    if settings.send_trace_id_event:
        payload["trace_id"] = trace_id
    return encode_sse("heartbeat", payload)


def encode_completed(
    *,
    trace_id: str,
    session_id: str,
    duration_ms: int,
    settings: ApiSseSettings,
) -> str:
    """Encode a fallback completed frame when the service stream stops cleanly."""

    payload: dict[str, Any] = {
        "session_id": session_id,
        "finish_reason": "stop",
        "duration_ms": duration_ms,
    }
    if settings.send_trace_id_event:
        payload["trace_id"] = trace_id
    return encode_sse("response.completed", payload)


async def encode_session_stream_event_for_api(
    event: SessionStreamEvent,
    *,
    settings: ApiSseSettings,
    policy_service: PolicyService,
    config: ConfigurationView,
    user_id: str | None = None,
    usecase_name: str | None = None,
) -> str | None:
    """Apply stream policy and then encode one session stream event for the public SSE contract."""

    payload_category = infer_stream_payload_category(event)
    request = build_stream_policy_request(event=event, payload_category=payload_category)
    context = build_readonly_policy_context(
        policy_service=policy_service,
        config=config,
        trace_id=event.trace_id,
        user_id=user_id,
        session_id=event.session_id,
        usecase_name=usecase_name,
    )
    decision = await policy_service.evaluate(request, context)
    if decision.is_denied:
        return None
    return encode_session_stream_event(
        event,
        settings=settings,
        artifact_retrieval_endpoint=resolve_public_artifact_retrieval_endpoint(config),
    )


def _started_payload(
    *,
    event: SessionStreamEvent,
    include_trace_id: bool,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": API_SCHEMA_VERSION,
        "session_id": event.session_id,
    }
    if include_trace_id:
        payload["trace_id"] = event.trace_id
    return payload


def _error_payload(event: SessionStreamEvent) -> dict[str, Any]:
    error = event.data.get("error")
    if isinstance(error, dict):
        code = _as_text(error.get("code")) or "backend_error"
        message = _as_text(error.get("message")) or "The request failed."
        retryable = bool(error.get("retryable", False))
    else:
        code = _as_text(event.data.get("code")) or "backend_error"
        message = _as_text(event.data.get("message")) or "The request failed."
        retryable = bool(event.data.get("retryable", False))

    payload: dict[str, Any] = {
        "trace_id": event.trace_id,
        "session_id": event.session_id,
        "error": {
            "code": code,
            "message": message,
            "retryable": retryable,
        },
    }
    return payload


def _as_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized:
        return None
    return normalized


def _as_delta_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    if value == "":
        return None
    return value


def _artifact_event_id(event: SessionStreamEvent) -> str | None:
    artifact_id = _as_text(event.data.get("artifact_id"))
    if artifact_id is not None:
        return artifact_id
    artifact = event.data.get("artifact")
    if isinstance(artifact, dict):
        return _as_text(artifact.get("artifact_id"))
    return None


def _artifact_started_payload(event: SessionStreamEvent) -> dict[str, Any] | None:
    artifact_id = _as_text(event.data.get("artifact_id"))
    chart_type = _as_text(event.data.get("chart_type"))
    renderer = _as_text(event.data.get("renderer"))
    spec_version = _as_text(event.data.get("spec_version"))
    data_mode = _as_text(event.data.get("data_mode"))
    artifact_type = _as_text(event.data.get("type")) or "chart"
    if artifact_id is None or chart_type is None or renderer is None or spec_version is None or data_mode is None:
        return None
    return {
        "artifact_id": artifact_id,
        "type": artifact_type,
        "chart_type": chart_type,
        "renderer": renderer,
        "spec_version": spec_version,
        "data_mode": data_mode,
    }


def _artifact_completed_payload(
    event: SessionStreamEvent,
    *,
    artifact_retrieval_endpoint: str | None,
) -> dict[str, Any] | None:
    artifact = event.data.get("artifact")
    if not isinstance(artifact, dict):
        return None
    projected_artifact = project_public_artifact(
        artifact,
        artifact_retrieval_endpoint=artifact_retrieval_endpoint,
    )
    if projected_artifact is None:
        return None
    return {"artifact": projected_artifact}


def _artifact_failed_payload(event: SessionStreamEvent) -> dict[str, Any] | None:
    artifact_id = _artifact_event_id(event)
    if artifact_id is None:
        return None
    error = event.data.get("error")
    if isinstance(error, dict):
        message = _as_text(error.get("message")) or "The chart artifact could not be delivered."
        code = _as_text(error.get("code")) or "artifact_delivery_failed"
    else:
        message = _as_text(event.data.get("message")) or "The chart artifact could not be delivered."
        code = _as_text(event.data.get("code")) or "artifact_delivery_failed"
    return {
        "artifact_id": artifact_id,
        "error": {
            "code": code,
            "message": message,
        },
    }