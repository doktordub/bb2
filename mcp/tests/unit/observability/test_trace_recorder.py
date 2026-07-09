from __future__ import annotations

from app.observability.context import TraceContext, trace_context_scope
from app.observability.tracing import InMemoryTraceRecorder
from app.security.redaction import REDACTED_VALUE, Redactor, TRUNCATED_SUFFIX


def test_trace_recorder_redacts_and_truncates_payload() -> None:
    recorder = InMemoryTraceRecorder(redactor=Redactor(max_string_length=20))

    with trace_context_scope(
        TraceContext(
            trace_id="trace_1234567890abcdef1234567890abcd",
            request_id="req-123",
            tool_name="websearch.search",
        )
    ):
        recorder.record_event(
            "mcp_tool_call_completed",
            {
                "authorization": "Bearer secret",
                "message": "x" * 50,
            },
        )

    event = recorder.events[0]

    assert event.payload["authorization"] == REDACTED_VALUE
    assert event.payload["message"].endswith(TRUNCATED_SUFFIX)
    assert event.payload["trace_id"] == "trace_1234567890abcdef1234567890abcd"
    assert event.payload["request_id"] == "req-123"
    assert event.payload["truncated"] is True


def test_trace_recorder_never_raises_on_unserializable_payloads() -> None:
    class BadRepr:
        def __repr__(self) -> str:
            raise RuntimeError("boom")

    recorder = InMemoryTraceRecorder(redactor=Redactor())
    recorder.record_event("mcp_tool_call_failed", {"bad": BadRepr()})

    assert len(recorder.events) == 1