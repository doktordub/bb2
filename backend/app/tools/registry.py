"""Logical tool registry and discovery merge behavior."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.contracts.tools import ToolDefinition, ToolListFilters
from app.tools.errors import ToolNotFoundError
from app.tools.mcp.protocol_models import MCPToolDefinition
from app.tools.models import (
    ResolvedToolDefinition,
    ToolAvailabilitySource,
    ToolDiscoverySnapshot,
    ToolRegistryEntry,
    ToolRuntimeExecutionMode,
)

_INTERNAL_METADATA_KEYS = frozenset(
    {
        "denylisted_fields",
        "denylisted_argument_fields",
        "argument_denylist",
    }
)


@dataclass(frozen=True, slots=True)
class ToolRegistryRefreshResult:
    """Outcome of applying one discovery snapshot to the registry."""

    snapshot: ToolDiscoverySnapshot
    entries: dict[str, ToolRegistryEntry]
    merged_tool_count: int
    missing_configured_tools: tuple[str, ...] = field(default_factory=tuple)
    discovered_only_tools: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "entries", dict(self.entries))
        object.__setattr__(
            self,
            "missing_configured_tools",
            tuple(self.missing_configured_tools),
        )
        object.__setattr__(
            self,
            "discovered_only_tools",
            tuple(self.discovered_only_tools),
        )

    @property
    def registry_status(self) -> str:
        if self.snapshot.error:
            return "degraded"
        if self.missing_configured_tools:
            return "degraded"
        return "ok"


class ToolRegistry:
    """Backend-owned registry of logical tool definitions."""

    def __init__(
        self,
        entries: Mapping[str, ToolRegistryEntry] | None = None,
        *,
        discovery_snapshot: ToolDiscoverySnapshot | None = None,
        allow_discovered_tools: bool = True,
        require_configured_allowlist: bool = True,
    ) -> None:
        self._configured_entries: dict[str, ToolRegistryEntry] = dict(entries or {})
        self._entries: dict[str, ToolRegistryEntry] = dict(entries or {})
        self._discovery_snapshot = discovery_snapshot
        self._allow_discovered_tools = allow_discovered_tools
        self._require_configured_allowlist = require_configured_allowlist

    @property
    def entries(self) -> dict[str, ToolRegistryEntry]:
        return dict(self._entries)

    @property
    def configured_entries(self) -> dict[str, ToolRegistryEntry]:
        return dict(self._configured_entries)

    @property
    def discovery_snapshot(self) -> ToolDiscoverySnapshot | None:
        return self._discovery_snapshot

    def register(
        self,
        definition: ResolvedToolDefinition,
        *,
        source: ToolAvailabilitySource = "configured",
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        entry = ToolRegistryEntry(
            definition=definition,
            source=source,
            metadata=dict(metadata or {}),
        )
        self._configured_entries[definition.logical_name] = entry
        self._entries[definition.logical_name] = entry

    def resolve(self, logical_name: str) -> ResolvedToolDefinition:
        entry = self._entries.get(logical_name)
        if entry is None:
            raise ToolNotFoundError(f"Unknown logical tool: {logical_name}")
        return entry.definition

    def resolve_entry(self, logical_name: str) -> ToolRegistryEntry:
        entry = self._entries.get(logical_name)
        if entry is None:
            raise ToolNotFoundError(f"Unknown logical tool: {logical_name}")
        return entry

    def list(self, filters: ToolListFilters | None = None) -> list[ToolDefinition]:
        effective_filters = filters or ToolListFilters()
        return [
            _to_public_definition(entry)
            for entry in self._iter_filtered_entries(effective_filters)
        ]

    def refresh_from_mcp(
        self,
        discovered: Sequence[MCPToolDefinition],
        *,
        snapshot: ToolDiscoverySnapshot,
    ) -> ToolRegistryRefreshResult:
        discovered_map: dict[str, MCPToolDefinition] = {}
        for item in discovered:
            discovered_map[item.name] = item
        object.__setattr__(snapshot, "tools", discovered_map)
        return self.refresh_from_snapshot(snapshot)

    def refresh_from_snapshot(
        self,
        snapshot: ToolDiscoverySnapshot,
    ) -> ToolRegistryRefreshResult:
        discovered_tools = snapshot.tools
        merged_entries: dict[str, ToolRegistryEntry] = {}
        missing_configured_tools: list[str] = []
        matched_discovered_names: set[str] = set()

        for logical_name, configured_entry in self._configured_entries.items():
            discovered = discovered_tools.get(configured_entry.mcp_tool_name)
            if discovered is None:
                if configured_entry.definition.enabled:
                    missing_configured_tools.append(logical_name)
                merged_entries[logical_name] = ToolRegistryEntry(
                    definition=configured_entry.definition,
                    source="configured",
                    metadata={**configured_entry.metadata, "mcp_available": False},
                )
                continue

            matched_discovered_names.add(discovered.name)
            merged_entries[logical_name] = ToolRegistryEntry(
                definition=_merge_definition(configured_entry.definition, discovered),
                source="merged",
                metadata={
                    **configured_entry.metadata,
                    "mcp_available": True,
                    "discovered_tool_name": discovered.name,
                },
            )

        discovered_only_tools = tuple(
            name for name in discovered_tools if name not in matched_discovered_names
        )
        if self._allow_discovered_tools:
            for discovered_name in discovered_only_tools:
                merged_entries[discovered_name] = ToolRegistryEntry(
                    definition=_build_discovered_only_definition(discovered_tools[discovered_name]),
                    source="discovered",
                    metadata={
                        "allowlisted": False,
                        "callable": False,
                        "mcp_available": True,
                    },
                )

        self._entries = merged_entries
        self._discovery_snapshot = snapshot
        return ToolRegistryRefreshResult(
            snapshot=snapshot,
            entries=merged_entries,
            merged_tool_count=len(merged_entries),
            missing_configured_tools=tuple(missing_configured_tools),
            discovered_only_tools=discovered_only_tools,
        )

    def _iter_filtered_entries(self, filters: ToolListFilters) -> Sequence[ToolRegistryEntry]:
        entries = list(self._entries.values())
        if filters.enabled_only:
            entries = [entry for entry in entries if entry.definition.enabled]
        if filters.names:
            allowed_names = set(filters.names)
            entries = [entry for entry in entries if entry.logical_name in allowed_names]
        if filters.tags:
            required_tags = set(filters.tags)
            entries = [
                entry
                for entry in entries
                if required_tags.issubset(set(entry.definition.tags))
            ]
        if filters.safety_levels:
            allowed_safety_levels = set(filters.safety_levels)
            entries = [
                entry
                for entry in entries
                if entry.definition.safety_level in allowed_safety_levels
            ]
        if filters.execution_mode is not None:
            entries = [
                entry
                for entry in entries
                if filters.execution_mode in entry.definition.execution_modes
            ]
        if filters.approval_required is not None:
            entries = [
                entry
                for entry in entries
                if entry.definition.approval_required is filters.approval_required
            ]
        if filters.name_prefix is not None:
            entries = [
                entry
                for entry in entries
                if entry.logical_name.startswith(filters.name_prefix)
            ]
        if filters.metadata:
            entries = [
                entry
                for entry in entries
                if _matches_metadata(entry, filters.metadata)
            ]
        return entries


def _merge_definition(
    configured: ResolvedToolDefinition,
    discovered: MCPToolDefinition,
) -> ResolvedToolDefinition:
    execution_modes = configured.execution_modes
    if discovered.supports_streaming and "stream" not in execution_modes:
        execution_modes = (*execution_modes, "stream")

    return ResolvedToolDefinition(
        logical_name=configured.logical_name,
        mcp_tool_name=configured.mcp_tool_name,
        description=configured.description or discovered.description,
        enabled=configured.enabled,
        execution_modes=execution_modes,
        safety_level=configured.safety_level,
        approval_required=configured.approval_required,
        timeout_seconds=configured.timeout_seconds,
        max_argument_bytes=configured.max_argument_bytes,
        max_result_bytes=configured.max_result_bytes,
        input_schema=_merge_schema(discovered.input_schema, configured.input_schema),
        output_schema=_merge_schema(discovered.output_schema, configured.output_schema),
        tags=configured.tags,
        allowed_usecases=configured.allowed_usecases,
        allowed_agents=configured.allowed_agents,
        allowed_strategies=configured.allowed_strategies,
        metadata={
            **configured.metadata,
            "discovered": True,
        },
    )


def _build_discovered_only_definition(discovered: MCPToolDefinition) -> ResolvedToolDefinition:
    execution_modes: tuple[ToolRuntimeExecutionMode, ...] = (
        ("sync", "stream") if discovered.supports_streaming else ("sync",)
    )
    return ResolvedToolDefinition(
        logical_name=discovered.name,
        mcp_tool_name=discovered.name,
        description=discovered.description,
        enabled=False,
        execution_modes=execution_modes,
        input_schema=dict(discovered.input_schema),
        output_schema=None if discovered.output_schema is None else dict(discovered.output_schema),
        metadata={"allowlisted": False, "discovered_only": True},
    )


def _merge_schema(
    base: Mapping[str, Any] | None,
    override: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if base is None and override is None:
        return None
    if base is None:
        return dict(override or {})
    if override is None:
        return dict(base)

    merged: dict[str, Any] = dict(base)
    for key, value in override.items():
        existing = merged.get(key)
        if isinstance(existing, Mapping) and isinstance(value, Mapping):
            merged[key] = _merge_schema(existing, value)
        else:
            merged[key] = value
    return merged


def _to_public_definition(entry: ToolRegistryEntry) -> ToolDefinition:
    definition = entry.definition
    return ToolDefinition(
        name=definition.logical_name,
        description=definition.description,
        input_schema=dict(definition.input_schema or {}),
        source=entry.source,
        output_schema=None if definition.output_schema is None else dict(definition.output_schema),
        enabled=definition.enabled,
        execution_modes=definition.execution_modes,
        safety_level=definition.safety_level,
        approval_required=definition.approval_required,
        tags=definition.tags,
        metadata={
            key: value
            for key, value in definition.metadata.items()
            if key not in _INTERNAL_METADATA_KEYS
        },
    )


def _matches_metadata(entry: ToolRegistryEntry, expected: Mapping[str, Any]) -> bool:
    combined = {**entry.definition.metadata, **entry.metadata}
    return all(combined.get(key) == value for key, value in expected.items())
