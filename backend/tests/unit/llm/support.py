from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.config.view import get_llm_settings
from app.contracts.context import OrchestrationContext, RequestContext
from app.llm.gateway import DefaultLLMGateway
from app.llm.profile_resolver import LLMProfileResolver
from app.llm.provider_registry import ProviderRegistry
from app.llm.providers import FakeLLMProviderAdapter
from app.observability.metrics import InMemoryMetricsRecorder, MetricsRecorder
from app.policy.service import DefaultPolicyService
from app.testing.fakes import (
    FakeConfigurationView,
    FakeLLMGateway,
    FakeMemoryGateway,
    FakeToolGateway,
    FakeTraceStore,
    FakeWorkflowStateStore,
)


def base_config(
    *,
    trace_payloads_enabled: bool = True,
    trace_prompts: bool = False,
    trace_completions: bool = False,
) -> dict[str, Any]:
    return {
        "app": {"active_usecase": "default_chat"},
        "llm": {
            "defaults": {
                "profile": "primary_profile",
                "timeout_seconds": 20,
                "stream_timeout_seconds": 45,
                "max_retries": 1,
                "trace_prompts": trace_prompts,
                "trace_completions": trace_completions,
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
                "fallback_provider": {
                    "type": "fake",
                    "enabled": True,
                    "timeout_seconds": 30,
                    "stream_timeout_seconds": 60,
                    "headers": {},
                    "extra": {},
                },
            },
            "profiles": {
                "primary_profile": {
                    "enabled": True,
                    "provider": "primary_provider",
                    "model": "primary-model",
                    "supports_streaming": True,
                    "supports_json_schema": True,
                    "supports_tool_calling": False,
                    "max_output_tokens": 32,
                    "max_input_tokens": 32,
                    "max_total_tokens": 64,
                    "allowed_for": {
                        "usecases": ["default_chat"],
                        "agents": ["support_agent"],
                        "strategies": ["direct_agent"],
                    },
                    "fallback_profiles": ["fallback_profile"],
                    "extra": {},
                },
                "fallback_profile": {
                    "enabled": True,
                    "provider": "fallback_provider",
                    "model": "fallback-model",
                    "supports_streaming": True,
                    "supports_json_schema": True,
                    "supports_tool_calling": False,
                    "max_output_tokens": 32,
                    "max_input_tokens": 32,
                    "max_total_tokens": 64,
                    "allowed_for": {
                        "usecases": ["default_chat"],
                        "agents": ["support_agent"],
                        "strategies": ["direct_agent"],
                    },
                    "fallback_profiles": [],
                    "extra": {},
                },
                "restricted_profile": {
                    "enabled": True,
                    "provider": "primary_provider",
                    "model": "restricted-model",
                    "supports_streaming": True,
                    "supports_json_schema": True,
                    "supports_tool_calling": False,
                    "max_output_tokens": 32,
                    "max_input_tokens": 32,
                    "max_total_tokens": 64,
                    "allowed_for": {
                        "usecases": ["default_chat"],
                        "agents": ["other_agent"],
                        "strategies": ["direct_agent"],
                    },
                    "fallback_profiles": [],
                    "extra": {},
                },
                "restricted_fallback_profile": {
                    "enabled": True,
                    "provider": "fallback_provider",
                    "model": "restricted-fallback-model",
                    "supports_streaming": True,
                    "supports_json_schema": True,
                    "supports_tool_calling": False,
                    "max_output_tokens": 32,
                    "max_input_tokens": 32,
                    "max_total_tokens": 64,
                    "allowed_for": {
                        "usecases": ["default_chat"],
                        "agents": ["other_agent"],
                        "strategies": ["direct_agent"],
                    },
                    "fallback_profiles": [],
                    "extra": {},
                },
            },
        },
        "usecases": {
            "default_chat": {
                "policy_profile": "default",
            }
        },
        "agents": {
            "support_agent": {
                "llm_profile": "primary_profile",
            },
            "other_agent": {
                "llm_profile": "restricted_profile",
            },
        },
        "strategies": {
            "direct_agent": {
                "llm_profile": "primary_profile",
            }
        },
        "policy": {
            "default_profile": "default",
            "profiles": {
                "default": {
                    "deny_unknown_tools": True,
                    "deny_unknown_llm_profiles": True,
                    "require_memory_scope": True,
                    "allow_memory_writes": False,
                }
            },
        },
        "observability": {
            "trace_enabled": True,
            "trace_payloads_enabled": trace_payloads_enabled,
            "trace_store_required": True,
            "redact_secrets": True,
            "max_trace_payload_chars": 200,
            "slow_request_ms": 5000,
            "slow_llm_call_ms": 10000,
            "slow_tool_call_ms": 5000,
            "structured_logging": True,
            "log_level": "INFO",
            "include_stack_traces_in_logs": False,
            "include_stack_traces_in_traces": False,
            "metrics_enabled": True,
        },
    }


def build_context(
    config_values: dict[str, Any],
    *,
    trace_store: FakeTraceStore | None = None,
    runtime_metadata: dict[str, object] | None = None,
) -> OrchestrationContext:
    config_view = FakeConfigurationView(deepcopy(config_values))
    policy_service = DefaultPolicyService(config_view)
    return OrchestrationContext(
        request=RequestContext(
            user_id="user_1",
            session_id="session_1",
            message="hello world",
            usecase="default_chat",
            trace_id="trace_1",
        ),
        llm=FakeLLMGateway(),
        memory=FakeMemoryGateway(),
        state=FakeWorkflowStateStore(),
        tools=FakeToolGateway(),
        trace=trace_store or FakeTraceStore(),
        policy=policy_service,
        config=config_view,
        runtime_metadata={
            "agent_name": "support_agent",
            "strategy_name": "direct_agent",
            **dict(runtime_metadata or {}),
        },
    )


def build_registry(
    config_values: dict[str, Any],
    *,
    primary_adapter: FakeLLMProviderAdapter | None = None,
    fallback_adapter: FakeLLMProviderAdapter | None = None,
) -> ProviderRegistry:
    config_view = FakeConfigurationView(deepcopy(config_values))
    settings = get_llm_settings(config_view)
    registry = ProviderRegistry(settings.providers)
    registry.register(
        "primary_provider",
        primary_adapter or FakeLLMProviderAdapter(name="primary_provider", response_text="primary answer"),
    )
    registry.register(
        "fallback_provider",
        fallback_adapter or FakeLLMProviderAdapter(name="fallback_provider", response_text="fallback answer"),
    )
    return registry


def build_gateway(
    config_values: dict[str, Any],
    *,
    registry: ProviderRegistry | None = None,
    metrics: MetricsRecorder | None = None,
) -> DefaultLLMGateway:
    config_view = FakeConfigurationView(deepcopy(config_values))
    return DefaultLLMGateway(
        config=config_view,
        registry=registry or build_registry(config_values),
        profile_resolver=LLMProfileResolver(),
        policy_service=DefaultPolicyService(config_view),
        metrics=metrics or InMemoryMetricsRecorder(),
    )