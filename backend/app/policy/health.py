"""Frontend-safe health exposure policy helpers."""

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


def build_health_policy_request(
    *,
    trace_id: str | None,
    user_id: str | None,
    payload: Mapping[str, Any],
) -> PolicyRequest:
    """Build a normalized policy request for health response exposure."""

    actor = PolicyActor(actor_type="user" if user_id else "anonymous", actor_id=user_id, user_id=user_id)
    metadata = {"field_names": tuple(sorted(str(key) for key in payload.keys()))}
    evaluation = PolicyEvaluationContext(
        trace_id=trace_id,
        exposure_level="summary",
        tags=("health",),
        metadata=dict(metadata),
    )
    return PolicyRequest(
        action="health.read",
        component="api.health",
        resource="health_response",
        scope={"user_id": user_id},
        metadata=metadata,
        actor=actor,
        evaluation=evaluation,
    )


async def evaluate_health_request(
    request: PolicyRequest,
    context: OrchestrationContext,
    profile: PolicyProfileSettings,
) -> PolicyDecision | None:
    """Evaluate whether API health metadata may be exposed."""

    _ = context
    if not profile.health.expose_enabled:
        return PolicyDecision.deny(
            reason="Health exposure is disabled by policy.",
            reason_code="policy.health.disabled",
            metadata={"resource": request.resource},
        )
    return PolicyDecision.allow(
        reason_code="policy.health.allowed",
        metadata={"resource": request.resource},
    )


def sanitize_health_payload(
    payload: Mapping[str, Any],
    *,
    profile: PolicyProfileSettings,
) -> dict[str, Any]:
    """Strip policy-sensitive fields from the health response."""

    sanitized = dict(payload)
    if not profile.health.include_profile_names:
        llm = sanitized.get("llm")
        if isinstance(llm, Mapping):
            llm_payload = dict(llm)
            llm_payload.pop("profiles", None)
            sanitized["llm"] = llm_payload
        policy_component = sanitized.get("policy")
        if isinstance(policy_component, Mapping):
            policy_payload = dict(policy_component)
            policy_payload.pop("default_profile", None)
            sanitized["policy"] = policy_payload

    if not profile.health.include_decision_counts:
        checks = sanitized.get("checks")
        if isinstance(checks, Mapping):
            sanitized["checks"] = {
                name: _strip_decision_counts(component)
                for name, component in checks.items()
            }

    _strip_sensitive_fields(sanitized)
    return sanitized


def _strip_decision_counts(component: object) -> object:
    if not isinstance(component, Mapping):
        return component
    return {
        key: value
        for key, value in component.items()
        if str(key) not in {"decision_counts", "rule_counts"}
    }


def _strip_sensitive_fields(payload: dict[str, Any]) -> None:
    for key in (
        "endpoint",
        "endpoints",
        "path",
        "paths",
        "database",
        "sqlite_path",
        "memory_provider",
        "trace_provider",
        "workflow_state_provider",
    ):
        payload.pop(key, None)
    for value in payload.values():
        if isinstance(value, dict):
            _strip_sensitive_fields(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    _strip_sensitive_fields(item)