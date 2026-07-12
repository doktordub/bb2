"""Validation and normalization helpers for structured dataset tool results."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from app.tools_base.dataset_models import (
    StructuredDatasetResponse,
    STRUCTURED_DATASET_OUTPUT_SCHEMA,
    bound_text,
)
from app.tools_base.results import ToolResultEnvelope, ToolResultSummary


@dataclass(frozen=True, slots=True)
class DatasetTransportLimits:
    """Shared transport limits for visualization-ready dataset payloads."""

    max_metadata_bytes: int = 8192
    max_result_bytes: int = 262144


def measure_json_bytes(value: Any) -> int:
    """Return the UTF-8 byte size of one JSON-safe payload."""

    serialized = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return len(serialized.encode("utf-8"))


def validate_structured_dataset_response(
    dataset: StructuredDatasetResponse | dict[str, Any],
    *,
    limits: DatasetTransportLimits | None = None,
) -> StructuredDatasetResponse:
    """Validate dataset shape plus transport-size bounds."""

    resolved_limits = limits or DatasetTransportLimits()
    validated = (
        dataset
        if isinstance(dataset, StructuredDatasetResponse)
        else StructuredDatasetResponse.model_validate(dataset)
    )

    metadata_payload = {
        "source": validated.source,
        "query_summary": validated.query_summary,
        "time_range": validated.time_range.model_dump(mode="json")
        if validated.time_range is not None
        else None,
        "warnings": validated.warnings,
        "provenance": validated.provenance,
    }
    metadata_bytes = measure_json_bytes(metadata_payload)
    if metadata_bytes > resolved_limits.max_metadata_bytes:
        raise ValueError(
            "dataset metadata exceeds max_metadata_bytes "
            f"({metadata_bytes} > {resolved_limits.max_metadata_bytes})."
        )

    dataset_payload = validated.model_dump(mode="json")
    dataset_bytes = measure_json_bytes(dataset_payload)
    if dataset_bytes > resolved_limits.max_result_bytes:
        raise ValueError(
            "dataset payload exceeds max_result_bytes "
            f"({dataset_bytes} > {resolved_limits.max_result_bytes})."
        )
    return validated


def normalize_structured_dataset_result(
    *,
    tool_name: str,
    dataset: StructuredDatasetResponse | dict[str, Any],
    summary_message: str | None = None,
    output_schema: str = STRUCTURED_DATASET_OUTPUT_SCHEMA,
    limits: DatasetTransportLimits | None = None,
) -> ToolResultEnvelope:
    """Wrap a validated dataset payload in the shared MCP result envelope."""

    validated = validate_structured_dataset_response(dataset, limits=limits)
    message = bound_text(summary_message or validated.query_summary, max_chars=240)
    envelope = ToolResultEnvelope(
        ok=True,
        tool_name=tool_name,
        summary=ToolResultSummary(
            message=message,
            item_count=validated.row_count,
            truncated=validated.truncated,
        ),
        data={"dataset": validated.model_dump(mode="json")},
        meta={
            "schema_version": validated.schema_version,
            "output_schema": output_schema,
            "dataset_id": validated.dataset_id,
        },
    )

    resolved_limits = limits or DatasetTransportLimits()
    envelope_bytes = measure_json_bytes(envelope.model_dump(mode="json"))
    if envelope_bytes > resolved_limits.max_result_bytes:
        raise ValueError(
            "normalized tool result exceeds max_result_bytes "
            f"({envelope_bytes} > {resolved_limits.max_result_bytes})."
        )
    return envelope