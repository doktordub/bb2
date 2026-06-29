from __future__ import annotations

from app.orchestration.result_builder import build_orchestration_result
from app.orchestration.trace_helpers import build_completed_trace_payload


def test_completed_trace_payload_whitelists_safe_summary_fields_only() -> None:
    result = build_orchestration_result(
        answer="safe answer",
        session_id="session_1",
        trace_id="trace_1",
        usecase="support_chat",
        strategy_name="fallback_answer",
        finish_reason="fallback",
        metadata={
            "fallback_used": True,
            "raw_prompt": "system prompt",
            "provider_chunk": {"delta": "hidden"},
            "stack_trace": "hidden",
        },
    )

    assert build_completed_trace_payload(result) == {
        "finish_reason": "fallback",
        "tool_call_count": 0,
        "memory_update_count": 0,
        "fallback_used": True,
    }