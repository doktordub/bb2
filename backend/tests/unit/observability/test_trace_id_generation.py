import re

from app.observability.ids import is_valid_trace_id, new_trace_id, resolve_incoming_trace_id


def test_new_trace_id_uses_expected_backend_format() -> None:
    trace_id = new_trace_id()

    assert re.fullmatch(r"trace_[0-9a-f]{32}", trace_id)


def test_resolve_incoming_trace_id_prefers_x_trace_id() -> None:
    resolved = resolve_incoming_trace_id(
        {
            "x-trace-id": "trace-primary-123",
            "x-request-id": "trace-alias-456",
        }
    )

    assert resolved == "trace-primary-123"


def test_resolve_incoming_trace_id_uses_alias_when_primary_is_invalid() -> None:
    resolved = resolve_incoming_trace_id(
        {
            "x-trace-id": "Bearer secret token",
            "x-request-id": "trace-alias-456",
        }
    )

    assert resolved == "trace-alias-456"


def test_is_valid_trace_id_rejects_unsafe_values() -> None:
    assert is_valid_trace_id("trace.valid-1234")
    assert not is_valid_trace_id("bad value with spaces")
    assert not is_valid_trace_id("trace_☃")
    assert not is_valid_trace_id("short")
    assert not is_valid_trace_id(None)