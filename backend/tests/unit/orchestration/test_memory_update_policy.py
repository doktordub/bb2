from __future__ import annotations

import pytest

from app.contracts.errors import PolicyDeniedError
from app.testing.fakes import FakeAgent, FakeMemoryGateway, FakePolicyService
from tests.unit.orchestration.test_memory_update_strategy import build_config, build_context
from app.orchestration.strategies.memory_update import MemoryUpdateStrategy


@pytest.mark.asyncio
async def test_memory_update_strategy_raises_when_policy_denies_memory_write() -> None:
    memory = FakeMemoryGateway()
    context = build_context(
        build_config(),
        message="Remember that alerts go to the ops channel.",
        memory=memory,
        policy=FakePolicyService(denied_actions={"memory.upsert"}),
    )

    with pytest.raises(PolicyDeniedError):
        await MemoryUpdateStrategy().run(context=context, agents=[FakeAgent(name="support_agent")])

    assert memory.writes == []


@pytest.mark.asyncio
async def test_memory_update_strategy_returns_pending_summary_when_policy_requires_approval() -> None:
    memory = FakeMemoryGateway()
    context = build_context(
        build_config(),
        message="Remember that deployment approvals need two reviewers.",
        memory=memory,
        policy=FakePolicyService(approval_required_actions={"memory.upsert"}),
    )

    result = await MemoryUpdateStrategy().run(
        context=context,
        agents=[FakeAgent(name="support_agent")],
    )

    assert result.answer == "This memory update requires approval before I can store it."
    assert result.memory_updates[0]["status"] == "approval_required"
    assert result.metadata["approval_required_count"] == 1
    assert memory.writes == []
