"""Typed tool policy helpers and evaluators."""

from __future__ import annotations

from app.contracts.context import OrchestrationContext
from app.contracts.policy import (
    PolicyAction,
    PolicyActor,
    PolicyDecision,
    PolicyEvaluationContext,
    PolicyRequest,
    PolicyScope,
)
from app.contracts.tools import ToolScopes
from app.policy.approval_policy import build_approval_required_decision
from app.policy.context import resolve_scope_value
from app.policy.rule_matcher import is_name_allowed
from app.policy.settings import PolicyProfileSettings

_TOOL_EXECUTION_ACTIONS = ("tool.call", "tool.execute", "tool.stream_execute")
_RAW_TOOL_PREFIXES = ("mcp:", "mcp/", "tool://")


def build_tool_policy_request(
    *,
    action: PolicyAction,
    component: str,
    tool_name: str,
    scopes: ToolScopes,
    context: OrchestrationContext,
    tool_known: bool,
    tool_enabled: bool,
    safety_level: str | None,
    approval_required: bool,
    supports_streaming: bool,
    allowed_usecases: tuple[str, ...] = (),
    allowed_agents: tuple[str, ...] = (),
    allowed_strategies: tuple[str, ...] = (),
    idempotency_key_present: bool = False,
    stream_requested: bool = False,
) -> PolicyRequest:
    request_context = context.request
    runtime_metadata = context.runtime_metadata
    usecase_name = scopes.usecase or request_context.usecase
    strategy_name = _optional_text(runtime_metadata.get("strategy_name"))
    agent_name = scopes.agent_name or _optional_text(runtime_metadata.get("agent_name"))

    actor = PolicyActor(
        actor_type="user" if request_context.user_id else "anonymous",
        actor_id=request_context.user_id,
        user_id=request_context.user_id,
        session_id=request_context.session_id,
    )
    _ = PolicyScope(
        tenant_id=scopes.tenant_id,
        project_id=scopes.project_id,
        user_id=scopes.user_id,
        session_id=scopes.session_id,
        usecase_name=usecase_name,
        strategy_name=strategy_name,
        agent_name=agent_name,
        resource_id=tool_name,
        attributes={"tool_group": scopes.tool_group, "tags": list(scopes.tags)},
    )
    metadata = {
        "tool_name": tool_name,
        "tool_known": tool_known,
        "tool_enabled": tool_enabled,
        "tool_safety_level": safety_level,
        "tool_approval_required": approval_required,
        "tool_supports_streaming": supports_streaming,
        "allowed_usecases": allowed_usecases,
        "allowed_agents": allowed_agents,
        "allowed_strategies": allowed_strategies,
        "tool_group": scopes.tool_group,
        "stream_requested": stream_requested,
        "idempotency_key_present": idempotency_key_present,
    }
    evaluation = PolicyEvaluationContext(
        trace_id=request_context.trace_id,
        usecase_name=usecase_name,
        strategy_name=strategy_name,
        agent_name=agent_name,
        tool_name=tool_name,
        risk_level=safety_level,
        exposure_level="summary",
        tags=("tool", safety_level or "unknown"),
        metadata=dict(metadata),
    )
    return PolicyRequest(
        action=action,
        component=component,
        resource=tool_name,
        scope={
            "user_id": scopes.user_id,
            "project_id": scopes.project_id,
            "tenant_id": scopes.tenant_id,
            "session_id": scopes.session_id,
            "agent_name": agent_name,
            "strategy_name": strategy_name,
            "usecase": usecase_name,
            "usecase_name": usecase_name,
            "tool_group": scopes.tool_group,
            "tags": list(scopes.tags),
        },
        metadata=metadata,
        actor=actor,
        evaluation=evaluation,
    )


