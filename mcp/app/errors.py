"""MCP server error types."""


class MCPConfigurationError(RuntimeError):
    """Raised when MCP configuration is missing or invalid."""


class MCPToolManifestError(MCPConfigurationError):
    """Raised when a tool manifest is missing or violates the MCP contract."""


class MCPToolConfigurationError(MCPConfigurationError):
    """Raised when tool-local configuration violates the declared schema."""


class MCPToolPluginError(RuntimeError):
    """Raised when a plugin instance does not satisfy the MCP plugin contract."""


class MCPSecretError(RuntimeError):
    """Raised when a required secret cannot be resolved safely."""


class MCPAuthError(RuntimeError):
    """Raised when inbound authentication fails or is misconfigured."""


class MCPJWTValidationError(MCPAuthError):
    """Raised when JWT validation cannot be completed safely."""


class MCPOAuthError(RuntimeError):
    """Raised when outbound OAuth token acquisition fails."""


class MCPTLSError(MCPConfigurationError):
    """Raised when TLS-related configuration is invalid."""


class ToolInputValidationError(ValueError):
    """Raised when a tool input violates shared MCP validation rules."""


class MCPRateLimitError(RuntimeError):
    """Raised when a shared MCP rate limit is exceeded."""
