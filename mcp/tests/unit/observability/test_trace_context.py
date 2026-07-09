from __future__ import annotations

from app.observability.context import (
    build_trace_context,
    get_trace_context,
    new_trace_id,
    resolve_incoming_request_id,
    resolve_incoming_trace_id,
    trace_context_scope,
)


def test_new_trace_id_uses_backend_compatible_format() -> None:
    trace_id = new_trace_id()

    assert trace_id.startswith("trace_")
    assert len(trace_id) == len("trace_") + 32


def test_header_resolution_validates_values_and_supports_aliases() -> None:
    headers = {
        "x-trace-id": "bad value\n",
        "traceparent": "00-0123456789abcdef0123456789abcdef-0123456789abcdef-01",
        "x-request-id": " request-123 ",
        "x-correlation-id": "correlation-456",
    }

    assert resolve_incoming_trace_id(headers) == "0123456789abcdef0123456789abcdef"
    assert resolve_incoming_request_id(headers) == "request-123"


def test_trace_context_scope_resets_after_use() -> None:
    context = build_trace_context(trace_id="bad trace id", request_id="req-123")

    assert context.trace_id.startswith("trace_")

    with trace_context_scope(context):
        assert get_trace_context() == context

    assert get_trace_context() is None