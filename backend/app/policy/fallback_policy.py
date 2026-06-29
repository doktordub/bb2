"""Typed fallback policy helpers and evaluators."""

from __future__ import annotations

from app.contracts.context import OrchestrationContext
from app.contracts.policy import (
    PolicyActor,
    PolicyDecision,
    PolicyEvaluationContext,
    PolicyRequest,
)
from app.policy.settings import PolicyProfileSettings

_DEGRADABLE_FAILURE_TYPES = frozenset(
    {
        "dependency_unavailable",
        "orchestration_timeout",
        "agent_execution_failed",
        "agent_not_found",
    }
)


def build_fallback_policy_request(
    *,
    context: OrchestrationContext,
    failed_strategy: str | None,
    fallback_strategy: str | None,
    failure_type: str,
    policy_denied: bool,
    side_effect_may_have_started: bool,
    response_started: bool,
    fallback_requires_broader_permissions: bool = False,
) -> PolicyRequest:
    """Build a normalized policy request for a strategy fallback attempt."""

    request_context = context.request
    actor = PolicyActor(
        actor_type="user" if request_context.user_id else "anonymous",
        actor_id=request_context.user_id,
        user_id=request_context.user_id,
        session_id=request_context.session_id,
    )
    metadata = {
        "failure_type": failure_type,
        "policy_denied": policy_denied,
        "side_effect_may_have_started": side_effect_may_have_started,
        "response_started": response_started,
        "fallback_requires_broader_permissions": fallback_requires_broader_permissions,
    }
    evaluation = PolicyEvaluationContext(
        trace_id=request_context.trace_id,
        usecase_name=request_context.usecase,
        strategy_name=failed_strategy,
        risk_level="degraded_path",
        exposure_level="summary",
        tags=("fallback",),
        metadata=dict(metadata),
    )
    return PolicyRequest(
        action="fallback.execute",
        component="orchestration.fallback",
        resource=fallback_strategy,
        scope={
            "user_id": request_context.user_id,
            "session_id": request_context.session_id,
            "usecase_name": request_context.usecase,
            "strategy_name": failed_strategy,
        },
        metadata=metadata,
        actor=actor,
        evaluation=evaluation,
    )


async def evaluate_fallback_request(
    request: PolicyRequest,
    context: OrchestrationContext,
    profile: PolicyProfileSettings,
) -> PolicyDecision | None:
    """Evaluate whether a degraded fallback path is safe to use."""

    _ = context
    fallback_strategy = request.resource
    failure_type = _optional_text(request.metadata.get("failure_type")) or "unknown"
    policy_denied = _read_bool(request.metadata.get("policy_denied"), False)
    side_effect_may_have_started = _read_bool(
        request.metadata.get("side_effect_may_have_started"),
        False,
    )
    response_started = _read_bool(request.metadata.get("response_started"), False)
    broader_permissions = _read_bool(
        request.metadata.get("fallback_requires_broader_permissions"),
        False,
    )

    if not profile.fallback.allow_fallbacks:
        return PolicyDecision.deny(
            reason="Fallback is disabled by policy.",
            reason_code="policy.fallback.disabled",
            metadata={"resource": fallback_strategy, "failure_type": failure_type},
        )
    if fallback_strategy is None:
        return PolicyDecision.deny(
            reason="No fallback strategy is configured.",
            reason_code="policy.fallback.not_configured",
            metadata={"failure_type": failure_type},
        )
    if profile.fallback.allowed_strategies and fallback_strategy not in profile.fallback.allowed_strategies:
        return PolicyDecision.deny(
            reason=f"Fallback strategy '{fallback_strategy}' is not allowed by policy.",
            reason_code="policy.fallback.strategy_denied",
            metadata={"resource": fallback_strategy, "failure_type": failure_type},
        )
    if policy_denied and not profile.fallback.allow_after_denial:
        return PolicyDecision.deny(
            reason="Fallback after policy denial is not allowed.",
            reason_code="policy.fallback.after_denial_denied",
            metadata={"resource": fallback_strategy, "failure_type": failure_type},
        )
    if side_effect_may_have_started and not profile.fallback.allow_after_external_side_effects:
        return PolicyDecision.deny(
            reason="Fallback after a possible side effect is not allowed.",
            reason_code="policy.fallback.side_effect_denied",
            metadata={"resource": fallback_strategy, "failure_type": failure_type},
        )
    if response_started:
        return PolicyDecision.deny(
            reason="Fallback after response emission is not allowed.",
            reason_code="policy.fallback.response_started_denied",
            metadata={"resource": fallback_strategy, "failure_type": failure_type},
        )
    if broader_permissions:
        return PolicyDecision.deny(
            reason="Fallback that requires broader permissions is not allowed.",
            reason_code="policy.fallback.broader_permissions_denied",
            metadata={"resource": fallback_strategy, "failure_type": failure_type},
        )
    if failure_type not in _DEGRADABLE_FAILURE_TYPES:
        return PolicyDecision.deny(
            reason="Fallback is not allowed for this failure type.",
            reason_code="policy.fallback.failure_type_denied",
            metadata={"resource": fallback_strategy, "failure_type": failure_type},
        )

    return PolicyDecision.allow(
        reason_code="policy.fallback.allowed",
        metadata={"resource": fallback_strategy, "failure_type": failure_type},
    )


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _read_bool(value: object, default: bool) -> bool:
    return value if isinstance(value, bool) else default