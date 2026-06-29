from __future__ import annotations

import pytest

from app.contracts.llm import LLMMessage, LLMRequest
from app.llm.errors import LLMPolicyDeniedError
from app.llm.providers import FakeLLMProviderAdapter
from tests.integration.llm.support import build_context, build_runtime_bundle, load_config_view


@pytest.mark.asyncio
async def test_gateway_policy_denial_blocks_fake_provider_execution() -> None:
    config = await load_config_view("llm_policy_denied.yaml")
    provider = FakeLLMProviderAdapter(name="fake_provider", response_text="should not run")
    runtime = build_runtime_bundle(config, provider_overrides={"fake_provider": provider})
    context = build_context(config)

    with pytest.raises(LLMPolicyDeniedError, match="not allowed for the active agent"):
        await runtime.gateway.complete(
            LLMRequest(messages=[LLMMessage(role="user", content="blocked by policy")]),
            context,
        )

    assert provider.calls == []