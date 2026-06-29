"""Trace-recorder helper for tests that need safe in-memory traces."""

from __future__ import annotations

from app.config.view import ObservabilitySettings
from app.observability.redaction import Redactor
from app.observability.tracing import TraceRecorder
from app.testing.fakes.fake_trace import FakeTraceStore


def build_fake_trace_recorder(
    *,
    store: FakeTraceStore | None = None,
    trace_enabled: bool = True,
    trace_payloads_enabled: bool = True,
    trace_store_required: bool = True,
) -> TraceRecorder:
    return TraceRecorder(
        store=store or FakeTraceStore(),
        settings=ObservabilitySettings(
            log_level="INFO",
            structured_logging=True,
            trace_enabled=trace_enabled,
            trace_payloads_enabled=trace_payloads_enabled,
            trace_store_required=trace_store_required,
            redact_secrets=True,
            include_stack_traces_in_logs=False,
            include_stack_traces_in_traces=False,
            max_trace_payload_chars=4000,
            slow_request_ms=2500,
            slow_llm_call_ms=15000,
            slow_tool_call_ms=5000,
            metrics_enabled=True,
        ),
        redactor=Redactor(redact_secrets=True, max_chars=None),
    )