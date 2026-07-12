"""Reusable MCP tool plugin contracts and helpers."""

from app.tools_base.decorators import guard_tool_call, structured_tool_result
from app.tools_base.dataset_models import (
    DATASET_SCHEMA_VERSION,
    DatasetColumn,
    DatasetTimeRange,
    MetricSeriesQuery,
    StructuredDatasetResponse,
    STRUCTURED_DATASET_OUTPUT_SCHEMA,
    build_metric_series_query_summary,
    export_metric_series_query_json_schema,
    export_structured_dataset_response_json_schema,
    generate_dataset_id,
)
from app.tools_base.dataset_validation import (
    DatasetTransportLimits,
    normalize_structured_dataset_result,
    validate_structured_dataset_response,
)
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
    "DATASET_SCHEMA_VERSION",
    "DatasetColumn",
    "DatasetTimeRange",
    "DatasetTransportLimits",
    "ManifestCapability",
    "ManifestTool",
    "MetricSeriesQuery",
    "PluginFactory",
    "STRUCTURED_DATASET_OUTPUT_SCHEMA",
    "StructuredDatasetResponse",
    "ToolConfigSchema",
    "ToolDescriptor",
    "ToolErrorEnvelope",
    "ToolHealth",
    "ToolManifest",
    "ToolPlugin",
    "ToolResultEnvelope",
    "ToolResultSummary",
    "build_metric_series_query_summary",
    "export_metric_series_query_json_schema",
    "export_structured_dataset_response_json_schema",
    "generate_dataset_id",
    "guard_tool_call",
    "load_manifest",
    "load_tool_config",
    "normalize_structured_dataset_result",
    "structured_tool_result",
    "validate_structured_dataset_response",
    "validate_plugin_instance",
    "validate_tool_config",
]