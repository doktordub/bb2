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
from app.testing.fakes.fake_memory import FakeMemoryGateway
from app.testing.fakes.fake_orchestration_runtime import FakeOrchestrationRuntime
from app.testing.fakes.fake_session_id_provider import FakeSessionIdProvider
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
        trace_id="trace-session-handle-0001",
        request_id="request-session-handle-0001",
        user_id="local_user",
        user_id_hash="user_hash_123",
        client_host="127.0.0.1",
        user_agent="pytest",
        path="/chat",
        method="POST",
        metadata={"auth_mode": "local"},
        headers_safe={"x-trace-id": "trace-session-handle-0001"},
    )


@pytest.mark.asyncio
async def test_default_session_service_loads_runs_and_saves_once() -> None:
    workflow_state = FakeWorkflowStateStore()
    trace_store = FakeTraceStore()
    orchestrator = FakeOrchestrationRuntime()
    clock = FakeClock(
        [
            datetime(2026, 6, 27, 12, 0, tzinfo=UTC),
            datetime(2026, 6, 27, 12, 0, 1, tzinfo=UTC),
        ]
    )
    service = DefaultSessionService(
        config=FakeConfigurationView(
            {
                "usecases": {
                    "default_chat": {"enabled": True},
                    "support_chat": {"enabled": True},
                }
            }
        ),
        settings=_build_settings(),
        workflow_state=workflow_state,
        trace_recorder=build_fake_trace_recorder(store=trace_store),
        orchestrator=orchestrator,
        id_provider=FakeSessionIdProvider(ids=["session_generated"]),
        clock=clock,
    )

    result = await service.handle_chat(
        request=build_session_chat_request(
            message="persist this",
            session_id="session_abc",
            usecase="support_chat",
            metadata={"client": "web"},
        ),
        context=_build_context(),
    )

    assert result.answer == "Echo: persist this"
    assert result.session_id == "session_abc"
    assert result.trace_id == "trace-session-handle-0001"
    assert result.metadata == {
        "usecase": "support_chat",
        "message_count": 2,
        "message_count_before": 0,
    }

    assert workflow_state.load_requests == ["session_abc"]
    assert len(workflow_state.save_calls) == 1
    assert workflow_state.save_calls[0].expected_version is None
    assert len(orchestrator.run_calls) == 1
    assert orchestrator.run_calls[0].request.session_id == "session_abc"
    assert orchestrator.run_calls[0].request.usecase == "support_chat"
    assert orchestrator.run_calls[0].request.metadata["client"] == "web"
    assert orchestrator.run_calls[0].state["conversation"]["messages"] == [
        {
            "role": "user",
            "content": "persist this",
            "created_at": "2026-06-27T12:00:00+00:00",
            "metadata": {
                "usecase": "support_chat",
                "request_id": "request-session-handle-0001",
                "turn_id": "request-session-handle-0001",
                "trace_id": "trace-session-handle-0001",
            },
        },
    ]

    saved_state = workflow_state.states["session_abc"]
    assert saved_state["conversation"]["messages"] == [
        {
            "role": "user",
            "content": "persist this",
            "created_at": "2026-06-27T12:00:00+00:00",
            "metadata": {
                "usecase": "support_chat",
                "request_id": "request-session-handle-0001",
                "turn_id": "request-session-handle-0001",
                "trace_id": "trace-session-handle-0001",
            },
        },
        {
            "role": "assistant",
            "content": "Echo: persist this",
            "created_at": "2026-06-27T12:00:01+00:00",
            "metadata": {
                "agent_name": "fake_session_agent",
                "strategy_name": "fake_direct_strategy",
                "llm_profile": "fake_local_profile",
                "request_id": "request-session-handle-0001",
                "turn_id": "request-session-handle-0001",
                "trace_id": "trace-session-handle-0001",
                "usecase": "support_chat",
            },
        },
    ]
    assert saved_state["workflow"]["current_step"] == "answered"
    assert saved_state["metadata"]["updated_at"] == "2026-06-27T12:00:01+00:00"


