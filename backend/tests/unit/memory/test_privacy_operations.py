from __future__ import annotations

import pytest

from app.contracts.memory import (
    MemoryDeleteByScopeRequest,
    MemoryExportByScopeRequest,
    MemoryRecord,
    MemoryScope,
)
from app.memory.adapters.fake import FakeMemoryAdapter
from app.memory.errors import (
    MemoryInvalidScopeError,
    MemoryPolicyDeniedError,
    MemoryPrivacyError,
)
from app.testing.fakes import FakePolicyService
from tests.unit.memory.support import build_context, build_gateway


def _record(memory_id: str, text: str) -> MemoryRecord:
    return MemoryRecord(
        memory_id=memory_id,
        text=text,
        memory_type="project_fact",
        scope=MemoryScope(user_id="user-1", project_id="project-1"),
    )


async def test_gateway_delete_and_export_require_enabled_privacy_features() -> None:
    adapter = FakeMemoryAdapter()
    gateway = build_gateway(
        adapter=adapter,
        allow_writes=True,
        enable_delete_by_scope=False,
        enable_export_by_scope=False,
    )
    context = build_context()

    with pytest.raises(MemoryPrivacyError, match="Delete by scope is disabled"):
        await gateway.delete_by_scope(
            MemoryDeleteByScopeRequest(scope=MemoryScope(project_id="project-1")),
            context,
        )

    with pytest.raises(MemoryPrivacyError, match="Export by scope is disabled"):
        await gateway.export_by_scope(
            MemoryExportByScopeRequest(scope=MemoryScope(project_id="project-1")),
            context,
        )

    assert adapter.delete_requests == []
    assert adapter.export_requests == []


async def test_gateway_delete_by_scope_requires_confirmation_and_hard_delete_opt_in() -> None:
    adapter = FakeMemoryAdapter()
    gateway = build_gateway(
        adapter=adapter,
        allow_writes=True,
        enable_delete_by_scope=True,
        hard_delete_enabled=False,
        delete_by_scope_requires_confirm=True,
    )
    context = build_context()

    with pytest.raises(MemoryPrivacyError, match="requires explicit confirmation"):
        await gateway.delete_by_scope(
            MemoryDeleteByScopeRequest(
                scope=MemoryScope(project_id="project-1"),
                require_confirmation=False,
            ),
            context,
        )

    with pytest.raises(MemoryPrivacyError, match="Hard delete is disabled"):
        await gateway.delete_by_scope(
            MemoryDeleteByScopeRequest(
                scope=MemoryScope(project_id="project-1"),
                hard_delete=True,
            ),
            context,
        )

    assert adapter.delete_requests == []


async def test_gateway_export_requires_explicit_durable_scope() -> None:
    adapter = FakeMemoryAdapter()
    gateway = build_gateway(
        adapter=adapter,
        allow_writes=True,
        enable_export_by_scope=True,
    )
    context = build_context()

    with pytest.raises(MemoryInvalidScopeError, match="explicit durable scope"):
        await gateway.export_by_scope(
            MemoryExportByScopeRequest(scope=MemoryScope(session_id="session-1")),
            context,
        )

    assert adapter.export_requests == []


async def test_gateway_export_bounds_record_content_and_honors_policy() -> None:
    adapter = FakeMemoryAdapter()
    adapter.records["memory-1"] = _record("memory-1", "Private export record body")
    gateway = build_gateway(
        adapter=adapter,
        allow_writes=True,
        enable_export_by_scope=True,
        max_result_chars=10,
    )
    context = build_context()

    result = await gateway.export_by_scope(
        MemoryExportByScopeRequest(
            scope=MemoryScope(project_id="project-1"),
            include_content=True,
        ),
        context,
    )

    assert result.record_count == 1
    assert result.records[0].text.endswith("...")
    assert len(result.records[0].text) <= 10
    assert adapter.export_requests[0].scope.project_id == "project-1"


async def test_gateway_export_policy_denial_blocks_adapter_execution() -> None:
    adapter = FakeMemoryAdapter()
    policy = FakePolicyService(
        denied_actions={"memory.export_by_scope"},
        deny_reason="Denied",
    )
    gateway = build_gateway(
        adapter=adapter,
        allow_writes=True,
        enable_export_by_scope=True,
    )
    context = build_context(policy=policy)

    with pytest.raises(MemoryPolicyDeniedError, match="Denied"):
        await gateway.export_by_scope(
            MemoryExportByScopeRequest(scope=MemoryScope(project_id="project-1")),
            context,
        )

    assert adapter.export_requests == []