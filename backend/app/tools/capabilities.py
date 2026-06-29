"""Safe tooling capability summaries for foundation responses."""

from __future__ import annotations

from typing import Any

from app.contracts.tools import ToolCapabilitiesResult

_SAFETY_LEVELS = (
    "read_only",
    "write",
    "destructive",
    "external_side_effect",
)


def build_tool_capabilities_payload(
    capabilities: ToolCapabilitiesResult,
    *,
    include_tool_names: bool = False,
) -> dict[str, Any]:
    """Build a frontend-safe tooling summary from the public gateway result."""

    safety_levels = {level: 0 for level in _SAFETY_LEVELS}
    approval_required_tools = 0
    available_tools: list[str] = []

    for tool in capabilities.available_logical_tools:
        safety_levels[tool.safety_level] = safety_levels.get(tool.safety_level, 0) + 1
        if tool.approval_required:
            approval_required_tools += 1
        if include_tool_names:
            available_tools.append(tool.name)

    payload: dict[str, Any] = {
        "enabled": capabilities.enabled,
        "configured": capabilities.mcp_configured,
        "streaming_supported": capabilities.streaming_supported,
        "total_tools": len(capabilities.available_logical_tools),
        "approval_required_tools": approval_required_tools,
        "safety_levels": safety_levels,
    }

    transport = _read_optional_str(capabilities.metadata.get("transport"))
    if transport is not None:
        payload["transport"] = transport

    discovery_enabled = capabilities.metadata.get("discovery_enabled")
    if isinstance(discovery_enabled, bool):
        payload["discovery_enabled"] = discovery_enabled

    if include_tool_names:
        payload["available_tools"] = sorted(available_tools)

    return payload


def _read_optional_str(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None