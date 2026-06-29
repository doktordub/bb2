"""Helpers for normalizing, resolving, and classifying backend memory scopes."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.contracts.context import OrchestrationContext
from app.contracts.memory import MemoryScope
from app.memory.errors import MemoryInvalidScopeError


def normalize_memory_scope(
    scope: MemoryScope | Mapping[str, Any] | None = None,
) -> MemoryScope:
    """Return a normalized memory scope value."""

    if scope is None:
        return MemoryScope()
    if isinstance(scope, MemoryScope):
        return scope.normalized()
    return MemoryScope(**dict(scope)).normalized()


def classify_memory_scope(
    scope: MemoryScope | Mapping[str, Any] | None = None,
) -> str:
    """Return the trace-safe logical scope type."""

    summary = scope_summary(scope)
    return str(summary["scope_type"])


def scope_summary(
    scope: MemoryScope | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a trace-safe summary for one logical scope."""

    return normalize_memory_scope(scope).summary()


def resolve_memory_scope(
    scope: MemoryScope | Mapping[str, Any] | None,
    *,
    context: OrchestrationContext,
    default_scope: str,
) -> MemoryScope:
    """Resolve one effective memory scope from request, runtime, and defaults."""

    normalized = normalize_memory_scope(scope)
    request_user_id = _optional_text(context.request.user_id)
    request_project_id = _optional_text(context.request.metadata.get("project_id"))
    runtime_project_id = _optional_text(context.runtime_metadata.get("project_id"))
    request_tenant_id = _optional_text(context.request.metadata.get("tenant_id"))
    runtime_tenant_id = _optional_text(context.runtime_metadata.get("tenant_id"))
    request_usecase = _optional_text(context.request.usecase)
    runtime_usecase = _optional_text(
        context.runtime_metadata.get("usecase_name")
        or context.runtime_metadata.get("usecase")
    )
    runtime_agent_name = _optional_text(context.runtime_metadata.get("agent_name"))

    if (
        normalized.user_id is not None
        and request_user_id is not None
        and normalized.user_id != request_user_id
    ):
        raise MemoryInvalidScopeError(
            "Cross-user memory scope overrides are not allowed."
        )

    current_project_id = request_project_id or runtime_project_id
    if (
        normalized.project_id is not None
        and current_project_id is not None
        and normalized.project_id != current_project_id
    ):
        raise MemoryInvalidScopeError(
            "Cross-project memory scope overrides are not allowed."
        )

    resolved_user_id = normalized.user_id
    resolved_project_id = normalized.project_id
    if resolved_user_id is None and resolved_project_id is None:
        if default_scope == "user":
            resolved_user_id = request_user_id
        elif default_scope == "project":
            resolved_project_id = current_project_id

    return MemoryScope(
        user_id=resolved_user_id,
        project_id=resolved_project_id,
        tenant_id=normalized.tenant_id or request_tenant_id or runtime_tenant_id,
        session_id=normalized.session_id or _optional_text(context.request.session_id),
        agent_name=normalized.agent_name or runtime_agent_name,
        usecase=normalized.usecase or request_usecase or runtime_usecase,
        source_id=normalized.source_id,
        document_id=normalized.document_id,
        tags=normalized.tags,
        metadata=dict(normalized.metadata),
    )


def scope_to_policy_scope(scope: MemoryScope) -> dict[str, Any]:
    """Convert one resolved scope into the policy-request payload shape."""

    normalized = normalize_memory_scope(scope)
    return {
        "user_id": normalized.user_id,
        "project_id": normalized.project_id,
        "tenant_id": normalized.tenant_id,
        "session_id": normalized.session_id,
        "agent_name": normalized.agent_name,
        "usecase": normalized.usecase,
        "source_id": normalized.source_id,
        "document_id": normalized.document_id,
        "tags": list(normalized.tags),
        "metadata": dict(normalized.metadata),
    }


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None