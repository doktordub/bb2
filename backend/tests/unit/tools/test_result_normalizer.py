from __future__ import annotations

import pytest

from app.observability.redaction import REDACTED_VALUE, TRUNCATED_VALUE
from app.tools.errors import ToolResultTooLargeError
from app.tools.mcp import MCPToolCallResult, MCPToolContent, MCPToolStreamEvent
from app.tools.models import ResolvedToolDefinition
from app.tools.result_normalizer import ToolResultNormalizer


def build_definition(*, max_result_bytes: int = 32768) -> ResolvedToolDefinition:
    return ResolvedToolDefinition(
        logical_name="documents.search",
        mcp_tool_name="documents.search",
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
