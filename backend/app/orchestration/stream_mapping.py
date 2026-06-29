"""Map strategy-emitted stream shapes into the runtime's safe event model."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.contracts.results import StreamEvent
from app.orchestration.errors import AgentExecutionError, OrchestrationCancelledError, OrchestrationError, orchestration_error_from_detail
from app.orchestration.events import OrchestrationStreamEvent
from app.orchestration.models import OrchestrationResult, sanitize_metadata


@dataclass(frozen=True, slots=True)
class StreamMappingResult:
    """Normalized effect of consuming one raw strategy stream item."""

    emitted_events: tuple[OrchestrationStreamEvent, ...] = ()
    answer_delta: str | None = None
    finish_reason: str | None = None
    runtime_result: OrchestrationResult | None = None
    agent_name: str | None = None
    llm_profile: str | None = None
    tool_call: dict[str, Any] | None = None
    metadata_patch: dict[str, Any] = field(default_factory=dict)
    terminal_error: OrchestrationError | None = None
    terminal_cancelled: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata_patch", sanitize_metadata(self.metadata_patch))
        object.__setattr__(self, "tool_call", None if self.tool_call is None else dict(self.tool_call))

    @property
    def should_stop(self) -> bool:
        return self.terminal_cancelled or self.terminal_error is not None


def map_stream_event(
    raw_event: StreamEvent | OrchestrationStreamEvent,
    *,
    trace_id: str,
    session_id: str,
) -> StreamMappingResult:
    if isinstance(raw_event, OrchestrationStreamEvent):
        return _map_orchestration_stream_event(raw_event)
    return _map_legacy_stream_event(raw_event, trace_id=trace_id, session_id=session_id)


def _map_orchestration_stream_event(raw_event: OrchestrationStreamEvent) -> StreamMappingResult:
    if raw_event.type == "response.delta":
        return StreamMappingResult(
            emitted_events=(raw_event,),
            answer_delta=raw_event.text,
        )
    if raw_event.type == "response.completed":
        return StreamMappingResult(
            finish_reason=_read_optional_text(raw_event.metadata.get("finish_reason")),
        )
    if raw_event.type == "orchestration.completed":
        return StreamMappingResult(
            runtime_result=raw_event.result,
            metadata_patch=dict(raw_event.metadata),
        )
    if raw_event.type == "strategy.selected":
        return StreamMappingResult(
            agent_name=_read_optional_text(raw_event.metadata.get("agent_name")),
            llm_profile=_read_optional_text(raw_event.metadata.get("llm_profile")),
            metadata_patch=dict(raw_event.metadata),
        )
    if raw_event.type == "orchestration.error":
        error = (
            AgentExecutionError()
            if raw_event.error is None
            else orchestration_error_from_detail(raw_event.error)
        )
        return StreamMappingResult(
            emitted_events=(raw_event,),
            terminal_error=error,
        )
    if raw_event.type == "orchestration.cancelled":
        return StreamMappingResult(
            emitted_events=(raw_event,),
            terminal_error=OrchestrationCancelledError(),
            terminal_cancelled=True,
        )
    return StreamMappingResult()


def _map_legacy_stream_event(
    raw_event: StreamEvent,
    *,
    trace_id: str,
    session_id: str,
) -> StreamMappingResult:
    if raw_event.event_type == "content_delta":
        text = _read_optional_text(raw_event.data.get("text"))
        if text is None:
            return StreamMappingResult()
        return StreamMappingResult(
            emitted_events=(
                OrchestrationStreamEvent.response_delta(
                    trace_id=trace_id,
                    session_id=session_id,
                    text=text,
                ),
            ),
            answer_delta=text,
        )

    if raw_event.event_type == "agent_summary":
        metadata_patch = {
            key: value
            for key, value in raw_event.data.items()
            if key not in {"agent_name", "strategy_name", "llm_profile", "finish_reason"}
        }
        return StreamMappingResult(
            agent_name=_read_optional_text(raw_event.data.get("agent_name")),
            llm_profile=_read_optional_text(raw_event.data.get("llm_profile")),
            metadata_patch=metadata_patch,
        )

    if raw_event.event_type == "tool_call_summary":
        return StreamMappingResult(tool_call=dict(raw_event.data))

    if raw_event.event_type == "trace_summary":
        return StreamMappingResult(metadata_patch={"trace_summary": dict(raw_event.data)})

    if raw_event.event_type == "message_completed":
        return StreamMappingResult(
            finish_reason=_read_optional_text(raw_event.data.get("finish_reason")),
        )

    if raw_event.event_type == "error":
        message = _read_optional_text(raw_event.data.get("message")) or "Streaming orchestration failed."
        error = AgentExecutionError(message)
        return StreamMappingResult(
            emitted_events=(
                OrchestrationStreamEvent.error_event(
                    trace_id=trace_id,
                    session_id=session_id,
                    error=error,
                ),
            ),
            terminal_error=error,
        )

    return StreamMappingResult()


def _read_optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None