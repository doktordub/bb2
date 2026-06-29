from __future__ import annotations

import pytest

from app.contracts.errors import PolicyDeniedError
from app.orchestration.errors import StrategyPolicyDeniedError
from app.orchestration.runtime import DefaultOrchestrationRuntime
from app.orchestration.strategies.memory_update import MemoryUpdateStrategy
from app.testing.fakes import (
    FakeAgent,
    FakeLLMGateway,
    FakeMemoryGateway,
    FakePolicyService,
    FakeTraceStore,
    FakeWorkflowStateStore,
)
from tests.unit.orchestration.test_fallback_policy_behavior import build_config as build_fallback_config
from tests.unit.orchestration.test_fallback_policy_behavior import build_request
from tests.unit.orchestration.test_memory_update_strategy import build_config as build_memory_update_config
from tests.unit.orchestration.test_memory_update_strategy import build_context as build_memory_update_context


@pytest.mark.asyncio
async def test_runtime_policy_denial_does_not_fallback_to_secondary_strategy() -> None:
    trace_store = FakeTraceStore()
    runtime = DefaultOrchestrationRuntime.from_config(
        config=build_fallback_config(),
        llm_gateway=FakeLLMGateway(response_text="should not be used"),
        memory=FakeMemoryGateway(),
        state=FakeWorkflowStateStore(),
        trace=trace_store,
        policy_service=FakePolicyService(denied_resources={"direct_agent"}),
    )
    request, context = build_request()

    with pytest.raises(StrategyPolicyDeniedError):
        await runtime.run_turn(request=request, context=context)

    assert [event.resolved_event_name for event in trace_store.events] == [
        "orchestration_started",
        "orchestration_failed",
    ]


@pytest.mark.asyncio
async def test_memory_update_strategy_stops_before_writing_when_policy_denies() -> None:
    memory = FakeMemoryGateway()
    context = build_memory_update_context(
        build_memory_update_config(),
        message="Remember that policy denials should stop writes.",
        memory=memory,
        policy=FakePolicyService(denied_actions={"memory.upsert"}),
    )

    with pytest.raises(PolicyDeniedError):
        await MemoryUpdateStrategy().run(
            context=context,
            agents=[FakeAgent(name="support_agent")],
        )

    assert memory.writes == []