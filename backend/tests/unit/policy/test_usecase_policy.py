from __future__ import annotations

import pytest

from app.contracts.policy import PolicyRequest
from app.policy.service import DefaultPolicyService
from app.testing.fakes import FakeConfigurationView
from tests.unit.orchestration.test_strategy_policy import build_context


@pytest.mark.asyncio
async def test_usecase_policy_denies_unknown_usecase() -> None:
    config = FakeConfigurationView(
        {
            "orchestration": {
                "enabled": True,
                "defaults": {"strategy": "direct_agent", "fallback_strategy": "direct_agent"},
                "strategies": {
                    "direct_agent": {
                        "enabled": True,
                        "type": "direct_agent",
                        "default_agent": "support_agent",
                        "allowed_usecases": ["default_chat"],
                    }
                },
                "usecases": {
                    "default_chat": {
                        "enabled": True,
                        "strategy": "direct_agent",
                        "agent": "support_agent",
                        "allowed_agents": ["support_agent"],
                        "policy_profile": "default",
                    }
                },
            },
            "agents": {
                "support_agent": {
                    "enabled": True,
                    "module": "app.testing.fakes.fake_agent",
                    "class_name": "FakeAgent",
                }
            },
            "policy": {
                "default_profile": "default",
                "profiles": {"default": {"usecases": {"allowed": ["default_chat"]}}},
            },
        }
    )
    service = DefaultPolicyService(config)
    context = build_context(config)

    decision = await service.evaluate(
        PolicyRequest(
            action="orchestration.run_strategy",
            component="orchestration.runtime",
            resource="admin_ops",
            scope={
                "usecase_name": "admin_ops",
                "strategy_name": "direct_agent",
                "agent_name": "support_agent",
            },
        ),
        context,
    )

    assert decision.decision == "deny"
    assert decision.reason_code == "policy.usecase.unknown"