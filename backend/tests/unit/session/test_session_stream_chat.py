from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.config.view import (
    SessionConcurrencySettings,
    SessionDefaultsSettings,
    SessionHistorySettings,
    SessionIdentifierSettings,
    SessionLifecycleSettings,
    SessionSettings,
    SessionStateSettings,
    SessionTracingSettings,
)
from app.llm.factory import build_llm_runtime
from app.orchestration.core import DirectAgentOrchestrationRuntime
from app.policy.factory import build_policy_runtime
from app.session.mapping import build_session_chat_request, build_session_request_context
from app.session.service import DefaultSessionService
from app.testing.fakes.fake_clock import FakeClock
from app.testing.fakes.fake_config import FakeConfigurationView
from app.testing.fakes.fake_llm import FakeLLMGateway
from app.testing.fakes.fake_memory import FakeMemoryGateway
from app.testing.fakes.fake_orchestration_runtime import FakeOrchestrationRuntime
from app.testing.fakes.fake_policy import FakePolicyService
from app.testing.fakes.fake_state import FakeWorkflowStateStore
from app.testing.fakes.fake_trace import FakeTraceStore
from app.testing.fakes.fake_trace_recorder import build_fake_trace_recorder


def _build_settings() -> SessionSettings:
    return SessionSettings(
        enabled=True,
        identifiers=SessionIdentifierSettings(
            prefix="session",
            accept_client_session_id=True,
            generate_when_missing=True,
            max_length=128,
            allowed_pattern="^[A-Za-z0-9_.:-]{3,128}$",
        ),
        defaults=SessionDefaultsSettings(
            default_user_id="local_user",
            default_usecase="default_chat",
            default_history_limit=50,
            max_history_limit=200,
            timezone_metadata_key="timezone",
        ),
        lifecycle=SessionLifecycleSettings(
            create_on_first_chat=True,
            resume_existing_sessions=True,
            reject_unknown_client_session_id=False,
            update_last_seen_on_load=True,
            save_after_failed_orchestration=True,
            save_after_cancelled_stream=True,
        ),
        concurrency=SessionConcurrencySettings(
            mode="optimistic_version",
            conflict_policy="reject",
            max_retries=1,
        ),
        state=SessionStateSettings(
            save_on_chat_completion=True,
            save_on_stream_completion=True,
            save_on_stream_cancellation=True,
            save_on_stream_failure=True,
            save_each_stream_delta=False,
        ),
        history=SessionHistorySettings(
            enabled=False,
            include_tool_summaries=False,
            include_system_messages=False,
            include_metadata=True,
            max_message_chars=4000,
            redaction_enabled=True,
        ),
        tracing=SessionTracingSettings(
            record_session_created=True,
            record_session_resumed=True,
            record_session_reset=True,
            record_state_loaded=True,
            record_state_saved=True,
            record_history_returned=True,
            record_stream_lifecycle=True,
        ),
    )
def _build_context():
    return build_session_request_context(
        trace_id="trace-session-stream-0001",
        request_id="request-session-stream-0001",
        user_id="local_user",
        user_id_hash="user_hash_123",
        client_host="127.0.0.1",
        user_agent="pytest",
        path="/chat/stream",
        method="POST",
        metadata={"auth_mode": "local"},
        headers_safe={"x-trace-id": "trace-session-stream-0001"},
    )


