"""Redaction helpers for logs, health output, and diagnostics."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any


REDACTED_VALUE = "***REDACTED***"
TRUNCATED_SUFFIX = "...<truncated>"
DEFAULT_SECRET_LIKE_KEYS = {
    "api_key",
    "authorization",
    "bearer",
    "client_secret",
    "cookie",
    "credential",
    "jwt",
    "password",
    "refresh_token",
    "secret",
    "token",
}


@dataclass(frozen=True, slots=True)
class Redactor:
    """Best-effort recursive sanitizer that never raises."""

    max_string_length: int = 2000
    redacted_value: str = REDACTED_VALUE
    secret_like_keys: frozenset[str] = field(
        default_factory=lambda: frozenset(DEFAULT_SECRET_LIKE_KEYS)
    )

    def sanitize(self, value: Any) -> Any:
        try:
            return self._sanitize(value, seen=set())
        except Exception:
            return "<redaction-error>"

    def _sanitize(self, value: Any, seen: set[int]) -> Any:
        if value is None or isinstance(value, (bool, int, float)):
            return value
        if isinstance(value, str):
            return self._truncate_string(value)
        if isinstance(value, (bytes, bytearray)):
            return f"<bytes:{len(value)}>"

        value_id = id(value)
        if value_id in seen:
            return "<recursive-reference>"

        if isinstance(value, Mapping):
            seen.add(value_id)
            return {
                self._safe_key(key): self.redacted_value
                if self._is_secret_like_key(key)
                else self._sanitize(item, seen)
                for key, item in value.items()
            }

        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            seen.add(value_id)
            return [self._sanitize(item, seen) for item in value]

        if hasattr(value, "model_dump"):
            try:
                return self._sanitize(value.model_dump(mode="python"), seen)
            except Exception:
                return self._safe_repr(value)

        if hasattr(value, "__dict__"):
            seen.add(value_id)
            attributes = vars(value)
            if not attributes:
                return self._safe_repr(value)
            return self._sanitize(attributes, seen)

        return self._safe_repr(value)

    def _is_secret_like_key(self, key: object) -> bool:
        try:
            normalized = str(key).strip().lower()
        except Exception:
            return False
        return any(secret_key in normalized for secret_key in self.secret_like_keys)

    def _safe_key(self, key: object) -> str:
        try:
            return str(key)
        except Exception:
            return "<unserializable-key>"

    def _safe_repr(self, value: object) -> str:
        try:
            return self._truncate_string(repr(value))
        except Exception:
            return f"<unrepresentable:{type(value).__name__}>"

    def _truncate_string(self, value: str) -> str:
        if len(value) <= self.max_string_length:
            return value
        cutoff = max(self.max_string_length - len(TRUNCATED_SUFFIX), 0)
        return value[:cutoff] + TRUNCATED_SUFFIX