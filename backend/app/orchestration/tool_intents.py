"""Logical tool-intent normalization and safe tool result helpers."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from app.contracts.tools import ToolDefinition, ToolExecutionResult
from app.orchestration.models import sanitize_metadata

_DEFAULT_TRIGGER_PREFIX = "tool:"
_RAW_TOOL_PREFIXES = ("mcp:", "mcp/", "tool://")


@dataclass(frozen=True, slots=True)
class ToolIntent:
    """Normalized logical tool intent produced from a user request."""

    tool_name: str
    arguments: dict[str, Any]
    query: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "tool_name", _normalize_tool_name(self.tool_name))
        object.__setattr__(self, "query", _normalize_text(self.query))
        object.__setattr__(self, "arguments", dict(self.arguments))
        object.__setattr__(self, "metadata", sanitize_metadata(self.metadata))


def choose_allowed_tool_name(*tool_name_groups: Sequence[str]) -> str | None:
    for group in tool_name_groups:
        for item in group:
            try:
                return _normalize_tool_name(item)
            except (TypeError, ValueError):
                continue
    return None


def resolve_tool_intent(
    message: str,
    *,
    allowed_tool_names: Sequence[str],
    prefix: str = _DEFAULT_TRIGGER_PREFIX,
) -> ToolIntent | None:
    normalized_message = _normalize_text(message)
    normalized_prefix = _normalize_prefix(prefix)
    if not normalized_message.casefold().startswith(normalized_prefix.casefold()):
        return None

    tool_name = choose_allowed_tool_name(allowed_tool_names)
    if tool_name is None:
        return None

    query = normalized_message[len(normalized_prefix) :].strip() or normalized_message
    return ToolIntent(
        tool_name=tool_name,
        arguments=build_default_tool_arguments(tool_name, query),
        query=query,
    )


def build_default_tool_arguments(tool_name: str, query: str) -> dict[str, object]:
    normalized_name = _normalize_tool_name(tool_name)
    normalized_query = _normalize_text(query)
    if "search" in normalized_name:
        return {"query": normalized_query, "limit": 3}
    return {"text": normalized_query}


def build_tool_policy_metadata(tool_definition: ToolDefinition | None) -> dict[str, Any]:
    if tool_definition is None:
        return {"tool_known": False, "tool_enabled": True}

    metadata = dict(tool_definition.metadata)
    metadata.update(
        {
            "tool_known": True,
            "tool_enabled": tool_definition.enabled,
            "tool_supports_streaming": tool_definition.supports_streaming,
            "tool_approval_required": tool_definition.approval_required,
            "tool_safety_level": tool_definition.safety_level,
        }
    )
    return sanitize_metadata(metadata)


def tool_result_safe_text(result: ToolExecutionResult) -> str:
    if result.summary is not None and result.summary.safe_message:
        return result.summary.safe_message
    for item in result.content:
        if item.text:
            return item.text
    if result.error_detail is not None and result.error_detail.message:
        return result.error_detail.message
    return "Tool completed without a text summary."


def _normalize_tool_name(value: object) -> str:
    normalized = _normalize_text(value)
    lowered = normalized.casefold()
    if any(lowered.startswith(prefix) for prefix in _RAW_TOOL_PREFIXES):
        raise ValueError("Raw MCP tool names are not allowed here.")
    if " " in normalized:
        raise ValueError("Tool names must not contain spaces.")
    return normalized


def _normalize_text(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("Tool intent text must be a string.")
    normalized = value.strip()
    if not normalized:
        raise ValueError("Tool intent text must not be empty.")
    return normalized


def _normalize_prefix(value: object) -> str:
    normalized = _normalize_text(value)
    return normalized if normalized.endswith(":") else f"{normalized}:"