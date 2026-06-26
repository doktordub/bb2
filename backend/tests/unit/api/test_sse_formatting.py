from __future__ import annotations

import json

from app.api.sse import (
    encode_completed,
    encode_heartbeat,
    encode_session_stream_event,
    encode_stream_error,
)
from app.config.view import ApiSseSettings
from app.session.models import SessionStreamEvent


def test_session_stream_event_encoding_respects_public_contract() -> None:
    settings = ApiSseSettings(
        heartbeat_seconds=15,
        send_trace_id_event=False,
        send_metadata_events=True,
    )

    started = encode_session_stream_event(
        SessionStreamEvent(
            event_type="response.started",
            trace_id="trace-123",
            session_id="session-123",
        ),
        settings=settings,
    )
    delta = encode_session_stream_event(
        SessionStreamEvent(
            event_type="response.delta",
            trace_id="trace-123",
            session_id="session-123",
            data={"delta": "hello"},
        ),
        settings=settings,
    )
    metadata = encode_session_stream_event(
        SessionStreamEvent(
            event_type="response.metadata",
            trace_id="trace-123",
            session_id="session-123",
            data={
                "agent_name": "support_agent",
                "strategy_name": "direct_agent",
                "llm_profile": "local_reasoning",
                "unsafe": "drop-me",
            },
        ),
        settings=settings,
    )
    completed = encode_completed(
        trace_id="trace-123",
        session_id="session-123",
        duration_ms=42,
        settings=settings,
    )
    heartbeat = encode_heartbeat(trace_id="trace-123", settings=settings)
    error = encode_stream_error(
        trace_id="trace-123",
        session_id="session-123",
        code="backend_error",
        message="The request failed.",
        retryable=True,
    )

    assert _decode_payload(started) == {
        "schema_version": "1.0",
        "session_id": "session-123",
    }
    assert _decode_payload(delta) == {"text": "hello"}
    assert _decode_payload(metadata) == {
        "agent_name": "support_agent",
        "strategy_name": "direct_agent",
        "llm_profile": "local_reasoning",
    }
    assert _decode_payload(completed) == {
        "session_id": "session-123",
        "finish_reason": "stop",
        "duration_ms": 42,
    }
    assert _decode_payload(heartbeat) == {}
    assert _decode_payload(error) == {
        "trace_id": "trace-123",
        "session_id": "session-123",
        "error": {
            "code": "backend_error",
            "message": "The request failed.",
            "retryable": True,
        },
    }


def test_metadata_event_can_be_suppressed() -> None:
    settings = ApiSseSettings(
        heartbeat_seconds=15,
        send_trace_id_event=True,
        send_metadata_events=False,
    )

    encoded = encode_session_stream_event(
        SessionStreamEvent(
            event_type="response.metadata",
            trace_id="trace-123",
            session_id="session-123",
            data={"agent_name": "support_agent"},
        ),
        settings=settings,
    )

    assert encoded is None


def _decode_payload(frame: str | None) -> dict[str, object]:
    assert frame is not None
    line = next(item for item in frame.splitlines() if item.startswith("data: "))
    return json.loads(line.removeprefix("data: "))