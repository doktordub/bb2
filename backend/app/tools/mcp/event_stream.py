"""Helpers for mapping MCP library models into backend-owned adapter DTOs."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import mcp.types as mcp_types

from app.tools.mcp.protocol_models import (
    MCPToolCallResult,
    MCPToolContent,
    MCPToolDefinition,
    MCPToolStreamEvent,
)


def tool_to_definition(tool: mcp_types.Tool) -> MCPToolDefinition:
    """Convert an MCP library tool model into the backend's internal tool DTO."""

    metadata: dict[str, Any] = {}
    if tool.annotations is not None:
        if tool.annotations.title is not None:
            metadata["title"] = tool.annotations.title
        if tool.annotations.readOnlyHint is not None:
            metadata["read_only_hint"] = tool.annotations.readOnlyHint
        if tool.annotations.destructiveHint is not None:
            metadata["destructive_hint"] = tool.annotations.destructiveHint
        if tool.annotations.idempotentHint is not None:
            metadata["idempotent_hint"] = tool.annotations.idempotentHint
        if tool.annotations.openWorldHint is not None:
            metadata["open_world_hint"] = tool.annotations.openWorldHint
    if tool.execution is not None and tool.execution.taskSupport is not None:
        metadata["task_support"] = tool.execution.taskSupport
    if isinstance(tool.meta, Mapping):
        explicit_streaming = tool.meta.get("supports_streaming")
        if isinstance(explicit_streaming, bool):
            metadata["supports_streaming"] = explicit_streaming
        camel_streaming = tool.meta.get("supportsStreaming")
        if isinstance(camel_streaming, bool):
            metadata["supports_streaming"] = camel_streaming

    supports_streaming = bool(metadata.get("supports_streaming", False))
    return MCPToolDefinition(
        name=tool.name,
        description=tool.description,
        input_schema=dict(tool.inputSchema),
        output_schema=(None if tool.outputSchema is None else dict(tool.outputSchema)),
        supports_streaming=supports_streaming,
        metadata=metadata,
    )


def call_tool_result_to_result(
    mcp_tool_name: str,
    result: mcp_types.CallToolResult,
) -> MCPToolCallResult:
    """Convert an MCP library CallToolResult into the backend's internal result DTO."""

    return MCPToolCallResult(
        mcp_tool_name=mcp_tool_name,
        status="failed" if result.isError else "completed",
        content=[_content_block_to_content(block) for block in result.content],
        structured_content=(
            None if result.structuredContent is None else dict(result.structuredContent)
        ),
        metadata=_safe_result_metadata(result),
        error_message=(
            _extract_result_error_message(result) if result.isError else None
        ),
    )


def transport_payload_to_event(
    mcp_tool_name: str,
    payload: Mapping[str, Any],
) -> MCPToolStreamEvent:
    """Convert a transport stream payload into the backend's internal stream event."""

    event_type = str(payload.get("type") or "error")
    if event_type == "started":
        return MCPToolStreamEvent.started(
            mcp_tool_name=mcp_tool_name,
            metadata=_event_metadata(payload),
        )
    if event_type == "progress":
        return MCPToolStreamEvent(
            type="progress",
            mcp_tool_name=mcp_tool_name,
            progress=_coerce_progress(payload.get("progress")),
            metadata=_event_metadata(payload),
        )
    if event_type == "delta":
        return MCPToolStreamEvent.delta(
            mcp_tool_name=mcp_tool_name,
            text=str(payload.get("text") or ""),
            metadata=_event_metadata(payload),
        )
    if event_type == "cancelled":
        return MCPToolStreamEvent.cancelled(
            mcp_tool_name=mcp_tool_name,
            metadata=_event_metadata(payload),
        )
    if event_type == "completed":
        result = _coerce_call_tool_result(payload.get("result"))
        return MCPToolStreamEvent.completed(
            mcp_tool_name=mcp_tool_name,
            result=call_tool_result_to_result(mcp_tool_name, result),
            metadata=_event_metadata(payload),
        )
    return MCPToolStreamEvent.error_event(
        mcp_tool_name=mcp_tool_name,
        error_message=_event_error_message(payload),
        metadata=_event_metadata(payload),
    )


def extract_error_message_from_call_result(result: mcp_types.CallToolResult) -> str:
    """Build a safe one-line error summary from an MCP CallToolResult."""

    return _extract_result_error_message(result)


def _content_block_to_content(block: mcp_types.ContentBlock) -> MCPToolContent:
    if isinstance(block, mcp_types.TextContent):
        return MCPToolContent(type="text", text=block.text)
    if isinstance(block, mcp_types.ImageContent):
        return MCPToolContent(
            type="text",
            text=f"[image content omitted: {block.mimeType}]",
        )
    if isinstance(block, mcp_types.AudioContent):
        return MCPToolContent(
            type="text",
            text=f"[audio content omitted: {block.mimeType}]",
        )
    if isinstance(block, mcp_types.ResourceLink):
        return MCPToolContent(
            type="file_ref",
            uri=str(block.uri),
            mime_type=block.mimeType,
        )
    if isinstance(block, mcp_types.EmbeddedResource):
        resource = block.resource
        if isinstance(resource, mcp_types.TextResourceContents):
            return MCPToolContent(
                type="text",
                text=resource.text,
                metadata={
                    "resource_uri": str(resource.uri),
                    "mime_type": resource.mimeType,
                },
            )
        return MCPToolContent(
            type="file_ref",
            uri=str(resource.uri),
            mime_type=resource.mimeType,
            metadata={"embedded": True},
        )

    return MCPToolContent(type="text", text="[unsupported MCP content omitted]")


def _safe_result_metadata(result: mcp_types.CallToolResult) -> dict[str, Any]:
    metadata: dict[str, Any] = {"is_error": result.isError}
    if isinstance(result.meta, Mapping) and result.meta:
        metadata["meta_keys"] = sorted(str(key) for key in result.meta)
    return metadata


def _extract_result_error_message(result: mcp_types.CallToolResult) -> str:
    for block in result.content:
        if isinstance(block, mcp_types.TextContent):
            text = block.text.strip()
            if text:
                return text
    structured = result.structuredContent
    if isinstance(structured, Mapping):
        message = structured.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
        error = structured.get("error")
        if isinstance(error, str) and error.strip():
            return error.strip()
    return "The MCP tool returned an error result."


def _event_metadata(payload: Mapping[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for key in ("message", "total"):
        value = payload.get(key)
        if value is not None:
            metadata[key] = value

    payload_metadata = payload.get("metadata")
    if isinstance(payload_metadata, Mapping):
        for key, value in payload_metadata.items():
            metadata[str(key)] = value
    return metadata


def _coerce_progress(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _coerce_call_tool_result(value: object) -> mcp_types.CallToolResult:
    if isinstance(value, mcp_types.CallToolResult):
        return value
    if isinstance(value, Mapping):
        return mcp_types.CallToolResult.model_validate(dict(value))
    raise ValueError("MCP stream completion payload was missing a valid tool result.")


def _event_error_message(payload: Mapping[str, Any]) -> str:
    message = payload.get("error_message")
    if isinstance(message, str) and message.strip():
        return message.strip()
    return "The MCP stream failed."


__all__ = [
    "call_tool_result_to_result",
    "extract_error_message_from_call_result",
    "tool_to_definition",
    "transport_payload_to_event",
]