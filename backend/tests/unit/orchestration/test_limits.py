from __future__ import annotations

import pytest

from app.config.view import (
    OrchestrationDefaultsSettings,
    OrchestrationSettings,
    OrchestrationStrategyMemorySettings,
    OrchestrationStrategyToolSettings,
    StrategySettings,
)
from app.orchestration.errors import OrchestrationLimitExceededError, OrchestrationTimeoutError
from app.orchestration.limits import OrchestrationLimitTracker


def build_tracker() -> OrchestrationLimitTracker:
    settings = OrchestrationSettings(
        enabled=True,
        defaults=OrchestrationDefaultsSettings(
            strategy="direct_agent",
            fallback_strategy="direct_agent",
            max_steps=2,
            max_tool_calls=1,
            max_memory_searches=1,
            max_memory_writes=1,
            max_llm_calls=1,
            max_tool_loop_iterations=1,
            max_context_bytes=2048,
            max_turn_duration_seconds=1,
            max_stream_duration_seconds=1,
            emit_step_events=True,
            emit_tool_events=True,
            emit_memory_events=True,
            stream_strategy_events=True,
            expose_strategy_metadata=True,
            expose_chain_of_thought=False,
            save_runtime_snapshots=False,
        ),
        strategies={},
        usecases={},
    )
    strategy = StrategySettings(
        name="direct_agent",
        enabled=True,
        type="direct_agent",
        description=None,
        default_agent="support_agent",
        allowed_usecases=("default_chat",),
        llm_profile=None,
        planner_llm_profile=None,
        executor_llm_profile=None,
        memory_enabled=False,
        memory_write_enabled=False,
        tools_enabled=False,
        max_steps=None,
        max_tool_calls=None,
        max_memory_searches=None,
        max_memory_writes=None,
        max_llm_calls=None,
        max_tool_loop_iterations=None,
        max_context_bytes=None,
        max_plan_steps=None,
        max_execute_steps=None,
        max_candidate_agents=None,
        candidate_limit=None,
        candidate_strategies=(),
        fallback_strategy=None,
        require_policy_approval=False,
        stream_llm_deltas=True,
        stream_tool_events=True,
        stream_strategy_events=None,
        expose_strategy_metadata=True,
        message=None,
        memory=OrchestrationStrategyMemorySettings(
            default_limit=0,
            include_document_chunks=False,
            include_user_memory=False,
            min_score=None,
            max_context_items=None,
            max_context_bytes=None,
        ),
        tools=OrchestrationStrategyToolSettings(
            max_calls=None,
            max_tool_loop_iterations=None,
            allowed_safety_levels=(),
            allowed_tools=(),
            stream_tool_events=True,
        ),
        metadata={},
    )
    return OrchestrationLimitTracker.from_settings(settings, strategy)


def test_limit_tracker_consumes_counts_and_raises_when_exceeded() -> None:
    tracker = build_tracker()
    tracker.mark_turn_started()

    tracker.consume_step()
    tracker.consume_step()
    tracker.consume_tool_call()
    tracker.consume_memory_search()
    tracker.consume_memory_write()
    tracker.consume_llm_call()

    assert tracker.steps_used == 2
    assert tracker.tool_calls_used == 1
    assert tracker.memory_searches_used == 1
    assert tracker.memory_writes_used == 1
    assert tracker.llm_calls_used == 1

    with pytest.raises(OrchestrationLimitExceededError):
        tracker.consume_step()
    with pytest.raises(OrchestrationLimitExceededError):
        tracker.consume_tool_call()
    with pytest.raises(OrchestrationLimitExceededError):
        tracker.consume_memory_search()
    with pytest.raises(OrchestrationLimitExceededError):
        tracker.consume_memory_write()
    with pytest.raises(OrchestrationLimitExceededError):
        tracker.consume_llm_call()


def test_limit_tracker_enforces_turn_and_stream_timeouts(monkeypatch: pytest.MonkeyPatch) -> None:
    timestamps = iter([0.0, 2.0, 0.0, 2.0])
    monkeypatch.setattr("app.orchestration.limits.perf_counter", lambda: next(timestamps))
    tracker = build_tracker()

    tracker.mark_turn_started()
    with pytest.raises(OrchestrationTimeoutError):
        tracker.check_turn_duration()

    tracker.mark_stream_started()
    with pytest.raises(OrchestrationTimeoutError):
        tracker.mark_stream_event()