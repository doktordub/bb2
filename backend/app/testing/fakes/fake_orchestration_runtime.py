"""Deterministic orchestration runtime fake for session-service tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from app.contracts.context import RequestContext
from app.contracts.results import OrchestrationResult as LegacyOrchestrationResult
from app.contracts.results import StreamEvent
from app.contracts.state import WorkflowStateDocument
from app.orchestration.context import build_orchestration_request, build_runtime_context
from app.orchestration.events import OrchestrationStreamEvent
from app.orchestration.models import ConversationMessage, OrchestrationRequest, OrchestrationResult, OrchestrationRuntimeContext
from app.orchestration.result_builder import build_orchestration_result, orchestration_result_to_contract
from app.orchestration.state_delta import WorkflowStateDelta
from app.orchestration.state_delta import WorkflowStateSnapshot, workflow_state_snapshot_from_document


@dataclass(frozen=True, slots=True)
class FakeOrchestrationRunCall:
    """Recorded runtime invocation for non-streaming orchestration."""

    request: RequestContext
    state: WorkflowStateDocument
    orchestration_request: OrchestrationRequest
    runtime_context: OrchestrationRuntimeContext
    state_snapshot: WorkflowStateSnapshot


@dataclass(frozen=True, slots=True)
class FakeOrchestrationStreamCall:
    """Recorded runtime invocation for streaming orchestration."""

    request: RequestContext
    state: WorkflowStateDocument
    orchestration_request: OrchestrationRequest
    runtime_context: OrchestrationRuntimeContext
    state_snapshot: WorkflowStateSnapshot


class FakeOrchestrationRuntime:
    """Simple fake runtime that records inputs and returns deterministic answers."""

    def __init__(
        self,
        *,
        answer_prefix: str = "Echo: ",
        agent_name: str = "fake_session_agent",
        strategy_name: str = "fake_direct_strategy",
        llm_profile: str = "fake_local_profile",
        metadata: dict[str, Any] | None = None,
        run_error: Exception | None = None,
        stream_error: Exception | None = None,
        stream_events: list[StreamEvent | OrchestrationStreamEvent] | None = None,
    ) -> None:
        self.answer_prefix = answer_prefix
        self.agent_name = agent_name
        self.strategy_name = strategy_name
        self.llm_profile = llm_profile
        self.metadata = dict(metadata or {})
        self.run_error = run_error
        self.stream_error = stream_error
        self.stream_events = list(stream_events or [])
        self.run_calls: list[FakeOrchestrationRunCall] = []
        self.stream_calls: list[FakeOrchestrationStreamCall] = []

    async def run(
        self,
        *,
        request: RequestContext,
        state: WorkflowStateDocument,
    ) -> LegacyOrchestrationResult:
        state_snapshot = workflow_state_snapshot_from_document(
            session_id=request.session_id,
            state=state,
        )
        orchestration_request = build_orchestration_request(request=request, state=state_snapshot)
        runtime_context = build_runtime_context(request)
        self.run_calls.append(
            FakeOrchestrationRunCall(
                request=_copy_request_context(request),
                state=deepcopy(state),
                orchestration_request=orchestration_request,
                runtime_context=runtime_context,
                state_snapshot=state_snapshot,
            )
        )
        if self.run_error is not None:
            raise self.run_error

        return orchestration_result_to_contract(self._build_runtime_result(request=orchestration_request))

    async def run_turn(
        self,
        *,
        request: OrchestrationRequest,
        context: OrchestrationRuntimeContext,
    ) -> OrchestrationResult:
        request_context = _request_context_from_orchestration_request(request)
        state = _state_from_workflow_snapshot(request.workflow_state, session_id=request.session_id)
        state_snapshot = request.workflow_state or workflow_state_snapshot_from_document(
            session_id=request.session_id,
            state=state,
        )
        self.run_calls.append(
            FakeOrchestrationRunCall(
                request=request_context,
                state=deepcopy(state),
                orchestration_request=request,
                runtime_context=context,
                state_snapshot=state_snapshot,
            )
        )
        if self.run_error is not None:
            raise self.run_error

        return self._build_runtime_result(request=request)

    async def stream(
        self,
        *,
        request: RequestContext,
        state: WorkflowStateDocument,
    ) -> AsyncIterator[StreamEvent | OrchestrationStreamEvent]:
        state_snapshot = workflow_state_snapshot_from_document(
            session_id=request.session_id,
            state=state,
        )
        orchestration_request = build_orchestration_request(request=request, state=state_snapshot)
        runtime_context = build_runtime_context(request)
        self.stream_calls.append(
            FakeOrchestrationStreamCall(
                request=_copy_request_context(request),
                state=deepcopy(state),
                orchestration_request=orchestration_request,
                runtime_context=runtime_context,
                state_snapshot=state_snapshot,
            )
        )
        if self.stream_error is not None:
            raise self.stream_error

        if self.stream_events:
            for event in self.stream_events:
                if isinstance(event, OrchestrationStreamEvent):
                    yield event
                else:
                    yield StreamEvent(event_type=event.event_type, data=dict(event.data))
            return

        runtime_result = self._build_runtime_result(request=orchestration_request)

        yield OrchestrationStreamEvent.started(
            trace_id=orchestration_request.trace_id,
            session_id=request.session_id,
            metadata={"usecase": request.usecase or "default_chat"},
        )
        yield OrchestrationStreamEvent.strategy_selected(
            trace_id=orchestration_request.trace_id,
            session_id=request.session_id,
            strategy_name=self.strategy_name,
            usecase=request.usecase or "default_chat",
            agent_name=self.agent_name,
            llm_profile=self.llm_profile,
        )
        for chunk in _chunk_text(runtime_result.answer):
            yield OrchestrationStreamEvent.response_delta(
                trace_id=orchestration_request.trace_id,
                session_id=request.session_id,
                text=chunk,
            )
        yield OrchestrationStreamEvent.completed(
            trace_id=orchestration_request.trace_id,
            session_id=request.session_id,
            result=runtime_result,
            metadata={
                "agent_name": self.agent_name,
                "strategy_name": self.strategy_name,
                "llm_profile": self.llm_profile,
            },
        )
        yield OrchestrationStreamEvent.response_completed(
            trace_id=orchestration_request.trace_id,
            session_id=request.session_id,
            finish_reason=runtime_result.finish_reason,
        )

    async def stream_turn(
        self,
        *,
        request: OrchestrationRequest,
        context: OrchestrationRuntimeContext,
    ) -> AsyncIterator[OrchestrationStreamEvent]:
        request_context = _request_context_from_orchestration_request(request)
        state = _state_from_workflow_snapshot(request.workflow_state, session_id=request.session_id)
        state_snapshot = request.workflow_state or workflow_state_snapshot_from_document(
            session_id=request.session_id,
            state=state,
        )
        self.stream_calls.append(
            FakeOrchestrationStreamCall(
                request=request_context,
                state=deepcopy(state),
                orchestration_request=request,
                runtime_context=context,
                state_snapshot=state_snapshot,
            )
        )
        if self.stream_error is not None:
            raise self.stream_error

        runtime_result = self._build_runtime_result(request=request)
        if self.stream_events:
            for event in self.stream_events:
                if isinstance(event, OrchestrationStreamEvent):
                    yield event
                else:
                    converted = _legacy_stream_event_to_orchestration_event(
                        event=event,
                        request=request,
                        runtime_result=runtime_result,
                    )
                    if converted is not None:
                        yield converted
            return

        yield OrchestrationStreamEvent.started(
            trace_id=request.trace_id,
            session_id=request.session_id,
            metadata={"usecase": request.usecase or "default_chat"},
        )
        yield OrchestrationStreamEvent.strategy_selected(
            trace_id=request.trace_id,
            session_id=request.session_id,
            strategy_name=self.strategy_name,
            usecase=request.usecase or "default_chat",
            agent_name=self.agent_name,
            llm_profile=self.llm_profile,
        )
        for chunk in _chunk_text(runtime_result.answer):
            yield OrchestrationStreamEvent.response_delta(
                trace_id=request.trace_id,
                session_id=request.session_id,
                text=chunk,
            )
        yield OrchestrationStreamEvent.completed(
            trace_id=request.trace_id,
            session_id=request.session_id,
            result=runtime_result,
            metadata={
                "agent_name": self.agent_name,
                "strategy_name": self.strategy_name,
                "llm_profile": self.llm_profile,
            },
        )
        yield OrchestrationStreamEvent.response_completed(
            trace_id=request.trace_id,
            session_id=request.session_id,
            finish_reason=runtime_result.finish_reason,
        )

    def _build_runtime_result(self, *, request: OrchestrationRequest) -> OrchestrationResult:
        answer = f"{self.answer_prefix}{request.message}"
        usecase = request.usecase or "default_chat"
        return build_orchestration_result(
            answer=answer,
            session_id=request.session_id,
            trace_id=request.trace_id,
            usecase=usecase,
            strategy_name=self.strategy_name,
            agent_name=self.agent_name,
            llm_profile=self.llm_profile,
            state_delta=WorkflowStateDelta(
                append_messages=[
                    ConversationMessage(
                        role="assistant",
                        content=answer,
                        metadata={
                            "agent_name": self.agent_name,
                            "strategy_name": self.strategy_name,
                            "llm_profile": self.llm_profile,
                        },
                    )
                ],
                set_active_usecase=usecase,
                set_active_agent=self.agent_name,
                metadata_patch={
                    "last_strategy": self.strategy_name,
                    "last_agent": self.agent_name,
                    "last_llm_profile": self.llm_profile,
                },
            ),
            metadata=dict(self.metadata),
        )


def _copy_request_context(request: RequestContext) -> RequestContext:
    return RequestContext(
        user_id=request.user_id,
        session_id=request.session_id,
        message=request.message,
        usecase=request.usecase,
        trace_id=request.trace_id,
        metadata=deepcopy(request.metadata),
    )


def _request_context_from_orchestration_request(request: OrchestrationRequest) -> RequestContext:
    return RequestContext(
        user_id=request.user_id,
        session_id=request.session_id,
        message=request.message,
        usecase=request.usecase,
        trace_id=request.trace_id,
        metadata=deepcopy(request.metadata),
    )


def _state_from_workflow_snapshot(
    snapshot: WorkflowStateSnapshot | None,
    *,
    session_id: str,
) -> WorkflowStateDocument:
    if snapshot is None:
        return {
            "session_id": session_id,
            "version": 1,
            "conversation": {"messages": []},
            "workflow": {"current_step": None, "checkpoint": None, "scratch": {}, "pending_actions": []},
            "last_result": {"agent_name": None, "strategy_name": None, "llm_profile": None},
            "metadata": {},
        }

    return {
        "session_id": snapshot.session_id,
        "version": snapshot.version,
        "conversation": {
            "messages": [message.as_dict() for message in snapshot.messages],
        },
        "workflow": {
            "current_step": None,
            "checkpoint": None,
            "scratch": {},
            "pending_actions": [dict(item) for item in snapshot.pending_approvals],
            "step_summaries": [summary.as_dict() for summary in snapshot.step_summaries],
        },
        "last_result": {
            "agent_name": snapshot.active_agent,
            "strategy_name": None,
            "llm_profile": None,
        },
        "metadata": dict(snapshot.metadata),
    }


def _legacy_stream_event_to_orchestration_event(
    *,
    event: StreamEvent,
    request: OrchestrationRequest,
    runtime_result: OrchestrationResult,
) -> OrchestrationStreamEvent | None:
    if event.event_type == "message_started":
        return OrchestrationStreamEvent.started(
            trace_id=request.trace_id,
            session_id=request.session_id,
            metadata={"usecase": request.usecase or runtime_result.usecase},
        )
    if event.event_type == "content_delta":
        text = event.data.get("text")
        if not isinstance(text, str) or not text:
            return None
        return OrchestrationStreamEvent.response_delta(
            trace_id=request.trace_id,
            session_id=request.session_id,
            text=text,
        )
    if event.event_type == "agent_summary":
        return OrchestrationStreamEvent.completed(
            trace_id=request.trace_id,
            session_id=request.session_id,
            result=runtime_result,
            metadata=dict(event.data),
        )
    if event.event_type == "message_completed":
        finish_reason = event.data.get("finish_reason")
        return OrchestrationStreamEvent.response_completed(
            trace_id=request.trace_id,
            session_id=request.session_id,
            finish_reason=finish_reason if isinstance(finish_reason, str) else runtime_result.finish_reason,
        )
    if event.event_type == "error":
        return OrchestrationStreamEvent.error_event(
            trace_id=request.trace_id,
            session_id=request.session_id,
            error=RuntimeError(str(event.data.get("message") or "Streaming orchestration failed.")),
        )
    return None


def _chunk_text(text: str) -> tuple[str, ...]:
    midpoint = max(len(text) // 2, 1)
    chunks = tuple(chunk for chunk in (text[:midpoint], text[midpoint:]) if chunk)
    return chunks or (text,)
