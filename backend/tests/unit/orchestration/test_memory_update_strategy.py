from __future__ import annotations

import pytest

from app.config.view import get_orchestration_settings
from app.contracts.context import OrchestrationContext, RequestContext
from app.orchestration.message_catalog import clear_message_catalog_cache
from app.orchestration.limits import OrchestrationLimitTracker
from app.orchestration.strategies.memory_update import MemoryUpdateStrategy
from app.testing.fakes import (
    FakeAgent,
    FakeConfigurationView,
    FakeLLMGateway,
    FakeMemoryGateway,
    FakePolicyService,
    FakeToolGateway,
    FakeTraceStore,
)


def build_config(*, max_memory_writes: int = 1, candidate_limit: int = 3) -> FakeConfigurationView:
    return FakeConfigurationView(
        {
            "orchestration": {
                "enabled": True,
                "defaults": {
                    "strategy": "memory_update",
                    "fallback_strategy": "direct_agent",
                    "max_steps": 8,
                    "max_tool_calls": 1,
                    "max_memory_searches": 1,
                    "max_memory_writes": max_memory_writes,
                    "max_llm_calls": 1,
                    "max_turn_duration_seconds": 120,
                    "max_stream_duration_seconds": 300,
                },
                "strategies": {
                    "memory_update": {
                        "enabled": True,
                        "type": "memory_update",
                        "default_agent": "support_agent",
                        "allowed_usecases": ["memory_capture"],
                        "memory_enabled": True,
                        "memory_write_enabled": True,
                        "max_memory_writes": max_memory_writes,
                        "candidate_limit": candidate_limit,
                        "require_policy_approval": True,
                    }
                },
                "usecases": {
                    "memory_capture": {
                        "enabled": True,
                        "strategy": "memory_update",
                        "agent": "support_agent",
                        "allowed_agents": ["support_agent"],
                        "policy_profile": "default",
                        "memory": {"enabled": True},
                    }
                },
            },
            "policy": {"profiles": {"default": {"allow_memory_writes": True}}},
            "memory": {
                "enabled": True,
                "lifecycle": {"allow_writes": True},
            },
        }
    )


def build_context(
    config: FakeConfigurationView,
    *,
    message: str,
    metadata: dict[str, object] | None = None,
    memory: FakeMemoryGateway | None = None,
    policy: FakePolicyService | None = None,
) -> OrchestrationContext:
    settings = get_orchestration_settings(config)
    strategy_settings = settings.strategies["memory_update"]
    limits = OrchestrationLimitTracker.from_settings(settings, strategy_settings)
    limits.mark_turn_started()
    return OrchestrationContext(
        request=RequestContext(
            user_id="user_1",
            session_id="session_1",
            message=message,
            usecase="memory_capture",
            trace_id="trace_1",
            metadata=dict(metadata or {}),
        ),
        llm=FakeLLMGateway(response_text="unused"),
        memory=memory or FakeMemoryGateway(),
        state=None,
        tools=FakeToolGateway(),
        trace=FakeTraceStore(),
        policy=policy or FakePolicyService(),
        config=config,
        runtime_metadata={"agent_name": "support_agent", "strategy_name": "memory_update"},
        settings=settings,
        strategy_settings=strategy_settings,
        limits=limits,
    )


@pytest.mark.asyncio
async def test_memory_update_strategy_writes_explicit_remember_request_through_memory_gateway() -> None:
    config = build_config()
    memory = FakeMemoryGateway()
    context = build_context(
        config,
        message="Remember that the backend project root is backend/.",
        memory=memory,
    )

    result = await MemoryUpdateStrategy().run(
        context=context,
        agents=[FakeAgent(name="support_agent")],
    )

    assert result.answer == "I stored 1 memory update for future turns."
    assert result.memory_updates[0]["status"] == "ok"
    assert result.memory_updates[0]["metadata"]["memory_id_present"] is True
    assert "affected_ids" not in result.memory_updates[0].get("metadata", {})
    assert memory.writes[0].text == "the backend project root is backend/."
    assert memory.writes[0].scope.user_id == "user_1"
    assert result.metadata["memory_write_count"] == 1
    assert [step["step_type"] for step in result.metadata["steps"]] == [
        "memory_candidate_extraction",
        "memory_write",
    ]


@pytest.mark.asyncio
async def test_memory_update_strategy_respects_write_limit_for_explicit_candidates() -> None:
    config = build_config(max_memory_writes=1, candidate_limit=3)
    memory = FakeMemoryGateway()
    context = build_context(
        config,
        message="Store these facts",
        metadata={
            "memory_candidates": [
                {"text": "User prefers concise answers.", "memory_type": "preference", "scope": "user"},
                {"text": "Project codename is bb2.", "memory_type": "project_fact", "scope": "project"},
            ]
        },
        memory=memory,
    )

    result = await MemoryUpdateStrategy().run(context=context, agents=[])

    assert result.answer == "I stored 1 memory update for future turns."
    assert len(memory.writes) == 1
    assert result.metadata["candidate_count"] == 2
    assert result.metadata["memory_write_count"] == 1
    assert result.metadata["skipped_candidate_count"] == 1


@pytest.mark.asyncio
async def test_memory_update_strategy_returns_no_candidate_message_when_no_durable_memory_is_found() -> None:
    config = build_config()
    context = build_context(
        config,
        message="Thanks for the update.",
        metadata={"memory_candidates": []},
    )

    result = await MemoryUpdateStrategy().run(context=context, agents=[])

    assert result.answer == "I did not find any durable memory to store from that request."
    assert result.metadata["candidate_count"] == 0
    assert result.metadata["memory_write_count"] == 0


@pytest.mark.asyncio
async def test_memory_update_strategy_uses_message_catalog_for_safe_messages(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "messages.yaml"
    path.write_text(
        "messages:\n"
        "  fallback_answer:\n"
        "    default_message: Catalog fallback answer.\n"
        "  memory_update:\n"
        "    no_candidate_answer: Catalog says nothing to store.\n"
        "    approval_required_answer: Catalog says approval is required.\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("APP_MESSAGES_CONFIG_PATH", str(path))
    clear_message_catalog_cache()

    config = build_config()
    no_candidate_context = build_context(
        config,
        message="Thanks for the update.",
        metadata={"memory_candidates": []},
    )

    no_candidate_result = await MemoryUpdateStrategy().run(
        context=no_candidate_context,
        agents=[],
    )

    assert no_candidate_result.answer == "Catalog says nothing to store."

    approval_context = build_context(
        config,
        message="Remember that phase 5 is active.",
        metadata={
            "memory_candidates": [
                {
                    "text": "phase 5 is active",
                    "memory_type": "project_fact",
                    "scope": "project",
                }
            ]
        },
        policy=FakePolicyService(approval_required_actions={"memory.upsert"}),
    )

    approval_result = await MemoryUpdateStrategy().run(context=approval_context, agents=[])

    assert approval_result.answer == "Catalog says approval is required."
    assert approval_result.memory_updates[0]["safe_message"] == "Catalog says approval is required."
