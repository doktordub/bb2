"""Factory helpers for assembling the concrete backend tooling runtime skeleton."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlparse

from app.config.view import ToolingSettings, get_tooling_settings
from app.contracts.config import ConfigurationView
from app.tools.discovery import ToolDiscoveryService
from app.tools.gateway import DefaultToolGateway
from app.tools.mcp.client_adapter import DefaultMCPClientAdapter
from app.tools.mcp.fake import FakeMCPClientAdapter
from app.tools.mcp.protocol_models import MCPClientAdapter, MCPToolDefinition
from app.tools.models import ResolvedToolDefinition, ToolDiscoverySnapshot, ToolRegistryEntry
from app.tools.registry import ToolRegistry
from app.tools.result_normalizer import ToolResultNormalizer
from app.tools.schema_validation import ToolArgumentValidator


@dataclass(frozen=True, slots=True)
class ToolingRuntimeBundle:
    """Composed tooling runtime pieces ready for later gateway and registry wiring."""

    settings: ToolingSettings
    registry: ToolRegistry
    discovery_service: ToolDiscoveryService
    argument_validator: ToolArgumentValidator
    result_normalizer: ToolResultNormalizer
    mcp_adapter: MCPClientAdapter
    gateway: DefaultToolGateway

    @property
    def registry_entries(self) -> dict[str, ToolRegistryEntry]:
        return self.registry.entries

    @property
    def discovery_snapshot(self) -> ToolDiscoverySnapshot:
        snapshot = self.registry.discovery_snapshot
        if snapshot is None:
            raise RuntimeError("Tooling runtime bundle is missing a discovery snapshot.")
        return snapshot


def build_tooling_runtime(
    config: ConfigurationView,
    *,
    mcp_adapter: MCPClientAdapter | None = None,
) -> ToolingRuntimeBundle:
    """Build the tooling runtime bundle around registry, validation, and MCP access."""

    settings = get_tooling_settings(config)
    registry_entries = _build_registry_entries(settings)
    discovery_snapshot = _build_discovery_snapshot(settings, registry_entries)
    adapter = mcp_adapter or _build_mcp_adapter(settings, registry_entries)
    registry = ToolRegistry(
        registry_entries,
        discovery_snapshot=discovery_snapshot,
        allow_discovered_tools=settings.registry.allow_discovered_tools,
        require_configured_allowlist=settings.registry.require_configured_allowlist,
    )
    discovery_service = ToolDiscoveryService(mcp_adapter=adapter, server=settings.mcp_server)
    argument_validator = ToolArgumentValidator(
        default_max_argument_bytes=settings.defaults.max_argument_bytes,
    )
    result_normalizer = ToolResultNormalizer(
        default_max_result_bytes=settings.defaults.max_result_bytes,
    )
    gateway = DefaultToolGateway(
        settings=settings,
        registry=registry,
        argument_validator=argument_validator,
        result_normalizer=result_normalizer,
        mcp_adapter=adapter,
    )
    return ToolingRuntimeBundle(
        settings=settings,
        registry=registry,
        discovery_service=discovery_service,
        argument_validator=argument_validator,
        result_normalizer=result_normalizer,
        mcp_adapter=adapter,
        gateway=gateway,
    )


async def initialize_tooling_runtime(runtime: ToolingRuntimeBundle) -> ToolingRuntimeBundle:
    """Perform optional startup discovery without running any work at import time."""

    if not runtime.settings.enabled:
        return runtime
    if not runtime.settings.defaults.discovery_on_startup:
        return runtime

    await runtime.discovery_service.refresh_registry(runtime.registry)
    return runtime


def _build_registry_entries(settings: ToolingSettings) -> dict[str, ToolRegistryEntry]:
    entries: dict[str, ToolRegistryEntry] = {}
    for logical_name, definition_settings in settings.registry.tools.items():
        resolved = ResolvedToolDefinition.from_settings(
            definition_settings,
            defaults=settings.defaults,
        )
        entries[logical_name] = ToolRegistryEntry(
            definition=resolved,
            source="configured",
            metadata={"allowlisted": True},
        )
    return entries


def _build_discovery_snapshot(
    settings: ToolingSettings,
    registry_entries: dict[str, ToolRegistryEntry],
) -> ToolDiscoverySnapshot:
    tools: dict[str, MCPToolDefinition] = {}
    for entry in registry_entries.values():
        if not entry.definition.enabled:
            continue
        tools[entry.mcp_tool_name] = MCPToolDefinition(
            name=entry.mcp_tool_name,
            description=entry.definition.description,
            input_schema=entry.definition.input_schema or {},
            output_schema=entry.definition.output_schema,
            supports_streaming=entry.definition.supports_streaming,
            metadata={"logical_name": entry.logical_name},
        )
    return ToolDiscoverySnapshot(
        server_name=settings.mcp_server.name,
        transport=settings.mcp_server.transport,
        discovery_enabled=settings.mcp_server.tool_discovery_enabled,
        tools=tools,
        metadata={
            "configured_tool_count": len(registry_entries),
            "allow_discovered_tools": settings.registry.allow_discovered_tools,
            "require_configured_allowlist": settings.registry.require_configured_allowlist,
        },
    )


def _build_mcp_adapter(
    settings: ToolingSettings,
    registry_entries: Mapping[str, ToolRegistryEntry],
) -> MCPClientAdapter:
    endpoint = (settings.mcp_server.endpoint or "").strip()
    normalized_endpoint = endpoint.lower()
    hostname = (urlparse(endpoint).hostname or "").lower()
    if normalized_endpoint.startswith("fake://") or hostname.endswith(".invalid"):
        return FakeMCPClientAdapter.from_registry_entries(
            registry_entries=registry_entries,
            enabled=settings.enabled and settings.mcp_server.enabled,
            endpoint=settings.mcp_server.endpoint,
            auth_mode=settings.mcp_server.auth.mode,
            metadata={"server_name": settings.mcp_server.name},
        )

    return DefaultMCPClientAdapter(server=settings.mcp_server)