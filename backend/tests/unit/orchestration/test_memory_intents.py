from __future__ import annotations

from app.config.view import get_orchestration_settings
from app.contracts.context import OrchestrationContext, RequestContext
from app.contracts.memory import MemoryResult
from app.orchestration.limits import OrchestrationLimitTracker
from app.orchestration.memory_intents import build_memory_context_block, build_memory_search_intent, build_memory_search_request
from app.orchestration.models import OrchestrationRuntimeContext
from app.testing.fakes import FakeConfigurationView, FakeLLMGateway, FakeMemoryGateway, FakePolicyService, FakeToolGateway, FakeTraceStore


def build_config() -> FakeConfigurationView:
    return FakeConfigurationView(
        {
            "orchestration": {
                "enabled": True,
                "defaults": {
                    "strategy": "retrieval_augmented",
                    "fallback_strategy": "direct_agent",
                    "max_steps": 8,
                    "max_tool_calls": 4,
                    "max_memory_searches": 3,
                    "max_llm_calls": 6,
                    "max_turn_duration_seconds": 120,
                    "max_stream_duration_seconds": 300,
                },
                "strategies": {
                    "retrieval_augmented": {
                        "enabled": True,
                        "type": "retrieval_augmented",
                        "default_agent": "support_agent",
                        "allowed_usecases": ["document_chat"],
                        "llm_profile": "retrieval_profile",
                        "memory_enabled": True,
                        "memory": {
                            "default_limit": 2,
                            "include_document_chunks": True,
                            "include_user_memory": True,
                        },
                    }
                },
                "usecases": {
                    "document_chat": {
                        "enabled": True,
                        "strategy": "retrieval_augmented",
                        "agent": "support_agent",
                        "allowed_agents": ["support_agent"],
                        "policy_profile": "default",
                        "memory": {"enabled": True, "include_document_chunks": True, "default_limit": 2},
                        "tools": {"enabled": False, "allowed_tools": []},
                    }
                },
            },
            "llm": {"defaults": {"profile": "retrieval_profile"}},
            "memory": {"enabled": True},
        }
    )


def build_context(config: FakeConfigurationView) -> OrchestrationContext:
    settings = get_orchestration_settings(config)
    strategy_settings = settings.strategies["retrieval_augmented"]
    limits = OrchestrationLimitTracker.from_settings(settings, strategy_settings)
    limits.mark_turn_started()
    return OrchestrationContext(
        request=RequestContext(
            user_id="user_1",
            session_id="session_1",
            message="Summarize the architecture",
            usecase="document_chat",
            trace_id="trace_1",
        ),
        llm=FakeLLMGateway(response_text="unused"),
        memory=FakeMemoryGateway(),
        state=None,
        tools=FakeToolGateway(),
        trace=FakeTraceStore(),
        policy=FakePolicyService(),
        config=config,
        runtime_metadata={"agent_name": "support_agent", "strategy_name": "retrieval_augmented"},
        runtime=OrchestrationRuntimeContext(
            request_id="request_1",
            trace_id="trace_1",
            session_id="session_1",
            user_id="user_1",
            project_id="project_1",
            tenant_id="tenant_1",
        ),
        settings=settings,
        strategy_settings=strategy_settings,
        limits=limits,
    )


def test_build_memory_search_intent_uses_runtime_scope_and_strategy_defaults() -> None:
    intent = build_memory_search_intent(build_context(build_config()), agent_name="support_agent")

    assert intent.scope.project_id == "project_1"
    assert intent.scope.tenant_id == "tenant_1"
    assert intent.limit == 2
    assert intent.include_document_chunks is True


def test_build_memory_context_block_bounds_retrieved_text() -> None:
    search_result = FakeMemoryGateway(
        results=[
            MemoryResult(
                memory_id="memory_1",
                text="The runtime resolves strategies through a registry.",
                memory_type="document_chunk",
                source_id="architecture.md",
            )
        ]
    ).search_result

    bounded = build_memory_context_block(search_result, max_items=4, max_bytes=256, max_item_chars=80)

    assert bounded.text.startswith("Retrieved context:")
    assert bounded.item_count == 1
    assert bounded.used_bytes <= 256


def test_build_memory_search_request_preserves_safe_intent_fields() -> None:
    intent = build_memory_search_intent(build_context(build_config()), agent_name="support_agent")
    request = build_memory_search_request(intent)

    assert request.text == "Summarize the architecture"
    assert request.scope.project_id == "project_1"
    assert request.limit == 2