def _build_chart_config() -> FakeConfigurationView:
    return FakeConfigurationView(
        {
            "app": {"active_usecase": "default_chat"},
            "usecases": {
                "default_chat": {
                    "enabled": True,
                }
            },
            "visualization": {
                "enabled": True,
                "context_summary": {
                    "enabled": True,
                    "mode": "summary_only",
                    "max_tokens_per_chart_summary": 600,
                    "max_chart_summaries_per_session_context": 5,
                    "max_total_visualization_context_tokens": 1800,
                    "include_data_ref": True,
                    "include_aggregate_stats": True,
                    "include_extrema": True,
                    "include_trend_summary": True,
                    "include_sample_rows": False,
                    "max_sample_rows": 0,
                    "eviction_policy": "most_recent_relevant",
                },
                "artifact_store": {
                    "enabled": True,
                    "provider": "workflow_state_cache",
                    "ttl_seconds": 7200,
                    "allow_reference_data_mode": True,
                    "public_retrieval_enabled": False,
                    "exact_followup_retrieval_enabled": True,
                    "retrieval_endpoint": "/artifacts/{artifact_id}",
                },
            },
            "orchestration": {
                "enabled": True,
                "defaults": {
                    "strategy": "direct_agent",
                    "fallback_strategy": "direct_agent",
                    "max_steps": 8,
                    "max_tool_calls": 4,
                    "max_memory_searches": 3,
                    "max_llm_calls": 6,
                    "max_turn_duration_seconds": 120,
                    "max_stream_duration_seconds": 300,
                },
                "strategies": {
                    "direct_agent": {
                        "enabled": True,
                        "type": "direct_agent",
                        "default_agent": "chart_agent",
                        "allowed_usecases": ["default_chat"],
                        "llm_profile": "fake_chart",
                    }
                },
                "usecases": {
                    "default_chat": {
                        "enabled": True,
                        "strategy": "direct_agent",
                        "agent": "chart_agent",
                        "allowed_agents": ["chart_agent"],
                        "allowed_strategies": ["direct_agent"],
                        "policy_profile": "default",
                    }
                },
            },
            "agents": {
                "chart_agent": {
                    "enabled": True,
                    "module": "app.testing.fakes.fake_visualization_agent",
                    "class_name": "FakeVisualizationAgent",
                    "llm_profile": "fake_chart",
                }
            },
            "llm": {"defaults": {"profile": "fake_chart"}},
            "observability": {
                "trace_enabled": True,
                "trace_payloads_enabled": True,
                "trace_store_required": True,
                "redact_secrets": True,
                "max_trace_payload_chars": 8000,
            },
        }
    )


@pytest.mark.asyncio
async def test_stream_chat_uses_runtime_stream_and_saves_once_on_completion() -> None:
    workflow_state = FakeWorkflowStateStore()
    trace_store = FakeTraceStore()
    orchestrator = FakeOrchestrationRuntime()
    service = DefaultSessionService(
        config=FakeConfigurationView({"usecases": {"default_chat": {"enabled": True}}}),
        settings=_build_settings(),
        workflow_state=workflow_state,
        trace_recorder=build_fake_trace_recorder(store=trace_store),
        orchestrator=orchestrator,
        clock=FakeClock(
            [
                datetime(2026, 6, 27, 16, 0, tzinfo=UTC),
                datetime(2026, 6, 27, 16, 0, 1, tzinfo=UTC),
            ]
        ),
    )

    events = [
        event
        async for event in service.stream_chat(
            request=build_session_chat_request(
                message="stream this",
                session_id="session_stream_1",
                usecase=None,
            ),
            context=_build_context(),
        )
    ]

    assert [event.event_type for event in events] == [
        "response.started",
        "response.delta",
        "response.delta",
        "response.metadata",
        "response.completed",
    ]
    assert [event.sequence_no for event in events] == [1, 2, 3, 4, 5]
    assert events[3].data == {
        "agent_name": "fake_session_agent",
        "strategy_name": "fake_direct_strategy",
        "llm_profile": "fake_local_profile",
        "usecase": "default_chat",
        "tool_call_count": 0,
        "memory_result_count": 0,
    }
    assert events[4].data["finish_reason"] == "stop"

    assert len(orchestrator.run_calls) == 0
    assert len(orchestrator.stream_calls) == 1
    assert len(workflow_state.save_calls) == 1
    assert workflow_state.save_calls[0].expected_version is None
    assert workflow_state.states["session_stream_1"]["conversation"]["messages"] == [
        {
            "role": "user",
            "content": "stream this",
            "created_at": "2026-06-27T16:00:00+00:00",
            "metadata": {
                "usecase": "default_chat",
                "request_id": "request-session-stream-0001",
                "turn_id": "request-session-stream-0001",
                "trace_id": "trace-session-stream-0001",
            },
        },
        {
            "role": "assistant",
            "content": "Echo: stream this",
            "created_at": "2026-06-27T16:00:01+00:00",
            "metadata": {
                "agent_name": "fake_session_agent",
                "strategy_name": "fake_direct_strategy",
                "llm_profile": "fake_local_profile",
                "request_id": "request-session-stream-0001",
                "turn_id": "request-session-stream-0001",
                "trace_id": "trace-session-stream-0001",
                "usecase": "default_chat",
            },
        },
    ]

    assert [event.resolved_event_name for event in trace_store.events] == [
        "stream_started",
        "stream_completed",
    ]


