"""Tool gateway contracts and normalized tool payloads."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from app.contracts.context import OrchestrationContext


@dataclass(slots=True)
class ToolSpec:
    """Logical description of a tool exposed to agents."""

    name: str
    description: str
    input_schema: dict[str, Any]
    source: str
    permissions: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ToolCallRequest:
    """Normalized request for a tool call."""

    tool_name: str
    arguments: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ToolResult:
    """Normalized result of a logical tool call."""

    tool_name: str
    success: bool
    data: Any | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class ToolGateway(Protocol):
    """Provider-neutral tool access used by agents and strategies."""

    async def list_tools(self, context: OrchestrationContext) -> list[ToolSpec]:
        ...

    async def call_tool(
        self,
        request: ToolCallRequest,
        context: OrchestrationContext,
    ) -> ToolResult:
        ...