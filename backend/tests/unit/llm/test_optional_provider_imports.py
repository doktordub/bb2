from __future__ import annotations

import pytest

from app.config.view import LLMProviderSettings
from app.llm.errors import LLMProviderUnavailableError
from app.llm.providers import CustomHttpProviderAdapter, GoogleProviderAdapter, OpenAIProviderAdapter


def _build_provider(provider_type: str) -> LLMProviderSettings:
    return LLMProviderSettings(
        name=f"{provider_type}_provider",
        type=provider_type,
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
    )


@pytest.mark.asyncio
async def test_optional_provider_modules_import_without_sdk_side_effects() -> None:
    openai_adapter = OpenAIProviderAdapter(_build_provider("openai"))
    google_adapter = GoogleProviderAdapter(_build_provider("google"))
    custom_http_adapter = CustomHttpProviderAdapter(_build_provider("custom_http"))

    openai_health = await openai_adapter.health()
    google_health = await google_adapter.health()
    custom_http_health = await custom_http_adapter.health()

    assert openai_health.provider_type == "openai"
    assert openai_health.status == "ok"
    assert google_health.status == "unavailable"
    assert custom_http_health.status == "unavailable"


@pytest.mark.asyncio
async def test_optional_provider_scaffolds_fail_safely_when_used() -> None:
    google_adapter = GoogleProviderAdapter(_build_provider("google"))
    custom_http_adapter = CustomHttpProviderAdapter(_build_provider("custom_http"))

    with pytest.raises(LLMProviderUnavailableError):
        await google_adapter.complete(None)  # type: ignore[arg-type]

    with pytest.raises(LLMProviderUnavailableError):
        await custom_http_adapter.complete(None)  # type: ignore[arg-type]