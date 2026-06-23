"""Trace ID helpers shared across runtime observability code."""

from __future__ import annotations

import re
from collections.abc import Mapping
from uuid import uuid4

from app.observability.models import TRACE_ID_ALIAS_HEADER, TRACE_ID_HEADER

_TRACE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{8,128}$")
_INBOUND_TRACE_ID_HEADERS = (TRACE_ID_HEADER, TRACE_ID_ALIAS_HEADER)


def new_trace_id() -> str:
    """Return a new backend-generated trace ID."""

    return f"trace_{uuid4().hex}"


def is_valid_trace_id(value: str | None) -> bool:
    """Return True when the candidate is safe to accept as a trace ID."""

    candidate = _normalize_trace_id(value)
    return bool(candidate and _TRACE_ID_PATTERN.fullmatch(candidate))


def resolve_incoming_trace_id(headers: Mapping[str, str]) -> str | None:
    """Return the first valid inbound trace ID using configured header precedence."""

    for header_name in _INBOUND_TRACE_ID_HEADERS:
        candidate = _normalize_trace_id(headers.get(header_name))
        if candidate and _TRACE_ID_PATTERN.fullmatch(candidate):
            return candidate
    return None


def _normalize_trace_id(value: str | None) -> str | None:
    if value is None:
        return None

    candidate = value.strip()
    if not candidate or not candidate.isascii():
        return None

    if any(character.isspace() or ord(character) < 32 or ord(character) == 127 for character in candidate):
        return None

    return candidate