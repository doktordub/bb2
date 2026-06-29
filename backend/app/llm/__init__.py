"""Concrete LLM runtime package for gateway internals."""

from app.llm.errors import (
    LLMAuthenticationError,
    LLMBadRequestError,
    LLMCancelledError,
    LLMContextLengthError,
    LLMMalformedResponseError,
    LLMPolicyDeniedError,
    LLMProfileResolutionError,
    LLMProviderTimeoutError,
    LLMProviderUnavailableError,
    LLMRateLimitError,
    LLMRuntimeError,
    LLMStreamingError,
    LLMUnsupportedCapabilityError,
)
from app.llm.gateway import DefaultLLMGateway
from app.llm.factory import LLMRuntimeBundle, build_llm_runtime
from app.llm.models import (
    ProfileHealthSummary,
    ProviderCapabilities,
    ProviderHealthSummary,
    ProviderLLMResponse,
    ProviderLLMStreamEvent,
    ResolvedLLMRequest,
)
from app.llm.profile_resolver import LLMProfileResolver
from app.llm.provider_base import LLMProviderAdapter
from app.llm.provider_registry import ProviderRegistry

__all__ = [
    "LLMAuthenticationError",
    "LLMBadRequestError",
    "LLMCancelledError",
    "LLMContextLengthError",
    "DefaultLLMGateway",
    "LLMMalformedResponseError",
    "LLMPolicyDeniedError",
    "LLMProfileResolutionError",
    "LLMProviderAdapter",
    "LLMProviderTimeoutError",
    "LLMProviderUnavailableError",
    "LLMProfileResolver",
    "LLMRateLimitError",
    "LLMRuntimeError",
    "LLMStreamingError",
    "LLMUnsupportedCapabilityError",
    "LLMRuntimeBundle",
    "ProfileHealthSummary",
    "ProviderCapabilities",
    "ProviderHealthSummary",
    "ProviderLLMResponse",
    "ProviderLLMStreamEvent",
    "ProviderRegistry",
    "ResolvedLLMRequest",
    "build_llm_runtime",
]