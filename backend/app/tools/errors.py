"""Internal error aliases for the backend tooling runtime package."""

from app.contracts.errors import (
    ConfigurationError,
    MCPAuthenticationError,
    MCPClientError,
    MCPDiscoveryError,
    MCPTransportError,
    ToolArgumentValidationError,
    ToolCancelledError,
    ToolDisabledError,
    ToolGatewayError,
    ToolNotFoundError,
    ToolPolicyApprovalRequiredError,
    ToolPolicyDeniedError,
    ToolResultTooLargeError,
    ToolTimeoutError,
)


class ToolingConfigurationError(ConfigurationError):
    """Tooling runtime configuration is invalid or unsupported."""


__all__ = [
    "MCPAuthenticationError",
    "MCPClientError",
    "MCPDiscoveryError",
    "MCPTransportError",
    "ToolArgumentValidationError",
    "ToolCancelledError",
    "ToolDisabledError",
    "ToolGatewayError",
    "ToolNotFoundError",
    "ToolPolicyApprovalRequiredError",
    "ToolPolicyDeniedError",
    "ToolResultTooLargeError",
    "ToolTimeoutError",
    "ToolingConfigurationError",
]