"""Fallback-decision helpers for strategy/runtime coordination."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.contracts.context import OrchestrationContext
from app.contracts.errors import PolicyApprovalRequiredError, PolicyDeniedError
from app.policy.fallback_policy import build_fallback_policy_request
from app.orchestration.errors import (
    OrchestrationCancelledError,
    OrchestrationError,
    StrategyPolicyDeniedError,
    normalize_orchestration_error,
)
from app.orchestration.models import sanitize_metadata

_DEGRADABLE_ERROR_CODES = frozenset(
    {
        "dependency_unavailable",
        "orchestration_timeout",
        "agent_execution_failed",
        "agent_not_found",
    }
)


@dataclass(frozen=True, slots=True)
class FallbackDecision:
    """Safe fallback classification result."""

    allowed: bool
    reason: str
    error: OrchestrationError
    failed_strategy: str | None = None
    fallback_strategy: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "reason", _normalize_reason(self.reason))
        object.__setattr__(self, "failed_strategy", _normalize_optional_name(self.failed_strategy))
        object.__setattr__(self, "fallback_strategy", _normalize_optional_name(self.fallback_strategy))
        object.__setattr__(self, "metadata", sanitize_metadata(self.metadata))


def decide_fallback(
    error: BaseException,
    *,
    failed_strategy: str | None = None,
    fallback_strategy: str | None = None,
    side_effect_pending: bool = False,
    response_started: bool = False,
) -> FallbackDecision:
    """Classify whether a strategy failure is eligible for a safe fallback path."""

    normalized = normalize_orchestration_error(error)
    resolved_failed_strategy = _normalize_optional_name(failed_strategy)
    resolved_fallback_strategy = _normalize_optional_name(fallback_strategy)
    metadata = {
        "failed_strategy": resolved_failed_strategy,
        "fallback_strategy": resolved_fallback_strategy,
        "error_code": normalized.code,
        "retryable": normalized.retryable,
    }

    if resolved_fallback_strategy is None:
        return FallbackDecision(
            allowed=False,
            reason="fallback_not_configured",
            error=normalized,
            failed_strategy=resolved_failed_strategy,
            fallback_strategy=resolved_fallback_strategy,
            metadata={**metadata, "fallback_blocked": True},
        )
    if resolved_failed_strategy is not None and resolved_failed_strategy == resolved_fallback_strategy:
        return FallbackDecision(
            allowed=False,
            reason="fallback_loop",
            error=normalized,
            failed_strategy=resolved_failed_strategy,
            fallback_strategy=resolved_fallback_strategy,
            metadata={**metadata, "fallback_blocked": True},
        )
    if isinstance(normalized, StrategyPolicyDeniedError):
        return FallbackDecision(
            allowed=False,
            reason="policy_denied",
            error=normalized,
            failed_strategy=resolved_failed_strategy,
            fallback_strategy=resolved_fallback_strategy,
            metadata={**metadata, "fallback_blocked": True},
        )
    if isinstance(normalized, OrchestrationCancelledError):
        return FallbackDecision(
            allowed=False,
            reason="cancelled",
            error=normalized,
            failed_strategy=resolved_failed_strategy,
            fallback_strategy=resolved_fallback_strategy,
            metadata={**metadata, "fallback_blocked": True},
        )
    if side_effect_pending:
        return FallbackDecision(
            allowed=False,
            reason="side_effect_pending",
            error=normalized,
            failed_strategy=resolved_failed_strategy,
            fallback_strategy=resolved_fallback_strategy,
            metadata={**metadata, "fallback_blocked": True},
        )
    if response_started:
        return FallbackDecision(
            allowed=False,
            reason="response_started",
            error=normalized,
            failed_strategy=resolved_failed_strategy,
            fallback_strategy=resolved_fallback_strategy,
            metadata={**metadata, "fallback_blocked": True},
        )
    if normalized.retryable or normalized.code in _DEGRADABLE_ERROR_CODES:
        return FallbackDecision(
            allowed=True,
            reason="degradable_failure",
            error=normalized,
            failed_strategy=resolved_failed_strategy,
            fallback_strategy=resolved_fallback_strategy,
            metadata={**metadata, "fallback_blocked": False},
        )
    return FallbackDecision(
        allowed=False,
        reason="non_degradable_failure",
        error=normalized,
        failed_strategy=resolved_failed_strategy,
        fallback_strategy=resolved_fallback_strategy,
        metadata={**metadata, "fallback_blocked": True},
    )


async def enforce_fallback_policy(
    *,
    context: OrchestrationContext,
    error: BaseException,
    failed_strategy: str | None,
    fallback_strategy: str | None,
    side_effect_pending: bool = False,
    response_started: bool = False,
    fallback_requires_broader_permissions: bool = False,
) -> FallbackDecision:
    """Apply fallback classification plus policy gating for a degraded path."""

    decision = decide_fallback(
        error,
        failed_strategy=failed_strategy,
        fallback_strategy=fallback_strategy,
        side_effect_pending=side_effect_pending,
        response_started=response_started,
    )
    if not decision.allowed or decision.fallback_strategy is None:
        return decision

    request = build_fallback_policy_request(
        context=context,
        failed_strategy=decision.failed_strategy,
        fallback_strategy=decision.fallback_strategy,
        failure_type=decision.error.code,
        policy_denied=isinstance(decision.error, StrategyPolicyDeniedError),
        side_effect_may_have_started=side_effect_pending,
        response_started=response_started,
        fallback_requires_broader_permissions=fallback_requires_broader_permissions,
    )
    try:
        await context.policy.require_allowed(request, context)
    except PolicyApprovalRequiredError:
        return FallbackDecision(
            allowed=False,
            reason="approval_required",
            error=decision.error,
            failed_strategy=decision.failed_strategy,
            fallback_strategy=decision.fallback_strategy,
            metadata={**decision.metadata, "fallback_blocked": True},
        )
    except PolicyDeniedError:
        return FallbackDecision(
            allowed=False,
            reason="policy_denied",
            error=decision.error,
            failed_strategy=decision.failed_strategy,
            fallback_strategy=decision.fallback_strategy,
            metadata={**decision.metadata, "fallback_blocked": True},
        )
    return decision


def _normalize_reason(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("Fallback reason must be a string.")
    normalized = value.strip()
    if not normalized:
        raise ValueError("Fallback reason must not be empty.")
    return normalized


def _normalize_optional_name(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None