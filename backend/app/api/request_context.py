"""Shared API request-context models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ApiRequestContext:
    """API-level request context passed into SessionService."""

    trace_id: str
    request_id: str
    user_id: str
    user_id_hash: str | None
    client_host: str | None
    user_agent: str | None
    path: str
    method: str
    headers_safe: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
