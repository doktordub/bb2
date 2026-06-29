"""Runtime-private tooling models used by the backend tool runtime package."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from app.config.view import ToolDefinitionSettings, ToolingDefaultsSettings
from app.tools.mcp.protocol_models import MCPToolCallRequest, MCPToolDefinition

ToolAvailabilitySource = Literal["configured", "discovered", "merged"]
ToolRuntimeExecutionMode = Literal["sync", "stream"]
ToolRuntimeSafetyLevel = Literal[
    "read_only",
    "write",
    "destructive",
    "external_side_effect",
]

_VALID_EXECUTION_MODES = frozenset({"sync", "stream"})


@dataclass(frozen=True, slots=True)
class ResolvedToolDefinition:
    """Runtime-resolved logical tool definition used by registry and gateway internals."""

    logical_name: str
    mcp_tool_name: str
    description: str | None = None
    enabled: bool = True
    execution_modes: tuple[ToolRuntimeExecutionMode, ...] = ("sync",)
    safety_level: ToolRuntimeSafetyLevel = "read_only"
    approval_required: bool = False
    timeout_seconds: int = 60
    max_argument_bytes: int = 65536
    max_result_bytes: int = 262144
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None
    tags: tuple[str, ...] = ()
    allowed_usecases: tuple[str, ...] = ()
    allowed_agents: tuple[str, ...] = ()
    allowed_strategies: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "logical_name", _required_text(self.logical_name))
        object.__setattr__(self, "mcp_tool_name", _required_text(self.mcp_tool_name))
        object.__setattr__(self, "description", _normalized_text(self.description))
        object.__setattr__(
            self,
            "execution_modes",
            _normalize_execution_modes(self.execution_modes),
        )
        object.__setattr__(self, "tags", _normalize_text_tuple(self.tags))
        object.__setattr__(
            self,
            "allowed_usecases",
            _normalize_text_tuple(self.allowed_usecases),
        )
        object.__setattr__(
            self,
            "allowed_agents",
            _normalize_text_tuple(self.allowed_agents),
        )
        object.__setattr__(
            self,
            "allowed_strategies",
            _normalize_text_tuple(self.allowed_strategies),
        )
        object.__setattr__(self, "metadata", dict(self.metadata))
        if self.input_schema is not None:
            object.__setattr__(self, "input_schema", dict(self.input_schema))
        if self.output_schema is not None:
            object.__setattr__(self, "output_schema", dict(self.output_schema))

    @property
    def supports_streaming(self) -> bool:
        return "stream" in self.execution_modes

    @classmethod
    def from_settings(
        cls,
        settings: ToolDefinitionSettings,
        *,
        defaults: ToolingDefaultsSettings,
    ) -> "ResolvedToolDefinition":
        extra = dict(settings.extra)
        return cls(
            logical_name=settings.name,
            mcp_tool_name=settings.mcp_tool_name,
            description=settings.description,
            enabled=settings.enabled,
            execution_modes=_resolve_execution_modes(extra),
            safety_level=settings.safety_level,
            approval_required=settings.approval_required,
            timeout_seconds=settings.timeout_seconds or defaults.timeout_seconds,
            max_argument_bytes=settings.max_argument_bytes or defaults.max_argument_bytes,
            max_result_bytes=settings.max_result_bytes or defaults.max_result_bytes,
            input_schema=_copy_optional_mapping(settings.input_schema_override),
            output_schema=_copy_optional_mapping(settings.output_schema_override),
            tags=settings.tags,
            allowed_usecases=settings.allowed_for.usecases,
            allowed_agents=settings.allowed_for.agents,
            allowed_strategies=settings.allowed_for.strategies,
            metadata=extra,
        )


@dataclass(frozen=True, slots=True)
class ToolRegistryEntry:
    """One runtime registry entry for a logical tool definition."""

    definition: ResolvedToolDefinition
    source: ToolAvailabilitySource = "configured"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def logical_name(self) -> str:
        return self.definition.logical_name

    @property
    def mcp_tool_name(self) -> str:
        return self.definition.mcp_tool_name


@dataclass(frozen=True, slots=True)
class ToolDiscoverySnapshot:
    """Cached view of discovered MCP tool metadata for later registry merge steps."""

    server_name: str
    transport: Literal["http", "sse", "websocket"]
    discovery_enabled: bool
    discovered_at: datetime | None = None
    tools: dict[str, MCPToolDefinition] = field(default_factory=dict)
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "server_name", _required_text(self.server_name))
        object.__setattr__(self, "error", _normalized_text(self.error))
        object.__setattr__(self, "tools", dict(self.tools))
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def tool_count(self) -> int:
        return len(self.tools)

    @property
    def tool_names(self) -> tuple[str, ...]:
        return tuple(self.tools)


@dataclass(frozen=True, slots=True)
class AdapterRequestMetadata:
    """Runtime metadata used to translate logical execution into adapter calls."""

    trace_id: str
    session_id: str | None = None
    idempotency_key: str | None = None
    timeout_seconds: int = 60
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "trace_id", _required_text(self.trace_id))
        object.__setattr__(self, "session_id", _normalized_text(self.session_id))
        object.__setattr__(
            self,
            "idempotency_key",
            _normalized_text(self.idempotency_key),
        )
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_mcp_request(
        self,
        *,
        mcp_tool_name: str,
        arguments: Mapping[str, Any],
    ) -> MCPToolCallRequest:
        return MCPToolCallRequest(
            mcp_tool_name=mcp_tool_name,
            arguments=dict(arguments),
            timeout_seconds=self.timeout_seconds,
            trace_id=self.trace_id,
            session_id=self.session_id,
            idempotency_key=self.idempotency_key,
            metadata=self.metadata,
        )


def _normalized_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _required_text(value: object) -> str:
    normalized = _normalized_text(value)
    if normalized is None:
        raise ValueError("Tooling runtime values must not be empty.")
    return normalized


def _normalize_text_tuple(values: Sequence[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for value in values:
        item = _normalized_text(value)
        if item is not None and item not in normalized:
            normalized.append(item)
    return tuple(normalized)


def _normalize_execution_modes(
    values: Sequence[ToolRuntimeExecutionMode],
) -> tuple[ToolRuntimeExecutionMode, ...]:
    normalized: list[ToolRuntimeExecutionMode] = []
    for value in values:
        if value not in _VALID_EXECUTION_MODES:
            raise ValueError("Unsupported tooling runtime execution mode.")
        if value not in normalized:
            normalized.append(value)
    return tuple(normalized) if normalized else ("sync",)


def _resolve_execution_modes(extra: Mapping[str, Any]) -> tuple[ToolRuntimeExecutionMode, ...]:
    explicit = extra.get("execution_modes")
    if isinstance(explicit, Sequence) and not isinstance(explicit, str):
        collected: list[ToolRuntimeExecutionMode] = []
        for item in explicit:
            if item in _VALID_EXECUTION_MODES and item not in collected:
                collected.append(item)
        if collected:
            return tuple(collected)
    supports_streaming = extra.get("supports_streaming")
    if supports_streaming is True:
        return ("sync", "stream")
    return ("sync",)


def _copy_optional_mapping(value: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return dict(value)