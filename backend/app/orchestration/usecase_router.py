"""Use-case routing and conservative strategy fallback for orchestration runtime."""

from __future__ import annotations

from dataclasses import dataclass

from app.config.view import StrategySettings, UseCaseSettings, get_orchestration_settings
from app.contracts.config import ConfigurationView
from app.contracts.context import RequestContext
from app.orchestration.errors import (
    AgentNotFoundError,
    OrchestrationDisabledError,
    StrategyDisabledError,
    StrategyNotFoundError,
    UnknownUseCaseError,
)
from app.orchestration.strategy_registry import ResolvedStrategy, StrategyRegistry


@dataclass(frozen=True, slots=True)
class ResolvedUseCaseRoute:
    """Resolved route for one orchestration turn."""

    usecase: UseCaseSettings
    resolved_strategy: ResolvedStrategy
    agent_name: str
    llm_profile: str | None

    @property
    def strategy_name(self) -> str:
        return self.resolved_strategy.settings.name


class UseCaseRouter:
    """Resolve the active use case, strategy, agent, and LLM profile."""

    def __init__(self, config: ConfigurationView) -> None:
        self._config = config

    def resolve(
        self,
        request: RequestContext,
        *,
        strategy_registry: StrategyRegistry,
    ) -> ResolvedUseCaseRoute:
        settings = get_orchestration_settings(self._config)
        if not settings.enabled:
            raise OrchestrationDisabledError()

        usecase_name = self._resolve_usecase_name(request)
        if usecase_name is None:
            raise UnknownUseCaseError("Active use case is not configured.")

        usecase = settings.usecases.get(usecase_name)
        if usecase is None:
            raise UnknownUseCaseError(f"Use case '{usecase_name}' is not configured.")
        if not usecase.enabled:
            raise UnknownUseCaseError(f"Use case '{usecase_name}' is disabled.")

        last_error: StrategyNotFoundError | StrategyDisabledError | None = None
        for source, strategy_name in self._strategy_candidates(usecase=usecase):
            try:
                resolved_strategy = strategy_registry.resolve(
                    strategy_name=strategy_name,
                    usecase=usecase.name,
                    source=source,
                )
            except StrategyNotFoundError as exc:
                last_error = exc
                continue
            except StrategyDisabledError as exc:
                if source == "usecase":
                    raise exc
                last_error = exc
                continue

            agent_name = self._resolve_agent_name(
                usecase=usecase,
                strategy=resolved_strategy.settings,
            )
            llm_profile = self._resolve_llm_profile(
                usecase=usecase,
                strategy=resolved_strategy.settings,
                agent_name=agent_name,
            )
            return ResolvedUseCaseRoute(
                usecase=usecase,
                resolved_strategy=resolved_strategy,
                agent_name=agent_name,
                llm_profile=llm_profile,
            )

        if last_error is not None:
            raise last_error

        raise StrategyNotFoundError(
            f"No strategy is configured for use case '{usecase.name}'."
        )

    def _resolve_usecase_name(self, request: RequestContext) -> str | None:
        return (
            _read_optional_str(request.usecase)
            or _read_optional_str(self._config.get("session.defaults.default_usecase"))
            or _read_optional_str(self._config.get("app.active_usecase"))
        )

    def _strategy_candidates(self, *, usecase: UseCaseSettings) -> tuple[tuple[str, str], ...]:
        settings = get_orchestration_settings(self._config)
        candidates: list[tuple[str, str]] = []
        for source, strategy_name in (
            ("usecase", usecase.strategy),
            ("default", settings.defaults.strategy),
            ("fallback", settings.defaults.fallback_strategy),
        ):
            if not strategy_name:
                continue
            if any(existing_name == strategy_name for _, existing_name in candidates):
                continue
            candidates.append((source, strategy_name))
        return tuple(candidates)

    def _resolve_agent_name(
        self,
        *,
        usecase: UseCaseSettings,
        strategy: StrategySettings,
    ) -> str:
        agent_name = usecase.agent or strategy.default_agent
        if agent_name is None:
            raise AgentNotFoundError(
                f"No agent is configured for use case '{usecase.name}' and strategy '{strategy.name}'."
            )

        if usecase.allowed_agents and agent_name not in usecase.allowed_agents:
            raise AgentNotFoundError(
                f"Configured agent '{agent_name}' is not allowed for use case '{usecase.name}'."
            )
        return agent_name

    def _resolve_llm_profile(
        self,
        *,
        usecase: UseCaseSettings,
        strategy: StrategySettings,
        agent_name: str,
    ) -> str | None:
        return (
            usecase.llm_profile
            or strategy.llm_profile
            or _read_optional_str(self._config.get(f"agents.{agent_name}.llm_profile"))
            or _read_optional_str(self._config.get("llm.defaults.profile"))
        )


def _read_optional_str(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None