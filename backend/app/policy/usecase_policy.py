"""Use-case scoped policy helpers for the internal engine."""

from __future__ import annotations

from collections.abc import Mapping

from app.contracts.config import ConfigurationView
from app.contracts.context import OrchestrationContext
from app.contracts.policy import PolicyAction, PolicyDecision, PolicyRequest
from app.policy.context import resolve_scope_value
from app.policy.rule_matcher import is_name_allowed
from app.policy.settings import PolicyProfileSettings


async def evaluate_usecase_access(
    request: PolicyRequest,
    context: OrchestrationContext,
    profile: PolicyProfileSettings,
    config: ConfigurationView,
) -> PolicyDecision | None:
    """Apply profile-level use-case allowlists when they are configured."""

    allowed_usecases = profile.usecases.allowed
    usecase_only = _read_bool(request.metadata.get("usecase_only"), False)
    if not allowed_usecases:
        if not usecase_only:
            return None

    usecase_name = resolve_scope_value(
        request,
        context,
        key="usecase_name",
        fallback=resolve_scope_value(request, context, key="usecase", fallback=getattr(context.request, "usecase", None)),
    )
    if usecase_name is None:
        return PolicyDecision.deny(
            reason="The active use case is not configured.",
            reason_code="policy.usecase.missing",
        )

    usecase_config = config.get(f"orchestration.usecases.{usecase_name}")
    if not isinstance(usecase_config, Mapping):
        return PolicyDecision.deny(
            reason=f"Use case '{usecase_name}' is not configured.",
            reason_code="policy.usecase.unknown",
            metadata={"resource": usecase_name},
        )
    if not _read_bool(usecase_config.get("enabled"), True):
        return PolicyDecision.deny(
            reason=f"Use case '{usecase_name}' is disabled.",
            reason_code="policy.usecase.disabled",
            metadata={"resource": usecase_name},
        )

    if not allowed_usecases:
        return PolicyDecision.allow(
            reason_code="policy.usecase.allowed",
            metadata={"resource": usecase_name},
        )

    if is_name_allowed(allowed_usecases, usecase_name):
        return PolicyDecision.allow(
            reason_code="policy.usecase.allowed",
            metadata={"resource": usecase_name},
        )
    return PolicyDecision.deny(
        reason=f"Use case '{usecase_name or 'unknown'}' is not allowed by policy.",
        reason_code="policy.usecase.denied",
        metadata={"resource": usecase_name},
    )


def _read_bool(value: object, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def build_usecase_policy_request(
    *,
    component: str,
    usecase_name: str,
    session_id: str,
    user_id: str,
    action: PolicyAction = "orchestration.run_strategy",
    strategy_name: str | None = None,
    agent_name: str | None = None,
    llm_profile: str | None = None,
    extra_metadata: dict[str, object] | None = None,
) -> PolicyRequest:
    """Build a normalized use-case policy request for runtime entry checks."""

    metadata: dict[str, object] = {
        "actor_type": "user",
        "actor_id": user_id,
        "usecase_only": True,
    }
    if llm_profile is not None:
        metadata["llm_profile"] = llm_profile
    if extra_metadata:
        metadata.update(extra_metadata)

    return PolicyRequest(
        action=action,
        component=component,
        resource=usecase_name,
        scope={
            "usecase_name": usecase_name,
            "session_id": session_id,
            "user_id": user_id,
            "strategy_name": strategy_name,
            "agent_name": agent_name,
        },
        metadata=metadata,
    )