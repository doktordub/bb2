"""Known backend error categories used across later contract implementations."""


class BackendError(Exception):
    """Base exception for known backend errors."""


class ConfigurationError(BackendError):
    """Configuration is missing, invalid, or inconsistent."""


class PolicyDeniedError(BackendError):
    """A policy check denied the requested action."""


class PolicyApprovalRequiredError(PolicyDeniedError):
    """A policy check requires approval before the action can proceed."""


class GatewayError(BackendError):
    """Base error for gateway failures."""


class LLMGatewayError(GatewayError):
    """LLM gateway failed or returned invalid output."""


class ToolGatewayError(GatewayError):
    """Tool gateway or downstream MCP call failed."""


class ToolNotFoundError(ToolGatewayError):
    """The requested logical tool could not be resolved."""


class ToolDisabledError(ToolGatewayError):
    """The requested tool is disabled by configuration or runtime mode."""


class ToolArgumentValidationError(ToolGatewayError):
    """Tool arguments failed backend-owned validation before execution."""


class ToolPolicyDeniedError(PolicyDeniedError, ToolGatewayError):
    """A policy check denied the requested tool action."""


class ToolPolicyApprovalRequiredError(ToolPolicyDeniedError, PolicyApprovalRequiredError):
    """A tool action requires approval before execution."""


class ToolTimeoutError(ToolGatewayError):
    """Tool execution exceeded its allowed timeout."""


class ToolCancelledError(ToolGatewayError):
    """Tool execution was cancelled before completion."""


class ToolResultTooLargeError(ToolGatewayError):
    """Tool output exceeded configured backend result limits."""


class MCPClientError(ToolGatewayError):
    """Base error for backend-owned MCP adapter failures."""


class MCPAuthenticationError(MCPClientError):
    """The backend could not authenticate to the configured MCP server."""


class MCPTransportError(MCPClientError):
    """The backend could not reach or safely communicate with the MCP server."""


class MCPDiscoveryError(MCPClientError):
    """The backend could not list or normalize tools from the MCP server."""


class MemoryGatewayError(GatewayError):
    """Memory gateway failed."""


class MemoryDisabledError(MemoryGatewayError):
    """Memory is disabled by configuration or runtime mode."""


class MemoryInvalidScopeError(MemoryGatewayError):
    """Memory scope is invalid or missing required durable identifiers."""


class MemoryNotFoundError(MemoryGatewayError):
    """The requested memory record or chunk was not found."""


class MemoryPolicyDeniedError(PolicyDeniedError, MemoryGatewayError):
    """A policy check denied the requested memory operation."""


class MemoryPolicyApprovalRequiredError(
    MemoryPolicyDeniedError,
    PolicyApprovalRequiredError,
):
    """A memory action requires approval before execution."""


class MemoryAdapterError(MemoryGatewayError):
    """The concrete memory adapter failed to execute or translate a request."""


class MemoryIngestionError(MemoryGatewayError):
    """Document ingestion failed before the memory layer could complete."""


class MemoryPrivacyError(MemoryGatewayError):
    """A privacy-scoped export, delete, or forget operation failed."""


class WorkflowStateError(GatewayError):
    """Workflow state load, save, or reset failed."""


class TraceStoreError(GatewayError):
    """Trace store write failed."""