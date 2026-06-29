"""Retry and error-classification helpers for the concrete tool gateway."""

from __future__ import annotations

import asyncio

from app.tools.errors import (
    MCPTransportError,
    ToolArgumentValidationError,
    ToolCancelledError,
    ToolGatewayError,
    ToolTimeoutError,
)
from app.tools.mcp.errors import map_mcp_exception
from app.tools.mcp.protocol_models import MCPToolCallResult
from app.tools.models import ResolvedToolDefinition


def normalize_runtime_error(
    error: BaseException,
    *,
    streaming: bool = False,
) -> ToolGatewayError:
    """Normalize arbitrary adapter failures into stable backend-owned tool errors."""

    if isinstance(error, ToolGatewayError):
        return error

    mapped = map_mcp_exception(error)
    if isinstance(mapped, ToolGatewayError):
        return mapped
    if isinstance(error, asyncio.CancelledError):
        return ToolCancelledError("Tool execution was cancelled.")
    if isinstance(error, TimeoutError):
        return ToolTimeoutError("Tool execution timed out.")
    if isinstance(error, ConnectionError):
        return MCPTransportError("The MCP transport is unavailable.")
    if isinstance(error, ValueError):
        return ToolArgumentValidationError(
            str(error) or "Tool arguments were rejected."
        )
    if streaming:
        return ToolGatewayError("Tool streaming failed.")
    return ToolGatewayError("Tool execution failed.")


def result_retry_error(result: MCPToolCallResult) -> ToolGatewayError | None:
    """Classify an adapter result into a retry-relevant error when possible."""

    if result.status == "timeout":
        return ToolTimeoutError(
            result.error_message or "Tool execution timed out."
        )
    if result.status == "cancelled":
        return ToolCancelledError(
            result.error_message or "Tool execution was cancelled."
        )
    if result.status == "failed" and result.metadata.get("retryable") is True:
        return MCPTransportError(
            result.error_message or "The MCP transport returned a retryable failure."
        )
    return None


def is_retryable_error(
    error: ToolGatewayError,
    *,
    definition: ResolvedToolDefinition,
    idempotency_key: str | None,
) -> bool:
    """Return True when the current tool and error can be retried safely."""

    if not _tool_allows_retry(definition=definition, idempotency_key=idempotency_key):
        return False
    return isinstance(error, (ToolTimeoutError, MCPTransportError))


def retry_attempts_for_request(
    *,
    definition: ResolvedToolDefinition,
    default_max_retries: int,
    idempotency_key: str | None,
) -> int:
    """Return the total attempt count, including the initial attempt."""

    retries = max(0, default_max_retries)
    if retries == 0:
        return 1
    if not _tool_allows_retry(definition=definition, idempotency_key=idempotency_key):
        return 1
    return retries + 1


def _tool_allows_retry(
    *,
    definition: ResolvedToolDefinition,
    idempotency_key: str | None,
) -> bool:
    if definition.safety_level in {"destructive", "external_side_effect"}:
        return False
    if definition.safety_level == "write" and not idempotency_key:
        return False
    return True


__all__ = [
    "is_retryable_error",
    "normalize_runtime_error",
    "result_retry_error",
    "retry_attempts_for_request",
]