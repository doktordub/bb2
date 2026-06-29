"""Google provider scaffold kept isolated from the main gateway path."""

from __future__ import annotations

from collections.abc import AsyncIterator

from app.config.view import LLMProviderSettings
from app.llm.errors import LLMProviderUnavailableError
from app.llm.models import (
    ProviderCapabilities,
    ProviderHealthSummary,
    ProviderLLMResponse,
    ProviderLLMStreamEvent,
    ResolvedLLMRequest,
)


class GoogleProviderAdapter:
    """Placeholder Google adapter that fails safely until a later phase."""

    def __init__(self, provider: LLMProviderSettings) -> None:
        self._provider = provider
        self.name = provider.name
        self.provider_type = provider.type
        self.capabilities = ProviderCapabilities(
            provider_name=provider.name,
            provider_type=provider.type,
            supports_streaming=True,
            supports_json_schema=True,
            supports_tool_calling=True,
        )

    async def complete(self, request: ResolvedLLMRequest) -> ProviderLLMResponse:
        _ = request
        raise LLMProviderUnavailableError(
            "Google provider support is not enabled in this phase.",
            metadata={"provider": self.name},
        )

    async def stream(self, request: ResolvedLLMRequest) -> AsyncIterator[ProviderLLMStreamEvent]:
        _ = request
        raise LLMProviderUnavailableError(
            "Google provider streaming is not enabled in this phase.",
            metadata={"provider": self.name},
        )
        yield ProviderLLMStreamEvent.started()

    async def health(self) -> ProviderHealthSummary:
        return ProviderHealthSummary(
            provider_name=self.name,
            provider_type=self.provider_type,
            status="unavailable",
            enabled=self._provider.enabled,
            available=False,
            metadata={"reason": "not_implemented"},
        )