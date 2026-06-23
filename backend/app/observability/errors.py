"""Trace-safe error metadata helpers for logs and trace events."""

from __future__ import annotations

from collections.abc import Mapping
import traceback
from typing import Any

from app.observability.redaction import Redactor


def build_log_error_details(
    exc: Exception,
    *,
    redactor: Redactor,
    details: Mapping[str, Any] | None = None,
    include_stack_trace: bool,
) -> dict[str, Any]:
    """Build redacted error metadata for structured logs."""

    return _build_error_details(
        exc,
        redactor=redactor,
        details=details,
        include_stack_trace=include_stack_trace,
    )


def build_trace_error_details(
    exc: Exception,
    *,
    redactor: Redactor,
    details: Mapping[str, Any] | None = None,
    include_stack_trace: bool,
) -> dict[str, Any]:
    """Build redacted error metadata for trace-event payloads."""

    return _build_error_details(
        exc,
        redactor=redactor,
        details=details,
        include_stack_trace=include_stack_trace,
    )


def _build_error_details(
    exc: Exception,
    *,
    redactor: Redactor,
    details: Mapping[str, Any] | None,
    include_stack_trace: bool,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "error_type": type(exc).__name__,
    }

    if details:
        payload["details"] = redactor.redact(dict(details))

    if include_stack_trace:
        payload["stack_trace"] = "".join(
            traceback.format_exception(type(exc), exc, exc.__traceback__)
        )

    return payload