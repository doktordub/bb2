from __future__ import annotations

import pytest

from app.contracts.context import OrchestrationContext, RequestContext
from app.contracts.llm import LLMMessage, LLMRequest
from app.llm.errors import LLMProviderUnavailableError, LLMUnsupportedCapabilityError
from app.llm.profile_resolver import LLMProfileResolver
from app.testing.fakes import (
    FakeConfigurationView,
    FakeLLMGateway,
    FakeMemoryGateway,
    FakePolicyService,
    FakeToolGateway,
    FakeTraceStore,
    FakeWorkflowStateStore,
)


def build_context(
    config_values: dict[str, object],
    *,
    usecase: str = "default_chat",
    runtime_metadata: dict[str, object] | None = None,
) -> OrchestrationContext:
    return OrchestrationContext(
        request=RequestContext(
            user_id="user_1",
            session_id="session_1",
            message="hello",
            usecase=usecase,
            trace_id="trace_1",
        ),
        llm=FakeLLMGateway(),
        memory=FakeMemoryGateway(),
        state=FakeWorkflowStateStore(),
        tools=FakeToolGateway(),
        trace=FakeTraceStore(),
        policy=FakePolicyService(),
        config=FakeConfigurationView(config_values),
        runtime_metadata=dict(runtime_metadata or {}),
    )


def base_config() -> dict[str, object]:
    return {
        "app": {"active_usecase": "default_chat"},
        "llm": {
            "defaults": {
                "profile": "default_profile",
                "timeout_seconds": 20,
                "stream_timeout_seconds": 45,
                "max_retries": 2,
                "trace_prompts": False,
                "trace_completions": False,
            },
            "providers": {
                "primary_provider": {
                    "type": "fake",
                    "enabled": True,
                    "timeout_seconds": 30,
                    "stream_timeout_seconds": 60,
                    "headers": {},
                    "extra": {},
                },
                "disabled_provider": {
                    "type": "fake",
                    "enabled": False,
                    "timeout_seconds": 30,
                    "stream_timeout_seconds": 60,
                    "headers": {},
                    "extra": {},
                },
            },
            "profiles": {
                "default_profile": {
                    "enabled": True,
                    "provider": "primary_provider",
                    "model": "default-model",
                    "supports_streaming": True,
                    "supports_json_schema": True,
                    "supports_tool_calling": False,
                    "allowed_for": {"usecases": [], "agents": [], "strategies": []},
                    "fallback_profiles": [],
                    "extra": {},
                },
                "agent_profile": {
                    "enabled": True,
                    "provider": "primary_provider",
                    "model": "agent-model",
                    "supports_streaming": True,
                    "supports_json_schema": False,
                    "supports_tool_calling": False,
                    "allowed_for": {"usecases": [], "agents": ["support_agent"], "strategies": []},
                    "fallback_profiles": [],
                    "extra": {},
                },
                "strategy_profile": {
                    "enabled": True,
                    "provider": "primary_provider",
                    "model": "strategy-model",
                    "supports_streaming": True,
                    "supports_json_schema": True,
                    "supports_tool_calling": False,
                    "allowed_for": {"usecases": [], "agents": [], "strategies": ["direct_agent"]},
                    "fallback_profiles": [],
                    "extra": {},
                },
                "orchestrator_profile": {
                    "enabled": True,
                    "provider": "primary_provider",
                    "model": "orchestrator-model",
                    "supports_streaming": False,
                    "supports_json_schema": True,
                    "supports_tool_calling": False,
                    "allowed_for": {"usecases": ["default_chat"], "agents": [], "strategies": []},
                    "fallback_profiles": [],
                    "extra": {},
                },
                "disabled_provider_profile": {
                    "enabled": True,
                    "provider": "disabled_provider",
                    "model": "disabled-model",
                    "supports_streaming": True,
                    "supports_json_schema": True,
                    "supports_tool_calling": False,
                    "allowed_for": {"usecases": [], "agents": [], "strategies": []},
                    "fallback_profiles": [],
                    "extra": {},
                },
            },
        },
        "usecases": {
            "default_chat": {
                "orchestrator_llm_profile": "orchestrator_profile",
            }
        },
        "agents": {
            "support_agent": {
                "llm_profile": "agent_profile",
            }
        },
        "strategies": {
            "direct_agent": {
                "llm_profile": "strategy_profile",
            }
        },
    }


