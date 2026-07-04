from __future__ import annotations

from app.agents.result_builder import build_run_request_from_context
from app.config.view import ConversationContextSettings
from app.contracts.context import OrchestrationContext, RequestContext
from app.orchestration.conversation_context import build_conversation_context_window, refresh_session_summary_metadata
from app.orchestration.models import ConversationMessage, OrchestrationRuntimeContext
from app.orchestration.state_delta import WorkflowStateSnapshot
from app.testing.fakes import (
    FakeConfigurationView,
    FakeLLMGateway,
    FakeMemoryGateway,
    FakePolicyService,
    FakeToolGateway,
    FakeTraceStore,
)
from app.testing.fakes.fake_trace_recorder import build_fake_trace_recorder


def _build_context(messages: list[ConversationMessage]) -> OrchestrationContext:
    return OrchestrationContext(
        request=RequestContext(
            user_id="user_1",
            session_id="session_1",
            message="repeat",
            usecase="default_chat",
            trace_id="trace-current",
            metadata={"request_id": "request-current"},
        ),
        llm=FakeLLMGateway(response_text="unused"),
        memory=FakeMemoryGateway(),
        state=WorkflowStateSnapshot(session_id="session_1", version=3, messages=messages),
        tools=FakeToolGateway(),
        trace=FakeTraceStore(),
        policy=FakePolicyService(),
        config=FakeConfigurationView(
            {
                "orchestration": {
                    "defaults": {
                        "conversation_context": {
                            "enabled": True,
                            "mode": "window",
                            "max_messages": 12,
                            "max_chars": 12000,
                            "include_assistant_messages": True,
                            "summary_threshold_messages": 24,
                            "summary_max_chars": 2000,
                        }
                    }
                }
            }
        ),
        runtime_metadata={"strategy_name": "direct_agent"},
        runtime=OrchestrationRuntimeContext(
            request_id="request-current",
            trace_id="trace-current",
            session_id="session_1",
            user_id="user_1",
        ),
        observability=build_fake_trace_recorder(),
    )


def test_conversation_context_filters_current_turn_by_request_id_not_message_text() -> None:
    context = _build_context(
        [
            ConversationMessage(
                role="user",
                content="repeat",
                metadata={"request_id": "request-old", "turn_id": "request-old", "trace_id": "trace-old"},
            ),
            ConversationMessage(
                role="assistant",
                content="You said repeat earlier.",
                metadata={"request_id": "request-old", "turn_id": "request-old", "trace_id": "trace-old"},
            ),
            ConversationMessage(
                role="user",
                content="repeat",
                metadata={
                    "request_id": "request-current",
                    "turn_id": "request-current",
                    "trace_id": "trace-current",
                },
            ),
        ]
    )

    window = build_conversation_context_window(context)

    assert [message.metadata.get("request_id") for message in window.messages] == [
        "request-old",
        "request-old",
    ]
    assert window.current_turn_deduped is True
    assert window.truncated is False

    request = build_run_request_from_context(context, agent_name="support_agent")

    assert [message.metadata.get("request_id") for message in request.conversation_history] == [
        "request-old",
        "request-old",
    ]
    assert request.metadata["conversation_history_turn_count"] == 2
    assert request.metadata["current_turn_deduped"] is True


def test_conversation_context_enforces_message_and_character_limits() -> None:
    context = _build_context(
        [
            ConversationMessage(role="user", content="alpha", metadata={"request_id": "request-1"}),
            ConversationMessage(role="assistant", content="bravo", metadata={"request_id": "request-1"}),
            ConversationMessage(role="user", content="charlie delta", metadata={"request_id": "request-2"}),
        ]
    )
    context.config = FakeConfigurationView(
        {
            "orchestration": {
                "defaults": {
                    "conversation_context": {
                        "enabled": True,
                        "mode": "window",
                        "max_messages": 2,
                        "max_chars": 6,
                        "include_assistant_messages": True,
                        "summary_threshold_messages": 12,
                        "summary_max_chars": 1200,
                    }
                }
            }
        }
    )
    context.settings = None

    window = build_conversation_context_window(context)

    assert [message.role for message in window.messages] == ["user"]
    assert window.messages[0].content == "cha..."
    assert window.truncated is True


def test_conversation_message_projects_turn_identity_from_metadata() -> None:
    message = ConversationMessage.from_mapping(
        {
            "role": "assistant",
            "content": "prior answer",
            "metadata": {
                "request_id": "request-123",
                "turn_id": "turn-123",
                "trace_id": "trace-123",
            },
        }
    )

    assert message.request_id == "request-123"
    assert message.turn_id == "turn-123"
    assert message.trace_id == "trace-123"


def test_conversation_context_uses_persisted_session_summary_when_long_history_is_compacted() -> None:
    context = _build_context(
        [
            ConversationMessage(role="user", content="I am Bob", metadata={"request_id": "request-1"}),
            ConversationMessage(role="assistant", content="Nice to meet you, Bob.", metadata={"request_id": "request-1"}),
            ConversationMessage(role="user", content="Turn 2", metadata={"request_id": "request-2"}),
            ConversationMessage(role="assistant", content="Ack 2", metadata={"request_id": "request-2"}),
            ConversationMessage(role="user", content="Turn 3", metadata={"request_id": "request-3"}),
            ConversationMessage(role="assistant", content="Ack 3", metadata={"request_id": "request-3"}),
        ]
    )
    context.config = FakeConfigurationView(
        {
            "orchestration": {
                "defaults": {
                    "conversation_context": {
                        "enabled": True,
                        "mode": "window",
                        "max_messages": 2,
                        "max_chars": 100,
                        "include_assistant_messages": True,
                        "summary_threshold_messages": 4,
                        "summary_max_chars": 120,
                    }
                }
            }
        }
    )
    context.settings = None

    state = {
        "session_id": "session_1",
        "conversation": {
            "messages": [message.as_dict() for message in context.state.messages],
        },
        "workflow": {"current_step": "answered", "pending_actions": [], "scratch": {}},
        "metadata": {},
        "last_result": {},
    }
    refresh_session_summary_metadata(
        state,
        settings=ConversationContextSettings(
            enabled=True,
            mode="window",
            max_messages=2,
            max_chars=100,
            include_assistant_messages=True,
            summary_threshold_messages=4,
            summary_max_chars=120,
        ),
        updated_at="2026-07-01T00:00:00+00:00",
    )
    context.state = WorkflowStateSnapshot(session_id="session_1", version=4, messages=context.state.messages, metadata=state["metadata"])

    window = build_conversation_context_window(context)

    assert [message.content for message in window.messages] == ["Turn 3", "Ack 3"]
    assert window.session_summary_used is True
    assert window.session_summary is not None
    assert "I am Bob" in window.session_summary

    request = build_run_request_from_context(context, agent_name="support_agent")

    assert request.session_summary is not None
    assert "I am Bob" in request.session_summary
    assert request.metadata["session_summary_used"] is True