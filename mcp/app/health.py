"""Safe internal health reporting for the MCP server."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastmcp import FastMCP

from app.config import redacted_settings_summary
from app.context import ToolRuntimeContext
from app.observability.events import MCP_HEALTH_CHECKED
from app.observability.logging import emit_observability_event
from app.registry import ToolRegistry
from app.schemas import AppSettings
from app.tools_base.decorators import observe_tool_call


DEFAULT_TOOL_COUNTS = {
    "loaded": 0,
    "enabled": 0,
    "disabled": 0,
    "failed": 0,
    "unhealthy": 0,
}

DEFAULT_SERVICE_READINESS = {
    "logging": "unknown",
    "redaction": "unknown",
    "credentials": "unknown",
    "http_client": "unknown",
    "rate_limiter": "unknown",
    "clock": "unknown",
    "metrics": "unknown",
    "tracing": "unknown",
    "auth": "unknown",
    "outbound_auth": "unknown",
}


def build_health_payload(
    settings: AppSettings,
    service_readiness: Mapping[str, str] | None = None,
    tool_counts: Mapping[str, int] | None = None,
    registry: ToolRegistry | None = None,
    *,
    config_loaded: bool = True,
) -> dict[str, Any]:
    counts = dict(DEFAULT_TOOL_COUNTS)
    if registry is not None:
        counts.update(registry.health_summary().as_counts())
    if tool_counts:
        counts.update(tool_counts)

    readiness = dict(DEFAULT_SERVICE_READINESS)
    if service_readiness:
        readiness.update(service_readiness)

    checks = {
        "process_liveness": "ok",
        "config_loaded": "ok" if config_loaded else "unhealthy",
        "registry_loaded": "ok" if registry is not None else "unhealthy",
        "required_tools_loaded": _required_tools_loaded(registry),
        "optional_failed_tools": _optional_failed_tools(registry),
        "security_mode_valid": "ok" if _security_mode_valid(settings) else "unhealthy",
        "websearch_local_readiness": _websearch_local_readiness(settings, registry),
    }
    status = _overall_health_status(checks)
    ready = all(
        checks[check_name] == "ok"
        for check_name in (
            "process_liveness",
            "config_loaded",
            "registry_loaded",
            "required_tools_loaded",
            "security_mode_valid",
        )
    ) and checks["websearch_local_readiness"] != "unhealthy"

    return {
        "status": status,
        "ready": ready,
        "server": {
            "name": settings.server.name,
            "version": settings.server.version,
            "environment": settings.server.environment,
        },
        "tools": counts,
        "security": {
            "inbound_auth_enabled": settings.security.inbound_auth.enabled,
            "inbound_auth_mode": settings.security.inbound_auth.mode,
            "tls_mode": settings.security.tls.mode,
            "outbound_oauth_clients_configured": len(settings.security.outbound_auth.oauth_clients),
        },
        "config": redacted_settings_summary(settings),
        "services": readiness,
        "checks": checks,
    }


def register_health_tool(
    server: FastMCP,
    context: ToolRuntimeContext,
    service_readiness: Mapping[str, str] | None = None,
    tool_counts: Mapping[str, int] | None = None,
    registry: ToolRegistry | None = None,
) -> None:
    @server.tool(name="mcp.health")
    @observe_tool_call(context, "mcp.health", capability_name="mcp.health")
    def health() -> dict[str, Any]:
        payload = build_health_payload(
            context.app_config,
            service_readiness,
            tool_counts,
            registry,
        )
        emit_observability_event(
            context.logger,
            context.tracer,
            MCP_HEALTH_CHECKED,
            payload={
                "server_name": context.server_name,
                "tool_name": "mcp.health",
                "status": payload["status"],
                "ready": payload["ready"],
                "unhealthy_tools": payload["tools"]["unhealthy"],
            },
        )
        return payload


def _required_tools_loaded(registry: ToolRegistry | None) -> str:
    if registry is None:
        return "unhealthy"
    if any(tool.required and tool.load_status != "loaded" for tool in registry.list_tools()):
        return "unhealthy"
    return "ok"


def _optional_failed_tools(registry: ToolRegistry | None) -> str:
    if registry is None:
        return "unhealthy"
    if any((not tool.required) and tool.load_status == "failed" for tool in registry.list_tools()):
        return "degraded"
    return "ok"


def _websearch_local_readiness(settings: AppSettings, registry: ToolRegistry | None) -> str:
    websearch_settings = settings.tools.get("websearch")
    websearch_enabled = websearch_settings.enabled if websearch_settings is not None else False
    if not websearch_enabled:
        return "ok"
    if registry is None:
        return "unhealthy"

    websearch_tool = registry.get_tool("websearch")
    if websearch_tool is None:
        return "unhealthy"
    if websearch_tool.load_status != "loaded" or websearch_tool.health_status == "error":
        return "unhealthy" if websearch_tool.required else "degraded"
    if websearch_tool.health_status == "degraded":
        return "degraded"
    return "ok"


def _security_mode_valid(settings: AppSettings) -> bool:
    inbound_auth = settings.security.inbound_auth
    if not inbound_auth.enabled:
        return inbound_auth.mode == "none"
    return inbound_auth.mode in {"bearer", "jwt"}


def _overall_health_status(checks: Mapping[str, str]) -> str:
    if any(status == "unhealthy" for status in checks.values()):
        return "unhealthy"
    if any(status == "degraded" for status in checks.values()):
        return "degraded"
    return "ok"
