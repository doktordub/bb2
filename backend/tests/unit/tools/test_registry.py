from __future__ import annotations

from app.contracts.tools import ToolListFilters
from app.tools.mcp import MCPToolDefinition
from app.tools.models import ResolvedToolDefinition, ToolDiscoverySnapshot, ToolRegistryEntry
from app.tools.registry import ToolRegistry


def test_registry_lists_enabled_tools_and_resolves_disabled_entries() -> None:
    registry = ToolRegistry(
        {
            "documents.search": ToolRegistryEntry(
                definition=ResolvedToolDefinition(
                    logical_name="documents.search",
                    mcp_tool_name="documents.search",
                    description="Search indexed documents.",
                    input_schema={"type": "object"},
                    execution_modes=("sync", "stream"),
                    tags=("documents",),
                ),
                metadata={"allowlisted": True},
            ),
            "admin.reset_cache": ToolRegistryEntry(
                definition=ResolvedToolDefinition(
                    logical_name="admin.reset_cache",
                    mcp_tool_name="admin.reset_cache",
                    description="Reset remote caches.",
                    enabled=False,
                    safety_level="destructive",
                    approval_required=True,
                    tags=("admin",),
                ),
                metadata={"allowlisted": True},
            ),
        },
        allow_discovered_tools=True,
        require_configured_allowlist=True,
    )

    listed = registry.list()

    assert [tool.name for tool in listed] == ["documents.search"]
    resolved = registry.resolve("admin.reset_cache")
    assert resolved.enabled is False

    destructive = registry.list(
        ToolListFilters(enabled_only=False, safety_levels=("destructive",))
    )
    assert [tool.name for tool in destructive] == ["admin.reset_cache"]


def test_registry_refresh_merges_discovery_schema_and_keeps_unallowlisted_tools_disabled() -> None:
    registry = ToolRegistry(
        {
            "documents.search": ToolRegistryEntry(
                definition=ResolvedToolDefinition(
                    logical_name="documents.search",
                    mcp_tool_name="documents.search",
                    description="Configured description.",
                    input_schema={"type": "object", "required": ["query"]},
                ),
                metadata={"allowlisted": True},
            )
        },
        allow_discovered_tools=True,
        require_configured_allowlist=True,
    )
    snapshot = ToolDiscoverySnapshot(
        server_name="fake_main",
        transport="http",
        discovery_enabled=True,
        tools={
            "documents.search": MCPToolDefinition(
                name="documents.search",
                description="Discovered description.",
                input_schema={
                    "type": "object",
                    "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}},
                },
                supports_streaming=True,
            ),
            "filesystem.read_project_file": MCPToolDefinition(
                name="filesystem.read_project_file",
                description="Read a project file.",
                input_schema={"type": "object"},
            ),
        },
    )

    refresh = registry.refresh_from_snapshot(snapshot)

    merged = registry.resolve("documents.search")
    assert merged.description == "Configured description."
    assert merged.supports_streaming is True
    assert merged.input_schema == {
        "type": "object",
        "required": ["query"],
        "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer"},
        },
    }
    discovered_only = registry.resolve("filesystem.read_project_file")
    assert discovered_only.enabled is False
    assert refresh.discovered_only_tools == ("filesystem.read_project_file",)


def test_registry_refresh_omits_discovered_only_tools_when_listing_them_is_disabled() -> None:
    registry = ToolRegistry(
        {
            "documents.search": ToolRegistryEntry(
                definition=ResolvedToolDefinition(
                    logical_name="documents.search",
                    mcp_tool_name="documents.search",
                ),
                metadata={"allowlisted": True},
            )
        },
        allow_discovered_tools=False,
        require_configured_allowlist=True,
    )
    snapshot = ToolDiscoverySnapshot(
        server_name="fake_main",
        transport="http",
        discovery_enabled=True,
        tools={
            "documents.search": MCPToolDefinition(name="documents.search"),
            "filesystem.read_project_file": MCPToolDefinition(
                name="filesystem.read_project_file"
            ),
        },
    )

    refresh = registry.refresh_from_snapshot(snapshot)

    assert tuple(registry.entries) == ("documents.search",)
    assert refresh.discovered_only_tools == ("filesystem.read_project_file",)
