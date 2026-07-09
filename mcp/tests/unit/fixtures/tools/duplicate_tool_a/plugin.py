from __future__ import annotations

from dataclasses import dataclass, field

from fastmcp import FastMCP

from app.context import ToolRuntimeContext
from app.tools_base.models import CapabilityDescriptor, ToolHealth
from app.tools_base.plugin import ToolPlugin


@dataclass(slots=True)
class DuplicateToolAPlugin:
    context: ToolRuntimeContext
    name: str = "duplicate_tool_a"
    version: str = "1.0.0"
    capabilities: list[CapabilityDescriptor] = field(
        default_factory=lambda: [
            CapabilityDescriptor(
                name="duplicate.echo",
                type="tool",
                description="Duplicate fixture capability.",
                risk_level="read_only",
            )
        ]
    )

    def register(self, mcp: FastMCP) -> None:
        @mcp.tool(name="duplicate.echo")
        def echo() -> dict[str, object]:
            return {"ok": True, "tool_name": "duplicate.echo"}

    async def health(self) -> ToolHealth:
        return ToolHealth(state="ok")


def create_plugin(context: ToolRuntimeContext) -> ToolPlugin:
    return DuplicateToolAPlugin(context)
