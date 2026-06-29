"""Shared redaction helpers for runtime telemetry and config summaries."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, is_dataclass
from datetime import date, datetime, time
from enum import Enum
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel

SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "auth",
    "authorization",
    "bearer",
    "client_secret",
    "connection_string",
    "cookie",
    "credential",
    "jwt",
    "key",
    "password",
    "refresh_token",
    "secret",
    "token",
)
NON_SENSITIVE_CONTROL_KEYS = frozenset(
    {
        "auth_header",
        "redact_secrets",
        "expose_secret_values",
        "max_input_tokens",
        "max_output_tokens",
        "max_total_tokens",
        "timezone_metadata_key",
    }
)
REDACTED_VALUE = "***REDACTED***"
TRUNCATED_VALUE = "<truncated>"
UNAVAILABLE_VALUE = "<unavailable>"


def is_sensitive_key(
    key: object,
    *,
    sensitive_key_parts: tuple[str, ...] = SENSITIVE_KEY_PARTS,
    non_sensitive_control_keys: frozenset[str] = NON_SENSITIVE_CONTROL_KEYS,
) -> bool:
    """Return True when a field name should be treated as sensitive."""

    normalized = str(key).strip().lower()
    if not normalized:
        return False

    if normalized in non_sensitive_control_keys:
        return False

    return any(part in normalized for part in sensitive_key_parts)


@dataclass(frozen=True, slots=True)
class Redactor:
    """Recursive, never-raise redactor shared by logs, traces, and config summaries."""

    redact_secrets: bool = True
    max_chars: int | None = None
    sensitive_key_parts: tuple[str, ...] = SENSITIVE_KEY_PARTS
    non_sensitive_control_keys: frozenset[str] = NON_SENSITIVE_CONTROL_KEYS

    def redact(self, value: object) -> object:
        """Return a redacted, JSON-safe copy of the input value."""

        try:
            return self._redact_value(value, sensitive_context=False)
        except Exception:
            return UNAVAILABLE_VALUE

    def _redact_value(self, value: object, *, sensitive_context: bool) -> object:
        if isinstance(value, Mapping):
            return self._redact_mapping(value, sensitive_context=sensitive_context)

        if isinstance(value, list):
            return [self._redact_child(item, sensitive_context=sensitive_context) for item in value]

        if isinstance(value, tuple):
            return tuple(self._redact_child(item, sensitive_context=sensitive_context) for item in value)

        if isinstance(value, set):
            return [
                self._redact_child(item, sensitive_context=sensitive_context)
                for item in sorted(value, key=self._sort_key)
            ]

        if is_dataclass(value) and not isinstance(value, type):
            return self._redact_child(asdict(value), sensitive_context=sensitive_context)

        if isinstance(value, BaseModel):
            return self._redact_child(value.model_dump(mode="json"), sensitive_context=sensitive_context)

        if sensitive_context and value is not None:
            return REDACTED_VALUE

        return self._serialize_scalar(value)

    def _redact_mapping(self, value: Mapping[object, object], *, sensitive_context: bool) -> dict[str, object] | str:
        try:
            items = list(value.items())
        except Exception:
            return UNAVAILABLE_VALUE

        result: dict[str, object] = {}
        for key, item in items:
            key_text = str(key)
            normalized_key = key_text.strip().lower()
            child_sensitive = sensitive_context or (
                self.redact_secrets
                and normalized_key not in {"auth", "oauth"}
                and is_sensitive_key(
                    key_text,
                    sensitive_key_parts=self.sensitive_key_parts,
                    non_sensitive_control_keys=self.non_sensitive_control_keys,
                )
            )
            result[key_text] = self._redact_child(item, sensitive_context=child_sensitive)

        return result

    def _redact_child(self, value: object, *, sensitive_context: bool) -> object:
        try:
            return self._redact_value(value, sensitive_context=sensitive_context)
        except Exception:
            return UNAVAILABLE_VALUE

    def _serialize_scalar(self, value: object) -> object:
        if value is None or isinstance(value, bool | int | float):
            return value

        if isinstance(value, str):
            return self._truncate_string(value)

        if isinstance(value, datetime | date | time):
            return value.isoformat()

        if isinstance(value, Path):
            return value.as_posix()

        if isinstance(value, UUID):
            return str(value)

        if isinstance(value, Enum):
            return self._serialize_scalar(value.value)

        return f"<{type(value).__name__}>"

    def _truncate_string(self, value: str) -> str:
        if self.max_chars is None or self.max_chars < 0 or len(value) <= self.max_chars:
            return value

        return f"{value[: self.max_chars]}{TRUNCATED_VALUE}"

    @staticmethod
    def _sort_key(value: object) -> str:
        return f"{type(value).__name__}:{value!s}"