"""Strategy construction helpers kept separate from runtime execution code."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from app.config.view import OrchestrationSettings, StrategySettings, get_orchestration_settings
from app.contracts.config import ConfigurationView
from app.orchestration.strategies import (
    BoundedPlannerStrategy,
    DirectAgentStrategy,
    EchoStrategy,
    FallbackAnswerStrategy,
    MemoryUpdateStrategy,
    RetrievalAugmentedStrategy,
    RouterStrategy,
    ToolAssistedStrategy,
)
from app.orchestration.strategy import OrchestrationStrategy
from app.orchestration.strategy_registry import StrategyRegistry

StrategyBuilder = Callable[[StrategySettings], OrchestrationStrategy]


@dataclass(slots=True)
class StrategyFactory:
    """Build configured strategies without mixing registration into runtime logic."""

    builders: dict[str, StrategyBuilder] = field(default_factory=dict)

    def register_builder(self, strategy_type: str, builder: StrategyBuilder) -> None:
        normalized_type = _normalize_strategy_type(strategy_type)
        if normalized_type in self.builders:
            raise ValueError(f"Strategy builder '{normalized_type}' is already registered.")
        self.builders[normalized_type] = builder

    def supports(self, strategy_type: str) -> bool:
        return _normalize_strategy_type(strategy_type) in self.builders

    def build(self, settings: StrategySettings) -> OrchestrationStrategy | None:
        builder = self.builders.get(_normalize_strategy_type(settings.type))
        if builder is None:
            return None
        return builder(settings)

    def build_registry(self, settings: OrchestrationSettings) -> StrategyRegistry:
        registry = StrategyRegistry()
        for strategy_settings in settings.strategies.values():
            strategy = self.build(strategy_settings)
            if strategy is None:
                continue
            registry.register(strategy, strategy_settings)
        return registry


def default_strategy_factory() -> StrategyFactory:
    factory = StrategyFactory()
    factory.register_builder("direct_agent", lambda settings: DirectAgentStrategy(name=settings.name))
    factory.register_builder("echo", lambda settings: EchoStrategy(name=settings.name))
    factory.register_builder(
        "retrieval_augmented",
        lambda settings: RetrievalAugmentedStrategy(name=settings.name),
    )
    factory.register_builder("tool_assisted", lambda settings: ToolAssistedStrategy(name=settings.name))
    factory.register_builder("router", lambda settings: RouterStrategy(name=settings.name))
    factory.register_builder("bounded_planner", lambda settings: BoundedPlannerStrategy(name=settings.name))
    factory.register_builder("fallback_answer", lambda settings: FallbackAnswerStrategy(name=settings.name))
    factory.register_builder("memory_update", lambda settings: MemoryUpdateStrategy(name=settings.name))
    return factory


def build_strategy_registry(
    config: ConfigurationView,
    *,
    factory: StrategyFactory | None = None,
) -> StrategyRegistry:
    """Build the runtime strategy registry from validated configuration."""

    strategy_factory = factory or default_strategy_factory()
    settings = get_orchestration_settings(config)
    return strategy_factory.build_registry(settings)


def _normalize_strategy_type(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("Strategy type must be a string.")
    normalized = value.strip()
    if not normalized:
        raise ValueError("Strategy type must not be empty.")
    return normalized