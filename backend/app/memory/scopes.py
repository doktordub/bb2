"""Helpers for normalizing, resolving, and classifying backend memory scopes."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.contracts.context import OrchestrationContext
from app.contracts.memory import MemoryScope
from app.memory.errors import MemoryInvalidScopeError

PROJECT_SCOPE_RESOLUTION_KEY = "project_scope_resolution"
PROJECT_SCOPE_ALLOWED_COUNT_KEY = "project_scope_allowed_count"


@dataclass(frozen=True, slots=True)
class ProjectScopeSettings:
    """Config-owned project scope constraints for one use case and agent."""

    allowed_project_ids: tuple[str, ...] = ()
    usecase_default_project_id: str | None = None
    agent_default_project_id: str | None = None


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

    normalized = normalize_memory_scope(scope)
    summary = normalized.summary()
    resolution = _optional_text(normalized.metadata.get(PROJECT_SCOPE_RESOLUTION_KEY))
    if resolution is not None:
        summary[PROJECT_SCOPE_RESOLUTION_KEY] = resolution
    allowed_count = _read_optional_positive_int(
        normalized.metadata.get(PROJECT_SCOPE_ALLOWED_COUNT_KEY)
    )
    if allowed_count is not None:
        summary[PROJECT_SCOPE_ALLOWED_COUNT_KEY] = allowed_count
    return summary


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

    usecase_name = normalized.usecase or request_usecase or runtime_usecase
    agent_name = normalized.agent_name or runtime_agent_name
    explicit_project_id = _resolve_explicit_project_id(
        normalized.project_id,
        request_project_id,
        runtime_project_id,
    )
    project_scope_settings = read_project_scope_settings(
        context.config,
        usecase_name=usecase_name,
        agent_name=agent_name,
    )
    resolved_project_id, project_scope_resolution = resolve_configured_project_id(
        explicit_project_id=explicit_project_id,
        settings=project_scope_settings,
    )

    resolved_user_id = normalized.user_id
    if resolved_user_id is None and resolved_project_id is None:
        if default_scope == "user":
            resolved_user_id = request_user_id
    resolved_scope = MemoryScope(
        user_id=resolved_user_id,
        project_id=resolved_project_id,
        tenant_id=normalized.tenant_id or request_tenant_id or runtime_tenant_id,
        session_id=normalized.session_id or _optional_text(context.request.session_id),
        agent_name=agent_name,
        usecase=usecase_name,
        source_id=normalized.source_id,
        document_id=normalized.document_id,
        tags=normalized.tags,
        metadata=dict(normalized.metadata),
    )
    if project_scope_resolution is not None:
        resolved_scope.metadata[PROJECT_SCOPE_RESOLUTION_KEY] = project_scope_resolution
    if project_scope_settings.allowed_project_ids:
        resolved_scope.metadata[PROJECT_SCOPE_ALLOWED_COUNT_KEY] = len(
            project_scope_settings.allowed_project_ids
        )
    return resolved_scope


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


def _resolve_explicit_project_id(*values: str | None) -> str | None:
    explicit_values = [value for value in values if value is not None]
    distinct = list(dict.fromkeys(explicit_values))
    if len(distinct) > 1:
        raise MemoryInvalidScopeError(
            "Cross-project memory scope overrides are not allowed."
        )
    return distinct[0] if distinct else None


def read_project_scope_settings(
    config: Any,
    *,
    usecase_name: str | None,
    agent_name: str | None,
) -> ProjectScopeSettings:
    from app.config.view import get_agents_settings, get_orchestration_settings
    from app.contracts.errors import ConfigurationError

    usecase_allowed_project_ids: tuple[str, ...] = ()
    usecase_default_project_id: str | None = None
    agent_allowed_project_ids: tuple[str, ...] = ()
    agent_default_project_id: str | None = None

    try:
        orchestration_settings = get_orchestration_settings(config)
    except ConfigurationError:
        orchestration_settings = None
    if orchestration_settings is not None and usecase_name is not None:
        usecase_settings = orchestration_settings.usecases.get(usecase_name)
        if usecase_settings is not None:
            usecase_allowed_project_ids = usecase_settings.memory.allowed_project_ids
            usecase_default_project_id = usecase_settings.memory.default_project_id

    try:
        agent_settings = get_agents_settings(config)
    except ConfigurationError:
        agent_settings = None
    if agent_settings is not None and agent_name is not None:
        plugin_settings = agent_settings.plugins.get(agent_name)
        if plugin_settings is not None:
            agent_allowed_project_ids = plugin_settings.memory.allowed_project_ids
            agent_default_project_id = plugin_settings.memory.default_project_id

    allowed_project_ids = _resolve_allowed_project_ids(
        usecase_allowed_project_ids=usecase_allowed_project_ids,
        agent_allowed_project_ids=agent_allowed_project_ids,
    )
    if (
        usecase_allowed_project_ids
        and agent_allowed_project_ids
        and not allowed_project_ids
    ):
        raise MemoryInvalidScopeError(
            "No allowed memory project_id is shared by the active use case and agent."
        )

    return ProjectScopeSettings(
        allowed_project_ids=allowed_project_ids,
        usecase_default_project_id=usecase_default_project_id,
        agent_default_project_id=agent_default_project_id,
    )


def _resolve_allowed_project_ids(
    *,
    usecase_allowed_project_ids: tuple[str, ...],
    agent_allowed_project_ids: tuple[str, ...],
) -> tuple[str, ...]:
    if usecase_allowed_project_ids and agent_allowed_project_ids:
        allowed = set(agent_allowed_project_ids)
        return tuple(
            project_id
            for project_id in usecase_allowed_project_ids
            if project_id in allowed
        )
    if usecase_allowed_project_ids:
        return usecase_allowed_project_ids
    if agent_allowed_project_ids:
        return agent_allowed_project_ids
    return ()


def resolve_configured_project_id(
    *,
    explicit_project_id: str | None,
    settings: ProjectScopeSettings,
) -> tuple[str | None, str | None]:
    allowed_project_ids = settings.allowed_project_ids
    if explicit_project_id is not None:
        if allowed_project_ids and explicit_project_id not in allowed_project_ids:
            raise MemoryInvalidScopeError(
                f"Requested memory project_id '{explicit_project_id}' is not allowed."
            )
        return explicit_project_id, "explicit"

    if not allowed_project_ids:
        return None, None

    usecase_default = _default_in_allowed(
        settings.usecase_default_project_id,
        allowed_project_ids,
    )
    if usecase_default is not None:
        return usecase_default, "usecase_default"

    agent_default = _default_in_allowed(
        settings.agent_default_project_id,
        allowed_project_ids,
    )
    if agent_default is not None:
        return agent_default, "agent_default"

    if len(allowed_project_ids) == 1:
        return allowed_project_ids[0], "singleton_intersection"

    raise MemoryInvalidScopeError(
        "Memory project scope is ambiguous; provide project_id explicitly or configure a default_project_id."
    )


def _default_in_allowed(
    value: str | None,
    allowed_project_ids: tuple[str, ...],
) -> str | None:
    if value is None:
        return None
    if value not in allowed_project_ids:
        return None
    return value


def _read_optional_positive_int(value: object) -> int | None:
    if not isinstance(value, int):
        return None
    if value <= 0:
        return None
    return value