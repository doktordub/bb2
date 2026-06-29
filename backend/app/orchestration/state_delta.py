"""Workflow-state snapshot and delta models owned by orchestration."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from app.contracts.state import (
    DEFAULT_WORKFLOW_STATE_VERSION,
    WorkflowStateDocument,
    WorkflowStateRecord,
)
from app.orchestration.models import (
    ConversationMessage,
    OrchestrationStepSummary,
    sanitize_metadata,
)


@dataclass(frozen=True, slots=True)
class WorkflowStateSnapshot:
    """Safe workflow-state projection supplied to orchestration."""

    session_id: str
    version: int
    messages: list[ConversationMessage] = field(default_factory=list)
    active_usecase: str | None = None
    active_agent: str | None = None
    step_summaries: list[OrchestrationStepSummary] = field(default_factory=list)
    pending_approvals: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "messages", list(self.messages))
        object.__setattr__(self, "step_summaries", list(self.step_summaries))
        object.__setattr__(self, "pending_approvals", _sanitize_pending_approvals(self.pending_approvals))
        object.__setattr__(self, "metadata", sanitize_metadata(self.metadata))


@dataclass(frozen=True, slots=True)
class WorkflowStateDelta:
    """Safe workflow-state patch returned by orchestration."""

    append_messages: list[ConversationMessage] = field(default_factory=list)
    set_active_usecase: str | None = None
    set_active_agent: str | None = None
    append_step_summaries: list[OrchestrationStepSummary] = field(default_factory=list)
    append_pending_approvals: list[dict[str, Any]] = field(default_factory=list)
    metadata_patch: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "append_messages", list(self.append_messages))
        object.__setattr__(self, "append_step_summaries", list(self.append_step_summaries))
        object.__setattr__(self, "append_pending_approvals", _sanitize_pending_approvals(self.append_pending_approvals))
        object.__setattr__(self, "metadata_patch", sanitize_metadata(self.metadata_patch))


def workflow_state_snapshot_from_record(record: WorkflowStateRecord) -> WorkflowStateSnapshot:
    """Build a safe orchestration snapshot from a workflow-state record."""

    version = record.version if isinstance(record.version, int) else _read_version(record.state)
    return workflow_state_snapshot_from_document(
        session_id=record.session_id,
        state=record.state,
        version=version,
    )


def workflow_state_snapshot_from_document(
    *,
    session_id: str,
    state: WorkflowStateDocument,
    version: int | None = None,
) -> WorkflowStateSnapshot:
    """Project the persisted workflow-state document into a safe orchestration snapshot."""

    messages = _project_messages(state)
    step_summaries = _project_step_summaries(state)
    workflow = state.get("workflow") if isinstance(state, dict) else None
    metadata = state.get("metadata") if isinstance(state, dict) else None
    last_result = state.get("last_result") if isinstance(state, dict) else None
    pending = workflow.get("pending_actions") if isinstance(workflow, dict) else None

    return WorkflowStateSnapshot(
        session_id=session_id,
        version=version if isinstance(version, int) and version > 0 else _read_version(state),
        messages=messages,
        active_usecase=_read_optional_text(
            metadata.get("usecase") if isinstance(metadata, dict) else None
        ),
        active_agent=_read_optional_text(
            last_result.get("agent_name") if isinstance(last_result, dict) else None
        ),
        step_summaries=step_summaries,
        pending_approvals=_sanitize_pending_approvals(pending if isinstance(pending, list) else []),
        metadata=sanitize_metadata(metadata if isinstance(metadata, Mapping) else {}),
    )


def workflow_state_delta_to_dict(delta: WorkflowStateDelta) -> dict[str, Any]:
    """Return a safe dictionary representation of one workflow-state delta."""

    return {
        "append_messages": [message.as_dict() for message in delta.append_messages],
        "set_active_usecase": delta.set_active_usecase,
        "set_active_agent": delta.set_active_agent,
        "append_step_summaries": [step.as_dict() for step in delta.append_step_summaries],
        "append_pending_approvals": [dict(item) for item in delta.append_pending_approvals],
        "metadata_patch": dict(delta.metadata_patch),
    }


def apply_workflow_state_delta(
    state: WorkflowStateDocument,
    delta: WorkflowStateDelta,
) -> WorkflowStateDocument:
    """Apply a safe orchestration delta to one workflow-state document copy."""

    updated = deepcopy(state) if isinstance(state, dict) else {}
    conversation = _ensure_dict(updated, "conversation")
    messages = conversation.get("messages")
    if not isinstance(messages, list):
        messages = []
        conversation["messages"] = messages

    workflow = _ensure_dict(updated, "workflow")
    metadata = _ensure_dict(updated, "metadata")
    last_result = _ensure_dict(updated, "last_result")
    step_summaries = workflow.get("step_summaries")
    if not isinstance(step_summaries, list):
        step_summaries = []
        workflow["step_summaries"] = step_summaries
    pending_actions = workflow.get("pending_actions")
    if not isinstance(pending_actions, list):
        pending_actions = []
        workflow["pending_actions"] = pending_actions

    for message in delta.append_messages:
        messages.append(message.as_dict())

    if delta.set_active_usecase is not None:
        metadata["usecase"] = delta.set_active_usecase
    if delta.set_active_agent is not None:
        last_result["agent_name"] = delta.set_active_agent

    for summary in delta.append_step_summaries:
        step_summaries.append(summary.as_dict())

    for approval in delta.append_pending_approvals:
        pending_actions.append(dict(approval))

    metadata.update(delta.metadata_patch)
    return updated


def _project_messages(state: WorkflowStateDocument) -> list[ConversationMessage]:
    conversation = state.get("conversation") if isinstance(state, dict) else None
    raw_messages = conversation.get("messages") if isinstance(conversation, dict) else None
    if not isinstance(raw_messages, list):
        return []

    messages: list[ConversationMessage] = []
    for item in raw_messages:
        if not isinstance(item, Mapping):
            continue
        try:
            messages.append(ConversationMessage.from_mapping(item))
        except (TypeError, ValueError):
            continue
    return messages


def _project_step_summaries(state: WorkflowStateDocument) -> list[OrchestrationStepSummary]:
    workflow = state.get("workflow") if isinstance(state, dict) else None
    raw_steps = workflow.get("step_summaries") if isinstance(workflow, dict) else None
    if not isinstance(raw_steps, list):
        return []

    summaries: list[OrchestrationStepSummary] = []
    for item in raw_steps:
        if not isinstance(item, Mapping):
            continue
        try:
            summaries.append(OrchestrationStepSummary.from_mapping(item))
        except (TypeError, ValueError):
            continue
    return summaries


def _sanitize_pending_approvals(values: object) -> list[dict[str, Any]]:
    if not isinstance(values, list):
        return []

    sanitized: list[dict[str, Any]] = []
    for item in values:
        if not isinstance(item, Mapping):
            continue
        sanitized.append(sanitize_metadata(item))
    return sanitized


def _ensure_dict(container: dict[str, Any], key: str) -> dict[str, Any]:
    value = container.get(key)
    if isinstance(value, dict):
        return value
    replacement: dict[str, Any] = {}
    container[key] = replacement
    return replacement


def _read_optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _read_version(state: WorkflowStateDocument) -> int:
    version = state.get("version") if isinstance(state, dict) else None
    if isinstance(version, int) and version > 0 and not isinstance(version, bool):
        return version
    return DEFAULT_WORKFLOW_STATE_VERSION