"""Typed memory policy helpers and evaluators."""

from __future__ import annotations

from app.contracts.context import OrchestrationContext
from app.contracts.memory import MemoryScope, MemoryWrite
from app.contracts.policy import (
    PolicyAction,
    PolicyActor,
    PolicyDecision,
    PolicyEvaluationContext,
    PolicyRequest,
    PolicyScope,
)
from app.policy.approval_policy import build_approval_required_decision
from app.policy.context import resolve_scope_value
from app.policy.settings import PolicyProfileSettings

_MEMORY_WRITE_ACTIONS = {
    "memory.upsert",
    "memory.promote",
    "memory.supersede",
    "memory.contradict",
    "memory.expire",
    "memory.forget",
    "memory.ingest_document",
    "memory.delete_by_scope",
    "memory.export_by_scope",
}
_MEMORY_READ_ACTIONS = {"memory.search", "memory.get", "memory.stats"}
_MEMORY_ADMIN_ACTIONS = {"memory.delete_by_scope", "memory.export_by_scope"}


def build_memory_policy_request(
    *,
    action: PolicyAction,
    component: str,
    scope: MemoryScope,
    context: OrchestrationContext,
    resource: str | None = None,
    provider: str,
    memory_write: MemoryWrite | None = None,
) -> PolicyRequest:
    request_context = context.request
    runtime_metadata = context.runtime_metadata
    scope_type = _classify_memory_scope(scope)
    strategy_name = _optional_text(runtime_metadata.get("strategy_name"))
    agent_name = scope.agent_name or _optional_text(runtime_metadata.get("agent_name"))
    usecase_name = scope.usecase or request_context.usecase or _optional_text(
        runtime_metadata.get("usecase_name")
    )

    metadata: dict[str, object] = {
        "provider": provider,
        "memory_scope_type": scope_type,
        "memory_scope_present": scope.has_explicit_scope(),
        "memory_write": action in _MEMORY_WRITE_ACTIONS,
        "memory_admin": action in _MEMORY_ADMIN_ACTIONS,
    }
    if memory_write is not None:
        metadata.update(
            {
                "memory_type": memory_write.memory_type,
                "stable_key_present": memory_write.stable_key is not None,
                "allow_retrieval": memory_write.allow_retrieval,
                "allow_llm_context": memory_write.allow_llm_context,
                "memory_intent_explicit": _memory_write_intent_is_explicit(memory_write),
                "memory_sensitivity": _memory_write_sensitivity(memory_write),
            }
        )

    actor = PolicyActor(
        actor_type="user" if request_context.user_id else "anonymous",
        actor_id=request_context.user_id,
        user_id=request_context.user_id,
        session_id=request_context.session_id,
    )
    _ = PolicyScope(
        tenant_id=scope.tenant_id,
        project_id=scope.project_id,
        user_id=scope.user_id,
        session_id=scope.session_id,
        usecase_name=usecase_name,
        strategy_name=strategy_name,
        agent_name=agent_name,
        memory_scope=scope_type,
        resource_id=resource,
        attributes={
            "source_id": scope.source_id,
            "document_id": scope.document_id,
            "tags": list(scope.tags),
        },
    )
    evaluation = PolicyEvaluationContext(
        trace_id=request_context.trace_id,
        usecase_name=usecase_name,
        strategy_name=strategy_name,
        agent_name=agent_name,
        risk_level="write" if action in _MEMORY_WRITE_ACTIONS else "read_only",
        exposure_level="summary",
        tags=("memory", scope_type, "write" if action in _MEMORY_WRITE_ACTIONS else "read"),
        metadata=dict(metadata),
    )
    return PolicyRequest(
        action=action,
        component=component,
        resource=resource,
        scope={
            "tenant_id": scope.tenant_id,
            "project_id": scope.project_id,
            "user_id": scope.user_id,
            "session_id": scope.session_id,
            "agent_name": agent_name,
            "usecase": usecase_name,
            "usecase_name": usecase_name,
            "source_id": scope.source_id,
            "document_id": scope.document_id,
            "memory_scope": scope_type,
            "tags": list(scope.tags),
        },
        metadata=metadata,
        actor=actor,
        evaluation=evaluation,
    )


