"""Internal error aliases for the backend memory runtime package."""

from app.contracts.errors import (
    ConfigurationError,
    MemoryAdapterError,
    MemoryDisabledError,
    MemoryGatewayError,
    MemoryIngestionError,
    MemoryInvalidScopeError,
    MemoryNotFoundError,
    MemoryPolicyApprovalRequiredError,
    MemoryPolicyDeniedError,
    MemoryPrivacyError,
)


class MemoryConfigurationError(ConfigurationError):
    """Memory runtime configuration is invalid or unsupported."""


__all__ = [
    "MemoryAdapterError",
    "MemoryConfigurationError",
    "MemoryDisabledError",
    "MemoryGatewayError",
    "MemoryIngestionError",
    "MemoryInvalidScopeError",
    "MemoryNotFoundError",
    "MemoryPolicyApprovalRequiredError",
    "MemoryPolicyDeniedError",
    "MemoryPrivacyError",
]