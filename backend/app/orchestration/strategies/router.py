"""Router orchestration strategy."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, replace
from typing import Any, cast

from app.contracts.agents import AgentPlugin
from app.contracts.context import OrchestrationContext
from app.contracts.llm import LLMRequest
from app.contracts.policy import PolicyRequest
from app.contracts.results import OrchestrationResult as LegacyOrchestrationResult
from app.contracts.results import StreamEvent
from app.orchestration.cancellation import raise_if_cancelled
from app.orchestration.errors import StrategyNotFoundError
from app.orchestration.events import OrchestrationStreamEvent
from app.orchestration.limits import OrchestrationLimitTracker
from app.orchestration.prompt_inputs import PromptSection, build_prompt_messages
from app.orchestration.strategy_steps import run_llm_completion_step
from app.orchestration.strategies.direct_agent import DirectAgentStrategy
from app.orchestration.strategies.retrieval_augmented import RetrievalAugmentedStrategy
from app.orchestration.strategies.tool_assisted import ToolAssistedStrategy

_COMPONENT = "orchestration.strategy.router"


@dataclass(slots=True)
class RouterStrategy:
    """Select one configured child strategy using conservative rules first."""

    name: str = "router"

    async def run(
        self,
        *,
        context: OrchestrationContext,
        agents: Sequence[AgentPlugin],
    ) -> LegacyOrchestrationResult:
        raise_if_cancelled(_cancellation_token(context))
        strategy_name, child_strategy, reason = await _resolve_route(context)
        child_context = _child_context(context, strategy_name=strategy_name, route_reason=reason)
        await context.policy.require_allowed(
            PolicyRequest(
                action="orchestration.run_strategy",
                component=_COMPONENT,
                resource=strategy_name,
                scope={
                    "usecase_name": context.request.usecase,
                    "strategy_name": strategy_name,
                    "agent_name": _runtime_value(context, "agent_name"),
                },
                metadata={"routed_by": self.name, "route_reason": reason},
            ),
            context,
        )
        result = cast(
            LegacyOrchestrationResult,
            await child_strategy.run(context=child_context, agents=agents),
        )
        result.metadata["routed_by"] = self.name
        result.metadata["route_reason"] = reason
        result.metadata["routed_strategy"] = strategy_name
        return result

    async def stream(
        self,
        *,
        context: OrchestrationContext,
        agents: Sequence[AgentPlugin],
    ) -> AsyncIterator[StreamEvent | OrchestrationStreamEvent]:
        raise_if_cancelled(_cancellation_token(context))
        strategy_name, child_strategy, reason = await _resolve_route(context)
        child_context = _child_context(context, strategy_name=strategy_name, route_reason=reason)
        await context.policy.require_allowed(
            PolicyRequest(
                action="orchestration.run_strategy",
                component=_COMPONENT,
                resource=strategy_name,
                scope={
                    "usecase_name": context.request.usecase,
                    "strategy_name": strategy_name,
                    "agent_name": _runtime_value(context, "agent_name"),
                },
                metadata={"routed_by": self.name, "route_reason": reason},
            ),
            context,
        )
        yield OrchestrationStreamEvent.strategy_selected(
            trace_id=context.request.trace_id or "unknown_trace",
            session_id=context.request.session_id,
            strategy_name=strategy_name,
            usecase=context.request.usecase,
            agent_name=_runtime_value(context, "agent_name"),
            llm_profile=_runtime_value(child_context, "llm_profile"),
            metadata={"routed_by": self.name, "route_reason": reason},
        )
        async for event in child_strategy.stream(context=child_context, agents=agents):
            yield event


async def _resolve_route(
    context: OrchestrationContext,
) -> tuple[str, Any, str]:
    limits = _require_limits(context)
    limits.consume_step()
    candidates = await _candidate_entries(context)
    if not candidates:
        raise StrategyNotFoundError("Router strategy has no configured candidate strategies.")
    candidate_map = {name: strategy for name, strategy in candidates}
    candidate_names = [name for name, _ in candidates]

    requested = _requested_strategy(context)
    if requested is not None and requested in candidate_map:
        return (requested, candidate_map[requested], "request_metadata")

    if _use_llm_classifier(context):
        selected = await _classify_with_llm(context, candidate_names)
        if selected is not None and selected in candidate_map:
            return (selected, candidate_map[selected], "llm_classifier")

    lowered = context.request.message.strip().casefold()
    if lowered.startswith("tool:") and "tool_assisted" in candidate_map:
        return ("tool_assisted", candidate_map["tool_assisted"], "tool_prefix")
    if any(token in lowered for token in ("document", "doc", "architecture", "memory")):
        if "retrieval_augmented" in candidate_map:
            return (
                "retrieval_augmented",
                candidate_map["retrieval_augmented"],
                "retrieval_keyword",
            )
    if "direct_agent" in candidate_map:
        return ("direct_agent", candidate_map["direct_agent"], "default_direct")

    selected = candidate_names[0]
    return (selected, candidate_map[selected], "candidate_fallback")


async def _classify_with_llm(
    context: OrchestrationContext,
    candidate_names: list[str],
) -> str | None:
    profile = _runtime_value(context, "llm_profile") or (
        None if context.strategy_settings is None else context.strategy_settings.llm_profile
    )
    if profile is None:
        return None
    response = await run_llm_completion_step(
        context,
        component=_COMPONENT,
        request=LLMRequest(
            component=_COMPONENT,
            profile=profile,
            messages=build_prompt_messages(
                user_request=context.request.message,
                sections=[
                    PromptSection(
                        title="Candidate strategies",
                        body=", ".join(candidate_names),
                    )
                ],
                system_prompt=(
                    "Choose exactly one candidate strategy name that best fits the user request. "
                    "Return only the candidate name."
                ),
            ),
        ),
        agent_name=_runtime_value(context, "agent_name"),
        strategy_name=_strategy_name(context),
    )
    normalized = response.text.strip()
    for candidate_name in candidate_names:
        if candidate_name.casefold() == normalized.casefold():
            return candidate_name

    lowered = normalized.casefold()
    for candidate_name in candidate_names:
        if candidate_name.casefold() in lowered:
            return candidate_name
    return None


async def _candidate_entries(
    context: OrchestrationContext,
) -> list[tuple[str, Any]]:
    if context.strategy_settings is None:
        return []

    candidates: list[tuple[str, Any]] = []
    for strategy_name in context.strategy_settings.candidate_strategies:
        if strategy_name == _strategy_name(context):
            continue
        strategy = _build_child_strategy(context, strategy_name)
        if strategy is None:
            continue
        if not await _candidate_allowed_by_policy(context, strategy_name):
            continue
        candidates.append((strategy_name, strategy))
    return candidates


async def _candidate_allowed_by_policy(
    context: OrchestrationContext,
    strategy_name: str,
) -> bool:
    decision = await context.policy.evaluate(
        PolicyRequest(
            action="orchestration.run_strategy",
            component=_COMPONENT,
            resource=strategy_name,
            scope={
                "usecase_name": context.request.usecase,
                "strategy_name": strategy_name,
                "agent_name": _runtime_value(context, "agent_name"),
            },
            metadata={"candidate": True, "routed_by": "router"},
        ),
        context,
    )
    return decision.allowed


def _build_child_strategy(context: OrchestrationContext, strategy_name: str) -> Any | None:
    registry = context.metadata.get("strategy_registry")
    if registry is not None:
        try:
            resolved = registry.resolve(
                strategy_name=strategy_name,
                usecase=context.request.usecase,
                source="router_candidate",
            )
        except StrategyNotFoundError:
            return None
        return resolved.strategy

    settings = None if context.settings is None else context.settings.strategies.get(strategy_name)
    if settings is None:
        return None
    if not settings.enabled:
        return None
    if settings.type == "direct_agent":
        return DirectAgentStrategy(name=settings.name)
    if settings.type == "retrieval_augmented":
        return RetrievalAugmentedStrategy(name=settings.name)
    if settings.type == "tool_assisted":
        return ToolAssistedStrategy(name=settings.name)
    return None


def _child_context(
    context: OrchestrationContext,
    *,
    strategy_name: str,
    route_reason: str,
) -> OrchestrationContext:
    if context.settings is None:
        raise StrategyNotFoundError("Router strategy requires orchestration settings.")
    settings = context.settings.strategies.get(strategy_name)
    if settings is None:
        raise StrategyNotFoundError(f"Strategy '{strategy_name}' is not configured.")
    runtime_metadata = dict(context.runtime_metadata)
    runtime_metadata["strategy_name"] = strategy_name
    runtime_metadata["route_reason"] = route_reason
    if settings.llm_profile is not None:
        runtime_metadata["llm_profile"] = settings.llm_profile
    return replace(
        context,
        strategy_settings=settings,
        runtime_metadata=runtime_metadata,
    )


def _requested_strategy(context: OrchestrationContext) -> str | None:
    for key in ("requested_strategy", "strategy_override"):
        value = _read_optional_str(context.request.metadata.get(key))
        if value is not None:
            return value
    return None


def _use_llm_classifier(context: OrchestrationContext) -> bool:
    if context.strategy_settings is None:
        return False
    raw_value = context.strategy_settings.metadata.get("use_llm_classifier")
    return bool(raw_value)


def _strategy_name(context: OrchestrationContext) -> str:
    return _runtime_value(context, "strategy_name") or "router"


def _runtime_value(context: OrchestrationContext, key: str) -> str | None:
    value = context.runtime_metadata.get(key)
    return _read_optional_str(value)


def _read_optional_str(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _require_limits(context: OrchestrationContext) -> OrchestrationLimitTracker:
    if context.limits is None:
        raise RuntimeError("Orchestration limits are required for router strategy execution.")
    return context.limits


def _cancellation_token(context: OrchestrationContext) -> object | None:
    if context.runtime is None:
        return None
    return context.runtime.cancellation_token