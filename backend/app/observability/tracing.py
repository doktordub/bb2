"""Trace event recording helpers for backend runtime modules."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
import logging
from typing import Any, cast

from app.config.view import ObservabilitySettings
from app.contracts.config import ConfigurationView
from app.contracts.errors import TraceStoreError
from app.contracts.policy import PolicyService
from app.contracts.trace import TraceEvent, TraceReadModel, TraceSearchFilters, TraceStore, TraceSummary
from app.observability.context import get_trace_context
from app.observability.ids import new_trace_id
from app.observability.events import (
    ERROR_OCCURRED,
    WORKFLOW_STATE_CONFLICT,
    WORKFLOW_STATE_LOADED,
    WORKFLOW_STATE_RESET,
    WORKFLOW_STATE_SAVED,
)
from app.observability.metrics import MetricsRecorder
from app.observability.redaction import Redactor
from app.policy.context import build_readonly_policy_context
from app.policy.redaction_policy import apply_redaction_obligations
from app.policy.trace_policy import build_trace_policy_request, infer_trace_payload_category

UNKNOWN_SESSION_ID = "unknown_session"
WORKFLOW_STATE_COMPONENT = "persistence.workflow_state"
WORKFLOW_STATE_PROVIDER = "sqlite"


@dataclass(slots=True)
class TraceRecorder:
    """Record bounded, redacted trace events through the shared store contract."""

    store: TraceStore
    settings: ObservabilitySettings
    redactor: Redactor
    policy_service: PolicyService | None = None
    config: ConfigurationView | None = None
    logger: logging.Logger = field(default_factory=lambda: logging.getLogger(__name__))

    async def record(
        self,
        *,
        event_type: str,
        component: str,
        event_name: str | None = None,
        status: str = "completed",
        severity: str = "info",
        trace_id: str | None = None,
        session_id: str | None = None,
        user_id: str | None = None,
        usecase: str | None = None,
        agent_name: str | None = None,
        strategy_name: str | None = None,
        llm_profile: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        tool_name: str | None = None,
        duration_ms: float | None = None,
        error_type: str | None = None,
        error_code: str | None = None,
        retryable: bool | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        if not self.settings.trace_enabled:
            return

        resolved_event_name = event_name or event_type
        resolved_event_type = (
            event_type if event_name is not None else _infer_trace_event_type(resolved_event_name)
        )

        (
            resolved_trace_id,
            resolved_session_id,
            resolved_user_id,
            resolved_usecase,
        ) = _resolve_event_context(
            trace_id=trace_id,
            session_id=session_id,
            user_id=user_id,
            usecase=usecase,
        )

        event = TraceEvent(
            trace_id=resolved_trace_id,
            session_id=resolved_session_id,
            event_type=resolved_event_type,
            component=component,
            timestamp=datetime.now(UTC),
            event_name=resolved_event_name,
            status=status,
            severity=severity,
            user_id=resolved_user_id,
            usecase=resolved_usecase,
            agent_name=agent_name,
            strategy_name=strategy_name,
            llm_profile=llm_profile,
            provider=provider,
            model=model,
            tool_name=tool_name,
            duration_ms=duration_ms,
            error_type=error_type,
            error_code=error_code,
            retryable=retryable,
            payload=self._build_payload(payload),
        )

        await self.record_trace_event(event)

    def _build_payload(self, payload: Mapping[str, Any] | None) -> dict[str, Any]:
        if not self.settings.trace_payloads_enabled or not payload:
            return {}

        return dict(payload)

    async def record_trace_event(self, event: TraceEvent) -> None:
        """Record a prebuilt trace event through the same redaction and failure policy path."""

        if not self.settings.trace_enabled:
            return

        payload = self._build_payload(event.payload)
        if self.policy_service is not None and self.config is not None:
            payload_category = infer_trace_payload_category(payload)
            policy_context = build_readonly_policy_context(
                policy_service=self.policy_service,
                config=self.config,
                trace_id=event.trace_id,
                user_id=event.user_id,
                session_id=event.session_id,
                usecase_name=event.usecase,
            )
            policy_request = build_trace_policy_request(
                trace_id=event.trace_id,
                session_id=event.session_id,
                user_id=event.user_id,
                usecase_name=event.usecase,
                event_name=event.resolved_event_name,
                component=event.component,
                payload=payload,
                payload_category=payload_category,
            )
            decision = await self.policy_service.evaluate(policy_request, policy_context)
            if decision.is_denied:
                payload = {}
            else:
                payload = apply_redaction_obligations(payload, decision=decision, redactor=self.redactor)
        else:
            redacted = self.redactor.redact(payload)
            if isinstance(redacted, dict):
                payload = cast(dict[str, Any], redacted)
            else:
                payload = {"value": redacted}

        redacted_event = replace(event, payload=payload)
        try:
            await self.store.record_event(redacted_event)
        except Exception as exc:
            if self.settings.trace_store_required:
                raise TraceStoreError("Trace store recording failed.") from exc

            self.logger.error(
                "Trace event persistence failed",
                extra={
                    "component": redacted_event.component,
                    "event_type": redacted_event.resolved_event_name,
                    "error_type": type(exc).__name__,
                    "details": {
                        "trace_id": redacted_event.trace_id,
                        "trace_event_type": redacted_event.event_type,
                    },
                },
            )

    async def record_trace_events(self, events: Sequence[TraceEvent]) -> None:
        """Record multiple prebuilt trace events through the recorder path."""

        for event in events:
            await self.record_trace_event(event)


@dataclass(slots=True)
class RecorderTraceStoreAdapter:
    """Write-only trace facade that keeps orchestration callers off the raw trace store."""

    recorder: TraceRecorder

    async def record_event(self, event: TraceEvent) -> None:
        await self.recorder.record_trace_event(event)

    async def record_events(self, events: Sequence[TraceEvent]) -> None:
        await self.recorder.record_trace_events(events)

    async def read_trace(
        self,
        *,
        trace_id: str,
        limit: int | None = None,
    ) -> TraceReadModel:
        _ = trace_id
        _ = limit
        raise TraceStoreError("Trace reads are not available through the orchestration recorder facade.")

    async def search_traces(self, *, filters: TraceSearchFilters) -> list[TraceSummary]:
        _ = filters
        raise TraceStoreError("Trace search is not available through the orchestration recorder facade.")

    async def health(self) -> dict[str, Any]:
        return {
            "status": "ok" if self.recorder.settings.trace_enabled else "disabled",
            "mode": "write_only",
        }


@dataclass(slots=True)
class WorkflowStateObserver:
    """Emit safe workflow-state trace events and metrics without affecting store writes."""

    store: TraceStore
    metrics: MetricsRecorder
    trace_enabled: bool = True
    logger: logging.Logger = field(default_factory=lambda: logging.getLogger(__name__))

    async def record_load(
        self,
        *,
        session_id: str | None,
        found: bool,
        state_version: int | None,
        history_message_count: int,
        duration_ms: int,
    ) -> None:
        payload = _drop_none_values(
            {
                "provider": WORKFLOW_STATE_PROVIDER,
                "operation": "load",
                "found": found,
                "state_version": state_version,
                "history_message_count": history_message_count,
                "duration_ms": duration_ms,
                "success": True,
            }
        )
        await self._record_trace(
            event_type="workflow_state",
            event_name=WORKFLOW_STATE_LOADED,
            session_id=session_id,
            status="completed",
            duration_ms=float(duration_ms),
            provider=WORKFLOW_STATE_PROVIDER,
            payload=payload,
        )

        tags = _workflow_state_metric_tags(operation="load", success=True)
        self.metrics.increment("backend.state.load.total", tags=tags)
        self.metrics.timing("backend.state.load.duration_ms", duration_ms, tags=tags)
        if not found:
            self.metrics.increment("backend.state.load.miss_total", tags=tags)

    async def record_save(
        self,
        *,
        session_id: str | None,
        state_version: int,
        state_size_bytes: int,
        history_message_count: int,
        duration_ms: int,
    ) -> None:
        payload = {
            "provider": WORKFLOW_STATE_PROVIDER,
            "operation": "save",
            "state_version": state_version,
            "state_size_bytes": state_size_bytes,
            "history_message_count": history_message_count,
            "duration_ms": duration_ms,
            "success": True,
        }
        await self._record_trace(
            event_type="workflow_state",
            event_name=WORKFLOW_STATE_SAVED,
            session_id=session_id,
            status="completed",
            duration_ms=float(duration_ms),
            provider=WORKFLOW_STATE_PROVIDER,
            payload=payload,
        )

        tags = _workflow_state_metric_tags(operation="save", success=True)
        self.metrics.increment("backend.state.save.total", tags=tags)
        self.metrics.timing("backend.state.save.duration_ms", duration_ms, tags=tags)
        self.metrics.increment("backend.state.save.bytes", value=state_size_bytes, tags=tags)

    async def record_reset(
        self,
        *,
        session_id: str | None,
        reset_generation: int,
        cleared_state_version: int | None,
        duration_ms: int,
    ) -> None:
        payload = _drop_none_values(
            {
                "provider": WORKFLOW_STATE_PROVIDER,
                "operation": "reset",
                "reset_generation": reset_generation,
                "cleared_state_version": cleared_state_version,
                "duration_ms": duration_ms,
                "success": True,
            }
        )
        await self._record_trace(
            event_type="workflow_state",
            event_name=WORKFLOW_STATE_RESET,
            session_id=session_id,
            status="completed",
            duration_ms=float(duration_ms),
            provider=WORKFLOW_STATE_PROVIDER,
            payload=payload,
        )

        tags = _workflow_state_metric_tags(operation="reset", success=True)
        self.metrics.increment("backend.state.reset.total", tags=tags)
        self.metrics.timing("backend.state.reset.duration_ms", duration_ms, tags=tags)

    async def record_failure(
        self,
        *,
        operation: str,
        session_id: str | None,
        error: Exception,
        duration_ms: int,
    ) -> None:
        error_type = type(error).__name__
        payload = {
            "provider": WORKFLOW_STATE_PROVIDER,
            "operation": operation,
            "duration_ms": duration_ms,
            "success": False,
            "error_type": error_type,
        }
        await self._record_trace(
            event_type="error",
            event_name=ERROR_OCCURRED,
            session_id=session_id,
            status="failed",
            severity="error",
            duration_ms=float(duration_ms),
            provider=WORKFLOW_STATE_PROVIDER,
            error_type=error_type,
            payload=payload,
        )

        tags = _workflow_state_metric_tags(
            operation=operation,
            success=False,
            error_type=error_type,
        )
        self.metrics.increment(f"backend.state.{operation}.total", tags=tags)
        self.metrics.timing(f"backend.state.{operation}.duration_ms", duration_ms, tags=tags)
        self.metrics.increment("backend.state.errors", tags=tags)

    async def record_conflict(
        self,
        *,
        operation: str,
        session_id: str | None,
        error: Exception,
        duration_ms: int,
    ) -> None:
        error_type = type(error).__name__
        payload = {
            "provider": WORKFLOW_STATE_PROVIDER,
            "operation": operation,
            "duration_ms": duration_ms,
            "success": False,
            "error_type": error_type,
        }
        await self._record_trace(
            event_type="workflow_state",
            event_name=WORKFLOW_STATE_CONFLICT,
            session_id=session_id,
            status="failed",
            severity="warning",
            duration_ms=float(duration_ms),
            provider=WORKFLOW_STATE_PROVIDER,
            error_type=error_type,
            payload=payload,
        )

        tags = _workflow_state_metric_tags(
            operation=operation,
            success=False,
            error_type=error_type,
        )
        self.metrics.increment(f"backend.state.{operation}.total", tags=tags)
        self.metrics.timing(f"backend.state.{operation}.duration_ms", duration_ms, tags=tags)
        self.metrics.increment("backend.state.conflicts", tags=tags)

    async def _record_trace(
        self,
        *,
        event_type: str,
        event_name: str,
        session_id: str | None,
        status: str,
        severity: str = "info",
        duration_ms: float | None = None,
        provider: str | None = None,
        error_type: str | None = None,
        payload: Mapping[str, Any],
    ) -> None:
        if not self.trace_enabled:
            return

        (
            resolved_trace_id,
            resolved_session_id,
            resolved_user_id,
            resolved_usecase,
        ) = _resolve_event_context(session_id=session_id)
        event = TraceEvent(
            trace_id=resolved_trace_id,
            session_id=resolved_session_id,
            event_type=event_type,
            event_name=event_name,
            component=WORKFLOW_STATE_COMPONENT,
            timestamp=datetime.now(UTC),
            status=status,
            severity=severity,
            user_id=resolved_user_id,
            usecase=resolved_usecase,
            provider=provider,
            duration_ms=duration_ms,
            error_type=error_type,
            payload=dict(payload),
        )

        try:
            await self.store.record_event(event)
        except Exception as exc:
            self.logger.error(
                "Workflow-state trace emission failed",
                extra={
                    "component": WORKFLOW_STATE_COMPONENT,
                    "event_type": event_type,
                    "error_type": type(exc).__name__,
                    "details": {"trace_id": resolved_trace_id},
                },
            )


def _infer_trace_event_type(event_name: str) -> str:
    if event_name.startswith(("request_", "response_")):
        return "request"
    if event_name.startswith("context_"):
        return "context"
    if event_name.startswith("workflow_state_"):
        return "workflow_state"
    if event_name.startswith("memory_"):
        return "memory"
    if event_name.startswith("llm_"):
        return "llm"
    if event_name.startswith("strategy_"):
        return "strategy"
    if event_name.startswith("agent_"):
        return "agent"
    if event_name.startswith("tool_"):
        return "tool"
    if event_name.startswith("mcp_"):
        return "mcp"
    if event_name.startswith("policy_"):
        return "policy"
    if event_name.startswith("stream_"):
        return "stream"
    if event_name.startswith("session_"):
        return "session"
    if event_name.startswith(("startup_", "config_")):
        return "startup"
    if event_name.startswith("health_"):
        return "health"
    if event_name.startswith("error_"):
        return "error"
    if event_name.startswith("trace_retention_"):
        return "trace"
    return event_name


def _resolve_event_context(
    *,
    trace_id: str | None = None,
    session_id: str | None = None,
    user_id: str | None = None,
    usecase: str | None = None,
) -> tuple[str, str, str | None, str | None]:
    context = get_trace_context()
    resolved_trace_id = trace_id or (None if context is None else context.trace_id) or new_trace_id()
    resolved_session_id = session_id or (None if context is None else context.session_id) or UNKNOWN_SESSION_ID
    resolved_user_id = user_id or (None if context is None else context.user_id)
    resolved_usecase = usecase or (None if context is None else context.usecase)
    return resolved_trace_id, resolved_session_id, resolved_user_id, resolved_usecase


def _workflow_state_metric_tags(
    *,
    operation: str,
    success: bool,
    error_type: str | None = None,
) -> dict[str, str]:
    tags: dict[str, str] = {
        "component": WORKFLOW_STATE_COMPONENT,
        "provider": WORKFLOW_STATE_PROVIDER,
        "operation": operation,
        "success": "true" if success else "false",
    }
    if error_type is not None:
        tags["error_type"] = error_type
    return tags


def _drop_none_values(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}