"""FastMCP plugin registration for the websearch tool."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from fastmcp import FastMCP

from app.context import ToolRuntimeContext
from app.tools_base.decorators import guard_tool_call, observe_tool_call
from app.tools_base.models import CapabilityDescriptor, ToolHealth
from app.tools_base.plugin import ToolPlugin

from tools.websearch.models import (
    SafeSearchValue,
    TimeLimitValue,
    WebSearchRequest,
    WebSearchResponse,
)
from tools.websearch.service import WebSearchService


class WebSearchRuntimeService(Protocol):
    """Protocol for the service surface used by the plugin wrapper."""

    async def search(self, request: WebSearchRequest) -> WebSearchResponse:
        ...

    def health_payload(self) -> dict[str, str]:
        ...


@dataclass(slots=True)
class WebSearchPlugin:
    """Plugin that exposes public web text search through DDGS."""

    context: ToolRuntimeContext
    service: WebSearchRuntimeService | None = None
    name: str = "websearch"
    version: str = "1.0.0"
    capabilities: list[CapabilityDescriptor] = field(
        default_factory=lambda: [
            CapabilityDescriptor(
                name="web.search",
                type="tool",
                description="Search public web results.",
                risk_level="read_only",
            )
        ]
    )

    def __post_init__(self) -> None:
        if self.service is None:
            self.service = WebSearchService(self.context)

    def register(self, mcp: FastMCP) -> None:
        service = self.service
        assert service is not None

        @mcp.tool(
            name="websearch.search",
            description="Search public web results using DuckDuckGo/DDGS.",
        )
        @observe_tool_call(
            self.context,
            "websearch.search",
            capability_name="web.search",
            timeout_seconds=int(self.context.tool_config.get("timeout_seconds", 20)),
        )
        @guard_tool_call(self.context, "websearch.search")
        async def search(
            query: str,
            max_results: int = 5,
            region: str | None = None,
            safesearch: SafeSearchValue | None = None,
            time_limit: TimeLimitValue | None = None,
        ) -> dict[str, object]:
            request = WebSearchRequest(
                query=query,
                max_results=max_results,
                region=region,
                safesearch=safesearch,
                time_limit=time_limit,
            )
            response = await service.search(request)
            return response.model_dump(mode="json")

    async def health(self) -> ToolHealth:
        service = self.service
        assert service is not None
        return ToolHealth(state="ok", details=service.health_payload())


def create_plugin(context: ToolRuntimeContext) -> ToolPlugin:
    return WebSearchPlugin(context)