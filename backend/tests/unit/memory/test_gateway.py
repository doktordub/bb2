from __future__ import annotations

from app.contracts.memory import MemoryResult, MemoryScope, MemorySearchRequest
from app.contracts.trace import MEMORY_SEARCH_COMPLETED, MEMORY_SEARCH_STARTED
from app.memory.adapters.fake import FakeMemoryAdapter
from app.testing.fakes import FakeTraceStore
from tests.unit.memory.support import build_context, build_gateway


async def test_gateway_bounds_results_and_emits_safe_search_traces() -> None:
    long_query = "secret project query with private details"
    long_text = "This is a long memory body that should be truncated before reaching the agent."
    adapter = FakeMemoryAdapter(
        results=[
            MemoryResult(
                memory_id="memory-1",
                text=long_text,
                score=0.9,
                memory_type="project_fact",
                metadata={"source": "fake"},
            )
        ]
    )
    trace_store = FakeTraceStore()
    gateway = build_gateway(adapter=adapter, max_result_chars=18, limit_max=2)
    context = build_context(trace_store=trace_store)

    result = await gateway.search(
        MemorySearchRequest(
            text=long_query,
            scope=MemoryScope(session_id="session-1"),
            limit=10,
        ),
        context,
    )

    assert len(result.results) == 1
    assert result.results[0].text == "This is a long..."
    assert adapter.search_requests[0].scope.project_id == "project-1"

    assert [event.event_type for event in trace_store.events] == [
        MEMORY_SEARCH_STARTED,
        MEMORY_SEARCH_COMPLETED,
    ]
    payload_text = str(trace_store.events[0].payload) + str(trace_store.events[1].payload)
    assert long_query not in payload_text
    assert long_text not in payload_text
    assert trace_store.events[0].payload["query_chars"] == len(long_query)
    assert trace_store.events[1].payload["result_count"] == 1
    assert trace_store.events[1].payload["max_score"] == 0.9
    assert trace_store.events[1].payload["min_score"] == 0.9