"""Typed LLM policy helpers used by gateway final-enforcement checks."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.contracts.context import OrchestrationContext
from app.contracts.policy import (
    PolicyAction,
    PolicyActor,
    PolicyDecision,
    PolicyEvaluationContext,
    PolicyRequest,
    PolicyScope,
)
from app.policy.context import resolve_scope_value
from app.policy.rule_matcher import is_name_allowed
from app.policy.settings import PolicyProfileSettings

if TYPE_CHECKING:
    from app.llm.models import ResolvedLLMRequest


def build_llm_policy_request(
    *,
    action: PolicyAction,
    resolved: ResolvedLLMRequest,
    context: OrchestrationContext,
    fallback_from_profile: str | None = None,
) -> PolicyRequest:
    """Build a normalized policy request for an LLM gateway operation."""

    request_context = context.request
    runtime_metadata = context.runtime_metadata
    strategy_name = resolved.strategy_name or _optional_text(
        runtime_metadata.get("strategy_name")
    )
    agent_name = resolved.agent_name or _optional_text(runtime_metadata.get("agent_name"))
    project_id = _optional_text(request_context.metadata.get("project_id"))

    actor = PolicyActor(
        actor_type="user" if request_context.user_id else "anonymous",
        actor_id=request_context.user_id,
        user_id=request_context.user_id,
        session_id=request_context.session_id,
    )
    scope = PolicyScope(
        project_id=project_id,
        user_id=request_context.user_id,
        session_id=request_context.session_id,
        usecase_name=resolved.usecase_name or request_context.usecase,
        strategy_name=strategy_name,
        agent_name=agent_name,
        resource_id=resolved.profile_name,
    )
    evaluation = PolicyEvaluationContext(
        trace_id=request_context.trace_id,
        usecase_name=scope.usecase_name,
        strategy_name=strategy_name,
        agent_name=agent_name,
        llm_profile=resolved.profile_name,
        exposure_level="summary",
        tags=("llm", "stream" if resolved.stream else "complete"),
        metadata={
            "provider": resolved.provider_name,
            "model": resolved.model,
            "stream": resolved.stream,
            "max_input_tokens": resolved.profile.max_input_tokens,
            "max_output_tokens": resolved.max_output_tokens,
            "max_total_tokens": resolved.profile.max_total_tokens,
            "fallback_from_profile": fallback_from_profile,
        },
    )
    return PolicyRequest(
        action=action,
        component=resolved.component,
        resource=resolved.profile_name,
        scope={
            "project_id": scope.project_id,
            "user_id": scope.user_id,
            "session_id": scope.session_id,
            "usecase_name": scope.usecase_name,
            "strategy_name": scope.strategy_name,
            "agent_name": scope.agent_name,
        },
        metadata={
            "trace_id": request_context.trace_id,
            "provider": resolved.provider_name,
            "model": resolved.model,
            "stream": resolved.stream,
            "fallback_from_profile": fallback_from_profile,
        },
        actor=actor,
        evaluation=evaluation,
    )


async def evaluate_llm_request(
    request: PolicyRequest,
    context: OrchestrationContext,
    profile: PolicyProfileSettings,
) -> PolicyDecision | None:
    """Apply typed LLM profile access and fallback checks."""

    llm_profile_name = request.resource
    if llm_profile_name is None:
        return PolicyDecision.deny(
            reason="No LLM profile was selected.",
            reason_code="policy.llm.missing_profile",
        )

    llm_profiles = context.config.section("llm.profiles")
    if llm_profile_name not in llm_profiles:
        if profile.llm.deny_unknown_profiles:
            return PolicyDecision.deny(
                reason="Unknown LLM profile is denied by policy.",
                reason_code="policy.llm.unknown_profile",
                metadata={"resource": llm_profile_name},
            )
        return PolicyDecision.allow(
            reason_code="policy.llm.unknown_profile_allowed",
            metadata={"resource": llm_profile_name},
        )

    profile_config = llm_profiles[llm_profile_name]
    if not isinstance(profile_config, dict):
        return PolicyDecision.deny(
            reason="LLM profile config is malformed.",
            reason_code="policy.llm.invalid_profile_config",
            metadata={"resource": llm_profile_name},
        )

    if profile.llm.allowed_profiles and llm_profile_name not in profile.llm.allowed_profiles:
        return PolicyDecision.deny(
            reason=f"LLM profile '{llm_profile_name}' is not allowed by policy.",
            reason_code="policy.llm.profile_denied",
            metadata={"resource": llm_profile_name},
        )

    allowed_for = profile_config.get("allowed_for", {})
    usecase_name = resolve_scope_value(
        request,
        context,
        key="usecase_name",
        fallback=resolve_scope_value(request, context, key="usecase", fallback=getattr(context.request, "usecase", None)),
    )
    agent_name = resolve_scope_value(request, context, key="agent_name")
    strategy_name = resolve_scope_value(request, context, key="strategy_name")

    if not is_name_allowed(allowed_for.get("usecases"), usecase_name):
        return PolicyDecision.deny(
            reason=f"LLM profile '{llm_profile_name}' is not allowed for the active use case.",
            reason_code="policy.llm.usecase_denied",
            metadata={"resource": llm_profile_name},
        )
    if not is_name_allowed(allowed_for.get("agents"), agent_name):
        return PolicyDecision.deny(
            reason=f"LLM profile '{llm_profile_name}' is not allowed for the active agent.",
            reason_code="policy.llm.agent_denied",
            metadata={"resource": llm_profile_name},
        )
    if not is_name_allowed(allowed_for.get("strategies"), strategy_name):
        return PolicyDecision.deny(
            reason=f"LLM profile '{llm_profile_name}' is not allowed for the active strategy.",
            reason_code="policy.llm.strategy_denied",
            metadata={"resource": llm_profile_name},
        )

    if request.action == "llm.stream" and not _read_bool(profile_config.get("supports_streaming"), False):
        return PolicyDecision.deny(
            reason=f"LLM profile '{llm_profile_name}' does not allow streaming.",
            reason_code="policy.llm.streaming_denied",
            metadata={"resource": llm_profile_name},
        )

    fallback_from_profile = _optional_text(request.metadata.get("fallback_from_profile"))
    if fallback_from_profile is not None and not profile.fallback.allow_fallbacks:
        return PolicyDecision.deny(
            reason="LLM fallback is denied by policy.",
            reason_code="policy.llm.fallback_denied",
            metadata={"resource": llm_profile_name, "fallback_from_profile": fallback_from_profile},
        )

    return PolicyDecision.allow(
        reason_code="policy.llm.allowed",
        metadata={"resource": llm_profile_name, "fallback_from_profile": fallback_from_profile},
    )


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _read_bool(value: object, default: bool) -> bool:
    return value if isinstance(value, bool) else default