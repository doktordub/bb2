from __future__ import annotations

import pytest

from app.config.view import LLMProviderSettings
from app.llm.errors import LLMProviderUnavailableError
from app.llm.provider_registry import ProviderRegistry
from app.llm.providers import FakeLLMProviderAdapter


def build_registry() -> ProviderRegistry:
    return ProviderRegistry(
        {
            "primary": LLMProviderSettings(
                name="primary",
                type="fake",
                enabled=True,
                base_url=None,
                endpoint=None,
                api_key=None,
                auth_header=None,
                auth_token=None,
                timeout_seconds=30,
                stream_timeout_seconds=60,
                headers={},
                extra={},
            ),
            "disabled": LLMProviderSettings(
                name="disabled",
                type="fake",
                enabled=False,
                base_url=None,
                endpoint=None,
                api_key=None,
                auth_header=None,
                auth_token=None,
                timeout_seconds=30,
                stream_timeout_seconds=60,
                headers={},
                extra={},
            ),
        }
    )


def test_provider_registry_rejects_duplicate_registration() -> None:
    registry = build_registry()
    adapter = FakeLLMProviderAdapter(name="primary")

    registry.register("primary", adapter)

    with pytest.raises(ValueError, match="already registered"):
        registry.register("primary", adapter)


def test_provider_registry_blocks_disabled_provider_lookup() -> None:
    registry = build_registry()
    registry.register("disabled", FakeLLMProviderAdapter(name="disabled", enabled=False))

    with pytest.raises(LLMProviderUnavailableError, match="disabled"):
        registry.get("disabled")


def test_provider_registry_returns_registered_adapter() -> None:
    registry = build_registry()
    adapter = FakeLLMProviderAdapter(name="primary")
    registry.register("primary", adapter)

    resolved = registry.get("primary")

    assert resolved is adapter
    assert registry.items() == ((registry.provider_settings("primary"), adapter),)