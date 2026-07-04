from __future__ import annotations

import pytest

from app.contracts.memory import MemoryScope
from app.memory.errors import MemoryInvalidScopeError
from app.memory.scopes import resolve_memory_scope, scope_summary
from tests.unit.memory.support import build_context, build_project_scope_config


def test_resolve_memory_scope_uses_request_project_default_and_runtime_fields() -> None:
    context = build_context(
        project_id="project-42",
        runtime_metadata={"agent_name": "agent-x", "usecase_name": "analysis"},
    )

    scope = resolve_memory_scope(
        MemoryScope(session_id="session-1"),
        context=context,
        default_scope="project",
    )

    assert scope.project_id == "project-42"
    assert scope.session_id == "session-1"
    assert scope.agent_name == "agent-x"
    assert scope.usecase == "support"


def test_resolve_memory_scope_rejects_cross_user_override() -> None:
    context = build_context(user_id="user-1")

    with pytest.raises(MemoryInvalidScopeError, match="Cross-user"):
        resolve_memory_scope(
            MemoryScope(user_id="user-2"),
            context=context,
            default_scope="user",
        )


def test_resolve_memory_scope_uses_usecase_default_when_project_is_omitted() -> None:
    context = build_context(
        project_id=None,
        usecase="architecture_document_qa",
        agent_name="architecture_document_agent",
        config_values=build_project_scope_config(
            usecase_name="architecture_document_qa",
            agent_name="architecture_document_agent",
            usecase_allowed_project_ids=("arch_docs", "design_docs"),
            usecase_default_project_id="arch_docs",
            agent_allowed_project_ids=("arch_docs", "design_docs"),
            agent_default_project_id="design_docs",
        ),
    )

    scope = resolve_memory_scope(
        MemoryScope(session_id="session-1"),
        context=context,
        default_scope="project",
    )

    assert scope.project_id == "arch_docs"
    assert scope_summary(scope)["project_scope_resolution"] == "usecase_default"


def test_resolve_memory_scope_uses_singleton_intersection_without_defaults() -> None:
    context = build_context(
        project_id=None,
        usecase="architecture_document_qa",
        agent_name="architecture_document_agent",
        config_values=build_project_scope_config(
            usecase_name="architecture_document_qa",
            agent_name="architecture_document_agent",
            usecase_allowed_project_ids=("arch_docs",),
            agent_allowed_project_ids=("arch_docs", "design_docs"),
        ),
    )

    scope = resolve_memory_scope(
        MemoryScope(session_id="session-1"),
        context=context,
        default_scope="project",
    )

    assert scope.project_id == "arch_docs"
    assert scope_summary(scope)["project_scope_resolution"] == "singleton_intersection"


def test_resolve_memory_scope_rejects_project_outside_configured_allowlist() -> None:
    context = build_context(
        project_id="design_docs",
        usecase="architecture_document_qa",
        agent_name="architecture_document_agent",
        config_values=build_project_scope_config(
            usecase_name="architecture_document_qa",
            agent_name="architecture_document_agent",
            usecase_allowed_project_ids=("arch_docs",),
            agent_allowed_project_ids=("arch_docs",),
        ),
    )

    with pytest.raises(MemoryInvalidScopeError, match="not allowed"):
        resolve_memory_scope(
            MemoryScope(session_id="session-1"),
            context=context,
            default_scope="project",
        )


def test_resolve_memory_scope_rejects_ambiguous_projects_without_default() -> None:
    context = build_context(
        project_id=None,
        usecase="architecture_document_qa",
        agent_name="architecture_document_agent",
        config_values=build_project_scope_config(
            usecase_name="architecture_document_qa",
            agent_name="architecture_document_agent",
            usecase_allowed_project_ids=("arch_docs", "design_docs"),
            agent_allowed_project_ids=("arch_docs", "design_docs"),
        ),
    )

    with pytest.raises(MemoryInvalidScopeError, match="ambiguous"):
        resolve_memory_scope(
            MemoryScope(session_id="session-1"),
            context=context,
            default_scope="project",
        )