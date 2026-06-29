from __future__ import annotations

import json
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
    name = "trace_redaction_agent"
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
        return (
            PromptSection(
                title="Internal Notes",
                body="SECRET_INTERNAL_INSTRUCTION should never appear in traces.",
            ),
        )


def build_context() -> tuple[OrchestrationContext, FakeTraceStore]:
    store = FakeTraceStore()
    llm = FakeLLMGateway(response_text="SECRET_LLM_RESPONSE", default_profile="gateway_default")
    context = OrchestrationContext(
        request=RequestContext(
            user_id="user_1",
            session_id="session_1",
            message="SECRET_USER_PROMPT",
            usecase="default_chat",
            trace_id="trace_secret",
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
        metadata={"session_summary": "SECRET_SESSION_SUMMARY"},
    )
    return context, store


@pytest.mark.asyncio
async def test_agent_traces_exclude_prompt_response_and_session_text() -> None:
    context, trace_store = build_context()
    agent = HarnessAgent(name="support_agent")
    agent.default_llm_profile = "agent_profile"
    agent.limits = SimpleNamespace(max_output_chars=200, max_llm_calls=1)

    request = build_run_request_from_context(context, agent_name=agent.name)
    result = await agent.run(request=request, context=context)

    assert result.answer == "SECRET_LLM_RESPONSE"

    serialized_payloads = json.dumps([event.payload for event in trace_store.events])
    assert "SECRET_USER_PROMPT" not in serialized_payloads
    assert "SECRET_SESSION_SUMMARY" not in serialized_payloads
    assert "SECRET_INTERNAL_INSTRUCTION" not in serialized_payloads
    assert "SECRET_LLM_RESPONSE" not in serialized_payloads
    assert "raw_prompt" not in serialized_payloads
    assert '"messages"' not in serialized_payloads