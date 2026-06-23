"""Secret-safe configuration redaction helpers."""

from app.observability.redaction import (
    NON_SENSITIVE_CONTROL_KEYS,
    REDACTED_VALUE,
    SENSITIVE_KEY_PARTS,
    Redactor,
    is_sensitive_key,
)

__all__ = (
    "NON_SENSITIVE_CONTROL_KEYS",
    "REDACTED_VALUE",
    "SENSITIVE_KEY_PARTS",
    "Redactor",
    "is_sensitive_key",
    "redact_config",
)


def redact_config(value: object) -> object:
    """Return a copy of a config structure with sensitive values redacted."""

    return Redactor(redact_secrets=True, max_chars=None).redact(value)