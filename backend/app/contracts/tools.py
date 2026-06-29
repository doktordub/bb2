"""Tool gateway contracts and normalized tool payloads."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Protocol

if TYPE_CHECKING:
    from app.contracts.context import OrchestrationContext

ToolExecutionMode = Literal["sync", "stream"]
ToolSafetyLevel = Literal[
    "read_only",
    "write",
    "destructive",
    "external_side_effect",
]
ToolExecutionStatus = Literal["completed", "failed", "cancelled", "timeout"]
ToolContentType = Literal["text", "json", "table", "file_ref", "image_ref"]
ToolStreamEventType = Literal[
    "started",
    "progress",
    "delta",
    "metadata",
    "completed",
    "error",
    "cancelled",
]

_TOOL_EXECUTION_MODES = frozenset({"sync", "stream"})
_TOOL_SAFETY_LEVELS = frozenset(
    {"read_only", "write", "destructive", "external_side_effect"}
)
_TOOL_EXECUTION_STATUSES = frozenset({"completed", "failed", "cancelled", "timeout"})
_TOOL_CONTENT_TYPES = frozenset({"text", "json", "table", "file_ref", "image_ref"})
_TOOL_STREAM_EVENT_TYPES = frozenset(
    {"started", "progress", "delta", "metadata", "completed", "error", "cancelled"}
)


@dataclass(slots=True)
class ToolScopes:
    """Logical scope carried into tool discovery and execution."""

    user_id: str | None = None
    project_id: str | None = None
    tenant_id: str | None = None
    session_id: str | None = None
    agent_name: str | None = None
    usecase: str | None = None
    tool_group: str | None = None
    tags: tuple[str, ...] | list[str] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.user_id = _normalized_text(self.user_id)
        self.project_id = _normalized_text(self.project_id)
        self.tenant_id = _normalized_text(self.tenant_id)
        self.session_id = _normalized_text(self.session_id)
        self.agent_name = _normalized_text(self.agent_name)
        self.usecase = _normalized_text(self.usecase)
        self.tool_group = _normalized_text(self.tool_group)
        self.tags = _normalize_text_tuple(self.tags)
        self.metadata = _copy_mapping(self.metadata)

    def has_explicit_scope(self) -> bool:
        return any(
            (
                self.user_id,
                self.project_id,
                self.tenant_id,
                self.session_id,
                self.agent_name,
                self.usecase,
                self.tool_group,
                self.tags,
            )
        )

    def has_durable_scope(self) -> bool:
        return any((self.user_id, self.project_id, self.tenant_id))

    def summary(self) -> dict[str, Any]:
        return {
            "user_id_present": self.user_id is not None,
            "project_id_present": self.project_id is not None,
            "tenant_id_present": self.tenant_id is not None,
            "session_id_present": self.session_id is not None,
            "agent_name_present": self.agent_name is not None,
            "usecase_present": self.usecase is not None,
            "tool_group_present": self.tool_group is not None,
            "tag_count": len(self.tags),
        }


@dataclass(slots=True)
class ToolDefinition:
    """Stable logical tool definition exposed to orchestration code."""

    name: str
    description: str | None = None
    input_schema: dict[str, Any] = field(default_factory=dict)
    source: str | None = None
    output_schema: dict[str, Any] | None = None
    display_name: str | None = None
    enabled: bool = True
    execution_modes: tuple[str, ...] | list[str] = field(
        default_factory=lambda: ("sync",)
    )
    safety_level: str = "read_only"
    approval_required: bool = False
    tags: tuple[str, ...] | list[str] = field(default_factory=tuple)
    permissions: tuple[str, ...] | list[str] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.name = _required_text(self.name, "Tool name must not be empty.")
        self.description = _normalized_text(self.description)
        self.display_name = _normalized_text(self.display_name)
        self.source = _normalized_text(self.source)
        self.input_schema = _copy_mapping(self.input_schema)
        self.output_schema = None if self.output_schema is None else _copy_mapping(self.output_schema)
        self.execution_modes = _normalize_literal_tuple(
            self.execution_modes,
            valid_values=_TOOL_EXECUTION_MODES,
            default=("sync",),
            error_message="Tool execution mode must be one of: sync, stream.",
        )
        self.safety_level = _normalize_literal_value(
            self.safety_level,
            valid_values=_TOOL_SAFETY_LEVELS,
            default="read_only",
            error_message=(
                "Tool safety level must be one of: read_only, write, destructive, "
                "external_side_effect."
            ),
        )
        self.tags = _normalize_text_tuple(self.tags)
        self.permissions = _normalize_text_tuple(self.permissions)
        self.metadata = _copy_mapping(self.metadata)

    @property
    def supports_streaming(self) -> bool:
        return "stream" in self.execution_modes


ToolSpec = ToolDefinition


@dataclass(slots=True)
class ToolListFilters:
    """Safe filters applied to tool discovery results."""

    names: tuple[str, ...] | list[str] = field(default_factory=tuple)
    tags: tuple[str, ...] | list[str] = field(default_factory=tuple)
    enabled_only: bool = True
    safety_levels: tuple[str, ...] | list[str] = field(
        default_factory=tuple
    )
    execution_mode: str | None = None
    approval_required: bool | None = None
    name_prefix: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.names = _normalize_text_tuple(self.names)
        self.tags = _normalize_text_tuple(self.tags)
        self.safety_levels = _normalize_literal_tuple(
            self.safety_levels,
            valid_values=_TOOL_SAFETY_LEVELS,
            default=tuple(),
            error_message=(
                "Tool safety level must be one of: read_only, write, destructive, "
                "external_side_effect."
            ),
        )
        self.execution_mode = _normalize_optional_literal(
            self.execution_mode,
            valid_values=_TOOL_EXECUTION_MODES,
            error_message="Tool execution mode must be one of: sync, stream.",
        )
        self.name_prefix = _normalized_text(self.name_prefix)
        self.metadata = _copy_mapping(self.metadata)


@dataclass(slots=True)
class ToolListResult:
    """Normalized public tool listing response."""

    tools: list[ToolDefinition] = field(default_factory=list)
    total_count: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        normalized_tools: list[ToolDefinition] = []
        for tool in self.tools:
            if isinstance(tool, ToolDefinition):
                normalized_tools.append(tool)
            elif isinstance(tool, Mapping):
                normalized_tools.append(ToolDefinition(**dict(tool)))
            else:
                raise TypeError("Tool list entries must be ToolDefinition instances.")
        self.tools = normalized_tools
        self.metadata = _copy_mapping(self.metadata)
        if self.total_count is None:
            self.total_count = len(self.tools)

    def __iter__(self) -> Iterator[ToolDefinition]:
        return iter(self.tools)

    def __len__(self) -> int:
        return len(self.tools)

    def __getitem__(self, index: int) -> ToolDefinition:
        return self.tools[index]

    def __eq__(self, other: object) -> bool:
        if isinstance(other, ToolListResult):
            return (
                self.tools == other.tools
                and self.total_count == other.total_count
                and self.metadata == other.metadata
            )
        if isinstance(other, list):
            return self.tools == other
        return False


@dataclass(slots=True)
class ToolExecutionRequest:
    """Normalized request for logical tool execution."""

    tool_name: str
    arguments: dict[str, Any]
    scopes: ToolScopes | Mapping[str, Any] = field(default_factory=ToolScopes)
    timeout_seconds: int | None = None
    idempotency_key: str | None = None
    stream: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.tool_name = _required_text(self.tool_name, "Tool name must not be empty.")
        self.arguments = _copy_mapping(self.arguments)
        self.scopes = _coerce_scopes(self.scopes)
        self.idempotency_key = _normalized_text(self.idempotency_key)
        self.metadata = _copy_mapping(self.metadata)


ToolCallRequest = ToolExecutionRequest


@dataclass(slots=True)
class ToolResultContent:
    """One bounded tool content block."""

    type: str
    text: str | None = None
    json_value: Any | None = None
    uri: str | None = None
    mime_type: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.type = _normalize_literal_value(
            self.type,
            valid_values=_TOOL_CONTENT_TYPES,
            default="text",
            error_message=(
                "Tool result content type must be one of: text, json, table, file_ref, "
                "image_ref."
            ),
        )
        self.text = _normalized_text(self.text)
        self.uri = _normalized_text(self.uri)
        self.mime_type = _normalized_text(self.mime_type)
        self.metadata = _copy_mapping(self.metadata)


@dataclass(slots=True)
class ToolResultSummary:
    """Safe summary of one normalized tool result."""

    result_count: int | None = None
    bytes_returned: int | None = None
    truncated: bool = False
    safe_message: str | None = None

    def __post_init__(self) -> None:
        self.safe_message = _normalized_text(self.safe_message)


@dataclass(slots=True)
class ToolErrorDetail:
    """Safe, backend-owned tool error detail."""

    code: str
    message: str
    category: str | None = None
    retryable: bool | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.code = _required_text(self.code, "Tool error code must not be empty.")
        self.message = _required_text(self.message, "Tool error message must not be empty.")
        self.category = _normalized_text(self.category)
        self.metadata = _copy_mapping(self.metadata)


@dataclass(slots=True)
class ToolExecutionResult:
    """Normalized result of a logical tool execution."""

    tool_name: str
    status: str
    content: list[ToolResultContent] = field(default_factory=list)
    structured_content: dict[str, Any] | None = None
    summary: ToolResultSummary | None = None
    duration_ms: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    error_detail: ToolErrorDetail | None = None

    def __post_init__(self) -> None:
        self.tool_name = _required_text(self.tool_name, "Tool name must not be empty.")
        self.status = _normalize_literal_value(
            self.status,
            valid_values=_TOOL_EXECUTION_STATUSES,
            default="failed",
            error_message=(
                "Tool execution status must be one of: completed, failed, cancelled, timeout."
            ),
        )
        normalized_content: list[ToolResultContent] = []
        for item in self.content:
            if isinstance(item, ToolResultContent):
                normalized_content.append(item)
            elif isinstance(item, Mapping):
                normalized_content.append(ToolResultContent(**dict(item)))
            else:
                raise TypeError("Tool result content entries must be ToolResultContent instances.")
        self.content = normalized_content
        self.structured_content = (
            None if self.structured_content is None else _copy_mapping(self.structured_content)
        )
        if isinstance(self.summary, Mapping):
            self.summary = ToolResultSummary(**dict(self.summary))
        if isinstance(self.error_detail, Mapping):
            self.error_detail = ToolErrorDetail(**dict(self.error_detail))
        self.metadata = _copy_mapping(self.metadata)

    @property
    def success(self) -> bool:
        return self.status == "completed"

    @property
    def data(self) -> Any | None:
        if self.structured_content is not None:
            return self.structured_content
        if len(self.content) != 1:
            return None
        item = self.content[0]
        if item.json_value is not None:
            return item.json_value
        if item.text is not None:
            return item.text
        if item.uri is not None:
            return item.uri
        return None

    @property
    def error(self) -> str | None:
        if self.error_detail is not None:
            return self.error_detail.message
        if self.summary is not None:
            return self.summary.safe_message
        return None


ToolResult = ToolExecutionResult


@dataclass(slots=True)
class ToolStreamEvent:
    """Normalized stream lifecycle event emitted by the tool gateway."""

    type: str
    tool_name: str
    text: str | None = None
    progress: float | None = None
    result: ToolExecutionResult | None = None
    error: ToolErrorDetail | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.type = _normalize_literal_value(
            self.type,
            valid_values=_TOOL_STREAM_EVENT_TYPES,
            default="error",
            error_message=(
                "Tool stream event type must be one of: started, progress, delta, metadata, "
                "completed, error, cancelled."
            ),
        )
        self.tool_name = _required_text(self.tool_name, "Tool name must not be empty.")
        self.text = _normalized_text(self.text)
        if isinstance(self.result, Mapping):
            self.result = ToolExecutionResult(**dict(self.result))
        if isinstance(self.error, Mapping):
            self.error = ToolErrorDetail(**dict(self.error))
        self.metadata = _copy_mapping(self.metadata)

    @classmethod
    def started(
        cls,
        *,
        tool_name: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> "ToolStreamEvent":
        return cls(type="started", tool_name=tool_name, metadata=dict(metadata or {}))

    @classmethod
    def progress_event(
        cls,
        *,
        tool_name: str,
        progress: float,
        metadata: Mapping[str, Any] | None = None,
    ) -> "ToolStreamEvent":
        return cls(
            type="progress",
            tool_name=tool_name,
            progress=progress,
            metadata=dict(metadata or {}),
        )

    @classmethod
    def delta(
        cls,
        *,
        tool_name: str,
        text: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> "ToolStreamEvent":
        return cls(
            type="delta",
            tool_name=tool_name,
            text=text,
            metadata=dict(metadata or {}),
        )

    @classmethod
    def completed(
        cls,
        *,
        tool_name: str,
        result: ToolExecutionResult | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "ToolStreamEvent":
        return cls(
            type="completed",
            tool_name=tool_name,
            result=result,
            metadata=dict(metadata or {}),
        )

    @classmethod
    def error_event(
        cls,
        *,
        tool_name: str,
        error: ToolErrorDetail,
        metadata: Mapping[str, Any] | None = None,
    ) -> "ToolStreamEvent":
        return cls(
            type="error",
            tool_name=tool_name,
            error=error,
            metadata=dict(metadata or {}),
        )

    @classmethod
    def cancelled(
        cls,
        *,
        tool_name: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> "ToolStreamEvent":
        return cls(type="cancelled", tool_name=tool_name, metadata=dict(metadata or {}))


@dataclass(slots=True)
class ToolHealthResult(Mapping[str, Any]):
    """Safe health summary for the public tool surface."""

    status: str
    tooling_enabled: bool
    mcp_configured: bool
    mcp_status: str
    tools_configured: int
    tools_discovered: int | None
    tools_enabled: int
    registry_status: str
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.status = self.status.strip() or "unknown"
        self.mcp_status = self.mcp_status.strip() or "unknown"
        self.registry_status = self.registry_status.strip() or "unknown"
        self.error = _normalized_text(self.error)
        self.metadata = _copy_mapping(self.metadata)

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "tooling_enabled": self.tooling_enabled,
            "mcp_configured": self.mcp_configured,
            "mcp_status": self.mcp_status,
            "tools_configured": self.tools_configured,
            "tools_discovered": self.tools_discovered,
            "tools_enabled": self.tools_enabled,
            "registry_status": self.registry_status,
            "error": self.error,
            "metadata": dict(self.metadata),
        }

    def __getitem__(self, key: str) -> Any:
        return self.as_dict()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.as_dict())

    def __len__(self) -> int:
        return len(self.as_dict())


@dataclass(slots=True)
class ToolCapabilitySummary:
    """Safe per-tool summary for capability payloads."""

    name: str
    display_name: str | None = None
    safety_level: str = "read_only"
    enabled: bool = True
    supports_streaming: bool = False
    approval_required: bool = False
    tags: tuple[str, ...] | list[str] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.name = _required_text(self.name, "Tool name must not be empty.")
        self.display_name = _normalized_text(self.display_name)
        self.safety_level = _normalize_literal_value(
            self.safety_level,
            valid_values=_TOOL_SAFETY_LEVELS,
            default="read_only",
            error_message=(
                "Tool safety level must be one of: read_only, write, destructive, "
                "external_side_effect."
            ),
        )
        self.tags = _normalize_text_tuple(self.tags)
        self.metadata = _copy_mapping(self.metadata)

    @classmethod
    def from_definition(cls, definition: ToolDefinition) -> "ToolCapabilitySummary":
        return cls(
            name=definition.name,
            display_name=definition.display_name or definition.description,
            safety_level=definition.safety_level,
            enabled=definition.enabled,
            supports_streaming=definition.supports_streaming,
            approval_required=definition.approval_required,
            tags=definition.tags,
            metadata=definition.metadata,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "safety_level": self.safety_level,
            "enabled": self.enabled,
            "supports_streaming": self.supports_streaming,
            "approval_required": self.approval_required,
            "tags": list(self.tags),
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class ToolCapabilitiesResult(Mapping[str, Any]):
    """Safe capability summary for tool availability and feature flags."""

    enabled: bool
    mcp_configured: bool
    streaming_supported: bool
    available_logical_tools: list[ToolCapabilitySummary] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        normalized_tools: list[ToolCapabilitySummary] = []
        for tool in self.available_logical_tools:
            if isinstance(tool, ToolCapabilitySummary):
                normalized_tools.append(tool)
            elif isinstance(tool, Mapping):
                normalized_tools.append(ToolCapabilitySummary(**dict(tool)))
            else:
                raise TypeError(
                    "Capability tool entries must be ToolCapabilitySummary instances."
                )
        self.available_logical_tools = normalized_tools
        self.metadata = _copy_mapping(self.metadata)

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "mcp_configured": self.mcp_configured,
            "streaming_supported": self.streaming_supported,
            "available_logical_tools": [
                tool.as_dict() for tool in self.available_logical_tools
            ],
            "metadata": dict(self.metadata),
        }

    def __getitem__(self, key: str) -> Any:
        return self.as_dict()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.as_dict())

    def __len__(self) -> int:
        return len(self.as_dict())


class ToolGateway(Protocol):
    """Provider-neutral tool access used by agents and strategies."""

    async def list_tools(
        self,
        context: OrchestrationContext,
        filters: ToolListFilters | None = None,
    ) -> ToolListResult:
        ...

    async def get_tool(
        self,
        tool_name: str,
        context: OrchestrationContext,
    ) -> ToolDefinition | None:
        ...

    async def execute(
        self,
        request: ToolExecutionRequest,
        context: OrchestrationContext,
    ) -> ToolExecutionResult:
        ...

    def stream_execute(
        self,
        request: ToolExecutionRequest,
        context: OrchestrationContext,
    ) -> AsyncIterator[ToolStreamEvent]:
        ...

    async def health(self) -> ToolHealthResult:
        ...

    async def capabilities(self) -> ToolCapabilitiesResult:
        ...

    async def call_tool(
        self,
        request: ToolCallRequest,
        context: OrchestrationContext,
    ) -> ToolResult:
        ...


def _normalized_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _required_text(value: object, message: str) -> str:
    normalized = _normalized_text(value)
    if normalized is None:
        raise ValueError(message)
    return normalized


def _copy_mapping(value: Mapping[str, Any] | None) -> dict[str, Any]:
    return dict(value or {})


def _normalize_text_tuple(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    normalized = []
    for value in values:
        item = _normalized_text(value)
        if item is not None:
            normalized.append(item)
    return tuple(dict.fromkeys(normalized))


def _normalize_literal_tuple(
    values: tuple[str, ...] | list[str],
    *,
    valid_values: frozenset[str],
    default: tuple[str, ...],
    error_message: str,
) -> tuple[str, ...]:
    if not values:
        return default
    normalized: list[str] = []
    for value in values:
        item = _required_text(value, error_message)
        if item not in valid_values:
            raise ValueError(error_message)
        if item not in normalized:
            normalized.append(item)
    return tuple(normalized)


def _normalize_literal_value(
    value: object,
    *,
    valid_values: frozenset[str],
    default: str,
    error_message: str,
) -> str:
    normalized = _normalized_text(value)
    if normalized is None:
        return default
    if normalized not in valid_values:
        raise ValueError(error_message)
    return normalized


def _normalize_optional_literal(
    value: object,
    *,
    valid_values: frozenset[str],
    error_message: str,
) -> str | None:
    normalized = _normalized_text(value)
    if normalized is None:
        return None
    if normalized not in valid_values:
        raise ValueError(error_message)
    return normalized


def _coerce_scopes(value: ToolScopes | Mapping[str, Any]) -> ToolScopes:
    if isinstance(value, ToolScopes):
        return value
    if isinstance(value, Mapping):
        return ToolScopes(**dict(value))
    raise TypeError("Tool scopes must be a ToolScopes instance or mapping.")