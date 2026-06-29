"""Provider registry for concrete LLM provider adapters."""

from __future__ import annotations

from collections.abc import Mapping

from app.config.view import LLMProviderSettings
from app.llm.errors import LLMProviderUnavailableError
from app.llm.provider_base import LLMProviderAdapter


class ProviderRegistry:
    """Registry that maps validated provider names to concrete adapters."""

    def __init__(self, providers: Mapping[str, LLMProviderSettings]) -> None:
        self._providers = dict(providers)
        self._adapters: dict[str, LLMProviderAdapter] = {}

    def register(self, provider_name: str, adapter: LLMProviderAdapter) -> None:
        if provider_name not in self._providers:
            raise LLMProviderUnavailableError(
                f"LLM provider '{provider_name}' is not defined in configuration."
            )
        if provider_name in self._adapters:
            raise ValueError(f"LLM provider '{provider_name}' is already registered.")
        self._adapters[provider_name] = adapter

    def has(self, provider_name: str) -> bool:
        return provider_name in self._adapters

    def get(self, provider_name: str, *, allow_disabled: bool = False) -> LLMProviderAdapter:
        provider = self.provider_settings(provider_name)
        if not provider.enabled and not allow_disabled:
            raise LLMProviderUnavailableError(
                f"LLM provider '{provider_name}' is disabled.",
                metadata={"provider": provider_name},
            )

        adapter = self._adapters.get(provider_name)
        if adapter is None:
            raise LLMProviderUnavailableError(
                f"LLM provider '{provider_name}' has no registered adapter.",
                metadata={"provider": provider_name},
            )
        return adapter

    def provider_settings(self, provider_name: str) -> LLMProviderSettings:
        provider = self._providers.get(provider_name)
        if provider is None:
            raise LLMProviderUnavailableError(
                f"LLM provider '{provider_name}' is not defined in configuration.",
                metadata={"provider": provider_name},
            )
        return provider

    def items(
        self,
        *,
        include_disabled: bool = False,
    ) -> tuple[tuple[LLMProviderSettings, LLMProviderAdapter], ...]:
        items: list[tuple[LLMProviderSettings, LLMProviderAdapter]] = []
        for provider_name, adapter in self._adapters.items():
            settings = self.provider_settings(provider_name)
            if settings.enabled or include_disabled:
                items.append((settings, adapter))
        return tuple(items)