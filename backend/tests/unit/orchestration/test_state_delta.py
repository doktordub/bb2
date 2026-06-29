from __future__ import annotations

from app.orchestration.models import ConversationMessage, OrchestrationStepSummary
from app.orchestration.state_delta import (
    WorkflowStateDelta,
    apply_workflow_state_delta,
    workflow_state_snapshot_from_document,
)


def test_workflow_state_snapshot_projects_safe_state_fields() -> None:
    snapshot = workflow_state_snapshot_from_document(
        session_id="session_123",
        state={
            "version": 7,
            "conversation": {
                "messages": [
                    {"role": "user", "content": "hello", "metadata": {"traceback": "skip", "safe": 1}},
                    {"role": "assistant", "content": "world"},
                ]
            },
            "workflow": {
                "step_summaries": [
                    {"step_id": "step_1", "step_type": "llm", "status": "completed"}
                ],
                "pending_actions": [
                    {"kind": "approval", "secret": "hidden", "safe": True}
                ],
            },
            "last_result": {"agent_name": "support_agent"},
            "metadata": {"usecase": "default_chat", "token": "hidden", "locale": "en-US"},
        },
    )

    assert snapshot.version == 7
    assert [message.content for message in snapshot.messages] == ["hello", "world"]
    assert snapshot.messages[0].metadata == {"safe": 1}
    assert snapshot.active_usecase == "default_chat"
    assert snapshot.active_agent == "support_agent"
    assert snapshot.step_summaries[0].step_id == "step_1"
    assert snapshot.pending_approvals == [{"kind": "approval", "safe": True}]
    assert snapshot.metadata == {"usecase": "default_chat", "locale": "en-US"}


def test_apply_workflow_state_delta_returns_updated_copy() -> None:
    original = {
        "version": 1,
        "conversation": {"messages": [{"role": "user", "content": "hello"}]},
        "workflow": {"current_step": None, "pending_actions": []},
        "last_result": {"agent_name": None},
        "metadata": {"usecase": "default_chat"},
    }
    delta = WorkflowStateDelta(
        append_messages=[ConversationMessage(role="assistant", content="world")],
        set_active_usecase="support_chat",
        set_active_agent="support_agent",
        append_step_summaries=[
            OrchestrationStepSummary(step_id="step_2", step_type="tool", status="completed")
        ],
        append_pending_approvals=[{"kind": "approval", "safe": True, "secret": "hidden"}],
        metadata_patch={"trace_id": "trace_123", "api_key": "hidden"},
    )

    updated = apply_workflow_state_delta(original, delta)

    assert original["conversation"]["messages"] == [{"role": "user", "content": "hello"}]
    assert updated["conversation"]["messages"][-1] == {"role": "assistant", "content": "world"}
    assert updated["metadata"]["usecase"] == "support_chat"
    assert updated["last_result"]["agent_name"] == "support_agent"
    assert updated["workflow"]["step_summaries"][0]["step_id"] == "step_2"
    assert updated["workflow"]["pending_actions"] == [{"kind": "approval", "safe": True}]
    assert updated["metadata"]["trace_id"] == "trace_123"
    assert "api_key" not in updated["metadata"]