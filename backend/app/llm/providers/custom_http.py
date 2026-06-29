"""Explicit custom HTTP provider scaffold for later provider-specific work."""

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


class CustomHttpProviderAdapter:
    """Safe scaffold for explicitly configured custom HTTP providers."""

    def __init__(self, provider: LLMProviderSettings) -> None:
        self._provider = provider
        self.name = provider.name
        self.provider_type = provider.type
        self.capabilities = ProviderCapabilities(
            provider_name=provider.name,
            provider_type=provider.type,
            supports_streaming=False,
            supports_json_schema=False,
            supports_tool_calling=False,
        )

    async def complete(self, request: ResolvedLLMRequest) -> ProviderLLMResponse:
        _ = request
        raise LLMProviderUnavailableError(
            "Custom HTTP providers require an explicit adapter implementation.",
            metadata={"provider": self.name},
        )

    async def stream(self, request: ResolvedLLMRequest) -> AsyncIterator[ProviderLLMStreamEvent]:
        _ = request
        raise LLMProviderUnavailableError(
            "Custom HTTP providers require an explicit streaming adapter implementation.",
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
            metadata={"reason": "explicit_adapter_required"},
        )