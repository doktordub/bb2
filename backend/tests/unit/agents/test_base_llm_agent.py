from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agents.errors import AgentConfigurationError, AgentPolicyDeniedError
from app.agents.plugins.base_llm_agent import BaseLlmAgent
from app.agents.result_builder import build_run_request_from_context
from app.contracts.context import OrchestrationContext, RequestContext
from app.orchestration.prompt_inputs import PromptSection
from app.testing.fakes import FakeConfigurationView, FakeLLMGateway, FakeMemoryGateway, FakePolicyService, FakeToolGateway, FakeTraceStore
from app.testing.fakes.fake_trace_recorder import build_fake_trace_recorder


class HarnessAgent(BaseLlmAgent):
    name = "harness_agent"
    type = "general_assistant"
    prompt_profile = "general_assistant_v1"

    def build_extra_prompt_sections(
        self,
        *,
        request,
        context,
    ) -> tuple[PromptSection, ...]:
        _ = request
        _ = context
        return (PromptSection(title="Harness", body="Keep the answer brief."),)


def build_context(
    *,
    response_text: str = "answer from llm",
    policy: FakePolicyService | None = None,
    trace_store: FakeTraceStore | None = None,
) -> tuple[OrchestrationContext, FakeLLMGateway, FakeTraceStore]:
    store = trace_store or FakeTraceStore()
    llm = FakeLLMGateway(response_text=response_text, default_profile="gateway_default")
    context = OrchestrationContext(
        request=RequestContext(
            user_id="user_1",
            session_id="session_1",
            message="Summarize the plan.",
            usecase="default_chat",
            trace_id="trace_1",
        ),
        llm=llm,
        memory=FakeMemoryGateway(),
        state=None,
        tools=FakeToolGateway(),
        trace=store,
        policy=policy or FakePolicyService(),
        config=FakeConfigurationView(),
        runtime_metadata={"strategy_name": "direct_agent", "llm_profile": "usecase_profile"},
        observability=build_fake_trace_recorder(store=store),
    )
    return context, llm, store


@pytest.mark.asyncio
async def test_base_llm_agent_uses_runtime_profile_and_records_safe_traces() -> None:
    context, llm, trace_store = build_context(response_text="  backend summary  ")
    agent = HarnessAgent(name="support_agent")
    agent.default_llm_profile = "agent_profile"
    agent.limits = SimpleNamespace(max_output_chars=200, max_llm_calls=1)
    agent.stream_llm_deltas = True

    result = await agent.run(context)

    assert result.answer == "backend summary"
    assert result.agent_name == "support_agent"
    assert result.llm_profile == "usecase_profile"
    assert llm.requests[0].profile == "usecase_profile"
    assert llm.requests[0].messages[0].role == "system"
    assert "backend general assistant" in str(llm.requests[0].messages[0].content).lower()

    event_names = [event.resolved_event_name for event in trace_store.events]
    assert event_names == [
        "agent_started",
        "agent_prompt_built",
        "agent_llm_started",
        "agent_llm_completed",
        "agent_completed",
    ]
    assert "raw_prompt" not in trace_store.events[1].payload
    assert trace_store.events[1].payload["prompt_profile"] == "general_assistant_v1"


@pytest.mark.asyncio
async def test_base_llm_agent_honors_explicit_prompt_overrides_before_profile_lookup() -> None:
    context, llm, _ = build_context(response_text="override answer")
    agent = HarnessAgent(name="support_agent")
    agent.default_llm_profile = "agent_profile"
    agent.limits = SimpleNamespace(max_output_chars=200, max_llm_calls=1)
    agent.system_prompt_override = "Use the explicit configured system prompt."
    agent.developer_prompt = "Respond with one sentence."

    await agent.run(context)

    assert llm.requests[0].messages[0].content == "Use the explicit configured system prompt."
    assert "Developer instructions" in str(llm.requests[0].messages[-1].content)
    assert "Respond with one sentence." in str(llm.requests[0].messages[-1].content)


@pytest.mark.asyncio
async def test_base_llm_agent_stream_can_suppress_llm_delta_events() -> None:
    context, _, _ = build_context(response_text="streamed answer")
    agent = HarnessAgent(name="support_agent")
    agent.default_llm_profile = "agent_profile"
    agent.limits = SimpleNamespace(max_output_chars=200, max_llm_calls=1)
    agent.stream_llm_deltas = False

    events = []

    structured_request = build_run_request_from_context(context, agent_name=agent.name)
    async for event in agent.stream(request=structured_request, context=context):
        events.append(event)

    assert [event.type for event in events] == [
        "agent.started",
        "agent.prompt_built",
        "agent.llm.started",
        "agent.llm.completed",
        "agent.completed",
    ]
    assert events[-1].result is not None
    assert events[-1].result.answer == "streamed answer"


@pytest.mark.asyncio
async def test_base_llm_agent_truncates_output_to_limit() -> None:
    context, _, _ = build_context(response_text="This answer is much longer than twelve chars.")
    agent = HarnessAgent(name="support_agent")
    agent.default_llm_profile = "agent_profile"
    agent.limits = SimpleNamespace(max_output_chars=12, max_llm_calls=1)

    request = build_run_request_from_context(context, agent_name=agent.name)
    result = await agent.run(request=request, context=context)

    assert result.answer == "This answ..."
    assert result.metadata["truncated"] is True
    assert result.warnings[0].code == "answer_truncated"


@pytest.mark.asyncio
async def test_base_llm_agent_requires_profile_and_policy() -> None:
    context, _, trace_store = build_context(
        policy=FakePolicyService(denied_actions={"llm.complete"}),
    )
    agent = HarnessAgent(name="support_agent")
    agent.default_llm_profile = None
    agent.limits = SimpleNamespace(max_output_chars=200, max_llm_calls=1)
    context.runtime_metadata = {}

    missing_profile_request = build_run_request_from_context(context, agent_name=agent.name)

    with pytest.raises(AgentConfigurationError):
        await agent.run(request=missing_profile_request, context=context)

    agent.default_llm_profile = "agent_profile"
    denied_request = build_run_request_from_context(context, agent_name=agent.name)
    with pytest.raises(AgentPolicyDeniedError):
        await agent.run(request=denied_request, context=context)

    assert trace_store.events[-1].resolved_event_name == "agent_policy_denied"