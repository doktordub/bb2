"""Normalize third-party MCP and HTTP failures into backend-owned tool errors."""

from __future__ import annotations

import asyncio

import httpx
from pydantic import ValidationError

from app.tools.errors import (
    MCPAuthenticationError,
    MCPClientError,
    MCPTransportError,
    ToolGatewayError,
    ToolTimeoutError,
    ToolingConfigurationError,
)


def map_mcp_exception(error: BaseException) -> BaseException:
    """Map transport, HTTP, and MCP-library failures to safe backend errors."""

    if isinstance(error, asyncio.CancelledError):
        return error
    if isinstance(
        error,
        (
            ToolGatewayError,
            ToolingConfigurationError,
        ),
    ):
        return error
    if isinstance(error, httpx.TimeoutException):
        return ToolTimeoutError("The MCP request timed out.")
    if isinstance(error, httpx.HTTPStatusError):
        return _map_http_status_error(error)
    if isinstance(error, httpx.HTTPError):
        return MCPTransportError("The MCP transport failed.")
    if isinstance(error, ValidationError):
        return MCPClientError("The MCP response payload was invalid.")

    mcp_error_type: type[BaseException] | None
    try:
        from mcp.shared.exceptions import McpError
    except ImportError:
        mcp_error_type = None
    else:
        mcp_error_type = McpError

    if mcp_error_type is not None and isinstance(error, mcp_error_type):
        return MCPClientError("The MCP server returned an error response.")

    message = str(error).lower()
    if "unsupported protocol version" in message:
        return MCPClientError("The MCP server negotiated an unsupported protocol version.")

    return MCPClientError("The MCP client failed.")


def _map_http_status_error(error: httpx.HTTPStatusError) -> ToolGatewayError:
    status_code = error.response.status_code
    if status_code in {401, 403}:
        return MCPAuthenticationError("The MCP server rejected backend authentication.")
    if status_code in {408, 504}:
        return ToolTimeoutError("The MCP request timed out.")
    if status_code in {429, 502, 503}:
        return MCPTransportError("The MCP server is temporarily unavailable.")
    if status_code in {400, 404, 405, 422}:
        return MCPClientError("The MCP server rejected the request.")
    return MCPTransportError("The MCP transport failed with an HTTP error.")


__all__ = ["map_mcp_exception"]