def test_profile_resolver_prefers_explicit_request_profile() -> None:
    resolver = LLMProfileResolver()
    context = build_context(
        base_config(),
        runtime_metadata={"agent_name": "support_agent", "strategy_name": "direct_agent"},
    )

    resolved = resolver.resolve(
        request=LLMRequest(
            profile="default_profile",
            messages=[LLMMessage(role="user", content="hello")],
        ),
        context=context,
    )

    assert resolved.profile_name == "default_profile"
    assert resolved.resolution_source == "request"


def test_profile_resolver_uses_agent_then_strategy_then_usecase_then_default() -> None:
    resolver = LLMProfileResolver()
    config = base_config()

    agent_context = build_context(
        config,
        runtime_metadata={"agent_name": "support_agent", "strategy_name": "direct_agent"},
    )
    agent_resolved = resolver.resolve(
        request=LLMRequest(messages=[LLMMessage(role="user", content="hello")]),
        context=agent_context,
    )

    strategy_context = build_context(
        config,
        runtime_metadata={"strategy_name": "direct_agent"},
    )
    strategy_resolved = resolver.resolve(
        request=LLMRequest(messages=[LLMMessage(role="user", content="hello")]),
        context=strategy_context,
    )

    usecase_context = build_context(config)
    usecase_resolved = resolver.resolve(
        request=LLMRequest(messages=[LLMMessage(role="user", content="hello")]),
        context=usecase_context,
    )

    default_only = base_config()
    assert isinstance(default_only["usecases"], dict)
    default_only["usecases"]["default_chat"] = {}
    default_context = build_context(default_only)
    default_resolved = resolver.resolve(
        request=LLMRequest(messages=[LLMMessage(role="user", content="hello")]),
        context=default_context,
    )

    assert agent_resolved.profile_name == "agent_profile"
    assert agent_resolved.resolution_source == "agent"
    assert strategy_resolved.profile_name == "strategy_profile"
    assert strategy_resolved.resolution_source == "strategy"
    assert usecase_resolved.profile_name == "orchestrator_profile"
    assert usecase_resolved.resolution_source == "usecase"
    assert default_resolved.profile_name == "default_profile"
    assert default_resolved.resolution_source == "default"


def test_profile_resolver_rejects_unsupported_streaming_and_json_schema() -> None:
    resolver = LLMProfileResolver()
    context = build_context(base_config())

    with pytest.raises(LLMUnsupportedCapabilityError, match="does not support streaming"):
        resolver.resolve(
            request=LLMRequest(
                profile="orchestrator_profile",
                stream=True,
                messages=[LLMMessage(role="user", content="hello")],
            ),
            context=context,
        )

    with pytest.raises(LLMUnsupportedCapabilityError, match="structured output"):
        resolver.resolve(
            request=LLMRequest(
                profile="agent_profile",
                messages=[LLMMessage(role="user", content="hello")],
                response_format={"type": "json_schema", "json_schema": {"type": "object"}},
            ),
            context=context,
        )


def test_profile_resolver_rejects_disabled_provider_profile() -> None:
    resolver = LLMProfileResolver()
    context = build_context(base_config())

    with pytest.raises(LLMProviderUnavailableError, match="unavailable"):
        resolver.resolve(
            request=LLMRequest(
                profile="disabled_provider_profile",
                messages=[LLMMessage(role="user", content="hello")],
            ),
            context=context,
        )