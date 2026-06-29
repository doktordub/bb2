"""Safe tooling and MCP health summaries for foundation responses."""

from __future__ import annotations

from typing import Any

from app.contracts.health import (
    HEALTH_DEGRADED,
    HEALTH_NOT_CHECKED,
    HEALTH_NOT_CONFIGURED,
    HEALTH_OK,
    HealthStatus,
)
from app.contracts.tools import ToolHealthResult
from app.observability.health import HealthCheckResult


def build_tooling_health_check(
    health: ToolHealthResult,
    *,
    expose_provider_details: bool,
) -> HealthCheckResult:
    """Map a tool-gateway health result into the shared foundation health shape."""

    metadata = dict(health.metadata)
    details: dict[str, Any] = {
        "configured": health.mcp_configured,
        "tooling_enabled": health.tooling_enabled,
        "adapter_reachable": health.mcp_status == "ok",
        "mcp_status": health.mcp_status,
        "discovery_enabled": bool(metadata.get("discovery_enabled", False)),
        "discovery_state": _read_optional_str(metadata.get("discovery_state"))
        or "not_checked",
        "tools_configured": health.tools_configured,
        "tools_discovered": health.tools_discovered,
        "tools_enabled": health.tools_enabled,
        "registry_status": health.registry_status,
    }

    if health.error is not None:
        details["error_present"] = True

    if expose_provider_details:
        transport = _read_optional_str(metadata.get("transport"))
        if transport is not None:
            details["transport"] = transport
        server_name = _read_optional_str(metadata.get("server_name"))
        if server_name is not None:
            details["server_name"] = server_name
        auth_mode = _read_optional_str(metadata.get("auth_mode"))
        if auth_mode is not None:
            details["identity_mode"] = auth_mode

    return HealthCheckResult(
        status=_normalize_tool_health_status(health.status),
        details=details,
    )


def _normalize_tool_health_status(status: str) -> HealthStatus:
    if status == "ok":
        return HEALTH_OK
    if status in {"degraded", "error"}:
        return HEALTH_DEGRADED
    if status in {"disabled", "not_configured"}:
        return HEALTH_NOT_CONFIGURED
    return HEALTH_NOT_CHECKED


def _read_optional_str(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None