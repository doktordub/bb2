"""Example MCP plugin used to exercise the tool contract."""

from __future__ import annotations

from dataclasses import dataclass, field

from fastmcp import FastMCP

from app.context import ToolRuntimeContext
from app.tools_base.models import CapabilityDescriptor, ToolHealth
from app.tools_base.decorators import guard_tool_call
from app.tools_base.plugin import ToolPlugin
from app.tools_base.results import ToolResultEnvelope, ToolResultSummary


@dataclass(slots=True)
class ExampleToolPlugin:
    """Small example plugin that exposes a bounded echo tool."""

    context: ToolRuntimeContext
    name: str = "example_tool"
    version: str = "1.0.0"
    capabilities: list[CapabilityDescriptor] = field(
        default_factory=lambda: [
            CapabilityDescriptor(
                name="example.echo",
                type="tool",
                description="Echo bounded text for plugin contract validation.",
                risk_level="read_only",
            )
        ]
    )

    def register(self, mcp: FastMCP) -> None:
        prefix = str(self.context.tool_config.get("default_prefix", "example"))
        allow_uppercase = bool(self.context.tool_config.get("allow_uppercase", True))

        @mcp.tool(name="example.echo", description="Return a bounded echo response for contract validation.")
        @guard_tool_call(self.context, "example.echo")
        def echo(message: str, uppercase: bool = False) -> dict[str, object]:
            normalized_message = message.strip()
            if not normalized_message:
                raise ValueError("message must not be blank.")
            if len(normalized_message) > 200:
                raise ValueError("message must be at most 200 characters long.")

            uppercase_applied = bool(uppercase and allow_uppercase)
            final_message = normalized_message.upper() if uppercase_applied else normalized_message
            self.context.rate_limiter.check("example.echo")
            self.context.logger.info(
                "mcp.tool.example.echo",
                payload={
                    "message_length": len(normalized_message),
                    "uppercase_requested": bool(uppercase),
                    "uppercase_applied": uppercase_applied,
                },
            )

            result = ToolResultEnvelope(
                tool_name="example.echo",
                summary=ToolResultSummary(message="Echo response generated.", item_count=1),
                data={
                    "message": f"{prefix}: {final_message}",
                    "uppercase_applied": uppercase_applied,
                    "prefix": prefix,
                },
                meta={"capability": "example.echo"},
            )
            return result.model_dump(mode="python")

    async def health(self) -> ToolHealth:
        return ToolHealth(
            state="ok",
            details={
                "tool_name": self.name,
                "configured_prefix": str(self.context.tool_config.get("default_prefix", "example")),
            },
        )


def create_plugin(context: ToolRuntimeContext) -> ToolPlugin:
    return ExampleToolPlugin(context)