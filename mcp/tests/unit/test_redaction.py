from app.security.redaction import REDACTED_VALUE, TRUNCATED_SUFFIX, Redactor


class BrokenRepresentation:
    def __repr__(self) -> str:
        raise RuntimeError("boom")


def test_redactor_redacts_nested_values_and_truncates_strings() -> None:
    redactor = Redactor(max_string_length=12)

    sanitized = redactor.sanitize(
        {
            "token": "top-secret-token",
            "nested": [{"password": "unsafe-password"}, "0123456789abcdef"],
        }
    )

    assert sanitized["token"] == REDACTED_VALUE
    assert sanitized["nested"][0]["password"] == REDACTED_VALUE
    assert sanitized["nested"][1].endswith(TRUNCATED_SUFFIX)


def test_redactor_never_raises_for_unrepresentable_values() -> None:
    redactor = Redactor()

    sanitized = redactor.sanitize({"value": BrokenRepresentation()})

    assert sanitized["value"] == "<unrepresentable:BrokenRepresentation>"