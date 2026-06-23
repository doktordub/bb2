import json

from app.observability.errors import build_log_error_details, build_trace_error_details
from app.observability.redaction import REDACTED_VALUE, Redactor


def test_error_observability_hides_secrets_and_stack_traces_when_disabled() -> None:
    redactor = Redactor(redact_secrets=True, max_chars=128)

    try:
        raise RuntimeError("token should stay hidden")
    except RuntimeError as exc:
        log_details = build_log_error_details(
            exc,
            redactor=redactor,
            details={
                "api_key": "super-secret-key",
                "note": "safe",
            },
            include_stack_trace=False,
        )
        trace_details = build_trace_error_details(
            exc,
            redactor=redactor,
            details={
                "authorization": "Bearer secret-token",
            },
            include_stack_trace=False,
        )

    assert log_details["error_type"] == "RuntimeError"
    assert log_details["details"] == {
        "api_key": REDACTED_VALUE,
        "note": "safe",
    }
    assert trace_details["details"] == {
        "authorization": REDACTED_VALUE,
    }
    assert "stack_trace" not in log_details
    assert "stack_trace" not in trace_details

    serialized = json.dumps({"log": log_details, "trace": trace_details})
    assert "super-secret-key" not in serialized
    assert "secret-token" not in serialized
    assert "token should stay hidden" not in serialized