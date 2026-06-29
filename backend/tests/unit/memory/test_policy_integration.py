from __future__ import annotations

import pytest

from app.contracts.memory import MemoryResult, MemoryScope, MemorySearchRequest
from app.memory.adapters.fake import FakeMemoryAdapter
from app.memory.errors import MemoryPolicyDeniedError
from app.testing.fakes import FakePolicyService
from tests.unit.memory.support import build_context, build_gateway


async def test_gateway_policy_denial_blocks_adapter_execution() -> None:
    adapter = FakeMemoryAdapter(
        results=[MemoryResult(memory_id="memory-1", text="hello", memory_type="project_fact")]
    )
    policy = FakePolicyService(allow=True, denied_actions={"memory.search"}, deny_reason="Denied")
    gateway = build_gateway(adapter=adapter)
    context = build_context(policy=policy)

    with pytest.raises(MemoryPolicyDeniedError, match="Denied"):
        await gateway.search(
            MemorySearchRequest(
                text="hello",
                scope=MemoryScope(project_id="project-1"),
            ),
            context,
        )

    assert adapter.search_requests == []
    assert len(policy.requests) == 1
    request = policy.requests[0]
    assert request.action == "memory.search"
    assert request.component == "app.memory.gateway"
    assert request.resource is None
    assert request.metadata["provider"] == "fake"
    assert request.metadata["memory_scope_type"] == "project"
    assert request.actor is not None
    assert request.evaluation is not None
    assert request.scope["project_id"] == "project-1"
    assert request.scope["session_id"] is None
    assert request.scope["agent_name"] == "assistant_agent"
    assert request.scope["usecase"] == "support"