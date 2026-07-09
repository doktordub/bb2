"""Tool plugin protocol definitions."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, runtime_checkable

from fastmcp import FastMCP

from app.context import ToolRuntimeContext
from app.tools_base.models import CapabilityDescriptor, ToolHealth


@runtime_checkable
class ToolPlugin(Protocol):
    """Protocol that every MCP tool plugin must implement."""

    name: str
    version: str
    capabilities: list[CapabilityDescriptor]

    def register(self, mcp: FastMCP) -> None:
        ...

    async def health(self) -> ToolHealth:
        ...


PluginFactory = Callable[[ToolRuntimeContext], ToolPlugin]