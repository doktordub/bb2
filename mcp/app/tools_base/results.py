"""Structured result envelopes for MCP tool outputs."""

from __future__ import annotations

from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator


SECRET_LIKE_KEY_PARTS = (
    "api_key",
    "authorization",
    "bearer",
    "cookie",
    "credential",
    "jwt",
    "password",
    "secret",
    "token",
)


def _assert_safe_json(value: object, *, path: str) -> None:
    if isinstance(value, httpx.Response | httpx.Client | httpx.AsyncClient):
        raise ValueError(f"{path} must not contain raw downstream HTTP client objects.")
    if isinstance(value, dict):
        for key, item in value.items():
            normalized_key = key.lower()
            if any(part in normalized_key for part in SECRET_LIKE_KEY_PARTS):
                raise ValueError(f"{path} must not expose secret-like key {key!r}.")
            _assert_safe_json(item, path=f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _assert_safe_json(item, path=f"{path}[{index}]")
        return
    if isinstance(value, (str, int, float, bool)) or value is None:
        return
    raise ValueError(f"{path} must contain JSON-serializable values only.")


class ToolResultSummary(BaseModel):
    """Small, human-readable summary for a bounded tool result."""

    model_config = ConfigDict(extra="forbid")

    message: str
    item_count: int | None = Field(default=None, ge=0)
    truncated: bool = False


class ToolErrorEnvelope(BaseModel):
    """Structured error payload returned by MCP tools."""

    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    retryable: bool = False
    details: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_payload(self) -> "ToolErrorEnvelope":
        if not self.code.strip() or not self.message.strip():
            raise ValueError("Tool errors must have non-empty code and message values.")
        _assert_safe_json(self.details, path="errors[].details")
        return self


class ToolResultEnvelope(BaseModel):
    """Structured and bounded success or failure payload for MCP tool handlers."""

    model_config = ConfigDict(extra="forbid")

    ok: bool = True
    tool_name: str
    summary: ToolResultSummary
    data: dict[str, Any] = Field(default_factory=dict)
    errors: list[ToolErrorEnvelope] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_payload(self) -> "ToolResultEnvelope":
        if not self.tool_name.strip():
            raise ValueError("Tool results must declare a non-empty tool_name.")
        if self.ok and self.errors:
            raise ValueError("Successful tool results must not include error envelopes.")
        if not self.ok and not self.errors:
            raise ValueError("Failed tool results must include at least one error envelope.")
        _assert_safe_json(self.data, path="data")
        _assert_safe_json(self.meta, path="meta")
        return self