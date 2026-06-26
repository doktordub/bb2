"""Protocol for the API-facing session service boundary."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from app.api.request_context import ApiRequestContext
from app.api.schemas import ChatRequest
from app.session.models import SessionChatResult, SessionResetResult, SessionStreamEvent


class SessionService(Protocol):
    """Thin session boundary consumed by API routes."""

    async def handle_chat(
        self,
        *,
        request: ChatRequest,
        context: ApiRequestContext,
    ) -> SessionChatResult:
        ...

    def stream_chat(
        self,
        *,
        request: ChatRequest,
        context: ApiRequestContext,
    ) -> AsyncIterator[SessionStreamEvent]:
        ...

    async def reset_session(
        self,
        *,
        session_id: str,
        reason: str | None,
        context: ApiRequestContext,
    ) -> SessionResetResult:
        ...
