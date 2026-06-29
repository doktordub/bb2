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

    redacted = Redactor(redact_secrets=True, max_chars=None).redact(value)
    if isinstance(redacted, dict):
        _redact_memory_paths(redacted)
    return redacted


def _redact_memory_paths(payload: dict[str, object]) -> None:
    for path in (
        ("memory", "store", "config_path"),
        ("memory", "store", "database", "path"),
        ("persistence", "memory", "memory_store", "config_path"),
        ("persistence", "memory", "memory_store", "database_path"),
        ("persistence", "memory", "config", "database_path"),
    ):
        _set_redacted_path(payload, path)


def _set_redacted_path(payload: dict[str, object], path: tuple[str, ...]) -> None:
    current: object = payload
    for segment in path[:-1]:
        if not isinstance(current, dict) or segment not in current:
            return
        current = current[segment]

    if isinstance(current, dict) and path[-1] in current:
        current[path[-1]] = REDACTED_VALUE