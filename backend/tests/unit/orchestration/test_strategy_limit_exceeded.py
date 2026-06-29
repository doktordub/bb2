from __future__ import annotations

import pytest

from app.contracts.tools import ToolDefinition
from app.orchestration.errors import OrchestrationLimitExceededError
from app.orchestration.strategies.tool_assisted import ToolAssistedStrategy
from app.testing.fakes import FakeAgent, FakeLLMGateway, FakeToolGateway
from tests.unit.orchestration.test_tool_assisted_strategy import build_config, build_context


@pytest.mark.asyncio
async def test_tool_assisted_strategy_blocks_repeated_tool_loop_before_execution() -> None:
    llm = FakeLLMGateway(response_text="tool assisted answer")
    tools = FakeToolGateway(
        tools=[ToolDefinition(name="documents.search", description="Search documents")]
    )
    context = build_context(build_config(), llm=llm, tools=tools)
    context.metadata["tool_signatures"] = [
        "documents.search:[('limit', 3), ('query', 'architecture notes')]"
    ]

    with pytest.raises(OrchestrationLimitExceededError):
        await ToolAssistedStrategy().run(
            context=context,
            agents=[FakeAgent(name="support_agent")],
        )

    assert tools.calls == []