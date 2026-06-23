"""Shared observability models and constants."""

from typing import Any, Literal

from pydantic import BaseModel, Field

TRACE_ID_HEADER = "x-trace-id"
TRACE_ID_ALIAS_HEADER = "x-request-id"
ErrorCode = Literal[
    "CONFIG_LOAD_ERROR",
    "VALIDATION_ERROR",
    "NOT_FOUND",
    "INTERNAL_ERROR",
]


class ApiErrorModel(BaseModel):
    """Stable API error payload."""

    code: ErrorCode
    message: str
    trace_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class ApiErrorEnvelope(BaseModel):
    """Wrapper used by all error responses."""

    error: ApiErrorModel