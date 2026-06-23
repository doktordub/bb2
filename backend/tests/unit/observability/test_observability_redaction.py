from app.observability.redaction import REDACTED_VALUE, TRUNCATED_VALUE, Redactor


class _OpaqueValue:
    def __repr__(self) -> str:
        return "api_key=should-not-appear"


def test_runtime_redactor_redacts_nested_sensitive_values() -> None:
    redactor = Redactor(redact_secrets=True, max_chars=128)

    redacted = redactor.redact(
        {
            "provider": "local",
            "credentials": {
                "api_key": "top-secret-key",
                "default_headers": {
                    "Authorization": "Bearer secret-value",
                },
            },
            "events": [
                {
                    "tool_token": "nested-secret",
                }
            ],
        }
    )

    assert redacted == {
        "provider": "local",
        "credentials": {
            "api_key": REDACTED_VALUE,
            "default_headers": {
                "Authorization": REDACTED_VALUE,
            },
        },
        "events": [
            {
                "tool_token": REDACTED_VALUE,
            }
        ],
    }


def test_runtime_redactor_truncates_long_strings() -> None:
    redactor = Redactor(redact_secrets=True, max_chars=12)

    redacted = redactor.redact({"note": "abcdefghijklmnopqrstuvwxyz"})

    assert redacted == {"note": f"abcdefghijkl{TRUNCATED_VALUE}"}


def test_runtime_redactor_serializes_unsupported_objects_safely() -> None:
    redactor = Redactor(redact_secrets=True, max_chars=128)

    redacted = redactor.redact({"payload": _OpaqueValue()})

    assert redacted == {"payload": "<_OpaqueValue>"}