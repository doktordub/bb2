"""Helpers for resolving typed policy context from compatibility requests."""

from __future__ import annotations

from dataclasses import dataclass

from app.contracts.context import OrchestrationContext, RequestContext
from app.contracts.policy import PolicyActor, PolicyEvaluationContext, PolicyRequest, PolicyScope


@dataclass(frozen=True, slots=True)
class ResolvedPolicyContext:
    """Typed resolved policy context extracted from a request."""

    actor: PolicyActor
    scope: PolicyScope
    evaluation: PolicyEvaluationContext


def resolve_policy_context(request: PolicyRequest) -> ResolvedPolicyContext:
    """Resolve additive typed context from the legacy-compatible request surface."""

    return ResolvedPolicyContext(
        actor=request.resolved_actor(),
        scope=request.resolved_scope(),
        evaluation=request.resolved_evaluation(),
    )


def resolve_scope_value(
    request: PolicyRequest,
    context: object,
    *,
    key: str,
    fallback: str | None = None,
) -> str | None:
    """Resolve one scope value from request scope, runtime metadata, or fallback."""

    value = request.scope.get(key)
    if isinstance(value, str):
        normalized = value.strip()
        if normalized:
            return normalized

    runtime_metadata = getattr(context, "runtime_metadata", {})
    if isinstance(runtime_metadata, dict):
        runtime_value = runtime_metadata.get(key)
        if isinstance(runtime_value, str):
            normalized_runtime = runtime_value.strip()
            if normalized_runtime:
                return normalized_runtime

    return fallback


def build_readonly_policy_context(
    *,
    policy_service: object,
    config: object,
    trace_id: str | None,
    user_id: str | None,
    session_id: str | None = None,
    usecase_name: str | None = None,
) -> OrchestrationContext:
    """Build a minimal context for read-only policy checks at API and observability boundaries."""

    return OrchestrationContext(
        request=RequestContext(
            user_id=user_id or "",
            session_id=session_id or "",
            message="",
            usecase=usecase_name,
            trace_id=trace_id,
        ),
        llm=None,  # type: ignore[arg-type]
        memory=None,  # type: ignore[arg-type]
        state=None,
        tools=None,  # type: ignore[arg-type]
        trace=None,  # type: ignore[arg-type]
        policy=policy_service,  # type: ignore[arg-type]
        config=config,  # type: ignore[arg-type]
    )