"""In-memory fake tool gateway for contract-focused tests."""

from __future__ import annotations

from collections.abc import AsyncIterator

from app.contracts.context import OrchestrationContext
from app.contracts.tools import (
    ToolCallRequest,
    ToolCapabilitiesResult,
    ToolCapabilitySummary,
    ToolDefinition,
    ToolErrorDetail,
    ToolExecutionRequest,
    ToolExecutionResult,
    ToolHealthResult,
    ToolListFilters,
    ToolListResult,
    ToolResult,
    ToolResultContent,
    ToolResultSummary,
    ToolSpec,
    ToolStreamEvent,
)


class FakeToolGateway:
    """Deterministic fake gateway that implements the full public tool surface."""

    def __init__(
        self,
        tools: list[ToolDefinition] | None = None,
        *,
        execution_results: dict[str, ToolExecutionResult] | None = None,
        enabled: bool = True,
    ) -> None:
        self.tools = list(tools or [])
        self.execution_results = dict(execution_results or {})
        self.enabled = enabled
        self.calls: list[ToolExecutionRequest] = []
        self.stream_calls: list[ToolExecutionRequest] = []
        self.contexts: list[OrchestrationContext] = []
        self.list_filters: list[ToolListFilters | None] = []

    async def list_tools(
        self,
        context: OrchestrationContext,
        filters: ToolListFilters | None = None,
    ) -> ToolListResult:
        self.contexts.append(context)
        self.list_filters.append(filters)
        tools = [tool for tool in self.tools if _matches_filters(tool, filters)]
        return ToolListResult(tools=tools)

    async def get_tool(
        self,
        tool_name: str,
        context: OrchestrationContext,
    ) -> ToolDefinition | None:
        self.contexts.append(context)
        for tool in self.tools:
            if tool.name == tool_name:
                return tool
        return None

    async def execute(
        self,
        request: ToolExecutionRequest,
        context: OrchestrationContext,
    ) -> ToolExecutionResult:
        self.calls.append(request)
        self.contexts.append(context)
        return self._resolve_result(request)

    async def call_tool(
        self,
        request: ToolCallRequest,
        context: OrchestrationContext,
    ) -> ToolResult:
        return await self.execute(request, context)

    async def stream_execute(
        self,
        request: ToolExecutionRequest,
        context: OrchestrationContext,
    ) -> AsyncIterator[ToolStreamEvent]:
        self.stream_calls.append(request)
        self.contexts.append(context)
        result = self._resolve_result(request)

        yield ToolStreamEvent.started(tool_name=request.tool_name)
        for item in result.content:
            if item.type == "text" and item.text:
                yield ToolStreamEvent.delta(tool_name=request.tool_name, text=item.text)

        if result.status == "completed":
            yield ToolStreamEvent.completed(tool_name=request.tool_name, result=result)
            return
        if result.status == "cancelled":
            yield ToolStreamEvent.cancelled(tool_name=request.tool_name, metadata=result.metadata)
            return

        yield ToolStreamEvent.error_event(
            tool_name=request.tool_name,
            error=result.error_detail
            or ToolErrorDetail(code="tool_failed", message=result.error or "Tool failed."),
            metadata=result.metadata,
        )

    async def health(self) -> ToolHealthResult:
        return ToolHealthResult(
            status="ok" if self.enabled else "disabled",
            tooling_enabled=self.enabled,
            mcp_configured=False,
            mcp_status="fake",
            tools_configured=len(self.tools),
            tools_discovered=len(self.tools),
            tools_enabled=sum(1 for tool in self.tools if tool.enabled),
            registry_status="ok",
            metadata={"provider": "fake"},
        )

    async def capabilities(self) -> ToolCapabilitiesResult:
        available_tools = [
            ToolCapabilitySummary.from_definition(tool)
            for tool in self.tools
            if tool.enabled
        ]
        return ToolCapabilitiesResult(
            enabled=self.enabled,
            mcp_configured=False,
            streaming_supported=any(tool.supports_streaming for tool in self.tools if tool.enabled),
            available_logical_tools=available_tools,
            metadata={"provider": "fake"},
        )

    def _resolve_result(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        configured = self.execution_results.get(request.tool_name)
        if configured is not None:
            return configured
        return ToolExecutionResult(
            tool_name=request.tool_name,
            status="completed",
            content=[
                ToolResultContent(
                    type="text",
                    text=f"Fake tool call completed: {request.tool_name}",
                )
            ],
            structured_content={"fake": True, "arguments": dict(request.arguments)},
            summary=ToolResultSummary(
                result_count=1,
                safe_message="Fake tool call completed.",
            ),
        )


def _matches_filters(tool: ToolSpec, filters: ToolListFilters | None) -> bool:
    if filters is None:
        return True
    if filters.enabled_only and not tool.enabled:
        return False
    if filters.names and tool.name not in filters.names:
        return False
    if filters.tags and not set(filters.tags).issubset(tool.tags):
        return False
    if filters.safety_levels and tool.safety_level not in filters.safety_levels:
        return False
    if filters.execution_mode and filters.execution_mode not in tool.execution_modes:
        return False
    if filters.approval_required is not None and tool.approval_required != filters.approval_required:
        return False
    if filters.name_prefix and not tool.name.startswith(filters.name_prefix):
        return False
    return True