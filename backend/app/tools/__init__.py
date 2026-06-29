"""Concrete tooling runtime package for backend-owned tool execution internals."""

from app.tools.errors import (
    MCPAuthenticationError,
    MCPClientError,
    MCPDiscoveryError,
    MCPTransportError,
    ToolArgumentValidationError,
    ToolCancelledError,
    ToolDisabledError,
    ToolGatewayError,
    ToolNotFoundError,
    ToolPolicyDeniedError,
    ToolResultTooLargeError,
    ToolTimeoutError,
    ToolingConfigurationError,
)
from app.tools.discovery import ToolDiscoveryService
from app.tools.factory import ToolingRuntimeBundle, build_tooling_runtime, initialize_tooling_runtime
from app.tools.gateway import DefaultToolGateway
from app.tools.mcp import (
    build_mcp_auth_provider,
    DefaultMCPClientAdapter,
    DefaultMCPTransport,
    FakeMCPClientAdapter,
    MCPAuthProvider,
    MCPClientAdapter,
    MCPHealthResult,
    MCPTransport,
    MCPToolCallRequest,
    MCPToolCallResult,
    MCPToolContent,
    MCPToolDefinition,
    MCPToolStreamEvent,
)
from app.tools.models import (
    AdapterRequestMetadata,
    ResolvedToolDefinition,
    ToolDiscoverySnapshot,
    ToolRegistryEntry,
)
from app.tools.registry import ToolRegistry, ToolRegistryRefreshResult
from app.tools.retry import (
    is_retryable_error,
    normalize_runtime_error,
    result_retry_error,
    retry_attempts_for_request,
)
from app.tools.result_normalizer import ToolResultNormalizer
from app.tools.schema_validation import ToolArgumentValidator

__all__ = [
    "AdapterRequestMetadata",
    "build_mcp_auth_provider",
    "DefaultMCPClientAdapter",
    "DefaultMCPTransport",
    "DefaultToolGateway",
    "FakeMCPClientAdapter",
    "MCPAuthProvider",
    "is_retryable_error",
    "MCPAuthenticationError",
    "MCPClientAdapter",
    "MCPClientError",
    "MCPDiscoveryError",
    "MCPHealthResult",
    "MCPTransport",
    "MCPToolCallRequest",
    "MCPToolCallResult",
    "MCPToolContent",
    "MCPToolDefinition",
    "MCPToolStreamEvent",
    "MCPTransportError",
    "normalize_runtime_error",
    "ResolvedToolDefinition",
    "result_retry_error",
    "ToolArgumentValidator",
    "ToolDiscoveryService",
    "ToolArgumentValidationError",
    "ToolCancelledError",
    "ToolDisabledError",
    "ToolDiscoverySnapshot",
    "ToolGatewayError",
    "ToolNotFoundError",
    "ToolPolicyDeniedError",
    "ToolRegistry",
    "ToolRegistryEntry",
    "ToolRegistryRefreshResult",
    "ToolResultNormalizer",
    "ToolResultTooLargeError",
    "ToolTimeoutError",
    "ToolingConfigurationError",
    "ToolingRuntimeBundle",
    "build_tooling_runtime",
    "initialize_tooling_runtime",
    "retry_attempts_for_request",
]