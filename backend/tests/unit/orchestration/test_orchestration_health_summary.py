from __future__ import annotations

from app.config.view import get_orchestration_settings
from app.contracts.health import HEALTH_NOT_CONFIGURED, HEALTH_OK
from app.orchestration.health import build_orchestration_health
from app.orchestration.registry import AgentRegistry
from app.orchestration.runtime import build_strategy_registry
from app.testing.fakes import FakeConfigurationView


def build_config(*, enabled: bool = True) -> FakeConfigurationView:
    return FakeConfigurationView(
        {
            "app": {"active_usecase": "default_chat"},
            "orchestration": {
                "enabled": enabled,
                "defaults": {
                    "strategy": "direct_agent",
                    "fallback_strategy": "direct_agent",
                },
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
        }
    )


def test_build_orchestration_health_reports_safe_runtime_counts() -> None:
    config = build_config()
    health = build_orchestration_health(
        get_orchestration_settings(config),
        strategy_registry=build_strategy_registry(config),
        agent_registry=AgentRegistry.from_config(config),
    )

    assert health.status == HEALTH_OK
    assert health.enabled is True
    assert health.registry_ready is True
    assert health.default_strategy == "direct_agent"
    assert health.fallback_strategy == "direct_agent"
    assert health.configured_strategy_count == 1
    assert health.enabled_strategy_count == 1
    assert health.registered_strategy_count == 1
    assert health.configured_usecase_count == 1
    assert health.enabled_usecase_count == 1
    assert health.configured_agent_count == 1
    assert health.agent_registry_status == HEALTH_OK
    assert health.metadata == {
        "agent_types": [],
        "registered_agent_count": 0,
        "strategies_ready_count": 1,
        "streaming_agent_count": 0,
        "strategy_types": ["direct_agent"],
    }
    assert health.agents == ()
    assert len(health.strategies) == 1
    assert health.strategies[0].strategy_name == "direct_agent"
    assert health.strategies[0].strategy_type == "direct_agent"
    assert health.strategies[0].status == HEALTH_OK
    assert health.strategies[0].configured_agent == "support_agent"
    assert health.strategies[0].configured_llm_profile is None
    assert health.strategies[0].streaming_supported is True
    assert health.strategies[0].metadata == {
        "registered": True,
        "allowed_usecase_count": 1,
        "enabled_usecase_count": 1,
        "agent_required": True,
    }


def test_build_orchestration_health_marks_disabled_runtime_not_configured() -> None:
    config = build_config(enabled=False)
    health = build_orchestration_health(
        get_orchestration_settings(config),
        strategy_registry=build_strategy_registry(config),
        agent_registry=AgentRegistry.from_config(config),
    )

    assert health.status == HEALTH_NOT_CONFIGURED
    assert health.enabled is False
    assert health.registry_ready is False
    assert health.agent_registry_status == HEALTH_NOT_CONFIGURED
    assert health.strategies[0].status == HEALTH_NOT_CONFIGURED