async def evaluate_tool_request(
    request: PolicyRequest,
    context: OrchestrationContext,
    profile: PolicyProfileSettings,
) -> PolicyDecision | None:
    tool_name = _optional_text(request.resource) or _optional_text(request.metadata.get("tool_name"))
    safety_level = _optional_text(request.metadata.get("tool_safety_level")) or "read_only"
    tool_known = _read_bool(request.metadata.get("tool_known"), True)
    tool_enabled = _read_bool(request.metadata.get("tool_enabled"), True)
    tool_supports_streaming = _read_bool(request.metadata.get("tool_supports_streaming"), False)
    tool_approval_required = _read_bool(request.metadata.get("tool_approval_required"), False)
    idempotency_key_present = _read_bool(request.metadata.get("idempotency_key_present"), False)

    usecase_name = resolve_scope_value(
        request,
        context,
        key="usecase_name",
        fallback=resolve_scope_value(request, context, key="usecase", fallback=getattr(context.request, "usecase", None)),
    )
    agent_name = resolve_scope_value(request, context, key="agent_name")
    strategy_name = resolve_scope_value(request, context, key="strategy_name")

    if tool_name is not None and tool_name.casefold().startswith(_RAW_TOOL_PREFIXES):
        return PolicyDecision.deny(
            reason="Raw MCP tool names are denied by policy.",
            reason_code="policy.tool.raw_name_denied",
            metadata={"resource": tool_name},
        )

    if not tool_known and profile.tools.deny_unknown_tools:
        return PolicyDecision.deny(
            reason=f"Unknown logical tool '{tool_name or 'unknown'}' is denied by policy.",
            reason_code="policy.tool.unknown",
            metadata={"resource": tool_name},
        )

    if profile.tools.allowed_tools and tool_name not in profile.tools.allowed_tools:
        return PolicyDecision.deny(
            reason=f"Tool '{tool_name or 'unknown'}' is not allowed by policy.",
            reason_code="policy.tool.profile_denied",
            metadata={"resource": tool_name},
        )

    if not tool_enabled:
        return PolicyDecision.deny(
            reason=f"Tool '{tool_name or 'unknown'}' is disabled.",
            reason_code="policy.tool.disabled",
            metadata={"resource": tool_name},
        )

    if request.action == "tool.stream_execute" and not tool_supports_streaming:
        return PolicyDecision.deny(
            reason=f"Tool '{tool_name or 'unknown'}' does not support streaming.",
            reason_code="policy.tool.streaming_unsupported",
            metadata={"resource": tool_name},
        )

    if not is_name_allowed(request.metadata.get("allowed_usecases"), usecase_name):
        return PolicyDecision.deny(
            reason=f"Tool '{tool_name or 'unknown'}' is not allowed for the active use case.",
            reason_code="policy.tool.usecase_denied",
            metadata={"resource": tool_name},
        )
    if not is_name_allowed(request.metadata.get("allowed_agents"), agent_name):
        return PolicyDecision.deny(
            reason=f"Tool '{tool_name or 'unknown'}' is not allowed for the active agent.",
            reason_code="policy.tool.agent_denied",
            metadata={"resource": tool_name},
        )
    if not is_name_allowed(request.metadata.get("allowed_strategies"), strategy_name):
        return PolicyDecision.deny(
            reason=f"Tool '{tool_name or 'unknown'}' is not allowed for the active strategy.",
            reason_code="policy.tool.strategy_denied",
            metadata={"resource": tool_name},
        )

    if request.action in _TOOL_EXECUTION_ACTIONS:
        if tool_approval_required and not profile.tools.allow_approval_required_tools:
            return build_approval_required_decision(
                reason=f"Tool '{tool_name or 'unknown'}' requires approval.",
                reason_code="policy.tool.approval_required",
                target=tool_name or request.action,
                metadata={"resource": tool_name, "safety_level": safety_level},
                value=safety_level,
            )
        if safety_level == "write":
            if not profile.tools.allow_write_tools:
                return PolicyDecision.deny(
                    reason=f"Tool '{tool_name or 'unknown'}' is denied by policy.",
                    reason_code="policy.tool.write_denied",
                    metadata={"resource": tool_name, "safety_level": safety_level},
                )
            if profile.approval.require_approval_for_write_tools and not idempotency_key_present:
                return build_approval_required_decision(
                    reason=f"Tool '{tool_name or 'unknown'}' requires approval.",
                    reason_code="policy.tool.approval_required",
                    target=tool_name or request.action,
                    metadata={"resource": tool_name, "safety_level": safety_level},
                    value=safety_level,
                )
        if safety_level == "destructive":
            if not profile.tools.allow_destructive_tools:
                return PolicyDecision.deny(
                    reason=f"Tool '{tool_name or 'unknown'}' is destructive and denied by policy.",
                    reason_code="policy.tool.destructive_denied",
                    metadata={"resource": tool_name, "safety_level": safety_level},
                )
            if profile.approval.require_approval_for_destructive_tools:
                return build_approval_required_decision(
                    reason=f"Tool '{tool_name or 'unknown'}' requires approval.",
                    reason_code="policy.tool.approval_required",
                    target=tool_name or request.action,
                    metadata={"resource": tool_name, "safety_level": safety_level},
                    value=safety_level,
                )
        if safety_level == "external_side_effect":
            if not profile.tools.allow_external_side_effect_tools:
                return PolicyDecision.deny(
                    reason=f"Tool '{tool_name or 'unknown'}' has external side effects and is denied by policy.",
                    reason_code="policy.tool.external_side_effect_denied",
                    metadata={"resource": tool_name, "safety_level": safety_level},
                )
            if profile.approval.require_approval_for_external_side_effect_tools:
                return build_approval_required_decision(
                    reason=f"Tool '{tool_name or 'unknown'}' requires approval.",
                    reason_code="policy.tool.approval_required",
                    target=tool_name or request.action,
                    metadata={"resource": tool_name, "safety_level": safety_level},
                    value=safety_level,
                )

    return PolicyDecision.allow(
        reason_code="policy.tool.allowed",
        metadata={"resource": tool_name, "safety_level": safety_level},
    )


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _read_bool(value: object, default: bool) -> bool:
    return value if isinstance(value, bool) else default