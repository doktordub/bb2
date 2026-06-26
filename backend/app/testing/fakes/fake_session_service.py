"""Deterministic in-memory session service fake for API boundary tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.api.request_context import ApiRequestContext
from app.api.schemas import ChatRequest
from app.contracts.context import RequestContext
from app.contracts.state import default_workflow_state, normalize_workflow_state_session_id
from app.session.models import SessionChatResult, SessionResetResult, SessionStreamEvent


@dataclass(frozen=True, slots=True)
class FakeSessionInvocation:
    """Recorded fake-session call for test assertions."""

    kind: str
    session_id: str
    trace_id: str
    request_context: RequestContext | None
    metadata: dict[str, Any]


class FakeSessionService:
    """Simple echo-style session fake that tracks state transitions deterministically."""

    def __init__(self) -> None:
        self.states: dict[str, dict[str, Any]] = {}
        self.invocations: list[FakeSessionInvocation] = []
        self._session_counter = 0

    async def handle_chat(
        self,
        *,
        request: ChatRequest,
        context: ApiRequestContext,
    ) -> SessionChatResult:
        session_id = self._resolve_session_id(request=request)
        state = deepcopy(self.states.get(session_id, default_workflow_state(session_id)))
        message_count_before = len(state["conversation"]["messages"])

        state["conversation"]["messages"].append(
            {
                "role": "user",
                "content": request.message,
            }
        )
        answer = f"Echo: {request.message}"
        state["conversation"]["messages"].append(
            {
                "role": "assistant",
                "content": answer,
            }
        )
        state["workflow"]["current_step"] = "answered"
        state["last_result"] = {
            "agent_name": "fake_session_agent",
            "strategy_name": "fake_direct_strategy",
            "llm_profile": "fake_local_profile",
        }
        state["metadata"] = {
            **dict(state.get("metadata", {})),
            "last_trace_id": context.trace_id,
            "last_request_id": context.request_id,
            "last_user_id": context.user_id,
            "updated_at": datetime.now(UTC).isoformat(),
            "loaded_empty": False,
        }
        self.states[session_id] = state

        request_context = self._to_request_context(
            request=request,
            context=context,
            session_id=session_id,
        )
        self.invocations.append(
            FakeSessionInvocation(
                kind="handle_chat",
                session_id=session_id,
                trace_id=context.trace_id,
                request_context=request_context,
                metadata={
                    "message_count_before": message_count_before,
                    "message_count_after": len(state["conversation"]["messages"]),
                    "usecase": request.usecase,
                },
            )
        )

        return SessionChatResult(
            answer=answer,
            session_id=session_id,
            trace_id=context.trace_id,
            agent_name="fake_session_agent",
            strategy_name="fake_direct_strategy",
            llm_profile="fake_local_profile",
            tool_calls=[],
            memory_updates=[],
            metadata={
                "usecase": request.usecase,
                "message_count": len(state["conversation"]["messages"]),
                "message_count_before": message_count_before,
            },
        )

    async def stream_chat(
        self,
        *,
        request: ChatRequest,
        context: ApiRequestContext,
    ) -> AsyncIterator[SessionStreamEvent]:
        result = await self.handle_chat(request=request, context=context)
        answer = result.answer

        self.invocations.append(
            FakeSessionInvocation(
                kind="stream_chat",
                session_id=result.session_id,
                trace_id=context.trace_id,
                request_context=self._to_request_context(
                    request=request,
                    context=context,
                    session_id=result.session_id,
                ),
                metadata={"chunks": 2},
            )
        )

        yield SessionStreamEvent(
            event_type="response.started",
            trace_id=context.trace_id,
            session_id=result.session_id,
            data={
                "message": "stream_started",
            },
        )
        midpoint = max(len(answer) // 2, 1)
        for chunk in (answer[:midpoint], answer[midpoint:]):
            if not chunk:
                continue
            yield SessionStreamEvent(
                event_type="response.delta",
                trace_id=context.trace_id,
                session_id=result.session_id,
                data={"delta": chunk},
            )
        yield SessionStreamEvent(
            event_type="response.metadata",
            trace_id=context.trace_id,
            session_id=result.session_id,
            data={
                "agent_name": result.agent_name,
                "strategy_name": result.strategy_name,
                "llm_profile": result.llm_profile,
            },
        )
        yield SessionStreamEvent(
            event_type="response.completed",
            trace_id=context.trace_id,
            session_id=result.session_id,
            data={
                "finish_reason": "stop",
                "duration_ms": 0,
            },
        )

    async def reset_session(
        self,
        *,
        session_id: str,
        reason: str | None,
        context: ApiRequestContext,
    ) -> SessionResetResult:
        normalized_session_id = normalize_workflow_state_session_id(session_id)
        self.states.pop(normalized_session_id, None)
        self.invocations.append(
            FakeSessionInvocation(
                kind="reset_session",
                session_id=normalized_session_id,
                trace_id=context.trace_id,
                request_context=None,
                metadata={"reason": reason},
            )
        )
        return SessionResetResult(
            session_id=normalized_session_id,
            trace_id=context.trace_id,
            reset=True,
            message="Session workflow state was reset.",
            metadata={"reason": reason},
        )

    def _resolve_session_id(self, *, request: ChatRequest) -> str:
        if request.session_id is not None:
            return normalize_workflow_state_session_id(request.session_id)

        self._session_counter += 1
        return f"session_{self._session_counter:04d}"

    @staticmethod
    def _to_request_context(
        *,
        request: ChatRequest,
        context: ApiRequestContext,
        session_id: str,
    ) -> RequestContext:
        return RequestContext(
            user_id=context.user_id,
            session_id=session_id,
            message=request.message,
            usecase=request.usecase,
            trace_id=context.trace_id,
            metadata={
                **dict(context.metadata),
                **dict(request.metadata),
                "client_host": context.client_host,
                "user_agent": context.user_agent,
            },
        )
