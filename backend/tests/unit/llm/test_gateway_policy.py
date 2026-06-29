from __future__ import annotations

import pytest

from app.contracts.llm import LLMMessage, LLMRequest
from app.llm.errors import LLMPolicyDeniedError
from app.llm.providers import FakeLLMProviderAdapter
from tests.unit.llm.support import base_config, build_context, build_gateway, build_registry


async def test_gateway_policy_denial_blocks_provider_execution() -> None:
    config = base_config()
    registry = build_registry(
        config,
        primary_adapter=FakeLLMProviderAdapter(name="primary_provider", response_text="should not run"),
    )
    gateway = build_gateway(config, registry=registry)
    context = build_context(config)

    with pytest.raises(LLMPolicyDeniedError, match="not allowed for the active agent"):
        await gateway.complete(
            LLMRequest(
                profile="restricted_profile",
                messages=[LLMMessage(role="user", content="hello world")],
            ),
            context,
        )

    assert registry.get("primary_provider").calls == []


async def test_gateway_rechecks_policy_on_fallback_profile() -> None:
    config = base_config()
    assert isinstance(config["llm"], dict)
    assert isinstance(config["llm"]["profiles"], dict)
    config["llm"]["profiles"]["primary_profile"]["fallback_profiles"] = ["restricted_fallback_profile"]
    registry = build_registry(
        config,
        primary_adapter=FakeLLMProviderAdapter(
            name="primary_provider",
            complete_errors=[ConnectionError("primary down"), ConnectionError("primary down again")],
        ),
        fallback_adapter=FakeLLMProviderAdapter(name="fallback_provider", response_text="should not run"),
    )
    gateway = build_gateway(config, registry=registry)
    context = build_context(config)

    with pytest.raises(LLMPolicyDeniedError, match="not allowed for the active agent"):
        await gateway.complete(
            LLMRequest(messages=[LLMMessage(role="user", content="hello world")]),
            context,
        )

    assert registry.get("fallback_provider").calls == []