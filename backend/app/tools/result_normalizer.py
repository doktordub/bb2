"""Normalize raw MCP adapter outputs into bounded public tool results."""

from __future__ import annotations

from dataclasses import dataclass
import json
from collections.abc import Mapping, Sequence
from typing import Any

from app.contracts.tools import (
    ToolErrorDetail,
    ToolExecutionResult,
    ToolResultContent,
    ToolResultSummary,
    ToolStreamEvent,
)
from app.observability.redaction import TRUNCATED_VALUE
from app.tools.errors import ToolResultTooLargeError
from app.tools.mcp.protocol_models import MCPToolCallResult, MCPToolContent, MCPToolStreamEvent
from app.tools.models import ResolvedToolDefinition
from app.tools.redaction import redact_tool_payload

_MAX_TEXT_BLOCK_CHARS = 12000
_MAX_CONTENT_BLOCKS = 20
_MAX_TABLE_ROWS = 100
_MAX_FILE_REFS = 50
_RESULT_OMITTED_TEXT = "Tool result omitted because it exceeded backend limits."
_STRUCTURED_DATASET_OUTPUT_SCHEMA = "structured_dataset_v1"


@dataclass(frozen=True, slots=True)
class _StructuredDatasetEnvelopeResult:
    status: str
    structured_content: dict[str, Any] | None
    metadata: dict[str, Any]
    error_detail: ToolErrorDetail | None = None
    result_count: int | None = None
    truncated: bool = False
    summary_message: str | None = None