async def evaluate_memory_request(
    request: PolicyRequest,
    context: OrchestrationContext,
    profile: PolicyProfileSettings,
) -> PolicyDecision | None:
    scope_type = _memory_scope_type(request, context)
    scope_allowed_names = _policy_scope_names(scope_type)
    metadata = request.metadata
    is_write = request.action in _MEMORY_WRITE_ACTIONS
    is_read = request.action in _MEMORY_READ_ACTIONS

    if request.action.startswith("memory.") and profile.memory.require_scope and scope_type == "global":
        return PolicyDecision.deny(
            reason="Memory scope is required by policy.",
            reason_code="policy.memory.scope_required",
            metadata={"scope_type": scope_type},
        )

    if is_read and profile.memory.allowed_read_scopes:
        if not _scope_names_allowed(scope_allowed_names, profile.memory.allowed_read_scopes):
            return PolicyDecision.deny(
                reason=f"Memory scope '{scope_type}' is not allowed for reads.",
                reason_code="policy.memory.read_scope_denied",
                metadata={"scope_type": scope_type},
            )

    if is_write:
        if not profile.memory.allow_writes:
            return PolicyDecision.deny(
                reason="Memory writes are disabled by policy.",
                reason_code="policy.memory.write_denied",
                metadata={"scope_type": scope_type},
            )
        if profile.memory.allowed_write_scopes and not _scope_names_allowed(
            scope_allowed_names,
            profile.memory.allowed_write_scopes,
        ):
            return PolicyDecision.deny(
                reason=f"Memory scope '{scope_type}' is not allowed for writes.",
                reason_code="policy.memory.write_scope_denied",
                metadata={"scope_type": scope_type},
            )

        sensitivity = _optional_text(metadata.get("memory_sensitivity"))
        if sensitivity == "sensitive":
            return PolicyDecision.deny(
                reason="Sensitive memory writes are denied by default.",
                reason_code="policy.memory.sensitive_denied",
                metadata={"scope_type": scope_type, "sensitivity": sensitivity},
            )

        if _read_bool(metadata.get("memory_admin"), False):
            return build_approval_required_decision(
                reason="Administrative memory operations require approval.",
                reason_code="policy.memory.approval_required",
                target=request.action,
                metadata={"scope_type": scope_type},
                value=scope_type,
            )

        if profile.approval.require_approval_for_memory_writes:
            return build_approval_required_decision(
                reason="Memory writes require approval.",
                reason_code="policy.memory.approval_required",
                target=request.action,
                metadata={"scope_type": scope_type},
                value=scope_type,
            )

    return PolicyDecision.allow(
        reason_code="policy.memory.allowed",
        metadata={"scope_type": scope_type},
    )


def _memory_scope_type(request: PolicyRequest, context: OrchestrationContext) -> str:
    explicit = _optional_text(request.scope.get("memory_scope"))
    if explicit is not None:
        return explicit
    fallback = resolve_scope_value(request, context, key="project_id")
    if fallback is not None:
        return "project"
    return "global"


def _classify_memory_scope(scope: MemoryScope) -> str:
    summary = scope.summary()
    scope_type = summary.get("scope_type")
    if isinstance(scope_type, str) and scope_type.strip():
        return scope_type.strip()
    return "global"


def _policy_scope_names(scope_type: str) -> tuple[str, ...]:
    if scope_type == "project_user":
        return ("project", "user")
    if scope_type == "document":
        return ("document", "source")
    return (scope_type,)


def _scope_names_allowed(scope_names: tuple[str, ...], allowed: tuple[str, ...]) -> bool:
    return any(name in allowed for name in scope_names)


def _memory_write_intent_is_explicit(memory_write: MemoryWrite) -> bool:
    reason = _optional_text(memory_write.metadata.get("reason"))
    source = _optional_text(memory_write.metadata.get("source"))
    return reason == "explicit_remember_request" or source == "request_message"


def _memory_write_sensitivity(memory_write: MemoryWrite) -> str | None:
    return _optional_text(memory_write.metadata.get("sensitivity"))


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _read_bool(value: object, default: bool) -> bool:
    return value if isinstance(value, bool) else default