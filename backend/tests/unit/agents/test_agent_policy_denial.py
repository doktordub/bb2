from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agents.models import AgentRunRequest
from app.agents.plugins.base_llm_agent import BaseLlmAgent
from app.agents.result_builder import build_run_request_from_context
from app.contracts.context import OrchestrationContext, RequestContext
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
    name = "policy_denial_agent"
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


def build_context() -> tuple[OrchestrationContext, FakeLLMGateway, FakeTraceStore]:
    store = FakeTraceStore()
    llm = FakeLLMGateway(response_text="should not be used", default_profile="gateway_default")
    context = OrchestrationContext(
        request=RequestContext(
            user_id="user_1",
            session_id="session_1",
            message="Summarize the status.",
            usecase="default_chat",
            trace_id="trace_policy_denial",
        ),
        llm=llm,
        memory=FakeMemoryGateway(),
        state=None,
        tools=FakeToolGateway(),
        trace=store,
        policy=FakePolicyService(denied_actions={"llm.stream"}),
        config=FakeConfigurationView(),
        runtime_metadata={"strategy_name": "direct_agent", "llm_profile": "usecase_profile"},
        observability=build_fake_trace_recorder(store=store),
    )
    return context, llm, store


@pytest.mark.asyncio
async def test_agent_stream_reports_policy_denial_without_calling_llm() -> None:
    context, llm, trace_store = build_context()
    agent = HarnessAgent(name="support_agent")
    agent.default_llm_profile = "agent_profile"
    agent.limits = SimpleNamespace(max_output_chars=200, max_llm_calls=1)

    request = build_run_request_from_context(context, agent_name=agent.name)
    events = [event async for event in agent.stream(request=request, context=context)]

    assert events[0].type == "agent.started"
    assert events[-1].type == "agent.failed"
    assert events[-1].error is not None
    assert events[-1].error.code == "agent_policy_denied"
    assert llm.requests == []
    assert trace_store.events[-1].resolved_event_name == "agent_policy_denied"