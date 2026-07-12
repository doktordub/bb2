"""Helpers for mapping runtime stream events to session stream events."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.contracts.results import StreamEvent
from app.orchestration.events import OrchestrationStreamEvent
from app.orchestration.models import ConversationMessage, OrchestrationResult
from app.orchestration.result_builder import build_orchestration_result
from app.orchestration.state_delta import WorkflowStateDelta
from app.session.models import SessionStreamEvent


@dataclass(slots=True)
class StreamAccumulator:
    """Accumulate safe stream output until final session-state save."""

    trace_id: str
    session_id: str
    usecase: str
    answer_parts: list[str] = field(default_factory=list)
    agent_name: str | None = None
    strategy_name: str | None = None
    llm_profile: str | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    finish_reason: str = "stop"
    runtime_result: OrchestrationResult | None = None

    def consume(
        self,
        *,
        event: StreamEvent | OrchestrationStreamEvent,
        sequence_no: int,
    ) -> tuple[SessionStreamEvent, ...]:
        """Consume one orchestration stream event and optionally emit a session event."""

        if isinstance(event, OrchestrationStreamEvent):
            return self._consume_orchestration_event(event=event, sequence_no=sequence_no)

        return self._consume_legacy_event(event=event, sequence_no=sequence_no)

    def _consume_legacy_event(
        self,
        *,
        event: StreamEvent,
        sequence_no: int,
    ) -> tuple[SessionStreamEvent, ...]:
        """Consume the current shared stream contract."""

        if event.event_type == "message_started":
            return (
                SessionStreamEvent(
                    event_type="response.started",
                    trace_id=self.trace_id,
                    session_id=self.session_id,
                    data={"schema_version": "1.0"},
                    sequence_no=sequence_no,
                ),
            )

        if event.event_type == "content_delta":
            delta = event.data.get("text")
            if not isinstance(delta, str) or not delta:
                return ()
            self.answer_parts.append(delta)
            return (
                SessionStreamEvent(
                    event_type="response.delta",
                    trace_id=self.trace_id,
                    session_id=self.session_id,
                    data={"delta": delta},
                    sequence_no=sequence_no,
                ),
            )

        if event.event_type == "tool_call_summary":
            self.tool_calls.append(dict(event.data))
            return ()

        if event.event_type == "agent_summary":
            agent_name = event.data.get("agent_name")
            strategy_name = event.data.get("strategy_name")
            llm_profile = event.data.get("llm_profile")
            self.agent_name = agent_name if isinstance(agent_name, str) else None
            self.strategy_name = strategy_name if isinstance(strategy_name, str) else None
            self.llm_profile = llm_profile if isinstance(llm_profile, str) else None
            self.metadata.update(
                {
                    key: value
                    for key, value in event.data.items()
                    if key not in {"agent_name", "strategy_name", "llm_profile"}
                }
            )
            return (
                SessionStreamEvent(
                    event_type="response.metadata",
                    trace_id=self.trace_id,
                    session_id=self.session_id,
                    data={
                        "agent_name": self.agent_name,
                        "strategy_name": self.strategy_name,
                        "llm_profile": self.llm_profile,
                        "usecase": self.usecase,
                        "tool_call_count": len(self.tool_calls),
                        "memory_result_count": 0,
                    },
                    sequence_no=sequence_no,
                ),
            )

        if event.event_type == "trace_summary":
            self.metadata.update({"trace_summary": dict(event.data)})
            return ()

        if event.event_type == "message_completed":
            finish_reason = event.data.get("finish_reason")
            if isinstance(finish_reason, str) and finish_reason.strip():
                self.finish_reason = finish_reason
            return ()

        if event.event_type == "error":
            message = event.data.get("message")
            if isinstance(message, str) and message.strip():
                raise RuntimeError(message)
            raise RuntimeError("Streaming orchestration failed.")

        return ()

    def _consume_orchestration_event(
        self,
        *,
        event: OrchestrationStreamEvent,
        sequence_no: int,
    ) -> tuple[SessionStreamEvent, ...]:
        """Consume the new orchestration-owned stream contract."""

        if event.type == "orchestration.started":
            return (
                SessionStreamEvent(
                    event_type="response.started",
                    trace_id=self.trace_id,
                    session_id=self.session_id,
                    data={"schema_version": "1.0"},
                    sequence_no=sequence_no,
                ),
            )

        if event.type == "strategy.selected":
            self._apply_summary_data(event.metadata)
            return ()

        if event.type == "response.delta":
            delta = event.text or _read_delta_text(event.metadata)
            if delta is None:
                return ()
            self.answer_parts.append(delta)
            return (
                SessionStreamEvent(
                    event_type="response.delta",
                    trace_id=self.trace_id,
                    session_id=self.session_id,
                    data={"delta": delta},
                    sequence_no=sequence_no,
                ),
            )

        if event.type == "orchestration.completed":
            emitted_events: list[SessionStreamEvent] = []
            if event.result is not None:
                self.runtime_result = event.result
                self.agent_name = event.result.agent_name
                self.strategy_name = event.result.strategy_name
                self.llm_profile = event.result.llm_profile
                self.tool_calls = [item.as_legacy_dict() for item in event.result.tool_calls]
                self.metadata.update(dict(event.result.metadata))
            self._apply_summary_data(event.metadata)
            emitted_events.append(
                SessionStreamEvent(
                    event_type="response.metadata",
                    trace_id=self.trace_id,
                    session_id=self.session_id,
                    data={
                        "agent_name": self.agent_name,
                        "strategy_name": self.strategy_name,
                        "llm_profile": self.llm_profile,
                        "usecase": self.usecase,
                        "tool_call_count": len(self.tool_calls),
                        "memory_result_count": 0,
                    },
                    sequence_no=sequence_no,
                )
            )
            if event.result is not None:
                emitted_events.extend(
                    self._artifact_session_events(
                        artifacts=event.result.artifacts,
                        start_sequence_no=sequence_no + len(emitted_events),
                    )
                )
            return tuple(emitted_events)

        if event.type == "response.completed":
            finish_reason = event.metadata.get("finish_reason")
            if isinstance(finish_reason, str) and finish_reason.strip():
                self.finish_reason = finish_reason
            return ()

        if event.type == "orchestration.error":
            if event.error is not None:
                raise RuntimeError(event.error.message)
            raise RuntimeError("Streaming orchestration failed.")

        if event.type == "orchestration.cancelled":
            raise RuntimeError("Streaming orchestration cancelled.")

        return ()

    def _apply_summary_data(self, payload: dict[str, Any]) -> None:
        agent_name = payload.get("agent_name")
        strategy_name = payload.get("strategy_name")
        llm_profile = payload.get("llm_profile")
        self.agent_name = agent_name if isinstance(agent_name, str) else self.agent_name
        self.strategy_name = strategy_name if isinstance(strategy_name, str) else self.strategy_name
        self.llm_profile = llm_profile if isinstance(llm_profile, str) else self.llm_profile
        self.metadata.update(
            {
                key: value
                for key, value in payload.items()
                if key not in {"agent_name", "strategy_name", "llm_profile"}
            }
        )

    def build_result(self) -> OrchestrationResult:
        """Return the accumulated orchestration result for final state save."""

        if self.runtime_result is not None:
            answer = "".join(self.answer_parts) or self.runtime_result.answer
            return build_orchestration_result(
                answer=answer,
                session_id=self.runtime_result.session_id,
                trace_id=self.runtime_result.trace_id,
                usecase=self.runtime_result.usecase,
                strategy_name=self.strategy_name or self.runtime_result.strategy_name,
                agent_name=self.agent_name or self.runtime_result.agent_name,
                llm_profile=self.llm_profile or self.runtime_result.llm_profile,
                steps=self.runtime_result.steps,
                tool_calls=self.runtime_result.tool_calls,
                memory_searches=self.runtime_result.memory_searches,
                memory_updates=self.runtime_result.memory_updates,
                citations=self.runtime_result.citations,
                artifacts=self.runtime_result.artifacts,
                context_contributions=self.runtime_result.context_contributions,
                state_delta=_merge_state_delta(
                    existing=self.runtime_result.state_delta,
                    answer=answer,
                    usecase=self.runtime_result.usecase,
                    agent_name=self.agent_name or self.runtime_result.agent_name,
                    strategy_name=self.strategy_name or self.runtime_result.strategy_name,
                    llm_profile=self.llm_profile or self.runtime_result.llm_profile,
                ),
                finish_reason=self.finish_reason,
                duration_ms=self.runtime_result.duration_ms,
                metadata={**dict(self.runtime_result.metadata), **dict(self.metadata)},
            )

        answer = "".join(self.answer_parts)
        return build_orchestration_result(
            answer=answer,
            session_id=self.session_id,
            trace_id=self.trace_id,
            usecase=self.usecase,
            strategy_name=self.strategy_name or "unknown_strategy",
            agent_name=self.agent_name,
            llm_profile=self.llm_profile,
            tool_calls=[dict(item) for item in self.tool_calls],
            memory_updates=[],
            state_delta=_merge_state_delta(
                existing=None,
                answer=answer,
                usecase=self.usecase,
                agent_name=self.agent_name,
                strategy_name=self.strategy_name,
                llm_profile=self.llm_profile,
            ),
            finish_reason=self.finish_reason,
            metadata=dict(self.metadata),
        )

    def completion_event(self, *, sequence_no: int, duration_ms: int) -> SessionStreamEvent:
        """Build the terminal response.completed event."""

        return SessionStreamEvent(
            event_type="response.completed",
            trace_id=self.trace_id,
            session_id=self.session_id,
            data={"finish_reason": self.finish_reason, "duration_ms": duration_ms},
            sequence_no=sequence_no,
        )

    def _artifact_session_events(
        self,
        *,
        artifacts: list[Any],
        start_sequence_no: int,
    ) -> list[SessionStreamEvent]:
        events: list[SessionStreamEvent] = []
        next_sequence_no = start_sequence_no
        for artifact in artifacts:
            payload = artifact.model_dump(mode="python")
            events.append(
                SessionStreamEvent(
                    event_type="artifact.started",
                    trace_id=self.trace_id,
                    session_id=self.session_id,
                    data={
                        "artifact_id": artifact.artifact_id,
                        "type": artifact.type,
                        "chart_type": artifact.chart_type,
                        "renderer": artifact.renderer,
                        "spec_version": artifact.spec_version,
                        "data_mode": artifact.data_mode,
                    },
                    sequence_no=next_sequence_no,
                )
            )
            next_sequence_no += 1
            events.append(
                SessionStreamEvent(
                    event_type="artifact.completed",
                    trace_id=self.trace_id,
                    session_id=self.session_id,
                    data={"artifact": payload},
                    sequence_no=next_sequence_no,
                )
            )
            next_sequence_no += 1
        return events


def _read_delta_text(data: dict[str, Any]) -> str | None:
    delta = data.get("text")
    if isinstance(delta, str) and delta:
        return delta
    delta = data.get("delta")
    if isinstance(delta, str) and delta:
        return delta
    return None


def _merge_state_delta(
    *,
    existing: WorkflowStateDelta | None,
    answer: str,
    usecase: str,
    agent_name: str | None,
    strategy_name: str | None,
    llm_profile: str | None,
) -> WorkflowStateDelta:
    metadata_patch = {
        key: value
        for key, value in {
            "last_strategy": strategy_name,
            "last_agent": agent_name,
            "last_llm_profile": llm_profile,
        }.items()
        if value is not None
    }
    message_metadata = {
        key: value
        for key, value in {
            "agent_name": agent_name,
            "strategy_name": strategy_name,
            "llm_profile": llm_profile,
        }.items()
        if value is not None
    }
    append_messages = [
        ConversationMessage(
            role="assistant",
            content=answer,
            metadata=message_metadata,
        )
    ]
    if existing is None:
        return WorkflowStateDelta(
            append_messages=append_messages,
            set_active_usecase=usecase,
            set_active_agent=agent_name,
            metadata_patch=metadata_patch,
        )

    return WorkflowStateDelta(
        append_messages=append_messages,
        set_active_usecase=existing.set_active_usecase or usecase,
        set_active_agent=existing.set_active_agent or agent_name,
        append_step_summaries=existing.append_step_summaries,
        append_pending_approvals=existing.append_pending_approvals,
        metadata_patch={**dict(existing.metadata_patch), **metadata_patch},
    )