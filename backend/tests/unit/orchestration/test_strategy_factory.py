from __future__ import annotations

from app.orchestration.strategy_factory import StrategyFactory, build_strategy_registry, default_strategy_factory
from app.testing.fakes import FakeConfigurationView


def build_config() -> FakeConfigurationView:
    return FakeConfigurationView(
        {
            "orchestration": {
                "enabled": True,
                "defaults": {
                    "strategy": "direct_agent",
                    "fallback_strategy": "direct_agent",
                    "max_steps": 8,
                    "max_tool_calls": 4,
                    "max_memory_searches": 3,
                    "max_llm_calls": 6,
                    "max_turn_duration_seconds": 120,
                    "max_stream_duration_seconds": 300,
                },
                "strategies": {
                    "direct_agent": {
                        "enabled": True,
                        "type": "direct_agent",
                        "default_agent": "support_agent",
                        "allowed_usecases": ["default_chat"],
                    },
                    "retrieval_augmented": {
                        "enabled": True,
                        "type": "retrieval_augmented",
                        "default_agent": "support_agent",
                        "allowed_usecases": ["default_chat"],
                        "memory_enabled": True,
                    },
                    "memory_update": {
                        "enabled": True,
                        "type": "memory_update",
                        "default_agent": "support_agent",
                        "allowed_usecases": ["default_chat"],
                        "memory_write_enabled": True,
                    },
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
            "llm": {"defaults": {"profile": "fake_chat"}},
        }
    )


def test_default_strategy_factory_reports_supported_runtime_types() -> None:
    factory = default_strategy_factory()

    assert factory.supports("bounded_planner") is True
    assert factory.supports("direct_agent") is True
    assert factory.supports("router") is True
    assert factory.supports("fallback_answer") is True
    assert factory.supports("memory_update") is True


def test_build_strategy_registry_registers_supported_strategies_only() -> None:
    registry = build_strategy_registry(build_config())

    descriptors = registry.list(enabled_only=False)
    assert [descriptor.name for descriptor in descriptors] == ["direct_agent", "memory_update", "retrieval_augmented"]


def test_custom_factory_builder_can_override_runtime_registry_construction() -> None:
    config = build_config()
    factory = StrategyFactory()
    factory.register_builder("direct_agent", lambda settings: type("CustomStrategy", (), {"name": settings.name})())

    registry = build_strategy_registry(config, factory=factory)
    resolved = registry.resolve(strategy_name="direct_agent", usecase="default_chat")

    assert resolved.strategy.name == "direct_agent"