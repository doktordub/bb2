"""FastMCP server construction."""

from __future__ import annotations

from fastmcp import FastMCP

from app.capabilities import register_capability_tools
from app.context import ServiceContainer
from app.health import register_health_tool
from app.registry import ToolRegistry


def build_server(services: ServiceContainer) -> FastMCP:
    auth_provider = None
    if services.auth_service is not None:
        auth_provider = services.auth_service.build_auth_provider(
            base_url=services.settings.server.public_base_url,
        )

    return FastMCP(
        services.settings.server.name,
        version=services.settings.server.version,
        auth=auth_provider,
    )


def register_internal_tools(
    server: FastMCP,
    services: ServiceContainer,
    registry: ToolRegistry,
) -> None:
    if not services.settings.policy.expose_internal_tools:
        return

    if services.settings.policy.expose_health_tool:
        register_health_tool(
            server=server,
            context=services.build_tool_runtime_context(
                tool_name="mcp.health",
                tool_config={},
            ),
            service_readiness=services.readiness_summary(),
            registry=registry,
        )

    if services.settings.policy.expose_capabilities_tool:
        register_capability_tools(
            server=server,
            context=services.build_tool_runtime_context(
                tool_name="mcp.capabilities",
                tool_config={},
            ),
            registry=registry,
        )
