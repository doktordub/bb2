"""Helpers for session continuity and workflow-state shaping."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from app.config.view import ConversationContextSettings
from app.contracts.context import RequestContext
from app.contracts.state import (
    DEFAULT_WORKFLOW_STATE_VERSION,
    WorkflowStateDocument,
    WorkflowStateRecord,
    default_workflow_state,
)
from app.orchestration.conversation_context import refresh_session_summary_metadata
from app.orchestration.models import ConversationMessage, OrchestrationResult
from app.orchestration.state_delta import WorkflowStateDelta, apply_workflow_state_delta
from app.session.mapping import HistoryReplayPayload, build_history_replay_payload
from app.visualization.settings import VisualizationHistoryReplaySettings


@dataclass(frozen=True, slots=True)
class PreparedSessionState:
    """Prepared workflow state ready for the orchestration runtime."""

    state: WorkflowStateDocument
    loaded_empty: bool
    message_count_before: int


class SessionClock(Protocol):
    """Clock abstraction used to keep session-state timestamps testable."""

    def now(self) -> datetime:
        ...


class SystemClock:
    """Production clock used by the session service."""

    def now(self) -> datetime:
        return datetime.now(UTC)


def prepare_state_for_chat(
    *,
    record: WorkflowStateRecord,
    session_id: str,
    request_context: RequestContext,
    usecase: str,
    created_at: datetime,
) -> PreparedSessionState:
    """Normalize loaded state and append the incoming user message."""

    normalized_state = normalize_session_state(record.state, session_id=session_id)
    metadata = metadata_dict(normalized_state)
    loaded_empty = record.loaded_empty or bool(metadata.get("loaded_empty", False))
    messages = conversation_messages(normalized_state)
    message_count_before = len(messages)
    messages.append(
        {
            "role": "user",
            "content": request_context.message,
            "created_at": created_at.isoformat(),
            "metadata": _user_message_metadata(request_context=request_context, usecase=usecase),
        }
    )
    normalized_state["workflow"]["current_step"] = "responding"
    metadata.setdefault("created_at", created_at.isoformat())
    metadata["usecase"] = usecase
    metadata["loaded_empty"] = False
    return PreparedSessionState(
        state=normalized_state,
        loaded_empty=loaded_empty,
        message_count_before=message_count_before,
    )


def apply_orchestration_result(
    state: WorkflowStateDocument,
    *,
    result: OrchestrationResult,
    conversation_context_settings: ConversationContextSettings,
    history_replay_settings: VisualizationHistoryReplaySettings,
    request_context: RequestContext,
    trace_id: str,
    request_id: str,
    user_id_hash: str | None,
    client_host: str | None,
    user_agent: str | None,
    completed_at: datetime,
    artifact_retrieval_endpoint: str | None = None,
) -> WorkflowStateDocument:
    """Apply a completed orchestration result to session workflow state."""

    state_delta = result.state_delta or _fallback_state_delta(result)
    updated_state = apply_workflow_state_delta(state, state_delta)
    history_replay = build_history_replay_payload(
        artifacts=[item.model_dump(mode="python") for item in result.artifacts],
        artifact_retrieval_endpoint=artifact_retrieval_endpoint,
        history_replay_settings=history_replay_settings,
    )
    _annotate_appended_messages(
        updated_state,
        appended_count=len(state_delta.append_messages),
        usecase=result.usecase,
        transport=_normalize_transport_label(request_context.metadata.get("transport")),
        trace_id=trace_id,
        request_id=request_id,
        created_at=completed_at,
        history_replay=history_replay,
    )
    updated_state["workflow"]["current_step"] = "answered"
    updated_state["last_result"] = {
        "agent_name": result.agent_name,
        "strategy_name": result.strategy_name,
        "llm_profile": result.llm_profile,
    }

    metadata = metadata_dict(updated_state)
    metadata.update(
        {
            "trace_id": trace_id,
            "request_id": request_id,
            "usecase": result.usecase,
            "updated_at": completed_at.isoformat(),
            "loaded_empty": False,
        }
    )
    if user_id_hash is not None:
        metadata["user_id_hash"] = user_id_hash
    if client_host is not None:
        metadata["last_client_host"] = client_host
    if user_agent is not None:
        metadata["last_user_agent"] = user_agent
    _update_task_execution_state_metadata(
        metadata=metadata,
        result=result,
        request_id=request_id,
        trace_id=trace_id,
        updated_at=completed_at.isoformat(),
    )
    refresh_session_summary_metadata(
        updated_state,
        settings=conversation_context_settings,
        updated_at=completed_at.isoformat(),
    )
    return updated_state


def mark_stream_interrupted(
    state: WorkflowStateDocument,
    *,
    conversation_context_settings: ConversationContextSettings,
    interrupted_at: datetime,
) -> WorkflowStateDocument:
    """Record a cancelled stream boundary without exposing raw content elsewhere."""

    metadata = metadata_dict(state)
    metadata["stream_status"] = "cancelled"
    metadata["updated_at"] = interrupted_at.isoformat()
    state["workflow"]["current_step"] = "cancelled"
    refresh_session_summary_metadata(
        state,
        settings=conversation_context_settings,
        updated_at=interrupted_at.isoformat(),
    )
    return state


def mark_stream_failed(
    state: WorkflowStateDocument,
    *,
    conversation_context_settings: ConversationContextSettings,
    failed_at: datetime,
) -> WorkflowStateDocument:
    """Record a failed stream boundary without exposing raw content elsewhere."""

    metadata = metadata_dict(state)
    metadata["stream_status"] = "failed"
    metadata["updated_at"] = failed_at.isoformat()
    state["workflow"]["current_step"] = "failed"
    refresh_session_summary_metadata(
        state,
        settings=conversation_context_settings,
        updated_at=failed_at.isoformat(),
    )
    return state


def normalize_session_state(
    state: WorkflowStateDocument,
    *,
    session_id: str,
) -> WorkflowStateDocument:
    """Normalize loaded state so session code can safely shape it."""

    normalized = deepcopy(state) if isinstance(state, dict) else default_workflow_state(session_id)
    normalized.setdefault("version", DEFAULT_WORKFLOW_STATE_VERSION)
    normalized["session_id"] = session_id

    conversation = normalized.get("conversation")
    if not isinstance(conversation, dict):
        conversation = {}
        normalized["conversation"] = conversation
    messages = conversation.get("messages")
    if not isinstance(messages, list):
        conversation["messages"] = []

    workflow = normalized.get("workflow")
    if not isinstance(workflow, dict):
        workflow = {}
        normalized["workflow"] = workflow
    workflow.setdefault("current_step", None)
    workflow.setdefault("checkpoint", None)
    workflow.setdefault("scratch", {})
    workflow.setdefault("pending_actions", [])

    last_result = normalized.get("last_result")
    if not isinstance(last_result, dict):
        last_result = {}
        normalized["last_result"] = last_result
    last_result.setdefault("agent_name", None)
    last_result.setdefault("strategy_name", None)
    last_result.setdefault("llm_profile", None)

    metadata = normalized.get("metadata")
    if not isinstance(metadata, dict):
        normalized["metadata"] = {}

    return normalized


def conversation_messages(state: WorkflowStateDocument) -> list[dict[str, Any]]:
    """Return the mutable conversation message list for one workflow-state document."""

    conversation = state["conversation"]
    messages = conversation.get("messages")
    if not isinstance(messages, list):
        messages = []
        conversation["messages"] = messages
    return messages


def metadata_dict(state: WorkflowStateDocument) -> dict[str, Any]:
    """Return the mutable metadata mapping for one workflow-state document."""

    metadata = state.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
        state["metadata"] = metadata
    return metadata


def state_message_count(state: WorkflowStateDocument) -> int:
    """Return the visible conversation message count for a workflow-state document."""

    return len(conversation_messages(state))


def _user_message_metadata(
    *,
    request_context: RequestContext,
    usecase: str,
) -> dict[str, str]:
    metadata = {"usecase": usecase}
    request_id = _normalize_message_identifier(request_context.metadata.get("request_id"))
    if request_id is not None:
        metadata["request_id"] = request_id
        metadata["turn_id"] = request_id
    trace_id = _normalize_message_identifier(request_context.trace_id)
    if trace_id is not None:
        metadata["trace_id"] = trace_id
    transport = _normalize_transport_label(request_context.metadata.get("transport"))
    if transport is not None:
        metadata["transport"] = transport
    return metadata


def _annotate_appended_messages(
    state: WorkflowStateDocument,
    *,
    appended_count: int,
    usecase: str,
    transport: str | None,
    trace_id: str,
    request_id: str,
    created_at: datetime,
    history_replay: HistoryReplayPayload | None = None,
) -> None:
    if appended_count <= 0:
        return

    messages = conversation_messages(state)
    for raw_message in messages[-appended_count:]:
        if not isinstance(raw_message, dict):
            continue

        created_value = raw_message.get("created_at")
        if not isinstance(created_value, str) or not created_value.strip():
            raw_message["created_at"] = created_at.isoformat()

        metadata = raw_message.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
            raw_message["metadata"] = metadata

        metadata.setdefault("usecase", usecase)
        if transport is not None:
            metadata.setdefault("transport", transport)
        metadata.setdefault("request_id", request_id)
        metadata.setdefault("turn_id", request_id)
        metadata.setdefault("trace_id", trace_id)
        if raw_message.get("role") == "assistant":
            if history_replay is not None:
                if history_replay.artifacts and not isinstance(raw_message.get("artifacts"), list):
                    raw_message["artifacts"] = deepcopy(history_replay.artifacts)
                for key, value in history_replay.metadata.items():
                    metadata.setdefault(key, deepcopy(value))
            metadata.setdefault("trace_id", trace_id)


def _normalize_transport_label(value: object) -> str | None:
    if not isinstance(value, str):
        return None

    normalized = value.strip()
    if not normalized:
        return None

    token = normalized.casefold().replace("-", "_").replace("/", "_").replace(" ", "_")
    if token in {"request_response", "non_streaming"}:
        return "request/response"
    if token == "streaming":
        return "streaming"
    return normalized


def _normalize_message_identifier(value: object) -> str | None:
    if not isinstance(value, str):
        return None

    normalized = value.strip()
    return normalized or None


def _fallback_state_delta(result: OrchestrationResult) -> WorkflowStateDelta:
    return WorkflowStateDelta(
        append_messages=[
            ConversationMessage(
                role="assistant",
                content=result.answer,
                metadata={
                    "agent_name": result.agent_name,
                    "strategy_name": result.strategy_name,
                    "llm_profile": result.llm_profile,
                },
            )
        ],
        set_active_usecase=result.usecase,
        set_active_agent=result.agent_name,
        metadata_patch={
            key: value
            for key, value in {
                "last_strategy": result.strategy_name,
                "last_agent": result.agent_name,
                "last_llm_profile": result.llm_profile,
            }.items()
            if value is not None
        },
    )


def _update_task_execution_state_metadata(
    *,
    metadata: dict[str, Any],
    result: OrchestrationResult,
    request_id: str,
    trace_id: str,
    updated_at: str,
) -> None:
    result_metadata = dict(result.metadata)
    response_mode = _normalize_metadata_text(result_metadata.get("response_mode"))
    if response_mode is None:
        metadata.pop("pending_task_flow", None)
        return

    task_flow_metadata: dict[str, Any] = {
        "response_mode": response_mode,
        "needs_user_input": bool(result_metadata.get("needs_user_input")),
        "pending_task_count": _resolve_pending_task_count(result_metadata),
        "generated_artifact_count": len(result.artifacts),
        "request_kind": _normalize_metadata_text(result_metadata.get("request_kind")),
        "safe_goal": _normalize_metadata_text(result_metadata.get("safe_goal")),
        "request_id": request_id,
        "trace_id": trace_id,
        "updated_at": updated_at,
    }

    clarification_question = _normalize_metadata_text(result.answer)
    if task_flow_metadata["needs_user_input"] and clarification_question is not None:
        task_flow_metadata["clarification_question"] = clarification_question

    missing_inputs = _normalize_text_list(result_metadata.get("missing_required_inputs"))
    if missing_inputs:
        task_flow_metadata["missing_required_inputs"] = missing_inputs

    plan_actions = _normalize_text_list(result_metadata.get("plan_actions"))
    if plan_actions:
        task_flow_metadata["plan_actions"] = plan_actions

    deterministic_computations = _normalize_text_list(
        result_metadata.get("required_deterministic_computations")
    )
    if deterministic_computations:
        task_flow_metadata["required_deterministic_computations"] = deterministic_computations

    preferred_agents = _normalize_text_list(result_metadata.get("preferred_agents"))
    if preferred_agents:
        task_flow_metadata["preferred_agents"] = preferred_agents

    preferred_tools = _normalize_text_list(result_metadata.get("preferred_tools"))
    if preferred_tools:
        task_flow_metadata["preferred_tools"] = preferred_tools

    metadata["pending_task_flow"] = {
        key: value
        for key, value in task_flow_metadata.items()
        if value is not None
    }


def _resolve_pending_task_count(metadata: dict[str, Any]) -> int:
    executed_step_count = _optional_non_negative_int(metadata.get("executed_step_count")) or 0
    plan_step_count = _optional_non_negative_int(metadata.get("plan_step_count"))
    if plan_step_count is None:
        return 0
    return max(plan_step_count - executed_step_count, 0)


def _normalize_metadata_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None

    normalized = value.strip()
    return normalized or None


def _normalize_text_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []

    normalized: list[str] = []
    for item in value:
        text = _normalize_metadata_text(item)
        if text is not None:
            normalized.append(text)
    return normalized


def _optional_non_negative_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value < 0:
        return None
    return value
