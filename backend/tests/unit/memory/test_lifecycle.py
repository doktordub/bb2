from __future__ import annotations

import pytest

from app.contracts.memory import (
    MemoryContradictRequest,
    MemoryForgetRequest,
    MemoryLifecycleRequest,
    MemoryRecord,
    MemoryScope,
    MemorySupersedeRequest,
)
from app.memory.adapters.fake import FakeMemoryAdapter
from app.memory.errors import MemoryPolicyDeniedError, MemoryPrivacyError
from app.testing.fakes import FakePolicyService
from tests.unit.memory.support import build_context, build_gateway


def _record(memory_id: str, *, status: str = "active") -> MemoryRecord:
    return MemoryRecord(
        memory_id=memory_id,
        text=f"{memory_id} body",
        memory_type="project_fact",
        scope=MemoryScope(project_id="project-1"),
        status=status,
    )


async def test_gateway_lifecycle_operations_route_through_adapter() -> None:
    adapter = FakeMemoryAdapter()
    adapter.records["old-memory"] = _record("old-memory")
    adapter.records["new-memory"] = _record("new-memory")
    gateway = build_gateway(adapter=adapter, allow_writes=True)
    context = build_context()

    promote_result = await gateway.promote(
        MemoryLifecycleRequest(
            memory_id="old-memory",
            scope=MemoryScope(project_id="project-1"),
            reason="confirmed",
        ),
        context,
    )
    supersede_result = await gateway.supersede(
        MemorySupersedeRequest(
            old_memory_id="old-memory",
            new_memory_id="new-memory",
            scope=MemoryScope(project_id="project-1"),
            reason="replacement",
        ),
        context,
    )
    contradict_result = await gateway.contradict(
        MemoryContradictRequest(
            memory_id_a="old-memory",
            memory_id_b="new-memory",
            scope=MemoryScope(project_id="project-1"),
            reason="conflict",
        ),
        context,
    )
    expire_result = await gateway.expire(
        MemoryLifecycleRequest(
            memory_id="new-memory",
            scope=MemoryScope(project_id="project-1"),
            reason="expired",
        ),
        context,
    )
    forget_result = await gateway.forget(
        MemoryForgetRequest(
            memory_id="old-memory",
            scope=MemoryScope(project_id="project-1"),
        ),
        context,
    )

    assert promote_result.operation == "promote"
    assert supersede_result.affected_ids == ("old-memory", "new-memory")
    assert contradict_result.affected_ids == ("old-memory", "new-memory")
    assert expire_result.operation == "expire"
    assert forget_result.status == "forgotten"
    assert adapter.records.get("old-memory") is None
    assert adapter.lifecycle_requests[0].scope.project_id == "project-1"
    assert adapter.lifecycle_requests[1].memory_id == "new-memory"
    assert len(adapter.supersede_requests) == 1
    assert len(adapter.contradict_requests) == 1
    assert len(adapter.forget_requests) == 1


async def test_gateway_hard_delete_forget_requires_enabled_privacy_setting() -> None:
    adapter = FakeMemoryAdapter()
    gateway = build_gateway(adapter=adapter, allow_writes=True, hard_delete_enabled=False)
    context = build_context()

    with pytest.raises(MemoryPrivacyError, match="Hard delete is disabled"):
        await gateway.forget(
            MemoryForgetRequest(
                memory_id="memory-1",
                scope=MemoryScope(project_id="project-1"),
                hard_delete=True,
            ),
            context,
        )

    assert adapter.forget_requests == []


async def test_gateway_lifecycle_policy_denial_blocks_adapter_execution() -> None:
    adapter = FakeMemoryAdapter()
    policy = FakePolicyService(denied_actions={"memory.promote"}, deny_reason="Denied")
    gateway = build_gateway(adapter=adapter, allow_writes=True)
    context = build_context(policy=policy)

    with pytest.raises(MemoryPolicyDeniedError, match="Denied"):
        await gateway.promote(
            MemoryLifecycleRequest(
                memory_id="memory-1",
                scope=MemoryScope(project_id="project-1"),
            ),
            context,
        )

    assert adapter.lifecycle_requests == []
    assert policy.requests[0].action == "memory.promote"