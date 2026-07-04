from __future__ import annotations

import pytest

from app.config.view import get_orchestration_settings
from app.contracts.context import OrchestrationContext, RequestContext
from app.orchestration.message_catalog import clear_message_catalog_cache
from app.orchestration.limits import OrchestrationLimitTracker
from app.orchestration.strategies.fallback_answer import FallbackAnswerStrategy
from app.testing.fakes import (
    FakeConfigurationView,
    FakeLLMGateway,
    FakeMemoryGateway,
    FakePolicyService,
    FakeToolGateway,
    FakeTraceStore,
)


def build_config(*, llm_profile: str | None) -> FakeConfigurationView:
    strategy: dict[str, object] = {
        "enabled": True,
        "type": "fallback_answer",
        "default_agent": "support_agent",
        "allowed_usecases": ["default_chat"],
        "message": "Fallback static answer.",
    }
    if llm_profile is not None:
        strategy["llm_profile"] = llm_profile

    config: dict[str, object] = {
        "orchestration": {
            "enabled": True,
            "defaults": {
                "strategy": "fallback_answer",
                "fallback_strategy": "fallback_answer",
            },
            "strategies": {
                "fallback_answer": strategy,
            },
            "usecases": {
                "default_chat": {
                    "enabled": True,
                    "strategy": "fallback_answer",
                    "agent": "support_agent",
                    "allowed_agents": ["support_agent"],
                    "policy_profile": "default",
                }
            },
        },
        "agents": {
            "support_agent": {
                "enabled": True,
                "module": "app.testing.fakes.fake_agent",
                "class_name": "FakeAgent",
            }
        },
    }
    if llm_profile is not None:
        config["llm"] = {"defaults": {"profile": "unused_default"}}
    return FakeConfigurationView(config)


def build_context(config: FakeConfigurationView, *, llm: FakeLLMGateway) -> OrchestrationContext:
    settings = get_orchestration_settings(config)
    strategy_settings = settings.strategies["fallback_answer"]
    limits = OrchestrationLimitTracker.from_settings(settings, strategy_settings)
    limits.mark_turn_started()
    runtime_metadata = {
        "agent_name": "support_agent",
        "strategy_name": "fallback_answer",
    }
    if strategy_settings.llm_profile is not None:
        runtime_metadata["llm_profile"] = strategy_settings.llm_profile
    return OrchestrationContext(
        request=RequestContext(
            user_id="user_1",
            session_id="session_1",
            message="How do I recover?",
            usecase="default_chat",
            trace_id="trace_1",
            metadata={
                "failed_strategy": "direct_agent",
                "failed_error_code": "dependency_unavailable",
                "failed_retryable": True,
                "fallback_reason": "degradable_failure",
                "failed_error_message": "Traceback: should never leak",
            },
        ),
        llm=llm,
        memory=FakeMemoryGateway(),
        state=None,
        tools=FakeToolGateway(),
        trace=FakeTraceStore(),
        policy=FakePolicyService(),
        config=config,
        runtime_metadata=runtime_metadata,
        settings=settings,
        strategy_settings=strategy_settings,
        limits=limits,
    )


@pytest.mark.asyncio
async def test_fallback_answer_strategy_uses_llm_with_safe_prompt_when_profile_is_configured() -> None:
    config = build_config(llm_profile="fallback_profile")
    llm = FakeLLMGateway(response_text="Safe fallback answer")
    context = build_context(config, llm=llm)

    result = await FallbackAnswerStrategy().run(context=context, agents=[])

    assert result.answer == "Safe fallback answer"
    assert result.metadata["fallback_used"] is True
    assert result.metadata["answer_source"] == "llm"
    assert result.metadata["failed_strategy"] == "direct_agent"
    assert llm.requests[0].profile == "fallback_profile"
    prompt_text = llm.requests[0].messages[-1].content
    assert isinstance(prompt_text, str)
    assert "Traceback" not in prompt_text
    assert [step["step_type"] for step in result.metadata["steps"]] == ["fallback"]


@pytest.mark.asyncio
async def test_fallback_answer_strategy_returns_static_message_when_no_llm_profile_is_available() -> None:
    config = build_config(llm_profile=None)
    llm = FakeLLMGateway(response_text="unused")
    context = build_context(config, llm=llm)

    result = await FallbackAnswerStrategy().run(context=context, agents=[])

    assert result.answer == "Fallback static answer."
    assert result.metadata["fallback_used"] is True
    assert result.metadata["answer_source"] == "static"
    assert llm.requests == []


@pytest.mark.asyncio
async def test_fallback_answer_strategy_uses_message_catalog_when_strategy_message_is_missing(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "messages.yaml"
    path.write_text(
        "messages:\n"
        "  fallback_answer:\n"
        "    default_message: Catalog fallback answer.\n"
        "  memory_update:\n"
        "    no_candidate_answer: Missing candidate.\n"
        "    approval_required_answer: Approval needed.\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("APP_MESSAGES_CONFIG_PATH", str(path))
    clear_message_catalog_cache()

    config = build_config(llm_profile=None)
    config.values["orchestration"]["strategies"]["fallback_answer"].pop("message", None)
    context = build_context(config, llm=FakeLLMGateway(response_text="unused"))

    result = await FallbackAnswerStrategy().run(context=context, agents=[])

    assert result.answer == "Catalog fallback answer."


@pytest.mark.asyncio
async def test_fallback_answer_strategy_uses_code_fallback_when_message_catalog_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_MESSAGES_CONFIG_PATH", "missing/messages.yaml")
    clear_message_catalog_cache()

    config = build_config(llm_profile=None)
    config.values["orchestration"]["strategies"]["fallback_answer"].pop("message", None)
    context = build_context(config, llm=FakeLLMGateway(response_text="unused"))

    result = await FallbackAnswerStrategy().run(context=context, agents=[])

    assert result.answer == "I could not complete the full workflow, but here is the safest answer I can provide."