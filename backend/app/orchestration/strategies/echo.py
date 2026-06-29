"""Local echo strategy used by walking-skeleton orchestration flows."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass

from app.contracts.agents import AgentPlugin
from app.contracts.context import OrchestrationContext
from app.contracts.results import OrchestrationResult as LegacyOrchestrationResult
from app.contracts.results import StreamEvent
from app.orchestration.events import OrchestrationStreamEvent


@dataclass(slots=True)
class EchoStrategy:
    """Local echo strategy used by fallback and walking-skeleton configurations."""

    name: str = "echo"
    answer_prefix: str = "Echo: "
    default_agent_name: str = "fake_session_agent"
    default_llm_profile: str = "fake_local_profile"

    async def run(
        self,
        *,
        context: OrchestrationContext,
        agents: Sequence[AgentPlugin],
    ) -> LegacyOrchestrationResult:
        _ = agents
        agent_name = _runtime_value(context, "agent_name") or self.default_agent_name
        strategy_name = _runtime_value(context, "strategy_name") or self.name
        llm_profile = _runtime_value(context, "llm_profile") or self.default_llm_profile
        return LegacyOrchestrationResult(
            answer=f"{self.answer_prefix}{context.request.message}",
            session_id=context.request.session_id,
            trace_id=context.request.trace_id,
            agent_name=agent_name,
            strategy_name=strategy_name,
            llm_profile=llm_profile,
            metadata={},
        )

    async def stream(
        self,
        *,
        context: OrchestrationContext,
        agents: Sequence[AgentPlugin],
    ) -> AsyncIterator[StreamEvent | OrchestrationStreamEvent]:
        result = await self.run(context=context, agents=agents)
        yield StreamEvent(
            event_type="agent_summary",
            data={
                "agent_name": result.agent_name,
                "strategy_name": result.strategy_name,
                "llm_profile": result.llm_profile,
            },
        )
        yield OrchestrationStreamEvent.response_delta(
            trace_id=result.trace_id or "unknown_trace",
            session_id=result.session_id,
            text=result.answer,
        )
        yield OrchestrationStreamEvent.response_completed(
            trace_id=result.trace_id or "unknown_trace",
            session_id=result.session_id,
            finish_reason="stop",
        )


def _runtime_value(context: OrchestrationContext, key: str) -> str | None:
    value = context.runtime_metadata.get(key)
    return _read_optional_str(value)


def _read_optional_str(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None