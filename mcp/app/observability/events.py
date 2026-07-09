"""Stable observability event names for the MCP server."""

from __future__ import annotations


MCP_STARTUP_STARTED = "mcp_startup_started"
MCP_CONFIG_LOADED = "mcp_config_loaded"
MCP_CONFIG_INVALID = "mcp_config_invalid"
MCP_TOOL_DISCOVERY_STARTED = "mcp_tool_discovery_started"
MCP_TOOL_MANIFEST_LOADED = "mcp_tool_manifest_loaded"
MCP_TOOL_CONFIG_LOADED = "mcp_tool_config_loaded"
MCP_TOOL_REGISTERED = "mcp_tool_registered"
MCP_TOOL_REGISTRATION_FAILED = "mcp_tool_registration_failed"
MCP_TOOL_CALL_STARTED = "mcp_tool_call_started"
MCP_TOOL_CALL_COMPLETED = "mcp_tool_call_completed"
MCP_TOOL_CALL_FAILED = "mcp_tool_call_failed"
MCP_TOOL_CALL_TIMEOUT = "mcp_tool_call_timeout"
MCP_TOOL_CALL_CANCELLED = "mcp_tool_call_cancelled"
MCP_HEALTH_CHECKED = "mcp_health_checked"
MCP_SHUTDOWN_STARTED = "mcp_shutdown_started"
MCP_SHUTDOWN_COMPLETED = "mcp_shutdown_completed"

EVENT_NAMES = (
    MCP_STARTUP_STARTED,
    MCP_CONFIG_LOADED,
    MCP_CONFIG_INVALID,
    MCP_TOOL_DISCOVERY_STARTED,
    MCP_TOOL_MANIFEST_LOADED,
    MCP_TOOL_CONFIG_LOADED,
    MCP_TOOL_REGISTERED,
    MCP_TOOL_REGISTRATION_FAILED,
    MCP_TOOL_CALL_STARTED,
    MCP_TOOL_CALL_COMPLETED,
    MCP_TOOL_CALL_FAILED,
    MCP_TOOL_CALL_TIMEOUT,
    MCP_TOOL_CALL_CANCELLED,
    MCP_HEALTH_CHECKED,
    MCP_SHUTDOWN_STARTED,
    MCP_SHUTDOWN_COMPLETED,
)


def all_event_names() -> tuple[str, ...]:
    """Return the complete supported event catalog."""

    return EVENT_NAMES