from __future__ import annotations

import pytest

from app.observability.redaction import REDACTED_VALUE, TRUNCATED_VALUE
from app.tools.errors import ToolResultTooLargeError
from app.tools.mcp import MCPToolCallResult, MCPToolContent, MCPToolStreamEvent
from app.tools.models import ResolvedToolDefinition
from app.tools.result_normalizer import ToolResultNormalizer


def build_definition(
    *,
    logical_name: str = "documents.search",
    mcp_tool_name: str | None = None,
    max_result_bytes: int = 32768,
) -> ResolvedToolDefinition:
    return ResolvedToolDefinition(
        logical_name=logical_name,
        mcp_tool_name=mcp_tool_name or logical_name,
        max_result_bytes=max_result_bytes,
    )


def test_result_normalizer_truncates_and_redacts_large_payloads() -> None:
    normalizer = ToolResultNormalizer(default_max_result_bytes=4096)
    raw_result = MCPToolCallResult(
        mcp_tool_name="documents.search",
        status="completed",
        content=[
            MCPToolContent(type="text", text="a" * 13000),
            MCPToolContent(
                type="table",
                json_value=[{"name": f"row-{index}", "api_key": "secret"} for index in range(120)],
            ),
        ],
        structured_content={"token": "secret", "rows": [{"name": "first"}]},
        metadata={"api_key": "secret", "row_count": 120},
    )

    normalized = normalizer.normalize_result(build_definition(), raw_result, duration_ms=42)

    assert normalized.tool_name == "documents.search"
    assert normalized.summary is not None
    assert normalized.summary.truncated is True
    assert normalized.summary.bytes_returned is not None
    assert normalized.content[0].text is not None
    assert normalized.content[0].text.endswith(TRUNCATED_VALUE)
    assert isinstance(normalized.content[1].json_value, list)
    assert len(normalized.content[1].json_value) == 100
    first_row = normalized.content[1].json_value[0]
    assert isinstance(first_row, dict)
    assert first_row["api_key"] == REDACTED_VALUE
    assert normalized.structured_content == {"token": REDACTED_VALUE, "rows": [{"name": "first"}]}
    assert normalized.metadata["api_key"] == REDACTED_VALUE


def test_result_normalizer_maps_completed_and_error_stream_events() -> None:
    normalizer = ToolResultNormalizer(default_max_result_bytes=4096)
    completed = normalizer.normalize_stream_event(
        build_definition(),
        MCPToolStreamEvent.completed(
            mcp_tool_name="documents.search",
            result=MCPToolCallResult(
                mcp_tool_name="documents.search",
                status="completed",
                content=[MCPToolContent(type="text", text="ok")],
            ),
        ),
    )
    failed = normalizer.normalize_stream_event(
        build_definition(),
        MCPToolStreamEvent.error_event(
            mcp_tool_name="documents.search",
            error_message="adapter failed",
        ),
    )

    assert completed.type == "completed"
    assert completed.result is not None
    assert completed.result.content[0].text == "ok"
    assert failed.type == "error"
    assert failed.error is not None
    assert failed.error.code == "tool_stream_error"
    assert failed.error.message == "adapter failed"


def test_result_normalizer_raises_when_budget_is_too_small_for_any_safe_payload() -> None:
    normalizer = ToolResultNormalizer(default_max_result_bytes=4096)
    raw_result = MCPToolCallResult(
        mcp_tool_name="documents.search",
        status="completed",
        content=[MCPToolContent(type="text", text="oversized")],
    )

    with pytest.raises(ToolResultTooLargeError):
        normalizer.normalize_result(build_definition(max_result_bytes=8), raw_result)


def test_result_normalizer_reduces_payload_to_fit_byte_budget() -> None:
    normalizer = ToolResultNormalizer(default_max_result_bytes=4096)
    raw_result = MCPToolCallResult(
        mcp_tool_name="documents.search",
        status="completed",
        content=[
            MCPToolContent(type="text", text="a" * 13000),
            MCPToolContent(
                type="table",
                json_value=[{"name": f"row-{index}", "api_key": "secret"} for index in range(120)],
            ),
        ],
        structured_content={"token": "secret", "rows": [{"name": "first"}]},
        metadata={"api_key": "secret", "row_count": 120},
    )

    normalized = normalizer.normalize_result(build_definition(max_result_bytes=4096), raw_result)

    assert normalized.summary is not None
    assert normalized.summary.truncated is True
    assert normalized.summary.bytes_returned is not None
    assert normalized.summary.bytes_returned <= 4096


