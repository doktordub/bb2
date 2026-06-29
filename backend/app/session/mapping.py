"""Mapping helpers between API/session/core request and result models."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.contracts.context import RequestContext
from app.contracts.state import WorkflowStateDocument
from app.orchestration.context import build_orchestration_request, build_runtime_context
from app.orchestration.models import (
    OrchestrationRequest,
    OrchestrationResult,
    OrchestrationRuntimeContext,
)
from app.orchestration.state_delta import WorkflowStateSnapshot
from app.session.models import SessionChatRequest, SessionChatResult, SessionRequestContext


def build_session_chat_request(
    *,
    message: str,
    session_id: str | None,
    usecase: str | None,
    metadata: Mapping[str, Any] | None = None,
) -> SessionChatRequest:
    """Build a session-owned request DTO from validated upstream values."""

    return SessionChatRequest(
        message=message,
        session_id=session_id,
        usecase=usecase,
        metadata=dict(metadata or {}),
    )


def build_session_request_context(
    *,
    trace_id: str,
    request_id: str,
    user_id: str,
    user_id_hash: str | None,
    client_host: str | None,
    user_agent: str | None,
    path: str | None,
    method: str | None,
    metadata: Mapping[str, Any] | None = None,
    headers_safe: Mapping[str, str] | None = None,
) -> SessionRequestContext:
    """Build a session-owned request context from safe upstream metadata."""

    resolved_metadata = dict(metadata or {})
    if headers_safe:
        resolved_metadata["headers_safe"] = dict(headers_safe)

    return SessionRequestContext(
        trace_id=trace_id,
        request_id=request_id,
        user_id=user_id,
        user_id_hash=user_id_hash,
        client_host=client_host,
        user_agent=user_agent,
        path=path,
        method=method,
        metadata=resolved_metadata,
    )


def build_core_request_context(
    *,
    request: SessionChatRequest,
    context: SessionRequestContext,
    session_id: str,
    default_usecase: str | None = None,
) -> RequestContext:
    """Map a session request into the orchestration-facing request contract."""

    metadata: dict[str, Any] = {
        **dict(context.metadata),
        **dict(request.metadata),
        "trace_id": context.trace_id,
        "request_id": context.request_id,
    }
    if context.path is not None:
        metadata["path"] = context.path
    if context.method is not None:
        metadata["method"] = context.method
    if context.user_id_hash is not None:
        metadata["user_id_hash"] = context.user_id_hash
    if context.client_host is not None:
        metadata["client_host"] = context.client_host
    if context.user_agent is not None:
        metadata["user_agent"] = context.user_agent

    return RequestContext(
        user_id=context.user_id,
        session_id=session_id,
        message=request.message,
        usecase=request.usecase or default_usecase,
        trace_id=context.trace_id,
        metadata=metadata,
    )


def build_session_orchestration_request(
    *,
    request_context: RequestContext,
    state: WorkflowStateSnapshot | WorkflowStateDocument | None = None,
    version: int | None = None,
) -> OrchestrationRequest:
    """Build the orchestration-owned request DTO for one session turn."""

    return build_orchestration_request(
        request=request_context,
        state=state,
        version=version,
    )


def build_session_orchestration_context(
    *,
    request_context: RequestContext,
    metadata: Mapping[str, Any] | None = None,
) -> OrchestrationRuntimeContext:
    """Build the orchestration runtime context for one session turn."""

    return build_runtime_context(request_context, metadata=metadata)


def orchestration_result_to_session_result(
    result: OrchestrationResult,
    *,
    trace_id: str,
) -> SessionChatResult:
    """Map the canonical orchestration result into the session boundary model."""

    return SessionChatResult(
        answer=result.answer,
        session_id=result.session_id,
        trace_id=result.trace_id or trace_id,
        agent_name=result.agent_name,
        strategy_name=result.strategy_name,
        llm_profile=result.llm_profile,
        tool_calls=[item.as_legacy_dict() for item in result.tool_calls],
        memory_updates=[item.as_legacy_dict() for item in result.memory_updates],
        metadata=dict(result.metadata),
    )