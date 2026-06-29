"""Helpers for constructing normalized policy decisions."""

from __future__ import annotations

from app.contracts.policy import PolicyDecision, PolicyObligation


def allow_decision(
    *,
    reason: str | None = None,
    reason_code: str | None = None,
    metadata: dict[str, object] | None = None,
    obligations: tuple[PolicyObligation, ...] = (),
) -> PolicyDecision:
    """Create a normalized allow decision."""

    return PolicyDecision.allow(
        reason=reason,
        reason_code=reason_code,
        metadata=dict(metadata or {}),
        obligations=obligations,
    )


def deny_decision(
    *,
    reason: str | None = None,
    reason_code: str | None = None,
    metadata: dict[str, object] | None = None,
    obligations: tuple[PolicyObligation, ...] = (),
) -> PolicyDecision:
    """Create a normalized deny decision."""

    return PolicyDecision.deny(
        reason=reason,
        reason_code=reason_code,
        metadata=dict(metadata or {}),
        obligations=obligations,
    )


def approval_required_decision(
    *,
    reason: str | None = None,
    reason_code: str | None = None,
    metadata: dict[str, object] | None = None,
    obligations: tuple[PolicyObligation, ...] = (),
) -> PolicyDecision:
    """Create a normalized approval-required decision."""

    return PolicyDecision.approval_required(
        reason=reason,
        reason_code=reason_code,
        metadata=dict(metadata or {}),
        obligations=obligations,
    )