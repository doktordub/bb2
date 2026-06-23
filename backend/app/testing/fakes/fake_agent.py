"""In-memory fake agent for contract-focused tests."""

from __future__ import annotations

from app.contracts.context import OrchestrationContext
from app.contracts.llm import LLMMessage, LLMRequest
from app.contracts.results import AgentResult


class FakeAgent:
    """Deterministic agent that delegates generation to the LLM gateway."""

    name = "fake_agent"
    description = "A fake test agent."
    capabilities = ["test"]

    def __init__(self, component: str | None = None) -> None:
        self.component = component or f"agent.{self.name}"
        self.runs: list[OrchestrationContext] = []

    async def run(self, context: OrchestrationContext) -> AgentResult:
        self.runs.append(context)
        response = await context.llm.complete(
            LLMRequest(
                component=self.component,
                messages=[LLMMessage(role="user", content=context.request.message)],
            ),
            context,
        )
        return AgentResult(
            answer=response.text,
            agent_name=self.name,
            llm_profile=response.profile,
        )