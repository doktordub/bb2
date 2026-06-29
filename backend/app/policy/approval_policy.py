"""Approval-required policy helpers shared by gateway and rule evaluators."""

from __future__ import annotations

from app.contracts.errors import PolicyApprovalRequiredError
from app.contracts.policy import PolicyDecision, PolicyObligation
from app.policy.decisions import approval_required_decision


def approval_required_obligation(
    *,
    target: str,
    value: object | None = None,
) -> PolicyObligation:
    return PolicyObligation(kind="require_approval", target=target, value=value)


def build_approval_required_decision(
    *,
    reason: str,
    reason_code: str,
    target: str,
    metadata: dict[str, object] | None = None,
    value: object | None = None,
) -> PolicyDecision:
    return approval_required_decision(
        reason=reason,
        reason_code=reason_code,
        metadata=dict(metadata or {}),
        obligations=(approval_required_obligation(target=target, value=value),),
    )


def raise_for_approval_required(decision: PolicyDecision) -> None:
    if decision.requires_approval:
        raise PolicyApprovalRequiredError(decision.safe_reason)