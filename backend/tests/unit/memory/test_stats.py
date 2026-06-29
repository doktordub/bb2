from __future__ import annotations

import pytest

from app.contracts.memory import MemoryRecord, MemoryScope, MemoryStatsResult
from app.contracts.trace import MEMORY_STATS_CHECKED
from app.memory.adapters.fake import FakeMemoryAdapter
from app.memory.errors import MemoryPolicyDeniedError
from app.testing.fakes import FakePolicyService, FakeTraceStore
from tests.unit.memory.support import build_context, build_gateway


def _record(memory_id: str, *, project_id: str, text: str, status: str) -> MemoryRecord:
    return MemoryRecord(
        memory_id=memory_id,
        text=text,
        memory_type="project_fact",
        scope=MemoryScope(project_id=project_id),
        status=status,
    )


async def test_gateway_stats_require_policy_when_context_is_provided() -> None:
    adapter = FakeMemoryAdapter()
    stats_called = False

    async def stats_probe(scopes: MemoryScope | None = None) -> MemoryStatsResult:
        nonlocal stats_called
        stats_called = True
        return MemoryStatsResult(total_records=1, provider="fake")

    adapter.stats = stats_probe  # type: ignore[method-assign]
    gateway = build_gateway(adapter=adapter)
    context = build_context(
        policy=FakePolicyService(denied_actions={"memory.stats"}, deny_reason="Denied")
    )

    with pytest.raises(MemoryPolicyDeniedError, match="Denied"):
        await gateway.stats(context=context)

    assert stats_called is False


async def test_gateway_stats_return_scoped_summary_and_safe_trace_payload() -> None:
    adapter = FakeMemoryAdapter()
    adapter.records["memory-1"] = _record(
        "memory-1",
        project_id="project-1",
        text="Project one secret memory body",
        status="active",
    )
    adapter.records["memory-2"] = _record(
        "memory-2",
        project_id="project-2",
        text="Other project body",
        status="expired",
    )
    policy = FakePolicyService()
    trace_store = FakeTraceStore()
    gateway = build_gateway(adapter=adapter)
    context = build_context(policy=policy, trace_store=trace_store)

    result = await gateway.stats(
        scopes=MemoryScope(project_id="project-1"),
        context=context,
    )

    assert result.total_records == 1
    assert result.status_counts == {"active": 1}
    assert result.type_counts == {"project_fact": 1}
    assert "text" not in result.as_dict()
    assert policy.requests[0].action == "memory.stats"
    assert policy.requests[0].scope["project_id"] == "project-1"
    assert [event.event_type for event in trace_store.events] == [MEMORY_STATS_CHECKED]
    assert trace_store.events[0].payload["total_records"] == 1
    assert "Project one secret memory body" not in str(trace_store.events[0].payload)