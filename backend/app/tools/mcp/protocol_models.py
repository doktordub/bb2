"""Internal MCP adapter protocol and DTOs hidden from orchestration callers."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, cast

MCPToolExecutionStatus = Literal["completed", "failed", "cancelled", "timeout"]
MCPToolStreamEventType = Literal[
    "started",
    "progress",
    "delta",
    "metadata",
    "completed",
    "error",
    "cancelled",
]
MCPToolContentType = Literal["text", "json", "table", "file_ref", "image_ref"]

_VALID_EXECUTION_STATUSES = frozenset({"completed", "failed", "cancelled", "timeout"})
_VALID_STREAM_EVENT_TYPES = frozenset(
    {"started", "progress", "delta", "metadata", "completed", "error", "cancelled"}
)
_VALID_CONTENT_TYPES = frozenset({"text", "json", "table", "file_ref", "image_ref"})


@dataclass(slots=True)
class MCPToolDefinition:
    """Internal discovered MCP tool metadata."""

    name: str
    description: str | None = None
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] | None = None
    supports_streaming: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.name = _required_text(self.name, "MCP tool name must not be empty.")
        self.description = _normalized_text(self.description)
        self.input_schema = dict(self.input_schema)
        self.output_schema = None if self.output_schema is None else dict(self.output_schema)
        self.metadata = dict(self.metadata)


@dataclass(slots=True)
class MCPToolCallRequest:
    """Internal MCP tool call request owned by the backend adapter layer."""

    mcp_tool_name: str
    arguments: dict[str, Any]
    timeout_seconds: int
    trace_id: str
    session_id: str | None = None
    idempotency_key: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.mcp_tool_name = _required_text(
            self.mcp_tool_name,
            "MCP tool name must not be empty.",
        )
        self.arguments = dict(self.arguments)
        self.trace_id = _required_text(self.trace_id, "Trace ID must not be empty.")
        self.session_id = _normalized_text(self.session_id)
        self.idempotency_key = _normalized_text(self.idempotency_key)
        self.metadata = dict(self.metadata)


@dataclass(slots=True)
class MCPToolContent:
    """One internal MCP tool content block before gateway normalization."""

    type: MCPToolContentType
    text: str | None = None
    json_value: Any | None = None
    uri: str | None = None
    mime_type: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.type = cast(
            MCPToolContentType,
            _normalize_literal(
                self.type,
                valid_values=_VALID_CONTENT_TYPES,
                default="text",
                message="MCP tool content type is invalid.",
            ),
        )
        self.text = _normalized_text(self.text)
        self.uri = _normalized_text(self.uri)
        self.mime_type = _normalized_text(self.mime_type)
        self.metadata = dict(self.metadata)


@dataclass(slots=True)
class MCPToolCallResult:
    """Internal MCP tool result payload returned by the adapter layer."""

    mcp_tool_name: str
    status: MCPToolExecutionStatus
    content: list[MCPToolContent] = field(default_factory=list)
    structured_content: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    error_message: str | None = None

    def __post_init__(self) -> None:
        self.mcp_tool_name = _required_text(
            self.mcp_tool_name,
            "MCP tool name must not be empty.",
        )
        self.status = cast(
            MCPToolExecutionStatus,
            _normalize_literal(
                self.status,
                valid_values=_VALID_EXECUTION_STATUSES,
                default="failed",
                message="MCP tool execution status is invalid.",
            ),
        )
        self.content = list(self.content)
        self.structured_content = (
            None if self.structured_content is None else dict(self.structured_content)
        )
        self.metadata = dict(self.metadata)
        self.error_message = _normalized_text(self.error_message)

    @property
    def success(self) -> bool:
        return self.status == "completed"


@dataclass(slots=True)
class MCPToolStreamEvent:
    """Internal MCP streaming event emitted by the adapter layer."""

    type: MCPToolStreamEventType
    mcp_tool_name: str
    text: str | None = None
    progress: float | None = None
    result: MCPToolCallResult | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.type = cast(
            MCPToolStreamEventType,
            _normalize_literal(
                self.type,
                valid_values=_VALID_STREAM_EVENT_TYPES,
                default="error",
                message="MCP tool stream event type is invalid.",
            ),
        )
        self.mcp_tool_name = _required_text(
            self.mcp_tool_name,
            "MCP tool name must not be empty.",
        )
        self.text = _normalized_text(self.text)
        self.error_message = _normalized_text(self.error_message)
        self.metadata = dict(self.metadata)

    @classmethod
    def started(
        cls,
        *,
        mcp_tool_name: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> "MCPToolStreamEvent":
        return cls(
            type="started",
            mcp_tool_name=mcp_tool_name,
            metadata=dict(metadata or {}),
        )

    @classmethod
    def delta(
        cls,
        *,
        mcp_tool_name: str,
        text: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> "MCPToolStreamEvent":
        return cls(
            type="delta",
            mcp_tool_name=mcp_tool_name,
            text=text,
            metadata=dict(metadata or {}),
        )

    @classmethod
    def completed(
        cls,
        *,
        mcp_tool_name: str,
        result: MCPToolCallResult,
        metadata: Mapping[str, Any] | None = None,
    ) -> "MCPToolStreamEvent":
        return cls(
            type="completed",
            mcp_tool_name=mcp_tool_name,
            result=result,
            metadata=dict(metadata or {}),
        )

    @classmethod
    def error_event(
        cls,
        *,
        mcp_tool_name: str,
        error_message: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> "MCPToolStreamEvent":
        return cls(
            type="error",
            mcp_tool_name=mcp_tool_name,
            error_message=error_message,
            metadata=dict(metadata or {}),
        )

    @classmethod
    def cancelled(
        cls,
        *,
        mcp_tool_name: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> "MCPToolStreamEvent":
        return cls(
            type="cancelled",
            mcp_tool_name=mcp_tool_name,
            metadata=dict(metadata or {}),
        )


@dataclass(slots=True)
class MCPHealthResult:
    """Safe MCP adapter health summary used by later gateway composition."""

    status: str
    configured: bool
    endpoint: str | None
    auth_mode: str
    tool_count: int
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.status = _required_text(self.status, "MCP health status must not be empty.")
        self.endpoint = _normalized_text(self.endpoint)
        self.auth_mode = _required_text(self.auth_mode, "MCP auth mode must not be empty.")
        self.error = _normalized_text(self.error)
        self.metadata = dict(self.metadata)


class MCPClientAdapter(Protocol):
    """Backend-owned adapter that is allowed to speak MCP protocol."""

    async def list_tools(self) -> list[MCPToolDefinition]:
        ...

    async def call_tool(
        self,
        *,
        request: MCPToolCallRequest,
    ) -> MCPToolCallResult:
        ...

    def stream_tool(
        self,
        *,
        request: MCPToolCallRequest,
    ) -> AsyncIterator[MCPToolStreamEvent]:
        ...

    async def health(self) -> MCPHealthResult:
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


def _normalize_literal(
    value: object,
    *,
    valid_values: frozenset[str],
    default: str,
    message: str,
) -> str:
    normalized = _normalized_text(value)
    if normalized is None:
        return default
    if normalized not in valid_values:
        raise ValueError(message)
    return normalized