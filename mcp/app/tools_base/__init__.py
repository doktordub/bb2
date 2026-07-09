"""Reusable MCP tool plugin contracts and helpers."""

from app.tools_base.decorators import guard_tool_call, structured_tool_result
from app.tools_base.manifest import ManifestCapability, ManifestTool, ToolConfigSchema, ToolManifest
from app.tools_base.models import CapabilityDescriptor, ToolDescriptor, ToolHealth
from app.tools_base.plugin import PluginFactory, ToolPlugin
from app.tools_base.results import ToolErrorEnvelope, ToolResultEnvelope, ToolResultSummary
from app.tools_base.validation import (
    load_manifest,
    load_tool_config,
    validate_plugin_instance,
    validate_tool_config,
)

__all__ = [
    "CapabilityDescriptor",
    "ManifestCapability",
    "ManifestTool",
    "PluginFactory",
    "ToolConfigSchema",
    "ToolDescriptor",
    "ToolErrorEnvelope",
    "ToolHealth",
    "ToolManifest",
    "ToolPlugin",
    "ToolResultEnvelope",
    "ToolResultSummary",
    "guard_tool_call",
    "load_manifest",
    "load_tool_config",
    "structured_tool_result",
    "validate_plugin_instance",
    "validate_tool_config",
]