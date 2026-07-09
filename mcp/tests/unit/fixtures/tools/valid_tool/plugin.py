from __future__ import annotations

from dataclasses import dataclass, field

from fastmcp import FastMCP

from app.context import ToolRuntimeContext
from app.tools_base.models import CapabilityDescriptor, ToolHealth
from app.tools_base.plugin import ToolPlugin


@dataclass(slots=True)
class ValidToolPlugin:
    context: ToolRuntimeContext
    name: str = "valid_tool"
    version: str = "1.0.0"
    capabilities: list[CapabilityDescriptor] = field(
        default_factory=lambda: [
            CapabilityDescriptor(
                name="valid.echo",
                type="tool",
                description="Return the configured fixture label.",
                risk_level="read_only",
            )
        ]
    )

    def register(self, mcp: FastMCP) -> None:
        @mcp.tool(name="valid.echo")
        def echo() -> dict[str, object]:
            return {
                "ok": True,
                "tool_name": "valid.echo",
                "data": {
                    "label": str(self.context.tool_config["label"]),
                },
            }

    async def health(self) -> ToolHealth:
        return ToolHealth(state="ok")


def create_plugin(context: ToolRuntimeContext) -> ToolPlugin:
    return ValidToolPlugin(context)
