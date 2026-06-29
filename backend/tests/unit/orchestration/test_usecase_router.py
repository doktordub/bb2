from __future__ import annotations

import pytest

from app.config.view import get_orchestration_settings
from app.contracts.context import RequestContext
from app.orchestration.errors import StrategyDisabledError, UnknownUseCaseError
from app.orchestration.strategies import DirectAgentStrategy
from app.orchestration.strategy_registry import StrategyRegistry
from app.orchestration.usecase_router import UseCaseRouter
from app.testing.fakes import FakeConfigurationView


def build_config() -> FakeConfigurationView:
    return FakeConfigurationView(
        {
            "app": {"active_usecase": "default_chat"},
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
                        "allowed_usecases": ["default_chat", "research_chat"],
                        "llm_profile": "strategy_profile",
                    },
                    "retrieval_augmented": {
                        "enabled": True,
                        "type": "retrieval_augmented",
                        "default_agent": "research_agent",
                        "allowed_usecases": ["research_chat"],
                        "llm_profile": "retrieval_profile",
                    },
                    "disabled_direct": {
                        "enabled": False,
                        "type": "direct_agent",
                        "default_agent": "support_agent",
                        "allowed_usecases": ["disabled_chat"],
                    },
                },
                "usecases": {
                    "default_chat": {
                        "enabled": True,
                        "strategy": "direct_agent",
                        "agent": "support_agent",
                        "allowed_agents": ["support_agent"],
                        "llm_profile": "usecase_profile",
                    },
                    "research_chat": {
                        "enabled": True,
                        "strategy": "retrieval_augmented",
                        "allowed_agents": ["support_agent"],
                    },
                    "disabled_chat": {
                        "enabled": True,
                        "strategy": "disabled_direct",
                        "allowed_agents": ["support_agent"],
                    },
                },
            },
            "agents": {
                "support_agent": {
                    "enabled": True,
                    "module": "app.testing.fakes.fake_agent",
                    "class_name": "FakeAgent",
                    "llm_profile": "agent_profile",
                }
            },
            "llm": {"defaults": {"profile": "gateway_default"}},
        }
    )


def build_registry(config: FakeConfigurationView) -> StrategyRegistry:
    settings = get_orchestration_settings(config)
    registry = StrategyRegistry()
    registry.register(DirectAgentStrategy(name="direct_agent"), settings.strategies["direct_agent"])
    registry.register(DirectAgentStrategy(name="disabled_direct"), settings.strategies["disabled_direct"])
    return registry


def test_router_resolves_usecase_strategy_agent_and_llm_profile() -> None:
    config = build_config()
    router = UseCaseRouter(config)

    route = router.resolve(
        RequestContext(
            user_id="user_1",
            session_id="session_1",
            message="hello",
            usecase="default_chat",
            trace_id="trace_1",
        ),
        strategy_registry=build_registry(config),
    )

    assert route.usecase.name == "default_chat"
    assert route.strategy_name == "direct_agent"
    assert route.resolved_strategy.source == "usecase"
    assert route.agent_name == "support_agent"
    assert route.llm_profile == "usecase_profile"


def test_router_falls_back_when_usecase_strategy_is_not_registered() -> None:
    config = build_config()
    router = UseCaseRouter(config)

    route = router.resolve(
        RequestContext(
            user_id="user_1",
            session_id="session_1",
            message="hello",
            usecase="research_chat",
            trace_id="trace_1",
        ),
        strategy_registry=build_registry(config),
    )

    assert route.usecase.name == "research_chat"
    assert route.strategy_name == "direct_agent"
    assert route.resolved_strategy.source == "default"
    assert route.agent_name == "support_agent"
    assert route.llm_profile == "strategy_profile"


def test_router_raises_normalized_errors_for_unknown_usecases_and_disabled_strategies() -> None:
    config = build_config()
    router = UseCaseRouter(config)
    registry = build_registry(config)

    with pytest.raises(UnknownUseCaseError, match="not configured"):
        router.resolve(
            RequestContext(
                user_id="user_1",
                session_id="session_1",
                message="hello",
                usecase="missing_chat",
                trace_id="trace_1",
            ),
            strategy_registry=registry,
        )

    with pytest.raises(StrategyDisabledError, match="disabled"):
        router.resolve(
            RequestContext(
                user_id="user_1",
                session_id="session_1",
                message="hello",
                usecase="disabled_chat",
                trace_id="trace_1",
            ),
            strategy_registry=registry,
        )