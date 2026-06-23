from __future__ import annotations

import logging

import pytest

from app.config.view import ObservabilitySettings
from app.contracts.errors import TraceStoreError
from app.observability.tracing import TraceRecorder
from app.observability.redaction import REDACTED_VALUE, TRUNCATED_VALUE, Redactor
from app.testing.fakes.fake_trace import FakeTraceStore


def build_settings(
    *,
    trace_enabled: bool = True,
    trace_payloads_enabled: bool = True,
    trace_store_required: bool = True,
    max_trace_payload_chars: int = 12,
) -> ObservabilitySettings:
    return ObservabilitySettings(
        log_level="INFO",
        structured_logging=True,
        trace_enabled=trace_enabled,
        trace_payloads_enabled=trace_payloads_enabled,
        trace_store_required=trace_store_required,
        redact_secrets=True,
        include_stack_traces_in_logs=False,
        include_stack_traces_in_traces=False,
        max_trace_payload_chars=max_trace_payload_chars,
        slow_request_ms=5000,
        slow_llm_call_ms=30000,
        slow_tool_call_ms=10000,
        metrics_enabled=True,
    )


@pytest.mark.asyncio
async def test_trace_recorder_records_redacted_event() -> None:
    store = FakeTraceStore()
    recorder = TraceRecorder(
        store=store,
        settings=build_settings(),
        redactor=Redactor(redact_secrets=True, max_chars=12),
    )

    await recorder.record(
        trace_id="trace_123",
        session_id="session_123",
        event_type="request_received",
        component="api.health",
        payload={
            "api_key": "top-secret-key",
            "message": "abcdefghijklmnopqrstuvwxyz",
        },
    )

    assert len(store.events) == 1
    event = store.events[0]
    assert event.trace_id == "trace_123"
    assert event.session_id == "session_123"
    assert event.payload == {
        "api_key": REDACTED_VALUE,
        "message": f"abcdefghijkl{TRUNCATED_VALUE}",
    }


@pytest.mark.asyncio
async def test_trace_recorder_omits_payload_when_disabled() -> None:
    store = FakeTraceStore()
    recorder = TraceRecorder(
        store=store,
        settings=build_settings(trace_payloads_enabled=False),
        redactor=Redactor(redact_secrets=True, max_chars=4),
    )

    await recorder.record(
        trace_id="trace_123",
        session_id="session_123",
        event_type="request_received",
        component="api.health",
        payload={"message": "will be ignored"},
    )

    assert store.events[0].payload == {}


@pytest.mark.asyncio
async def test_trace_recorder_raises_when_store_is_required() -> None:
    recorder = TraceRecorder(
        store=FakeTraceStore(record_error=RuntimeError("boom")),
        settings=build_settings(trace_store_required=True),
        redactor=Redactor(redact_secrets=True, max_chars=8),
    )

    with pytest.raises(TraceStoreError, match="Trace store recording failed"):
        await recorder.record(
            trace_id="trace_123",
            session_id="session_123",
            event_type="request_received",
            component="api.health",
            payload={"message": "safe"},
        )


@pytest.mark.asyncio
async def test_trace_recorder_logs_and_continues_when_store_is_optional(
    caplog: pytest.LogCaptureFixture,
) -> None:
    recorder = TraceRecorder(
        store=FakeTraceStore(record_error=RuntimeError("boom")),
        settings=build_settings(trace_store_required=False),
        redactor=Redactor(redact_secrets=True, max_chars=8),
        logger=logging.getLogger("tests.trace_recorder"),
    )

    with caplog.at_level(logging.ERROR, logger="tests.trace_recorder"):
        await recorder.record(
            trace_id="trace_123",
            session_id="session_123",
            event_type="request_received",
            component="api.health",
            payload={"message": "safe"},
        )

    assert "Trace event persistence failed" in caplog.text


@pytest.mark.asyncio
async def test_trace_recorder_skips_when_tracing_is_disabled() -> None:
    store = FakeTraceStore()
    recorder = TraceRecorder(
        store=store,
        settings=build_settings(trace_enabled=False),
        redactor=Redactor(redact_secrets=True, max_chars=8),
    )

    await recorder.record(
        trace_id="trace_123",
        session_id="session_123",
        event_type="request_received",
        component="api.health",
        payload={"message": "safe"},
    )

    assert store.events == []