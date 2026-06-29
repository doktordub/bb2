"""Normalized LLM runtime errors used by the concrete gateway package."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.contracts.errors import LLMGatewayError
from app.contracts.llm import LLMErrorDetail


class LLMRuntimeError(LLMGatewayError):
    """Base class for normalized LLM runtime failures."""

    default_code = "llm_runtime_error"
    default_retryable = False

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        retryable: bool | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code or self.default_code
        self.retryable = self.default_retryable if retryable is None else retryable
        self.metadata = dict(metadata or {})

    def as_error_detail(self) -> LLMErrorDetail:
        return LLMErrorDetail(
            type=type(self).__name__,
            code=self.code,
            message=str(self),
            retryable=self.retryable,
            metadata=dict(self.metadata),
        )


class LLMProfileResolutionError(LLMRuntimeError):
    default_code = "llm_profile_resolution_error"


class LLMPolicyDeniedError(LLMRuntimeError):
    default_code = "llm_policy_denied"


class LLMProviderUnavailableError(LLMRuntimeError):
    default_code = "llm_provider_unavailable"
    default_retryable = True


class LLMProviderTimeoutError(LLMRuntimeError):
    default_code = "llm_provider_timeout"
    default_retryable = True


class LLMRateLimitError(LLMRuntimeError):
    default_code = "llm_rate_limited"
    default_retryable = True


class LLMAuthenticationError(LLMRuntimeError):
    default_code = "llm_authentication_error"


class LLMBadRequestError(LLMRuntimeError):
    default_code = "llm_bad_request"


class LLMUnsupportedCapabilityError(LLMRuntimeError):
    default_code = "llm_unsupported_capability"


class LLMContextLengthError(LLMRuntimeError):
    default_code = "llm_context_length_exceeded"


class LLMMalformedResponseError(LLMRuntimeError):
    default_code = "llm_malformed_response"


class LLMStreamingError(LLMRuntimeError):
    default_code = "llm_streaming_error"
    default_retryable = True


class LLMCancelledError(LLMRuntimeError):
    default_code = "llm_cancelled"
