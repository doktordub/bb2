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


def test_artifact_events_encode_with_artifact_ids() -> None:
    settings = ApiSseSettings(
        heartbeat_seconds=15,
        send_trace_id_event=False,
        send_metadata_events=True,
    )

    started = encode_session_stream_event(
        SessionStreamEvent(
            event_type="artifact.started",
            trace_id="trace-123",
            session_id="session-123",
            data={
                "artifact_id": "chart-1",
                "type": "chart",
                "chart_type": "bar",
                "renderer": "echarts",
                "spec_version": "1.0",
                "data_mode": "inline",
            },
        ),
        settings=settings,
    )
    completed = encode_session_stream_event(
        SessionStreamEvent(
            event_type="artifact.completed",
            trace_id="trace-123",
            session_id="session-123",
            data={
                "artifact": {
                    "artifact_id": "chart-1",
                    "type": "chart",
                    "chart_type": "bar",
                    "title": "Revenue",
                    "description": "Monthly revenue.",
                    "renderer": "echarts",
                    "spec_version": "1.0",
                    "data_mode": "inline",
                    "data": [{"month": "Jan", "revenue": 1200}],
                    "data_ref": None,
                    "encoding": {"x": "month", "y": ["revenue"]},
                    "options": {},
                    "warnings": [],
                    "metadata": {"source": "workflow_state"},
                }
            },
        ),
        settings=settings,
    )

    assert _decode_frame(started) == {
        "event": "artifact.started",
        "id": "chart-1",
        "data": {
            "artifact_id": "chart-1",
            "type": "chart",
            "chart_type": "bar",
            "renderer": "echarts",
            "spec_version": "1.0",
            "data_mode": "inline",
        },
    }
    assert _decode_frame(completed) == {
        "event": "artifact.completed",
        "id": "chart-1",
        "data": {
            "artifact": {
                "artifact_id": "chart-1",
                "type": "chart",
                "chart_type": "bar",
                "title": "Revenue",
                "description": "Monthly revenue.",
                "renderer": "echarts",
                "spec_version": "1.0",
                "data_mode": "inline",
                "data": [{"month": "Jan", "revenue": 1200}],
                "data_ref": None,
                "encoding": {"x": "month", "y": ["revenue"]},
                "options": {},
                "warnings": [],
                "metadata": {"source": "workflow_state"},
            }
        },
    }


def test_reference_artifact_events_rewrite_public_data_ref() -> None:
    settings = ApiSseSettings(
        heartbeat_seconds=15,
        send_trace_id_event=False,
        send_metadata_events=True,
    )

    completed = encode_session_stream_event(
        SessionStreamEvent(
            event_type="artifact.completed",
            trace_id="trace-123",
            session_id="session-123",
            data={
                "artifact": {
                    "artifact_id": "chart-2",
                    "type": "chart",
                    "chart_type": "line",
                    "title": "Revenue Trend",
                    "description": "Monthly revenue trend.",
                    "renderer": "echarts",
                    "spec_version": "1.0",
                    "data_mode": "reference",
                    "data": None,
                    "data_ref": "artifact://session-123/chart-2",
                    "encoding": {"x": "month", "y": ["revenue"]},
                    "options": {},
                    "warnings": [],
                    "metadata": {"source": "workflow_state"},
                }
            },
        ),
        settings=settings,
        artifact_retrieval_endpoint="/artifacts/{artifact_id}",
    )

    assert _decode_frame(completed)["data"]["artifact"]["data_ref"] == "/artifacts/chart-2"


def test_response_delta_encoding_preserves_significant_whitespace() -> None:
    settings = ApiSseSettings(
        heartbeat_seconds=15,
        send_trace_id_event=False,
        send_metadata_events=True,
    )

    leading_space = encode_session_stream_event(
        SessionStreamEvent(
            event_type="response.delta",
            trace_id="trace-123",
            session_id="session-123",
            data={"delta": " world"},
        ),
        settings=settings,
    )
    paragraph_break = encode_session_stream_event(
        SessionStreamEvent(
            event_type="response.delta",
            trace_id="trace-123",
            session_id="session-123",
            data={"delta": "\n\n"},
        ),
        settings=settings,
    )

    assert _decode_payload(leading_space) == {"text": " world"}
    assert _decode_payload(paragraph_break) == {"text": "\n\n"}


def _decode_payload(frame: str | None) -> dict[str, object]:
    assert frame is not None
    line = next(item for item in frame.splitlines() if item.startswith("data: "))
    return json.loads(line.removeprefix("data: "))


def _decode_frame(frame: str | None) -> dict[str, object]:
    assert frame is not None
    parsed: dict[str, object] = {}
    for line in frame.splitlines():
        if line.startswith("id: "):
            parsed["id"] = line.removeprefix("id: ")
        elif line.startswith("event: "):
            parsed["event"] = line.removeprefix("event: ")
        elif line.startswith("data: "):
            parsed["data"] = json.loads(line.removeprefix("data: "))
    return parsed