@pytest.mark.asyncio
async def test_stream_chat_can_use_real_llm_gateway_streaming_path() -> None:
    workflow_state = FakeWorkflowStateStore()
    trace_store = FakeTraceStore()
    config = FakeConfigurationView(
        {
            "app": {"active_usecase": "default_chat"},
                "orchestration": {
                    "defaults": {
                        "strategy": "direct_agent",
                        "fallback_strategy": "direct_agent",
                    },
                    "strategies": {
                        "direct_agent": {
                            "enabled": True,
                            "type": "direct_agent",
                            "default_agent": "support_agent",
                            "allowed_usecases": ["default_chat"],
                            "llm_profile": "fake_streaming",
                        }
                    },
                    "usecases": {
                        "default_chat": {
                            "enabled": True,
                            "strategy": "direct_agent",
                            "agent": "support_agent",
                            "llm_profile": "fake_streaming",
                            "allowed_agents": ["support_agent"],
                            "policy_profile": "default",
                        }
                    },
                },
            "usecases": {
                "default_chat": {
                    "enabled": True,
                    "strategy": "direct_agent",
                    "default_agent": "support_agent",
                    "allowed_agents": ["support_agent"],
                    "policy_profile": "default",
                }
            },
            "strategies": {"direct_agent": {"enabled": True, "type": "direct"}},
            "agents": {
                "support_agent": {
                    "enabled": True,
                    "module": "app.testing.fakes.fake_agent",
                    "class_name": "FakeAgent",
                    "description": "Gateway-backed fake agent.",
                    "llm_profile": "fake_streaming",
                }
            },
            "llm": {
                "defaults": {
                    "profile": "fake_streaming",
                    "timeout_seconds": 45,
                    "stream_timeout_seconds": 60,
                    "max_retries": 0,
                    "trace_prompts": False,
                    "trace_completions": False,
                },
                "providers": {
                    "fake_provider": {
                        "type": "fake",
                        "enabled": True,
                        "timeout_seconds": 45,
                        "stream_timeout_seconds": 60,
                        "headers": {},
                        "extra": {
                            "stream_chunks": ["fake ", "response"],
                        },
                    }
                },
                "profiles": {
                    "fake_streaming": {
                        "enabled": True,
                        "provider": "fake_provider",
                        "model": "fake-stream-model",
                        "supports_streaming": True,
                        "supports_json_schema": False,
                        "supports_tool_calling": False,
                        "max_output_tokens": 256,
                        "allowed_for": {
                            "usecases": ["default_chat"],
                            "agents": ["support_agent"],
                            "strategies": ["direct_agent"],
                        },
                        "fallback_profiles": [],
                        "extra": {},
                    }
                },
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
                "trace_payloads_enabled": False,
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
    )
    policy_runtime = build_policy_runtime(config)
    llm_runtime = build_llm_runtime(config, policy_service=policy_runtime.service)
    orchestrator = DirectAgentOrchestrationRuntime.from_config(
        config=config,
        llm_gateway=llm_runtime.gateway,
        memory=FakeMemoryGateway(),
        state=workflow_state,
        trace=trace_store,
        policy_service=policy_runtime.service,
    )
    service = DefaultSessionService(
        config=config,
        settings=_build_settings(),
        workflow_state=workflow_state,
        trace_recorder=build_fake_trace_recorder(store=trace_store),
        orchestrator=orchestrator,
        clock=FakeClock(
            [
                datetime(2026, 6, 27, 17, 0, tzinfo=UTC),
                datetime(2026, 6, 27, 17, 0, 1, tzinfo=UTC),
            ]
        ),
    )

    events = [
        event
        async for event in service.stream_chat(
            request=build_session_chat_request(
                message="stream the llm gateway result",
                session_id="session_stream_llm",
                usecase="default_chat",
            ),
            context=_build_context(),
        )
    ]

    assert [event.event_type for event in events] == [
        "response.started",
        "response.delta",
        "response.delta",
        "response.metadata",
        "response.completed",
    ]
    assert events[1].data["delta"] == "fake "
    assert events[2].data["delta"] == "response"
    assert events[3].data == {
        "agent_name": "support_agent",
        "strategy_name": "direct_agent",
        "llm_profile": "fake_streaming",
        "usecase": "default_chat",
        "tool_call_count": 0,
        "memory_result_count": 0,
    }
    assert events[4].data["finish_reason"] == "completed"
    assert workflow_state.states["session_stream_llm"]["conversation"]["messages"] == [
        {
            "role": "user",
            "content": "stream the llm gateway result",
            "created_at": "2026-06-27T17:00:00+00:00",
            "metadata": {
                "usecase": "default_chat",
                "request_id": "request-session-stream-0001",
                "turn_id": "request-session-stream-0001",
                "trace_id": "trace-session-stream-0001",
            },
        },
        {
            "role": "assistant",
            "content": "fake response",
            "created_at": "2026-06-27T17:00:01+00:00",
            "metadata": {
                "agent_name": "support_agent",
                "strategy_name": "direct_agent",
                "llm_profile": "fake_streaming",
                "request_id": "request-session-stream-0001",
                "turn_id": "request-session-stream-0001",
                "trace_id": "trace-session-stream-0001",
                "usecase": "default_chat",
            },
        },
    ]


@pytest.mark.asyncio
async def test_stream_chat_persists_visualization_summary_once_on_completion() -> None:
    workflow_state = FakeWorkflowStateStore()
    trace_store = FakeTraceStore()
    config = _build_chart_config()
    orchestrator = DirectAgentOrchestrationRuntime.from_config(
        config=config,
        llm_gateway=FakeLLMGateway(response_text="unused"),
        memory=FakeMemoryGateway(),
        state=workflow_state,
        trace=trace_store,
        policy_service=FakePolicyService(),
    )
    service = DefaultSessionService(
        config=config,
        settings=_build_settings(),
        workflow_state=workflow_state,
        trace_recorder=build_fake_trace_recorder(store=trace_store),
        orchestrator=orchestrator,
        clock=FakeClock(
            [
                datetime(2026, 6, 27, 18, 0, tzinfo=UTC),
                datetime(2026, 6, 27, 18, 0, 1, tzinfo=UTC),
            ]
        ),
    )

    events = [
        event
        async for event in service.stream_chat(
            request=build_session_chat_request(
                message="Plot revenue by month as a bar chart.",
                session_id="session_stream_chart",
                usecase="default_chat",
            ),
            context=_build_context(),
        )
    ]

    assert [event.event_type for event in events] == [
        "response.started",
        "response.delta",
        "response.metadata",
        "artifact.started",
        "artifact.completed",
        "response.completed",
    ]
    assert events[3].data == {
        "artifact_id": "chart_vis_001",
        "type": "chart",
        "chart_type": "bar",
        "renderer": "echarts",
        "spec_version": "1.0",
        "data_mode": "inline",
    }
    assert events[4].data["artifact"]["artifact_id"] == "chart_vis_001"
    assert len(workflow_state.save_calls) == 1
    saved_visualization_context = workflow_state.states["session_stream_chart"]["metadata"]["visualization_context"]
    assert saved_visualization_context["summaries"][0]["artifact_id"] == "chart_vis_001"
    assert "data" not in saved_visualization_context["summaries"][0]