def test_result_normalizer_unwraps_structured_dataset_success_envelope() -> None:
    normalizer = ToolResultNormalizer(default_max_result_bytes=4096)
    dataset = {
        "schema_version": "1.0",
        "dataset_id": "reporting.metric_series.monthly_income_expense.v1",
        "columns": [
            {
                "name": "reporting_period",
                "data_type": "date",
                "nullable": False,
                "semantic_role": "time",
                "unit": None,
            },
            {
                "name": "income",
                "data_type": "number",
                "nullable": False,
                "semantic_role": "metric",
                "unit": "USD",
            },
        ],
        "rows": [{"reporting_period": "2026-01-01", "income": 125000.0}],
        "row_count": 1,
        "total_row_count": 1,
        "truncated": False,
        "source": "reporting_fixture",
        "query_summary": "Returned one fixture row.",
        "time_range": None,
        "warnings": [],
        "provenance": {"provider": "fixture"},
    }
    raw_result = MCPToolCallResult(
        mcp_tool_name="reporting.query_metric_series",
        status="completed",
        structured_content={
            "ok": True,
            "tool_name": "reporting.query_metric_series",
            "summary": {
                "message": "Returned one fixture row.",
                "item_count": 1,
                "truncated": False,
            },
            "data": {"dataset": dataset},
            "errors": [],
            "meta": {
                "schema_version": "1.0",
                "output_schema": "structured_dataset_v1",
                "dataset_id": "reporting.metric_series.monthly_income_expense.v1",
            },
        },
    )

    normalized = normalizer.normalize_result(
        build_definition(logical_name="reporting.query_metric_series"),
        raw_result,
        duration_ms=18,
    )

    assert normalized.status == "completed"
    assert normalized.structured_content == dataset
    assert normalized.summary is not None
    assert normalized.summary.result_count == 1
    assert normalized.metadata["output_schema"] == "structured_dataset_v1"
    assert normalized.metadata["dataset_id"] == dataset["dataset_id"]


def test_result_normalizer_maps_structured_dataset_error_envelope_to_failed_result() -> None:
    normalizer = ToolResultNormalizer(default_max_result_bytes=4096)
    raw_result = MCPToolCallResult(
        mcp_tool_name="reporting.query_metric_series",
        status="completed",
        structured_content={
            "ok": False,
            "tool_name": "reporting.query_metric_series",
            "summary": {
                "message": "The requested metric is not approved for visualization queries.",
                "item_count": 0,
                "truncated": False,
            },
            "data": {},
            "errors": [
                {
                    "code": "unsupported_metric",
                    "message": "Metric 'gross_margin' is not enabled for reporting queries.",
                    "retryable": False,
                    "details": {"field": "metric_names", "value": "gross_margin"},
                }
            ],
            "meta": {
                "schema_version": "1.0",
                "output_schema": "structured_dataset_v1",
            },
        },
    )

    normalized = normalizer.normalize_result(
        build_definition(logical_name="reporting.query_metric_series"),
        raw_result,
        duration_ms=18,
    )

    assert normalized.status == "failed"
    assert normalized.structured_content is None
    assert normalized.summary is not None
    assert normalized.summary.safe_message == "The requested metric is not approved for visualization queries."
    assert normalized.error_detail is not None
    assert normalized.error_detail.code == "unsupported_metric"
    assert normalized.error_detail.metadata == {
        "field": "metric_names",
        "value": "gross_margin",
    }


def test_result_normalizer_maps_structured_dataset_timeout_envelope_to_timeout_status() -> None:
    normalizer = ToolResultNormalizer(default_max_result_bytes=4096)
    raw_result = MCPToolCallResult(
        mcp_tool_name="reporting.query_metric_series",
        status="completed",
        structured_content={
            "ok": False,
            "tool_name": "reporting.query_metric_series",
            "summary": {
                "message": "The reporting provider timed out before it returned a dataset.",
                "item_count": 0,
                "truncated": False,
            },
            "data": {},
            "errors": [
                {
                    "code": "timeout",
                    "message": "Reporting provider timed out.",
                    "retryable": True,
                    "details": {},
                }
            ],
            "meta": {
                "schema_version": "1.0",
                "output_schema": "structured_dataset_v1",
            },
        },
    )

    normalized = normalizer.normalize_result(
        build_definition(logical_name="reporting.query_metric_series"),
        raw_result,
        duration_ms=18,
    )

    assert normalized.status == "timeout"
    assert normalized.error_detail is not None
    assert normalized.error_detail.code == "timeout"
    assert normalized.error_detail.retryable is True
