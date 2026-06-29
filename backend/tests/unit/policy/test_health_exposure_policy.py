from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest

from app.contracts.context import OrchestrationContext, RequestContext
from app.policy.health import build_health_policy_request, evaluate_health_request, sanitize_health_payload
from app.policy.settings import PolicyHealthSettings, PolicyProfileSettings
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
async def test_health_policy_can_disable_exposure() -> None:
    context = _build_context()
    request = build_health_policy_request(
        trace_id="trace-1",
        user_id="user-1",
        payload={"status": "ok"},
    )

    decision = await evaluate_health_request(
        request,
        context,
        PolicyProfileSettings(
            name="default",
            health=PolicyHealthSettings(expose_enabled=False),
        ),
    )

    assert decision is not None
    assert decision.decision == "deny"
    assert decision.reason_code == "policy.health.disabled"


def test_health_sanitizer_removes_profile_and_provider_details() -> None:
    payload = {
        "status": "ok",
        "llm": {"profiles": {"default": {"status": "ok"}}, "provider": "secret"},
        "checks": {"policy": {"decision_counts": {"allow": 1}, "status": "ok"}},
    }

    result = sanitize_health_payload(
        payload,
        profile=PolicyProfileSettings(name="default", health=PolicyHealthSettings(include_profile_names=False)),
    )

    assert "profiles" not in result["llm"]
    assert result["llm"]["provider"] == "secret"
    assert "decision_counts" not in result["checks"]["policy"]