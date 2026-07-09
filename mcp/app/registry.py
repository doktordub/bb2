"""Internal registry for discovered MCP tools and capabilities."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

from app.errors import MCPToolPluginError
from app.tools_base.manifest import ToolManifest
from app.tools_base.models import RiskLevel, ToolDescriptor
from app.tools_base.plugin import ToolPlugin


ToolLoadStatus = Literal["loaded", "disabled", "failed"]
RegisteredToolHealth = Literal["ok", "degraded", "error", "disabled"]


@dataclass(frozen=True, slots=True)
class ToolLoadErrorSummary:
    """Safe error summary retained for registry and diagnostics."""

    error_type: str
    message: str


@dataclass(frozen=True, slots=True)
class RegisteredCapability:
    """Safe registry record for one exposed tool capability."""

    capability_name: str
    type: str
    tool_name: str
    risk_level: RiskLevel
    enabled: bool
    status: ToolLoadStatus
    version: str

    def to_summary(self) -> dict[str, str | bool]:
        return {
            "capability_name": self.capability_name,
            "type": self.type,
            "tool_name": self.tool_name,
            "risk_level": self.risk_level,
            "enabled": self.enabled,
            "status": self.status,
            "version": self.version,
        }


@dataclass(frozen=True, slots=True)
class RegisteredTool:
    """Internal metadata captured for one discovered tool plugin."""

    folder_name: str
    package_name: str
    manifest_name: str
    version: str
    enabled: bool
    required: bool
    load_status: ToolLoadStatus
    fastmcp_tool_names: tuple[str, ...]
    capabilities: tuple[RegisteredCapability, ...]
    risk_levels: tuple[RiskLevel, ...]
    owner: str
    tags: tuple[str, ...]
    health_status: RegisteredToolHealth
    last_load_error: ToolLoadErrorSummary | None = None
    health_reason: str | None = None

    def to_summary(self) -> dict[str, object]:
        return {
            "name": self.manifest_name,
            "version": self.version,
            "enabled": self.enabled,
            "required": self.required,
            "status": self.load_status,
            "health": self.health_status,
            "tools": list(self.fastmcp_tool_names),
            "owner": self.owner,
            "tags": list(self.tags),
            "last_error": None if self.last_load_error is None else self.last_load_error.message,
        }


@dataclass(frozen=True, slots=True)
class ToolRegistryHealth:
    """Aggregated registry health counts for internal MCP health reporting."""

    loaded: int = 0
    enabled: int = 0
    disabled: int = 0
    failed: int = 0
    unhealthy: int = 0

    def as_counts(self) -> dict[str, int]:
        return {
            "loaded": self.loaded,
            "enabled": self.enabled,
            "disabled": self.disabled,
            "failed": self.failed,
            "unhealthy": self.unhealthy,
        }


class ToolRegistry:
    """Tracks loaded, disabled, and failed tools with duplicate detection."""

    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}
        self._fastmcp_tool_names: dict[str, str] = {}

    def register_plugin(
        self,
        plugin: ToolPlugin,
        manifest: ToolManifest,
        config: dict[str, object],
    ) -> None:
        del config
        self._ensure_fastmcp_names_available(
            manifest.tool_descriptors(),
            owner_name=manifest.name,
        )
        registered_tool = self._build_registered_tool(
            manifest=manifest,
            enabled=True,
            load_status="loaded",
            health_status=self._plugin_health_status(plugin),
            last_load_error=None,
        )
        self._store_registered_tool(registered_tool)

    def assert_can_register(self, manifest: ToolManifest) -> None:
        self._ensure_fastmcp_names_available(
            manifest.tool_descriptors(),
            owner_name=manifest.name,
        )

    def register_disabled(self, manifest: ToolManifest) -> None:
        registered_tool = self._build_registered_tool(
            manifest=manifest,
            enabled=False,
            load_status="disabled",
            health_status="disabled",
            last_load_error=None,
        )
        self._tools[manifest.name] = registered_tool

    def register_failed(
        self,
        manifest_or_name: ToolManifest | str,
        error: Exception,
        required: bool,
    ) -> None:
        if isinstance(manifest_or_name, ToolManifest):
            manifest = manifest_or_name
            registered_tool = self._build_registered_tool(
                manifest=manifest,
                enabled=True,
                load_status="failed",
                health_status="error",
                last_load_error=self._error_summary(error),
            )
            self._store_registered_tool(registered_tool)
            return

        tool_name = manifest_or_name
        self._tools[tool_name] = RegisteredTool(
            folder_name=tool_name,
            package_name=f"mcp.tools.{tool_name}",
            manifest_name=tool_name,
            version="unknown",
            enabled=True,
            required=required,
            load_status="failed",
            fastmcp_tool_names=(),
            capabilities=(),
            risk_levels=(),
            owner="unknown",
            tags=(),
            health_status="error",
            last_load_error=self._error_summary(error),
        )

    def get_tool(self, tool_name: str) -> RegisteredTool | None:
        return self._tools.get(tool_name)

    def list_tools(self) -> list[RegisteredTool]:
        return [self._tools[name] for name in sorted(self._tools)]

    def list_capabilities(self) -> list[RegisteredCapability]:
        capabilities = [
            capability
            for tool in self.list_tools()
            for capability in tool.capabilities
        ]
        return sorted(
            capabilities,
            key=lambda capability: (capability.capability_name, capability.tool_name),
        )

    def mark_unhealthy(self, tool_name: str, reason: str) -> None:
        registered_tool = self._tools.get(tool_name)
        if registered_tool is None:
            raise KeyError(f"Unknown tool {tool_name!r}.")

        degraded_health: RegisteredToolHealth = (
            "error" if registered_tool.load_status == "failed" else "degraded"
        )
        self._tools[tool_name] = replace(
            registered_tool,
            health_status=degraded_health,
            health_reason=reason,
        )

    def health_summary(self) -> ToolRegistryHealth:
        registered_tools = self.list_tools()
        return ToolRegistryHealth(
            loaded=sum(1 for tool in registered_tools if tool.load_status == "loaded"),
            enabled=sum(1 for tool in registered_tools if tool.enabled),
            disabled=sum(1 for tool in registered_tools if tool.load_status == "disabled"),
            failed=sum(1 for tool in registered_tools if tool.load_status == "failed"),
            unhealthy=sum(
                1
                for tool in registered_tools
                if tool.health_status in {"degraded", "error"}
            ),
        )

    def _build_registered_tool(
        self,
        *,
        manifest: ToolManifest,
        enabled: bool,
        load_status: ToolLoadStatus,
        health_status: RegisteredToolHealth,
        last_load_error: ToolLoadErrorSummary | None,
    ) -> RegisteredTool:
        tool_descriptors = manifest.tool_descriptors()
        capability_types = {capability.name: capability.type for capability in manifest.capabilities}
        risk_levels = tuple(sorted({descriptor.risk_level for descriptor in tool_descriptors}))
        tags = tuple(sorted({tag for descriptor in tool_descriptors for tag in descriptor.tags}))

        capabilities = tuple(
            RegisteredCapability(
                capability_name=descriptor.capability,
                type=capability_types[descriptor.capability],
                tool_name=descriptor.name,
                risk_level=descriptor.risk_level,
                enabled=enabled and load_status == "loaded",
                status=load_status,
                version=manifest.version,
            )
            for descriptor in tool_descriptors
        )
        return RegisteredTool(
            folder_name=manifest.name,
            package_name=manifest.package,
            manifest_name=manifest.name,
            version=manifest.version,
            enabled=enabled,
            required=manifest.required,
            load_status=load_status,
            fastmcp_tool_names=tuple(descriptor.name for descriptor in tool_descriptors),
            capabilities=capabilities,
            risk_levels=risk_levels,
            owner=manifest.owner,
            tags=tags,
            health_status=health_status,
            last_load_error=last_load_error,
        )

    def _ensure_fastmcp_names_available(
        self,
        tool_descriptors: list[ToolDescriptor],
        *,
        owner_name: str,
    ) -> None:
        duplicate_names = []
        for descriptor in tool_descriptors:
            tool_name = descriptor.name
            existing_owner = self._fastmcp_tool_names.get(tool_name)
            if existing_owner is not None and existing_owner != owner_name:
                duplicate_names.append((tool_name, existing_owner))

        if duplicate_names:
            duplicate_name, existing_owner = duplicate_names[0]
            raise MCPToolPluginError(
                f"Duplicate FastMCP tool name {duplicate_name!r} declared by {owner_name!r}; already provided by {existing_owner!r}."
            )

    def _store_registered_tool(self, registered_tool: RegisteredTool) -> None:
        self._tools[registered_tool.manifest_name] = registered_tool
        if registered_tool.enabled:
            for tool_name in registered_tool.fastmcp_tool_names:
                self._fastmcp_tool_names[tool_name] = registered_tool.manifest_name

    @staticmethod
    def _error_summary(error: Exception) -> ToolLoadErrorSummary:
        return ToolLoadErrorSummary(
            error_type=error.__class__.__name__,
            message=str(error) or error.__class__.__name__,
        )

    @staticmethod
    def _plugin_health_status(plugin: ToolPlugin) -> RegisteredToolHealth:
        return "ok"
