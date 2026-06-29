from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agents.errors import AgentPolicyDeniedError
from app.agents.plugins.base_llm_agent import BaseLlmAgent
from app.agents.result_builder import build_run_request_from_context
from app.contracts.context import OrchestrationContext, RequestContext
from app.testing.fakes import FakeConfigurationView, FakeLLMGateway, FakeMemoryGateway, FakePolicyService, FakeToolGateway, FakeTraceStore
from app.testing.fakes.fake_trace_recorder import build_fake_trace_recorder


class _AnswerOnlyAgent(BaseLlmAgent):
    name = "answer_only_agent"
    type = "general_assistant"
    prompt_profile = "general_assistant_v1"


def _build_context(*, policy: FakePolicyService | None = None) -> OrchestrationContext:
    trace_store = FakeTraceStore()
    return OrchestrationContext(
        request=RequestContext(
            user_id="user_1",
            session_id="session_1",
            message="hello",
            usecase="default_chat",
            trace_id="trace_1",
        ),
        llm=FakeLLMGateway(response_text="ok", default_profile="fake_profile"),
        memory=FakeMemoryGateway(),
        state=None,
        tools=FakeToolGateway(),
        trace=trace_store,
        policy=policy or FakePolicyService(),
        config=FakeConfigurationView(),
        runtime_metadata={
            "strategy_name": "direct_agent",
            "agent_name": "answer_only_agent",
            "llm_profile": "fake_profile",
        },
        observability=build_fake_trace_recorder(store=trace_store),
    )


@pytest.mark.asyncio
async def test_agent_capability_use_runs_policy_check_before_execution() -> None:
    policy = FakePolicyService(denied_actions={"agent.invoke"}, deny_reason="Capability denied")
    context = _build_context(policy=policy)
    agent = _AnswerOnlyAgent(name="answer_only_agent")
    agent.default_llm_profile = "fake_profile"
    agent.limits = SimpleNamespace(max_output_chars=200, max_llm_calls=1)

    request = build_run_request_from_context(context, agent_name=agent.name)
    with pytest.raises(AgentPolicyDeniedError, match="Capability denied"):
        await agent.run(request=request, context=context)

    assert policy.requests[0].metadata["agent_action"] == "use_capability"
    assert policy.requests[0].metadata["agent_capability"] == "answer"