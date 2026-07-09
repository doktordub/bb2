"""Detection of secret-like MCP tool arguments before plugin execution."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import re
from typing import Any

from app.errors import ToolInputValidationError


SECRET_LIKE_KEY_PARTS = frozenset(
    {
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
)
BEARER_TOKEN_PATTERN = re.compile(r"^bearer\s+[A-Za-z0-9._~+/=-]{12,}$", re.IGNORECASE)
JWT_LIKE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}$")


def detect_secret_like_arguments(value: Any, *, path: str = "arguments") -> list[str]:
    """Return paths that appear to contain secret-like keys or values."""

    findings: list[str] = []
    _scan_value(value, path=path, findings=findings)
    return findings


def assert_no_secret_like_arguments(value: Any, *, tool_name: str | None = None) -> None:
    """Reject tool arguments that appear to contain credentials or bearer material."""

    findings = detect_secret_like_arguments(value)
    if findings:
        prefix = "Tool arguments"
        if tool_name is not None:
            prefix = f"Tool {tool_name!r} arguments"
        raise ToolInputValidationError(
            f"{prefix} must not include secret-like keys or credential values."
        )


def _scan_value(value: Any, *, path: str, findings: list[str]) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key)
            nested_path = f"{path}.{key_text}"
            if _is_secret_like_key(key_text):
                findings.append(nested_path)
            _scan_value(item, path=nested_path, findings=findings)
        return

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            _scan_value(item, path=f"{path}[{index}]", findings=findings)
        return

    if isinstance(value, str) and _is_secret_like_value(value):
        findings.append(path)


def _is_secret_like_key(value: str) -> bool:
    normalized = value.strip().lower()
    return any(part in normalized for part in SECRET_LIKE_KEY_PARTS)


def _is_secret_like_value(value: str) -> bool:
    candidate = value.strip()
    if len(candidate) < 18:
        return False
    return bool(BEARER_TOKEN_PATTERN.fullmatch(candidate) or JWT_LIKE_PATTERN.fullmatch(candidate))