"""Compatibility builders for orchestration-owned request and runtime context DTOs."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.contracts.context import RequestContext
from app.contracts.state import WorkflowStateDocument, WorkflowStateRecord
from app.orchestration.models import OrchestrationRequest, OrchestrationRuntimeContext, sanitize_metadata
from app.orchestration.state_delta import (
    WorkflowStateSnapshot,
    workflow_state_snapshot_from_document,
    workflow_state_snapshot_from_record,
)


def build_orchestration_request(
    *,
    request: RequestContext,
    state: WorkflowStateSnapshot | WorkflowStateDocument | None = None,
    version: int | None = None,
) -> OrchestrationRequest:
    """Build an orchestration-owned request from the current core request contract."""

    workflow_state = _coerce_workflow_state(
        session_id=request.session_id,
        state=state,
        version=version,
    )
    trace_id = _read_optional_text(request.trace_id) or _read_optional_text(request.metadata.get("trace_id")) or "unknown_trace"

    return OrchestrationRequest(
        session_id=request.session_id,
        trace_id=trace_id,
        user_id=request.user_id,
        message=request.message,
        usecase=request.usecase,
        metadata=sanitize_metadata(request.metadata),
        workflow_state=workflow_state,
    )


def build_runtime_context(
    request: RequestContext,
    *,
    metadata: Mapping[str, Any] | None = None,
) -> OrchestrationRuntimeContext:
    """Build a safe runtime-context DTO from the current request metadata."""

    merged_metadata = dict(request.metadata)
    if metadata is not None:
        merged_metadata.update(metadata)

    request_id = _read_optional_text(merged_metadata.get("request_id")) or f"{request.session_id}:request"
    trace_id = _read_optional_text(request.trace_id) or _read_optional_text(merged_metadata.get("trace_id")) or "unknown_trace"
    timezone = _read_optional_text(merged_metadata.get("timezone")) or _read_optional_text(merged_metadata.get("tz"))
    client = (
        _read_optional_text(merged_metadata.get("client"))
        or _read_optional_text(merged_metadata.get("client_host"))
        or _read_optional_text(merged_metadata.get("user_agent"))
    )

    return OrchestrationRuntimeContext(
        request_id=request_id,
        trace_id=trace_id,
        session_id=request.session_id,
        user_id=request.user_id,
        project_id=_read_optional_text(merged_metadata.get("project_id")),
        tenant_id=_read_optional_text(merged_metadata.get("tenant_id")),
        timezone=timezone,
        client=client,
        metadata=sanitize_metadata(merged_metadata),
    )


def build_workflow_state_snapshot(record: WorkflowStateRecord) -> WorkflowStateSnapshot:
    """Build a workflow-state snapshot from the current record contract."""

    return workflow_state_snapshot_from_record(record)


def build_workflow_state_snapshot_from_document(
    *,
    session_id: str,
    state: WorkflowStateDocument,
    version: int | None = None,
) -> WorkflowStateSnapshot:
    """Build a workflow-state snapshot from the current document contract."""

    return workflow_state_snapshot_from_document(
        session_id=session_id,
        state=state,
        version=version,
    )


def _coerce_workflow_state(
    *,
    session_id: str,
    state: WorkflowStateSnapshot | WorkflowStateDocument | None,
    version: int | None,
) -> WorkflowStateSnapshot | None:
    if state is None:
        return None
    if isinstance(state, WorkflowStateSnapshot):
        return state
    return workflow_state_snapshot_from_document(session_id=session_id, state=state, version=version)


def _read_optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None