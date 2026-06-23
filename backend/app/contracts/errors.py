"""Known backend error categories used across later contract implementations."""


class BackendError(Exception):
    """Base exception for known backend errors."""


class ConfigurationError(BackendError):
    """Configuration is missing, invalid, or inconsistent."""


class PolicyDeniedError(BackendError):
    """A policy check denied the requested action."""


class GatewayError(BackendError):
    """Base error for gateway failures."""


class LLMGatewayError(GatewayError):
    """LLM gateway failed or returned invalid output."""


class ToolGatewayError(GatewayError):
    """Tool gateway or downstream MCP call failed."""


class MemoryGatewayError(GatewayError):
    """Memory gateway failed."""


class WorkflowStateError(GatewayError):
    """Workflow state load, save, or reset failed."""


class TraceStoreError(GatewayError):
    """Trace store write failed."""