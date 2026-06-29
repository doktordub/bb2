from __future__ import annotations

import asyncio
from types import SimpleNamespace
from collections.abc import AsyncIterator

import pytest

from app.agents.errors import AgentCancelledError
from app.agents.models import AgentRunRequest
from app.agents.plugins.base_llm_agent import BaseLlmAgent
from app.agents.result_builder import build_run_request_from_context
from app.contracts.context import OrchestrationContext, RequestContext
from app.contracts.llm import LLMRequest, LLMResponse, LLMStreamEvent
from app.orchestration.prompt_inputs import PromptSection
from app.testing.fakes import (
    FakeConfigurationView,
    FakeLLMGateway,
    FakeMemoryGateway,
    FakePolicyService,
    FakeToolGateway,
    FakeTraceStore,
)
from app.testing.fakes.fake_trace_recorder import build_fake_trace_recorder


class HarnessAgent(BaseLlmAgent):
    name = "cancellation_agent"
    type = "general_assistant"
    prompt_profile = "general_assistant_v1"

    def build_extra_prompt_sections(
        self,
        *,
        request: AgentRunRequest,
        context: OrchestrationContext,
    ) -> tuple[PromptSection, ...]:
        _ = request
        _ = context
        return (PromptSection(title="Mode", body="Keep the answer brief."),)


class CancellingLLMGateway(FakeLLMGateway):
    async def complete(
        self,
        request: LLMRequest,
        context: OrchestrationContext,
    ) -> LLMResponse:
        self.requests.append(request)
        self.contexts.append(context)
        raise asyncio.CancelledError()

    async def stream(
        self,
        request: LLMRequest,
        context: OrchestrationContext,
    ) -> AsyncIterator[LLMStreamEvent]:
        self.requests.append(request)
        self.contexts.append(context)
        raise asyncio.CancelledError()
        if False:
            yield LLMStreamEvent.delta(text="unused")


def build_context() -> tuple[OrchestrationContext, CancellingLLMGateway, FakeTraceStore]:
    store = FakeTraceStore()
    llm = CancellingLLMGateway(response_text="unused", default_profile="gateway_default")
    context = OrchestrationContext(
        request=RequestContext(
            user_id="user_1",
            session_id="session_1",
            message="Summarize the status.",
            usecase="default_chat",
            trace_id="trace_cancelled",
        ),
        llm=llm,
        memory=FakeMemoryGateway(),
        state=None,
        tools=FakeToolGateway(),
        trace=store,
        policy=FakePolicyService(),
        config=FakeConfigurationView(),
        runtime_metadata={"strategy_name": "direct_agent", "llm_profile": "usecase_profile"},
        observability=build_fake_trace_recorder(store=store),
    )
    return context, llm, store


@pytest.mark.asyncio
async def test_agent_run_raises_normalized_cancellation() -> None:
    context, llm, trace_store = build_context()
    agent = HarnessAgent(name="support_agent")
    agent.default_llm_profile = "agent_profile"
    agent.limits = SimpleNamespace(max_output_chars=200, max_llm_calls=1)

    request = build_run_request_from_context(context, agent_name=agent.name)
    with pytest.raises(AgentCancelledError):
        await agent.run(request=request, context=context)

    assert len(llm.requests) == 1
    assert trace_store.events[-1].resolved_event_name == "agent_cancelled"


@pytest.mark.asyncio
async def test_agent_stream_emits_cancelled_event_on_cancellation() -> None:
    context, llm, trace_store = build_context()
    agent = HarnessAgent(name="support_agent")
    agent.default_llm_profile = "agent_profile"
    agent.limits = SimpleNamespace(max_output_chars=200, max_llm_calls=1)

    request = build_run_request_from_context(context, agent_name=agent.name)
    events = [event async for event in agent.stream(request=request, context=context)]

    assert events[-1].type == "agent.cancelled"
    assert not any(event.type == "agent.completed" for event in events)
    assert len(llm.requests) == 1
    assert trace_store.events[-1].resolved_event_name == "agent_cancelled"