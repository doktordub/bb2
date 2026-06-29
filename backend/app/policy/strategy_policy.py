"""Strategy policy evaluators used by the internal policy engine."""

from __future__ import annotations

from collections.abc import Mapping

from app.config.view import get_orchestration_settings
from app.contracts.config import ConfigurationView
from app.contracts.context import OrchestrationContext
from app.contracts.errors import ConfigurationError
from app.contracts.policy import PolicyDecision, PolicyRequest
from app.policy.context import resolve_scope_value
from app.policy.rule_matcher import is_name_allowed
from app.policy.settings import PolicyProfileSettings


async def evaluate_strategy_access(
    request: PolicyRequest,
    context: OrchestrationContext,
    profile: PolicyProfileSettings,
    config: ConfigurationView,
) -> PolicyDecision | None:
    """Evaluate configured orchestration strategy access."""

    if _read_bool(request.metadata.get("usecase_only"), False):
        return None

    usecase_name = resolve_scope_value(
        request,
        context,
        key="usecase_name",
        fallback=resolve_scope_value(request, context, key="usecase", fallback=getattr(context.request, "usecase", None)),
    )
    strategy_name = request.resource or resolve_scope_value(request, context, key="strategy_name")
    agent_name = resolve_scope_value(request, context, key="agent_name")

    try:
        settings = get_orchestration_settings(config)
    except ConfigurationError:
        return PolicyDecision.deny(
            reason="Orchestration configuration is invalid.",
            reason_code="policy.strategy.invalid_config",
        )

    if not settings.enabled:
        return PolicyDecision.deny(
            reason="Orchestration is disabled.",
            reason_code="policy.strategy.orchestration_disabled",
        )

    if usecase_name is None:
        return PolicyDecision.deny(
            reason="The active use case is not configured.",
            reason_code="policy.strategy.missing_usecase",
        )

    usecase = settings.usecases.get(usecase_name)
    if usecase is None:
        return PolicyDecision.deny(
            reason=f"Use case '{usecase_name}' is not configured.",
            reason_code="policy.strategy.unknown_usecase",
            metadata={"resource": usecase_name},
        )
    if not usecase.enabled:
        return PolicyDecision.deny(
            reason=f"Use case '{usecase_name}' is disabled.",
            reason_code="policy.strategy.usecase_disabled",
            metadata={"resource": usecase_name},
        )

    if strategy_name is None:
        return PolicyDecision.deny(
            reason="No orchestration strategy was selected.",
            reason_code="policy.strategy.missing_strategy",
        )

    if not is_name_allowed(profile.strategies.allowed, strategy_name):
        return PolicyDecision.deny(
            reason=f"Strategy '{strategy_name}' is not allowed by policy.",
            reason_code="policy.strategy.profile_denied",
            metadata={"resource": strategy_name},
        )

    strategy = settings.strategies.get(strategy_name)
    if strategy is None:
        return PolicyDecision.deny(
            reason=f"Strategy '{strategy_name}' is not configured.",
            reason_code="policy.strategy.unknown_strategy",
            metadata={"resource": strategy_name},
        )
    if not strategy.enabled:
        return PolicyDecision.deny(
            reason=f"Strategy '{strategy_name}' is disabled.",
            reason_code="policy.strategy.disabled",
            metadata={"resource": strategy_name},
        )
    if usecase.allowed_strategies and strategy_name not in usecase.allowed_strategies:
        return PolicyDecision.deny(
            reason=f"Strategy '{strategy_name}' is not allowed for use case '{usecase_name}'.",
            reason_code="policy.strategy.usecase_allowlist_denied",
            metadata={"resource": strategy_name},
        )
    if strategy.allowed_usecases and usecase_name not in strategy.allowed_usecases:
        return PolicyDecision.deny(
            reason=f"Strategy '{strategy_name}' is not allowed for use case '{usecase_name}'.",
            reason_code="policy.strategy.usecase_mismatch",
            metadata={"resource": strategy_name},
        )

    if agent_name is not None:
        if not is_name_allowed(profile.agents.allowed, agent_name):
            return PolicyDecision.deny(
                reason=f"Agent '{agent_name}' is not allowed by policy.",
                reason_code="policy.strategy.agent_profile_denied",
                metadata={"resource": agent_name},
            )

        agent_config = config.get(f"agents.{agent_name}")
        if not isinstance(agent_config, Mapping):
            return PolicyDecision.deny(
                reason=f"Agent '{agent_name}' is not configured.",
                reason_code="policy.strategy.unknown_agent",
                metadata={"resource": agent_name},
            )
        if usecase.allowed_agents and agent_name not in usecase.allowed_agents:
            return PolicyDecision.deny(
                reason=f"Agent '{agent_name}' is not allowed for use case '{usecase_name}'.",
                reason_code="policy.strategy.agent_usecase_mismatch",
                metadata={"resource": agent_name},
            )

    return PolicyDecision.allow(
        reason_code="policy.strategy.allowed",
        metadata={
            "resource": strategy_name,
            "usecase": usecase_name,
            "agent_name": agent_name,
        },
    )


def _read_bool(value: object, default: bool) -> bool:
    return value if isinstance(value, bool) else default