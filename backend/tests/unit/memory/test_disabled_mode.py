from __future__ import annotations

import pytest

from app.contracts.memory import (
    MemoryDeleteByScopeRequest,
    MemoryResult,
    MemoryScope,
    MemorySearchRequest,
    MemoryWrite,
)
from app.memory.adapters.fake import FakeMemoryAdapter
from app.memory.errors import MemoryDisabledError
from tests.unit.memory.support import build_context, build_gateway


async def test_gateway_search_returns_empty_result_when_memory_is_disabled() -> None:
    adapter = FakeMemoryAdapter(
        results=[MemoryResult(memory_id="memory-1", text="hello", memory_type="project_fact")]
    )
    gateway = build_gateway(adapter=adapter, enabled=False)
    context = build_context()

    result = await gateway.search(
        MemorySearchRequest(text="hello", scope=MemoryScope(project_id="project-1")),
        context,
    )

    assert result.results == []
    assert adapter.search_requests == []


async def test_gateway_write_and_admin_operations_fail_when_memory_is_disabled() -> None:
    adapter = FakeMemoryAdapter()
    gateway = build_gateway(adapter=adapter, enabled=False)
    context = build_context()

    with pytest.raises(MemoryDisabledError):
        await gateway.upsert(
            MemoryWrite(
                text="remember this",
                scope=MemoryScope(project_id="project-1"),
                memory_type="project_fact",
            ),
            context,
        )

    with pytest.raises(MemoryDisabledError):
        await gateway.delete_by_scope(
            MemoryDeleteByScopeRequest(scope=MemoryScope(project_id="project-1")),
            context,
        )

    assert adapter.writes == []
    assert adapter.delete_requests == []