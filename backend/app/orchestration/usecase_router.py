"""Use-case routing and conservative strategy fallback for orchestration runtime."""

from __future__ import annotations

from collections.abc import Mapping
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
from app.visualization.context_selector import collect_chart_summaries


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

        visualization_override = self._resolve_visualization_override(
            request=request,
            usecase=usecase,
            strategy_registry=strategy_registry,
        )
        if visualization_override is not None:
            return visualization_override

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

    def _resolve_visualization_override(
        self,
        *,
        request: RequestContext,
        usecase: UseCaseSettings,
        strategy_registry: StrategyRegistry,
    ) -> ResolvedUseCaseRoute | None:
        if not self._visualization_enabled():
            return None
        if _visualization_override_disabled(usecase):
            return None
        if not self._looks_like_visualization_turn(request):
            return None
        if usecase.allowed_agents and "chart_agent" not in usecase.allowed_agents:
            return None
        if usecase.allowed_strategies and "direct_agent" not in usecase.allowed_strategies:
            return None

        try:
            resolved_strategy = strategy_registry.resolve(
                strategy_name="direct_agent",
                usecase=usecase.name,
                source="visualization",
            )
        except (StrategyNotFoundError, StrategyDisabledError):
            return None

        llm_profile = self._resolve_llm_profile(
            usecase=usecase,
            strategy=resolved_strategy.settings,
            agent_name="chart_agent",
        )
        return ResolvedUseCaseRoute(
            usecase=usecase,
            resolved_strategy=resolved_strategy,
            agent_name="chart_agent",
            llm_profile=llm_profile,
        )

    def _visualization_enabled(self) -> bool:
        configured = self._config.get("visualization.enabled")
        return configured if isinstance(configured, bool) else False

    def _looks_like_visualization_turn(self, request: RequestContext) -> bool:
        normalized_message = request.message.casefold()
        if _looks_like_chart_request(normalized_message):
            return True

        summaries = collect_chart_summaries(request.metadata)
        if not summaries:
            return False
        return _looks_like_chart_followup(normalized_message, summaries)

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


def _visualization_override_disabled(usecase: UseCaseSettings) -> bool:
    metadata = usecase.metadata if isinstance(usecase.metadata, Mapping) else {}
    if _read_optional_str(metadata.get("routing_mode")) == "task_first":
        return True

    raw_flag = metadata.get("keep_visualization_override_disabled")
    if isinstance(raw_flag, bool):
        return raw_flag
    normalized_flag = _read_optional_str(raw_flag)
    return normalized_flag in {"1", "true", "yes", "on"}


def _looks_like_chart_request(normalized_message: str) -> bool:
    request_markers = (
        " chart",
        "graph",
        "plot",
        "visualize",
        "visualization",
        "histogram",
        "heatmap",
        "scatter",
        "bubble",
        "pie",
        "donut",
        "treemap",
        "waterfall",
        "gantt",
        "radar",
    )
    return any(marker in normalized_message for marker in request_markers)


def _looks_like_chart_followup(
    normalized_message: str,
    summaries: tuple[object, ...],
) -> bool:
    if any(token in normalized_message for token in ("chart", "graph", "plot", "artifact")):
        return True

    question_cues = (
        "highest",
        "lowest",
        "trend",
        "compare",
        "comparison",
        "increase",
        "decrease",
        "which",
        "what",
        "why",
        "value",
    )
    if not any(cue in normalized_message for cue in question_cues):
        return False

    for summary in summaries:
        artifact_id = getattr(summary, "artifact_id", "")
        title = getattr(summary, "title", "")
        chart_type = getattr(summary, "chart_type", "")
        x_field = getattr(summary, "x_field", None)
        y_fields = getattr(summary, "y_fields", ())
        series_field = getattr(summary, "series_field", None)

        if isinstance(artifact_id, str) and artifact_id.casefold() in normalized_message:
            return True
        if isinstance(title, str) and title and title.casefold() in normalized_message:
            return True
        if isinstance(chart_type, str) and chart_type.replace("_", " ") in normalized_message:
            return True

        field_names = [x_field, series_field, *y_fields]
        for field_name in field_names:
            if isinstance(field_name, str) and field_name.casefold() in normalized_message:
                return True

    return False