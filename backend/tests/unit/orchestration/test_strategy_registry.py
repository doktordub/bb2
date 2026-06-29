from __future__ import annotations

import pytest

from app.config.view import get_orchestration_settings
from app.orchestration.errors import StrategyDisabledError, StrategyNotFoundError
from app.orchestration.strategies import DirectAgentStrategy, EchoStrategy
from app.orchestration.strategy_registry import StrategyRegistry
from app.testing.fakes import FakeConfigurationView


def build_config() -> FakeConfigurationView:
    return FakeConfigurationView(
        {
            "orchestration": {
                "enabled": True,
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
                        "metadata": {
                            "safe": True,
                            "secret_token": "hidden",
                        },
                    },
                    "disabled_echo": {
                        "enabled": False,
                        "type": "echo",
                        "allowed_usecases": ["default_chat"],
                    },
                },
                "usecases": {
                    "default_chat": {
                        "enabled": True,
                        "strategy": "direct_agent",
                        "agent": "support_agent",
                        "allowed_agents": ["support_agent"],
                    }
                },
            }
        }
    )


def test_registry_lists_safe_descriptors_and_filters_disabled_entries() -> None:
    config = build_config()
    settings = get_orchestration_settings(config)
    registry = StrategyRegistry()
    registry.register(DirectAgentStrategy(name="direct_agent"), settings.strategies["direct_agent"])
    registry.register(EchoStrategy(name="disabled_echo"), settings.strategies["disabled_echo"])

    descriptors = registry.list()

    assert [descriptor.name for descriptor in descriptors] == ["direct_agent"]
    assert descriptors[0].metadata == {"safe": True}


def test_registry_resolve_enforces_usecase_allowlists_and_disabled_strategies() -> None:
    config = build_config()
    settings = get_orchestration_settings(config)
    registry = StrategyRegistry()
    registry.register(DirectAgentStrategy(name="direct_agent"), settings.strategies["direct_agent"])
    registry.register(EchoStrategy(name="disabled_echo"), settings.strategies["disabled_echo"])

    resolved = registry.resolve(
        strategy_name="direct_agent",
        usecase="default_chat",
        source="fallback",
    )

    assert resolved.settings.name == "direct_agent"
    assert resolved.source == "fallback"

    with pytest.raises(StrategyNotFoundError, match="not allowed"):
        registry.resolve(strategy_name="direct_agent", usecase="research_chat")

    with pytest.raises(StrategyDisabledError, match="disabled"):
        registry.resolve(strategy_name="disabled_echo", usecase="default_chat")