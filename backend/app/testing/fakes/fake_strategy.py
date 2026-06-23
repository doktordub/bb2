"""In-memory fake strategy for contract-focused tests."""

from __future__ import annotations

from app.contracts.agents import AgentPlugin
from app.contracts.context import OrchestrationContext
from app.contracts.results import OrchestrationResult


class FakeDirectStrategy:
    """Deterministic strategy that runs the first provided agent."""

    name = "fake_direct_strategy"

    def __init__(self) -> None:
        self.contexts: list[OrchestrationContext] = []
        self.agent_names: list[str] = []

    async def run(
        self,
        context: OrchestrationContext,
        agents: list[AgentPlugin],
    ) -> OrchestrationResult:
        if not agents:
            raise ValueError("FakeDirectStrategy requires at least one agent")

        agent = agents[0]
        self.contexts.append(context)
        self.agent_names.append(agent.name)

        result = await agent.run(context)
        return OrchestrationResult(
            answer=result.answer,
            session_id=context.request.session_id,
            trace_id=context.request.trace_id,
            agent_name=result.agent_name,
            strategy_name=self.name,
            llm_profile=result.llm_profile,
            tool_calls=list(result.tool_calls),
            memory_updates=list(result.memory_updates),
            citations=list(result.citations),
            metadata=dict(result.metadata),
        )