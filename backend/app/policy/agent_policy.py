"""Agent policy evaluators used by the internal policy engine."""

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


async def evaluate_agent_access(
    request: PolicyRequest,
    context: OrchestrationContext,
    profile: PolicyProfileSettings,
    config: ConfigurationView,
) -> PolicyDecision | None:
    """Evaluate configured agent access for explicit agent invocation."""

    agent_name = request.resource or resolve_scope_value(request, context, key="agent_name")
    if agent_name is None:
        return PolicyDecision.deny(
            reason="No agent was selected.",
            reason_code="policy.agent.missing_agent",
        )

    if not is_name_allowed(profile.agents.allowed, agent_name):
        return PolicyDecision.deny(
            reason=f"Agent '{agent_name}' is not allowed by policy.",
            reason_code="policy.agent.profile_denied",
            metadata={"resource": agent_name},
        )

    agent_config = config.get(f"agents.{agent_name}")
    if not isinstance(agent_config, Mapping):
        return PolicyDecision.deny(
            reason=f"Agent '{agent_name}' is not configured.",
            reason_code="policy.agent.unknown",
            metadata={"resource": agent_name},
        )

    usecase_name = resolve_scope_value(
        request,
        context,
        key="usecase_name",
        fallback=resolve_scope_value(request, context, key="usecase", fallback=getattr(context.request, "usecase", None)),
    )
    if usecase_name is None:
        return PolicyDecision.allow(
            reason_code="policy.agent.allowed",
            metadata={"resource": agent_name},
        )

    try:
        settings = get_orchestration_settings(config)
    except ConfigurationError:
        return PolicyDecision.deny(
            reason="Orchestration configuration is invalid.",
            reason_code="policy.agent.invalid_config",
            metadata={"resource": agent_name},
        )

    usecase = settings.usecases.get(usecase_name)
    if usecase is not None and usecase.allowed_agents and agent_name not in usecase.allowed_agents:
        return PolicyDecision.deny(
            reason=f"Agent '{agent_name}' is not allowed for use case '{usecase_name}'.",
            reason_code="policy.agent.usecase_mismatch",
            metadata={"resource": agent_name},
        )

    return PolicyDecision.allow(
        reason_code="policy.agent.allowed",
        metadata={"resource": agent_name, "usecase": usecase_name},
    )