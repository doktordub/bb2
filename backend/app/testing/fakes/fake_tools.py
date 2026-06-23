"""In-memory fake tool gateway for contract-focused tests."""

from __future__ import annotations

from app.contracts.context import OrchestrationContext
from app.contracts.tools import ToolCallRequest, ToolResult, ToolSpec


class FakeToolGateway:
    """Deterministic tool fake that records logical tool calls."""

    def __init__(self, tools: list[ToolSpec] | None = None) -> None:
        self.tools = list(tools or [])
        self.calls: list[ToolCallRequest] = []
        self.contexts: list[OrchestrationContext] = []

    async def list_tools(self, context: OrchestrationContext) -> list[ToolSpec]:
        self.contexts.append(context)
        return list(self.tools)

    async def call_tool(
        self,
        request: ToolCallRequest,
        context: OrchestrationContext,
    ) -> ToolResult:
        self.calls.append(request)
        self.contexts.append(context)
        return ToolResult(
            tool_name=request.tool_name,
            success=True,
            data={"fake": True, "arguments": dict(request.arguments)},
        )