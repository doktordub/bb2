"""Frontend-safe capability exposure policy helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.contracts.context import OrchestrationContext
from app.contracts.policy import (
    PolicyActor,
    PolicyDecision,
    PolicyEvaluationContext,
    PolicyRequest,
)
from app.policy.settings import PolicyProfileSettings


def build_capabilities_policy_request(
    *,
    trace_id: str | None,
    user_id: str | None,
    payload: Mapping[str, Any],
) -> PolicyRequest:
    """Build a normalized policy request for capabilities response exposure."""

    actor = PolicyActor(actor_type="user" if user_id else "anonymous", actor_id=user_id, user_id=user_id)
    metadata = {"field_names": tuple(sorted(str(key) for key in payload.keys()))}
    evaluation = PolicyEvaluationContext(
        trace_id=trace_id,
        exposure_level="summary",
        tags=("capabilities",),
        metadata=dict(metadata),
    )
    return PolicyRequest(
        action="capabilities.read",
        component="api.capabilities",
        resource="capabilities_response",
        scope={"user_id": user_id},
        metadata=metadata,
        actor=actor,
        evaluation=evaluation,
    )


async def evaluate_capabilities_request(
    request: PolicyRequest,
    context: OrchestrationContext,
    profile: PolicyProfileSettings,
) -> PolicyDecision | None:
    """Evaluate whether API capability metadata may be exposed."""

    _ = context
    if not profile.capabilities.expose_enabled:
        return PolicyDecision.deny(
            reason="Capabilities exposure is disabled by policy.",
            reason_code="policy.capabilities.disabled",
            metadata={"resource": request.resource},
        )
    return PolicyDecision.allow(
        reason_code="policy.capabilities.allowed",
        metadata={"resource": request.resource},
    )


def sanitize_capabilities_payload(
    payload: Mapping[str, Any],
    *,
    profile: PolicyProfileSettings,
) -> dict[str, Any]:
    """Strip policy-sensitive fields from the capabilities response."""

    sanitized = dict(payload)
    if not profile.capabilities.include_policy_profiles:
        sanitized.pop("policy", None)

    if not profile.capabilities.include_denied_actions:
        debug = sanitized.get("debug")
        if isinstance(debug, Mapping):
            sanitized["debug"] = {
                key: value
                for key, value in debug.items()
                if str(key) not in {"denied_actions", "policy_profiles"}
            }

    _strip_sensitive_fields(sanitized)
    return sanitized


def _strip_sensitive_fields(payload: dict[str, Any]) -> None:
    for key in ("endpoint", "endpoints", "url", "urls", "schema"):
        if key in payload:
            payload.pop(key, None)
    for value in payload.values():
        if isinstance(value, dict):
            _strip_sensitive_fields(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    _strip_sensitive_fields(item)