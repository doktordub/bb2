from __future__ import annotations

import pytest

from app.contracts.errors import ConfigurationError
from app.contracts.llm import LLMMessage, LLMRequest
from tests.integration.llm.support import build_context, build_runtime_bundle, load_config_view


@pytest.mark.asyncio
async def test_gateway_complete_runs_through_fake_provider_fixture() -> None:
    config = await load_config_view("llm_fake_basic.yaml")
    runtime = build_runtime_bundle(config)
    context = build_context(config)

    response = await runtime.gateway.complete(
        LLMRequest(messages=[LLMMessage(role="user", content="hello integration")]),
        context,
    )
    health = await runtime.gateway.health()

    assert response.text == "fake response"
    assert response.profile == "fake_basic"
    assert response.provider == "fake_provider"
    assert health.status == "ok"
    assert health.default_profile == "fake_basic"
    assert health.providers["fake_provider"].type == "fake"


@pytest.mark.asyncio
async def test_unknown_profile_fixture_fails_fast_during_config_load() -> None:
    with pytest.raises(ConfigurationError, match="LLM default profile 'missing_profile' is not defined"):
        await load_config_view("llm_unknown_profile.yaml")