from __future__ import annotations

import pytest

from app.contracts.context import RequestContext
from app.contracts.memory import MemoryRecord, MemoryResult, MemorySearchResult, MemoryScope
from app.memory.adapters.fake import FakeMemoryAdapter
from app.memory.gateway import DefaultMemoryGateway
from app.orchestration.core import DirectAgentOrchestrationRuntime
from app.testing.fakes import (
    FakeLLMGateway,
    FakePolicyService,
    FakeTraceStore,
    FakeWorkflowStateStore,
)
from tests.integration.memory.support import build_gateway, load_config_view


@pytest.mark.asyncio
async def test_direct_runtime_uses_memory_gateway_through_agent_context() -> None:
    config = await load_config_view("memory_fake_basic.yaml", base_name="valid_full.yaml")
    memory_gateway = await build_gateway(config)

    assert isinstance(memory_gateway, DefaultMemoryGateway)
    adapter = memory_gateway._adapter
    assert isinstance(adapter, FakeMemoryAdapter)

    record = MemoryRecord(
        memory_id="memory-1",
        text="Memory access stays behind MemoryGateway.",
        memory_type="project_fact",
        scope=MemoryScope(project_id="project-1"),
        title="Memory boundary",
    )
    adapter.search_result = MemorySearchResult(
        results=[MemoryResult.from_record(record, score=0.95)],
        total_candidates=1,
        search_strategy="fake",
    )

    runtime = DirectAgentOrchestrationRuntime.from_config(
        config=config,
        llm_gateway=FakeLLMGateway(response_text="memory-backed answer"),
        memory=memory_gateway,
        state=FakeWorkflowStateStore(),
        trace=FakeTraceStore(),
        policy_service=FakePolicyService(),
    )

    result = await runtime.run(
        request=RequestContext(
            user_id="user-1",
            session_id="session-memory-1",
            message="What do we know about the memory boundary?",
            usecase="support_chat",
            trace_id="trace-memory-1",
            metadata={"project_id": "project-1"},
        ),
        state={},
    )

    assert result.answer == "memory-backed answer"
    assert result.agent_name == "support_agent"
    assert result.metadata["memory_result_count"] == 1
    assert len(adapter.search_requests) == 1
    assert adapter.search_requests[0].text == "What do we know about the memory boundary?"
    assert adapter.search_requests[0].scope.project_id == "project-1"
