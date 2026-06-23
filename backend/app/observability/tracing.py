"""Trace event recording helpers for backend runtime modules."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
import logging
from typing import Any, cast

from app.config.view import ObservabilitySettings
from app.contracts.errors import TraceStoreError
from app.contracts.trace import TraceEvent, TraceStore
from app.observability.context import get_trace_context
from app.observability.ids import new_trace_id
from app.observability.redaction import Redactor

UNKNOWN_SESSION_ID = "unknown_session"


@dataclass(slots=True)
class TraceRecorder:
    """Record bounded, redacted trace events through the shared store contract."""

    store: TraceStore
    settings: ObservabilitySettings
    redactor: Redactor
    logger: logging.Logger = field(default_factory=lambda: logging.getLogger(__name__))

    async def record(
        self,
        *,
        event_type: str,
        component: str,
        trace_id: str | None = None,
        session_id: str | None = None,
        user_id: str | None = None,
        usecase: str | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        if not self.settings.trace_enabled:
            return

        context = get_trace_context()
        resolved_trace_id = trace_id or (None if context is None else context.trace_id) or new_trace_id()
        resolved_session_id = (
            session_id or (None if context is None else context.session_id) or UNKNOWN_SESSION_ID
        )
        resolved_user_id = user_id or (None if context is None else context.user_id)
        resolved_usecase = usecase or (None if context is None else context.usecase)

        event = TraceEvent(
            trace_id=resolved_trace_id,
            session_id=resolved_session_id,
            event_type=event_type,
            component=component,
            timestamp=datetime.now(UTC),
            user_id=resolved_user_id,
            usecase=resolved_usecase,
            payload=self._build_payload(payload),
        )

        try:
            await self.store.record_event(event)
        except Exception as exc:
            if self.settings.trace_store_required:
                raise TraceStoreError("Trace store recording failed.") from exc

            self.logger.error(
                "Trace event persistence failed",
                extra={
                    "component": component,
                    "event_type": event_type,
                    "error_type": type(exc).__name__,
                    "details": {"trace_id": resolved_trace_id},
                },
            )

    def _build_payload(self, payload: Mapping[str, Any] | None) -> dict[str, Any]:
        if not self.settings.trace_payloads_enabled or not payload:
            return {}

        redacted = self.redactor.redact(dict(payload))
        if not isinstance(redacted, dict):
            return {"value": redacted}
        return cast(dict[str, Any], redacted)