"""Deterministic in-memory session service fake for API boundary tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.contracts.context import RequestContext
from app.contracts.state import default_workflow_state
from app.session.errors import SessionNotFoundError
from app.session.identifiers import normalize_session_id
from app.session.mapping import build_core_request_context
from app.session.models import (
    SessionChatRequest,
    SessionChatResult,
    SessionDeleteResult,
    SessionHistoryMessage,
    SessionHistoryResult,
    SessionListResult,
    SessionRequestContext,
    SessionResetResult,
    SessionSummary,
    SessionStreamEvent,
)
from app.testing.fakes.fake_session_id_provider import FakeSessionIdProvider


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

    def __init__(self, *, id_provider: FakeSessionIdProvider | None = None) -> None:
        self.states: dict[str, dict[str, Any]] = {}
        self.invocations: list[FakeSessionInvocation] = []
        self.id_provider = id_provider or FakeSessionIdProvider()

    async def handle_chat(
        self,
        *,
        request: SessionChatRequest,
        context: SessionRequestContext,
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
        request: SessionChatRequest,
        context: SessionRequestContext,
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
            sequence_no=1,
        )
        midpoint = max(len(answer) // 2, 1)
        sequence_no = 1
        for chunk in (answer[:midpoint], answer[midpoint:]):
            if not chunk:
                continue
            sequence_no += 1
            yield SessionStreamEvent(
                event_type="response.delta",
                trace_id=context.trace_id,
                session_id=result.session_id,
                data={"delta": chunk},
                sequence_no=sequence_no,
            )
        sequence_no += 1
        yield SessionStreamEvent(
            event_type="response.metadata",
            trace_id=context.trace_id,
            session_id=result.session_id,
            data={
                "agent_name": result.agent_name,
                "strategy_name": result.strategy_name,
                "llm_profile": result.llm_profile,
            },
            sequence_no=sequence_no,
        )
        sequence_no += 1
        yield SessionStreamEvent(
            event_type="response.completed",
            trace_id=context.trace_id,
            session_id=result.session_id,
            data={
                "finish_reason": "stop",
                "duration_ms": 0,
            },
            sequence_no=sequence_no,
        )

    async def reset_session(
        self,
        *,
        session_id: str,
        reason: str | None,
        context: SessionRequestContext,
    ) -> SessionResetResult:
        normalized_session_id = normalize_session_id(session_id)
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

    async def get_history(
        self,
        *,
        session_id: str,
        limit: int,
        context: SessionRequestContext,
    ) -> SessionHistoryResult:
        normalized_session_id = normalize_session_id(session_id)
        state = deepcopy(self.states.get(normalized_session_id, default_workflow_state(normalized_session_id)))
        raw_messages = state.get("conversation", {}).get("messages", [])
        messages: list[SessionHistoryMessage] = []
        if isinstance(raw_messages, list):
            for item in raw_messages[-limit:]:
                if not isinstance(item, dict):
                    continue
                role = item.get("role")
                content = item.get("content")
                if not isinstance(role, str) or not isinstance(content, str):
                    continue
                messages.append(
                    SessionHistoryMessage(
                        role=role,
                        content=content,
                        metadata={"message_chars": len(content)},
                    )
                )

        self.invocations.append(
            FakeSessionInvocation(
                kind="get_history",
                session_id=normalized_session_id,
                trace_id=context.trace_id,
                request_context=None,
                metadata={"limit": limit, "message_count": len(messages)},
            )
        )
        return SessionHistoryResult(
            trace_id=context.trace_id,
            session_id=normalized_session_id,
            messages=messages,
            truncated=False,
            metadata={"limit": limit, "returned_count": len(messages)},
        )

    async def list_sessions(
        self,
        *,
        limit: int | None,
        context: SessionRequestContext,
    ) -> SessionListResult:
        resolved_limit = 50 if limit is None else limit
        sessions = []
        for session_id, state in self.states.items():
            raw_messages = state.get("conversation", {}).get("messages", [])
            metadata = state.get("metadata", {})
            usecase = None
            if isinstance(metadata, dict):
                raw_usecase = metadata.get("usecase")
                if isinstance(raw_usecase, str) and raw_usecase.strip():
                    usecase = raw_usecase.strip()
            sessions.append(
                SessionSummary(
                    session_id=session_id,
                    usecase=usecase,
                    status="active",
                    reset_count=0,
                    message_count=len(raw_messages) if isinstance(raw_messages, list) else 0,
                )
            )
        sessions.sort(key=lambda item: item.session_id)
        limited_sessions = sessions[:resolved_limit]
        self.invocations.append(
            FakeSessionInvocation(
                kind="list_sessions",
                session_id="*",
                trace_id=context.trace_id,
                request_context=None,
                metadata={"limit": resolved_limit, "returned_count": len(limited_sessions)},
            )
        )
        return SessionListResult(
            trace_id=context.trace_id,
            sessions=limited_sessions,
            limit=resolved_limit,
            has_more=len(sessions) > resolved_limit,
            metadata={
                "limit": resolved_limit,
                "returned_count": len(limited_sessions),
                "has_more": len(sessions) > resolved_limit,
            },
        )

    async def delete_session(
        self,
        *,
        session_id: str,
        context: SessionRequestContext,
    ) -> SessionDeleteResult:
        normalized_session_id = normalize_session_id(session_id)
        deleted = normalized_session_id in self.states
        self.invocations.append(
            FakeSessionInvocation(
                kind="delete_session",
                session_id=normalized_session_id,
                trace_id=context.trace_id,
                request_context=None,
                metadata={"deleted": deleted},
            )
        )
        if not deleted:
            raise SessionNotFoundError()

        self.states.pop(normalized_session_id, None)
        return SessionDeleteResult(
            session_id=normalized_session_id,
            trace_id=context.trace_id,
            deleted=True,
            message="Session workflow state was deleted.",
            metadata={"deleted": True},
        )

    def _resolve_session_id(self, *, request: SessionChatRequest) -> str:
        if request.session_id is not None:
            return normalize_session_id(request.session_id)

        return normalize_session_id(self.id_provider.new_session_id())

    @staticmethod
    def _to_request_context(
        *,
        request: SessionChatRequest,
        context: SessionRequestContext,
        session_id: str,
    ) -> RequestContext:
        return build_core_request_context(
            request=request,
            context=context,
            session_id=session_id,
            default_usecase=request.usecase,
        )
