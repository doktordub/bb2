"""OpenAI adapter scaffold built on the OpenAI-compatible HTTP surface."""

from __future__ import annotations

from dataclasses import replace

import httpx

from app.config.view import LLMProviderSettings
from app.llm.providers.openai_compatible import OpenAICompatibleProviderAdapter


class OpenAIProviderAdapter(OpenAICompatibleProviderAdapter):
    """Thin OpenAI adapter that reuses the OpenAI-compatible HTTP contract."""

    def __init__(
        self,
        provider: LLMProviderSettings,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        normalized = provider
        if provider.base_url is None:
            normalized = replace(provider, base_url="https://api.openai.com/v1")
        super().__init__(normalized, client=client)
        self.provider_type = "openai"
        self.capabilities = replace(
            self.capabilities,
            provider_type="openai",
        )