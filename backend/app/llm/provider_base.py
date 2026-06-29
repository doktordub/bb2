"""Provider adapter contract for the concrete LLM runtime."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from app.llm.models import (
    ProviderCapabilities,
    ProviderHealthSummary,
    ProviderLLMResponse,
    ProviderLLMStreamEvent,
    ResolvedLLMRequest,
)


class LLMProviderAdapter(Protocol):
    """Concrete provider adapter boundary owned by the LLM runtime package."""

    name: str
    provider_type: str
    capabilities: ProviderCapabilities

    async def complete(self, request: ResolvedLLMRequest) -> ProviderLLMResponse:
        ...

    def stream(self, request: ResolvedLLMRequest) -> AsyncIterator[ProviderLLMStreamEvent]:
        ...

    async def health(self) -> ProviderHealthSummary:
        ...