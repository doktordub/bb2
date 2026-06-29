from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest

from app.contracts.context import OrchestrationContext, RequestContext
from app.policy.capabilities import build_capabilities_policy_request, sanitize_capabilities_payload
from app.policy.settings import PolicyCapabilitySettings, PolicyProfileSettings
from app.policy.capabilities import evaluate_capabilities_request
from app.testing.fakes import FakeConfigurationView


def _build_context() -> OrchestrationContext:
    return cast(
        OrchestrationContext,
        SimpleNamespace(
            request=RequestContext(
                user_id="user-1",
                session_id="session-1",
                message="",
                trace_id="trace-1",
            ),
            runtime_metadata={},
            config=FakeConfigurationView({}),
        ),
    )


@pytest.mark.asyncio
async def test_capabilities_policy_can_disable_exposure() -> None:
    context = _build_context()
    request = build_capabilities_policy_request(
        trace_id="trace-1",
        user_id="user-1",
        payload={"chat": {"enabled": True}},
    )

    decision = await evaluate_capabilities_request(
        request,
        context,
        PolicyProfileSettings(
            name="default",
            capabilities=PolicyCapabilitySettings(expose_enabled=False),
        ),
    )

    assert decision is not None
    assert decision.decision == "deny"
    assert decision.reason_code == "policy.capabilities.disabled"


def test_capabilities_sanitizer_removes_policy_fields() -> None:
    payload = {
        "chat": {"enabled": True},
        "policy": {"profiles": ["default"]},
        "debug": {"trace_routes_enabled": False, "policy_profiles": ["default"]},
    }

    result = sanitize_capabilities_payload(
        payload,
        profile=PolicyProfileSettings(name="default"),
    )

    assert "policy" not in result
    assert "policy_profiles" not in result["debug"]