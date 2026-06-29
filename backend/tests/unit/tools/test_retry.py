from __future__ import annotations

import httpx

from app.tools.errors import MCPTransportError, ToolTimeoutError
from app.tools.mcp.protocol_models import MCPToolCallResult
from app.tools.models import ResolvedToolDefinition
from app.tools.retry import (
    is_retryable_error,
    normalize_runtime_error,
    result_retry_error,
    retry_attempts_for_request,
)


def test_normalize_runtime_error_maps_httpx_timeouts_and_transport_failures() -> None:
    request = httpx.Request("POST", "http://localhost:9001/mcp")

    timeout_error = normalize_runtime_error(httpx.ReadTimeout("timed out", request=request))
    transport_error = normalize_runtime_error(
        httpx.ConnectError("connect failed", request=request)
    )

    assert isinstance(timeout_error, ToolTimeoutError)
    assert isinstance(transport_error, MCPTransportError)


def test_result_retry_error_classifies_timeout_and_retryable_failures() -> None:
    timeout = result_retry_error(
        MCPToolCallResult(
            mcp_tool_name="documents.search",
            status="timeout",
            error_message="timed out",
        )
    )
    retryable_failure = result_retry_error(
        MCPToolCallResult(
            mcp_tool_name="documents.search",
            status="failed",
            error_message="temporary outage",
            metadata={"retryable": True},
        )
    )

    assert isinstance(timeout, ToolTimeoutError)
    assert isinstance(retryable_failure, MCPTransportError)


def test_retry_helpers_require_idempotency_for_write_tools() -> None:
    read_only = ResolvedToolDefinition(
        logical_name="documents.search",
        mcp_tool_name="documents.search",
        safety_level="read_only",
    )
    write_tool = ResolvedToolDefinition(
        logical_name="notes.write",
        mcp_tool_name="notes.write",
        safety_level="write",
    )

    assert retry_attempts_for_request(
        definition=read_only,
        default_max_retries=2,
        idempotency_key=None,
    ) == 3
    assert retry_attempts_for_request(
        definition=write_tool,
        default_max_retries=2,
        idempotency_key=None,
    ) == 1
    assert is_retryable_error(
        MCPTransportError("temporary outage"),
        definition=write_tool,
        idempotency_key="idem-123",
    ) is True