@pytest.mark.asyncio
async def test_default_session_service_uses_loaded_version_for_resumed_session() -> None:
    workflow_state = FakeWorkflowStateStore()
    workflow_state.states["session_resume_1"] = {
        "conversation": {
            "messages": [
                {"role": "user", "content": "first"},
                {"role": "assistant", "content": "Echo: first"},
            ]
        },
        "workflow": {"current_step": "answered"},
        "metadata": {"loaded_empty": False},
    }
    workflow_state.versions["session_resume_1"] = 4

    service = DefaultSessionService(
        config=FakeConfigurationView({"usecases": {"default_chat": {"enabled": True}}}),
        settings=_build_settings(),
        workflow_state=workflow_state,
        trace_recorder=build_fake_trace_recorder(store=FakeTraceStore()),
        orchestrator=FakeOrchestrationRuntime(),
        clock=FakeClock(
            [
                datetime(2026, 6, 27, 13, 0, tzinfo=UTC),
                datetime(2026, 6, 27, 13, 0, 1, tzinfo=UTC),
            ]
        ),
    )

    result = await service.handle_chat(
        request=build_session_chat_request(
            message="second",
            session_id="session_resume_1",
            usecase=None,
        ),
        context=_build_context(),
    )

    assert result.metadata == {
        "usecase": "default_chat",
        "message_count": 4,
        "message_count_before": 2,
    }
    assert workflow_state.save_calls[0].expected_version == 4
    assert workflow_state.versions["session_resume_1"] == 5


@pytest.mark.asyncio
async def test_default_session_service_can_run_through_real_llm_gateway_path() -> None:
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
                            "llm_profile": "fake_basic",
                        }
                    },
                    "usecases": {
                        "default_chat": {
                            "enabled": True,
                            "strategy": "direct_agent",
                            "agent": "support_agent",
                            "llm_profile": "fake_basic",
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
                }
            },
            "llm": {
                "defaults": {
                    "profile": "fake_basic",
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
                        "extra": {},
                    }
                },
                "profiles": {
                    "fake_basic": {
                        "enabled": True,
                        "provider": "fake_provider",
                        "model": "fake-basic-model",
                        "supports_streaming": False,
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
        id_provider=FakeSessionIdProvider(ids=["session_llm_gateway"]),
        clock=FakeClock(
            [
                datetime(2026, 6, 27, 14, 0, tzinfo=UTC),
                datetime(2026, 6, 27, 14, 0, 1, tzinfo=UTC),
            ]
        ),
    )

    result = await service.handle_chat(
        request=build_session_chat_request(
            message="route this through llm gateway",
            session_id="session_llm_gateway",
            usecase="default_chat",
        ),
        context=_build_context(),
    )

    assert result.answer == "fake response"
    assert result.agent_name == "support_agent"
    assert result.strategy_name == "direct_agent"
    assert result.llm_profile == "fake_basic"
    assert workflow_state.states["session_llm_gateway"]["conversation"]["messages"] == [
        {
            "role": "user",
            "content": "route this through llm gateway",
            "created_at": "2026-06-27T14:00:00+00:00",
            "metadata": {
                "usecase": "default_chat",
                "request_id": "request-session-handle-0001",
                "turn_id": "request-session-handle-0001",
                "trace_id": "trace-session-handle-0001",
            },
        },
        {
            "role": "assistant",
            "content": "fake response",
            "created_at": "2026-06-27T14:00:01+00:00",
            "metadata": {
                "agent_name": "support_agent",
                "strategy_name": "direct_agent",
                "llm_profile": "fake_basic",
                "request_id": "request-session-handle-0001",
                "turn_id": "request-session-handle-0001",
                "trace_id": "trace-session-handle-0001",
                "usecase": "default_chat",
            },
        },
    ]