class ToolResultNormalizer:
    """Convert raw adapter payloads into bounded backend-owned tool result models."""

    def __init__(
        self,
        *,
        default_max_result_bytes: int = 262144,
        max_text_block_chars: int = _MAX_TEXT_BLOCK_CHARS,
        max_content_blocks: int = _MAX_CONTENT_BLOCKS,
        max_table_rows: int = _MAX_TABLE_ROWS,
        max_file_refs: int = _MAX_FILE_REFS,
    ) -> None:
        self._default_max_result_bytes = default_max_result_bytes
        self._max_text_block_chars = max_text_block_chars
        self._max_content_blocks = max_content_blocks
        self._max_table_rows = max_table_rows
        self._max_file_refs = max_file_refs

    def normalize_result(
        self,
        definition: ResolvedToolDefinition,
        result: MCPToolCallResult,
        *,
        duration_ms: int | None = None,
    ) -> ToolExecutionResult:
        max_result_bytes = definition.max_result_bytes or self._default_max_result_bytes
        adapted_envelope = _adapt_structured_dataset_envelope(result.structured_content)
        effective_status = result.status if adapted_envelope is None else adapted_envelope.status
        normalized_content, content_truncated = self._normalize_content_blocks(result.content)
        structured_content, structured_truncated = self._normalize_structured_content(
            result.structured_content
            if adapted_envelope is None
            else adapted_envelope.structured_content
        )
        metadata = self._normalize_metadata(result.metadata)
        if adapted_envelope is not None and adapted_envelope.metadata:
            metadata.update(self._normalize_metadata(adapted_envelope.metadata))
        truncated = content_truncated or structured_truncated
        if adapted_envelope is not None:
            truncated = truncated or adapted_envelope.truncated

        error_detail: ToolErrorDetail | None = (
            None if adapted_envelope is None else adapted_envelope.error_detail
        )
        if effective_status != "completed" and error_detail is None:
            error_detail = ToolErrorDetail(
                code=_error_code_for_status(effective_status),
                message=_truncate_text(
                    result.error_message or "Tool execution failed.",
                    max_chars=512,
                ),
                category="tool_execution",
                retryable=effective_status == "timeout",
            )

        normalized_content, structured_content, metadata, reduced = self._fit_to_budget(
            content=normalized_content,
            structured_content=structured_content,
            metadata=metadata,
            max_result_bytes=max_result_bytes,
        )
        truncated = truncated or reduced

        bytes_returned = _payload_size_bytes(
            content=normalized_content,
            structured_content=structured_content,
            metadata=metadata,
        )
        summary = ToolResultSummary(
            result_count=(
                adapted_envelope.result_count
                if adapted_envelope is not None and adapted_envelope.result_count is not None
                else _infer_result_count(structured_content, normalized_content)
            ),
            bytes_returned=bytes_returned,
            truncated=truncated,
            safe_message=_summary_message(
                effective_status,
                truncated,
                error_detail,
                summary_message=(
                    None if adapted_envelope is None else adapted_envelope.summary_message
                ),
            ),
        )
        return ToolExecutionResult(
            tool_name=definition.logical_name,
            status=effective_status,
            content=normalized_content,
            structured_content=structured_content,
            summary=summary,
            duration_ms=duration_ms,
            metadata=metadata,
            error_detail=error_detail,
        )

    def normalize_stream_event(
        self,
        definition: ResolvedToolDefinition,
        event: MCPToolStreamEvent,
        *,
        duration_ms: int | None = None,
    ) -> ToolStreamEvent:
        metadata = self._normalize_metadata(event.metadata)
        if event.type == "started":
            return ToolStreamEvent.started(tool_name=definition.logical_name, metadata=metadata)
        if event.type == "progress":
            return ToolStreamEvent.progress_event(
                tool_name=definition.logical_name,
                progress=event.progress or 0.0,
                metadata=metadata,
            )
        if event.type == "delta":
            text = _truncate_text(event.text or "", max_chars=self._max_text_block_chars)
            return ToolStreamEvent.delta(
                tool_name=definition.logical_name,
                text=text,
                metadata=metadata,
            )
        if event.type == "metadata":
            return ToolStreamEvent(
                type="metadata",
                tool_name=definition.logical_name,
                metadata=metadata,
            )
        if event.type == "completed":
            normalized_result = self.normalize_result(
                definition,
                event.result or MCPToolCallResult(mcp_tool_name=event.mcp_tool_name, status="completed"),
                duration_ms=duration_ms,
            )
            return ToolStreamEvent.completed(
                tool_name=definition.logical_name,
                result=normalized_result,
                metadata=metadata,
            )
        if event.type == "cancelled":
            return ToolStreamEvent.cancelled(
                tool_name=definition.logical_name,
                metadata=metadata,
            )
        return ToolStreamEvent.error_event(
            tool_name=definition.logical_name,
            error=ToolErrorDetail(
                code="tool_stream_error",
                message=_truncate_text(event.error_message or "Tool stream failed.", max_chars=512),
                category="tool_stream",
                retryable=False,
            ),
            metadata=metadata,
        )

    def _normalize_content_blocks(
        self,
        content: Sequence[MCPToolContent],
    ) -> tuple[list[ToolResultContent], bool]:
        normalized: list[ToolResultContent] = []
        truncated = len(content) > self._max_content_blocks
        file_ref_count = 0
        for raw_item in content[: self._max_content_blocks]:
            item, item_truncated = self._normalize_content_item(raw_item)
            if item is None:
                continue
            if item.type in {"file_ref", "image_ref"}:
                file_ref_count += 1
                if file_ref_count > self._max_file_refs:
                    truncated = True
                    continue
            truncated = truncated or item_truncated
            normalized.append(item)
        return normalized, truncated

    def _normalize_content_item(
        self,
        item: MCPToolContent,
    ) -> tuple[ToolResultContent | None, bool]:
        metadata = self._normalize_metadata(item.metadata)
        if item.type == "text":
            if item.text is None:
                return None, False
            text = _truncate_text(item.text, max_chars=self._max_text_block_chars)
            return (
                ToolResultContent(type="text", text=text, metadata=metadata),
                text != item.text,
            )

        if item.type == "json":
            json_value = redact_tool_payload(item.json_value, max_chars=self._max_text_block_chars)
            return (
                ToolResultContent(type="json", json_value=json_value, metadata=metadata),
                json_value != item.json_value,
            )

        if item.type == "table":
            table_value, truncated = _normalize_table_value(
                item.json_value,
                max_rows=self._max_table_rows,
                max_chars=self._max_text_block_chars,
            )
            return (
                ToolResultContent(type="table", json_value=table_value, metadata=metadata),
                truncated,
            )

        if item.type in {"file_ref", "image_ref"}:
            return (
                ToolResultContent(
                    type=item.type,
                    uri=item.uri,
                    mime_type=item.mime_type,
                    metadata=metadata,
                ),
                False,
            )

        return None, False

    def _normalize_structured_content(
        self,
        structured_content: Mapping[str, Any] | None,
    ) -> tuple[dict[str, Any] | None, bool]:
        if structured_content is None:
            return None, False
        normalized = redact_tool_payload(
            structured_content,
            max_chars=self._max_text_block_chars,
        )
        if isinstance(normalized, dict):
            return normalized, normalized != dict(structured_content)
        return {"value": normalized}, True

    def _normalize_metadata(self, metadata: Mapping[str, Any]) -> dict[str, Any]:
        normalized = redact_tool_payload(metadata, max_chars=512)
        return normalized if isinstance(normalized, dict) else {}

    def _fit_to_budget(
        self,
        *,
        content: list[ToolResultContent],
        structured_content: dict[str, Any] | None,
        metadata: dict[str, Any],
        max_result_bytes: int,
    ) -> tuple[list[ToolResultContent], dict[str, Any] | None, dict[str, Any], bool]:
        current_content = list(content)
        current_structured = structured_content
        current_metadata = dict(metadata)
        if _payload_size_bytes(
            content=current_content,
            structured_content=current_structured,
            metadata=current_metadata,
        ) <= max_result_bytes:
            return current_content, current_structured, current_metadata, False

        reduced = True
        current_structured = None
        current_metadata = {"truncated": True}
        if _payload_size_bytes(
            content=current_content,
            structured_content=current_structured,
            metadata=current_metadata,
        ) <= max_result_bytes:
            return current_content, current_structured, current_metadata, reduced

        while len(current_content) > 1:
            current_content.pop()
            if _payload_size_bytes(
                content=current_content,
                structured_content=current_structured,
                metadata=current_metadata,
            ) <= max_result_bytes:
                return current_content, current_structured, current_metadata, reduced

        if current_content:
            current_content = [self._reduce_content_block(current_content[0])]
            if _payload_size_bytes(
                content=current_content,
                structured_content=current_structured,
                metadata=current_metadata,
            ) <= max_result_bytes:
                return current_content, current_structured, current_metadata, reduced

        placeholder = [
            ToolResultContent(
                type="text",
                text=_RESULT_OMITTED_TEXT,
                metadata={"truncated": True},
            )
        ]
        if _payload_size_bytes(
            content=placeholder,
            structured_content=None,
            metadata=current_metadata,
        ) <= max_result_bytes:
            return placeholder, None, current_metadata, reduced
        raise ToolResultTooLargeError("Tool result exceeded configured backend result limits.")

    def _reduce_content_block(self, block: ToolResultContent) -> ToolResultContent:
        metadata = {**block.metadata, "truncated": True}
        if block.type == "text" and block.text is not None:
            return ToolResultContent(
                type="text",
                text=_truncate_text(block.text, max_chars=max(16, self._max_text_block_chars // 4)),
                metadata=metadata,
            )
        if block.type in {"json", "table"}:
            reduced_json = _shrink_json_value(block.json_value)
            return ToolResultContent(type=block.type, json_value=reduced_json, metadata=metadata)
        return ToolResultContent(
            type="text",
            text=_RESULT_OMITTED_TEXT,
            metadata=metadata,
        )


def _normalize_table_value(
    value: Any,
    *,
    max_rows: int,
    max_chars: int,
) -> tuple[Any, bool]:
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        rows = list(value)
        truncated = len(rows) > max_rows
        safe_rows = rows[:max_rows]
        return redact_tool_payload(safe_rows, max_chars=max_chars), truncated

    if isinstance(value, Mapping) and isinstance(value.get("rows"), Sequence):
        rows_value = value.get("rows")
        assert isinstance(rows_value, Sequence)
        rows = list(rows_value)
        truncated = len(rows) > max_rows
        safe_rows = rows[:max_rows]
        payload = {**value, "rows": safe_rows}
        return redact_tool_payload(payload, max_chars=max_chars), truncated

    normalized = redact_tool_payload(value, max_chars=max_chars)
    return normalized, normalized != value


def _infer_result_count(
    structured_content: Mapping[str, Any] | None,
    content: Sequence[ToolResultContent],
) -> int | None:
    if structured_content is not None:
        results_value = structured_content.get("results")
        if isinstance(results_value, Sequence) and not isinstance(results_value, str | bytes | bytearray):
            return len(results_value)
        rows_value = structured_content.get("rows")
        if isinstance(rows_value, Sequence) and not isinstance(rows_value, str | bytes | bytearray):
            return len(rows_value)
    if not content:
        return 0
    if len(content) == 1 and content[0].type == "table":
        table_value = content[0].json_value
        if isinstance(table_value, Sequence) and not isinstance(table_value, str | bytes | bytearray):
            return len(table_value)
        if isinstance(table_value, Mapping):
            rows_value = table_value.get("rows")
            if isinstance(rows_value, Sequence) and not isinstance(rows_value, str | bytes | bytearray):
                return len(rows_value)
    return len(content)


def _summary_message(
    status: str,
    truncated: bool,
    error_detail: ToolErrorDetail | None,
    *,
    summary_message: str | None = None,
) -> str | None:
    if error_detail is not None:
        return summary_message or error_detail.message
    if status == "completed" and truncated:
        return summary_message or "Tool result truncated to backend limits."
    return None


def _adapt_structured_dataset_envelope(
    structured_content: Mapping[str, Any] | None,
) -> _StructuredDatasetEnvelopeResult | None:
    if structured_content is None:
        return None

    ok = structured_content.get("ok")
    meta = structured_content.get("meta")
    if not isinstance(ok, bool) or not isinstance(meta, Mapping):
        return None

    output_schema = meta.get("output_schema")
    if output_schema != _STRUCTURED_DATASET_OUTPUT_SCHEMA:
        return None

    summary = structured_content.get("summary")
    summary_message = None
    result_count = None
    truncated = False
    if isinstance(summary, Mapping):
        message_value = summary.get("message")
        if isinstance(message_value, str) and message_value.strip():
            summary_message = message_value.strip()
        item_count = summary.get("item_count")
        if isinstance(item_count, int) and item_count >= 0:
            result_count = item_count
        truncated = summary.get("truncated") is True

    metadata = {
        "output_schema": _STRUCTURED_DATASET_OUTPUT_SCHEMA,
        "schema_version": meta.get("schema_version"),
    }
    dataset_id = meta.get("dataset_id")
    if isinstance(dataset_id, str) and dataset_id.strip():
        metadata["dataset_id"] = dataset_id.strip()

    if ok:
        data = structured_content.get("data")
        dataset = data.get("dataset") if isinstance(data, Mapping) else None
        if isinstance(dataset, Mapping):
            return _StructuredDatasetEnvelopeResult(
                status="completed",
                structured_content=dict(dataset),
                metadata=metadata,
                result_count=result_count,
                truncated=truncated,
                summary_message=summary_message,
            )

        return _StructuredDatasetEnvelopeResult(
            status="failed",
            structured_content=None,
            metadata=metadata,
            error_detail=ToolErrorDetail(
                code="tool_contract_error",
                message="The MCP tool returned a structured dataset envelope without a dataset payload.",
                category="tool_contract",
                retryable=False,
            ),
            result_count=result_count,
            truncated=truncated,
            summary_message=summary_message,
        )

    error_detail = _error_detail_from_structured_dataset_envelope(
        structured_content,
        summary_message=summary_message,
    )
    return _StructuredDatasetEnvelopeResult(
        status=_status_for_structured_dataset_error(error_detail.code),
        structured_content=None,
        metadata=metadata,
        error_detail=error_detail,
        result_count=result_count,
        truncated=truncated,
        summary_message=summary_message,
    )


def _error_detail_from_structured_dataset_envelope(
    structured_content: Mapping[str, Any],
    *,
    summary_message: str | None,
) -> ToolErrorDetail:
    errors = structured_content.get("errors")
    if isinstance(errors, Sequence) and not isinstance(errors, str | bytes | bytearray):
        for item in errors:
            if not isinstance(item, Mapping):
                continue
            code = item.get("code")
            message = item.get("message")
            retryable = item.get("retryable")
            details = item.get("details")
            return ToolErrorDetail(
                code=(code.strip() if isinstance(code, str) and code.strip() else "tool_failed"),
                message=(
                    summary_message
                    or message.strip()
                    if isinstance(message, str) and message.strip()
                    else "The MCP tool returned an error result."
                ),
                category="tool_execution",
                retryable=retryable if isinstance(retryable, bool) else None,
                metadata=dict(details) if isinstance(details, Mapping) else {},
            )

    return ToolErrorDetail(
        code="tool_failed",
        message=summary_message or "The MCP tool returned an error result.",
        category="tool_execution",
        retryable=False,
    )


def _status_for_structured_dataset_error(code: str) -> str:
    if code == "timeout":
        return "timeout"
    if code == "cancelled":
        return "cancelled"
    return "failed"


def _payload_size_bytes(
    *,
    content: Sequence[ToolResultContent],
    structured_content: Mapping[str, Any] | None,
    metadata: Mapping[str, Any],
) -> int:
    payload = {
        "content": [_content_to_dict(item) for item in content],
        "structured_content": structured_content,
        "metadata": metadata,
    }
    return len(
        json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )


def _content_to_dict(item: ToolResultContent) -> dict[str, Any]:
    return {
        "type": item.type,
        "text": item.text,
        "json_value": item.json_value,
        "uri": item.uri,
        "mime_type": item.mime_type,
        "metadata": item.metadata,
    }


def _truncate_text(text: str, *, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    if max_chars <= len(TRUNCATED_VALUE):
        return TRUNCATED_VALUE[:max_chars]
    return f"{text[: max_chars - len(TRUNCATED_VALUE)]}{TRUNCATED_VALUE}"


def _shrink_json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {"truncated": True}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        if not value:
            return []
        return [redact_tool_payload(value[0], max_chars=256), {"truncated": True}]
    if isinstance(value, str):
        return _truncate_text(value, max_chars=256)
    return {"truncated": True}


def _error_code_for_status(status: str) -> str:
    if status == "timeout":
        return "tool_timeout"
    if status == "cancelled":
        return "tool_cancelled"
    return "tool_failed"
