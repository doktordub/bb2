from __future__ import annotations

import pytest

from app.contracts.memory import MemoryScope
from app.memory.errors import MemoryInvalidScopeError
from app.memory.scopes import resolve_memory_scope
from tests.unit.memory.support import build_context


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