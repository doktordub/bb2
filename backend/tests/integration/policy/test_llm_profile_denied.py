from __future__ import annotations

import pytest

from app.contracts.llm import LLMMessage, LLMRequest
from app.llm.errors import LLMPolicyDeniedError
from app.llm.providers import FakeLLMProviderAdapter
from tests.integration.llm.support import build_context, build_runtime_bundle, load_config_view


@pytest.mark.asyncio
async def test_gateway_denies_profile_not_in_policy_allowlist() -> None:
    config = await load_config_view("llm_policy_denied.yaml")
    provider = FakeLLMProviderAdapter(name="fake_provider", response_text="should not run")
    runtime = build_runtime_bundle(config, provider_overrides={"fake_provider": provider})
    context = build_context(config)

    with pytest.raises(LLMPolicyDeniedError):
        await runtime.gateway.complete(
            LLMRequest(
                profile="restricted_profile",
                messages=[LLMMessage(role="user", content="blocked")],
            ),
            context,
        )

    assert provider.calls == []