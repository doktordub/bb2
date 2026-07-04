"""Protocol and default implementation for the session boundary."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from time import perf_counter
from types import SimpleNamespace
from typing import Any, Protocol, cast

from app.config.view import ConversationContextSettings, SessionSettings, get_orchestration_settings
from app.contracts.config import ConfigurationView
from app.contracts.context import OrchestrationContext, RequestContext
from app.contracts.errors import ConfigurationError
from app.contracts.policy import PolicyService
from app.contracts.state import WorkflowStateRecord, WorkflowStateSaveResult, WorkflowStateStore
from app.observability.events import (
    SESSION_CREATED,
    SESSION_RESUMED,
    SESSION_RESET,
    STREAM_CANCELLED,
    STREAM_COMPLETED,
    STREAM_FAILED,
    STREAM_STARTED,
)
from app.observability.tracing import TraceRecorder
from app.orchestration.core import OrchestrationRuntime
from app.orchestration.models import OrchestrationResult
from app.persistence.errors import (
    WorkflowStateConflictError,
    WorkflowStateError as PersistenceWorkflowStateError,
)
from app.policy.session_policy import build_session_policy_request
from app.session.concurrency import map_conflict_error
from app.session.errors import (
    SessionDeleteDisabledError,
    SessionDeleteFailedError,
    SessionHistoryDisabledError,
    SessionHistoryUnavailableError,
    SessionListDisabledError,
    SessionListUnavailableError,
    SessionNotFoundError,
    SessionResetFailedError,
    SessionStateUnavailableError,
    UnknownUseCaseError,
)
from app.session.history import project_session_history
from app.session.identifiers import (
    PrefixedUuidSessionIdProvider,
    SessionIdProvider,
    resolve_session_id,
)
from app.session.lifecycle import (
    PreparedSessionState,
    SessionClock,
    SystemClock,
    apply_orchestration_result,
    mark_stream_failed,
    mark_stream_interrupted,
    prepare_state_for_chat,
    state_message_count,
)
from app.session.mapping import (
    build_core_request_context,
    build_session_orchestration_context,
    build_session_orchestration_request,
    orchestration_result_to_session_result,
)
from app.session.models import (
    SessionChatRequest,
    SessionChatResult,
    SessionDeleteResult,
    SessionHistoryResult,
    SessionListResult,
    SessionRequestContext,
    SessionResetResult,
    SessionStreamEvent,
)
from app.session.streaming import StreamAccumulator

_SESSION_COMPONENT = "session.service"


class SessionService(Protocol):
    """Thin session boundary consumed by API routes."""

    async def handle_chat(
        self,
        *,
        request: SessionChatRequest,
        context: SessionRequestContext,
    ) -> SessionChatResult:
        ...

    def stream_chat(
        self,
        *,
        request: SessionChatRequest,
        context: SessionRequestContext,
    ) -> AsyncIterator[SessionStreamEvent]:
        ...

    async def reset_session(
        self,
        *,
        session_id: str,
        reason: str | None,
        context: SessionRequestContext,
    ) -> SessionResetResult:
        ...

    async def get_history(
        self,
        *,
        session_id: str,
        limit: int,
        context: SessionRequestContext,
    ) -> SessionHistoryResult:
        ...

    async def list_sessions(
        self,
        *,
        limit: int | None,
        context: SessionRequestContext,
    ) -> SessionListResult:
        ...

    async def delete_session(
        self,
        *,
        session_id: str,
        context: SessionRequestContext,
    ) -> SessionDeleteResult:
        ...


@dataclass(slots=True)
class DefaultSessionService:
    """Own session continuity while delegating response generation to an orchestration runtime."""

    config: ConfigurationView
    settings: SessionSettings
    workflow_state: WorkflowStateStore
    trace_recorder: TraceRecorder
    orchestrator: OrchestrationRuntime
    policy_service: PolicyService | None = None
    id_provider: SessionIdProvider = field(default_factory=PrefixedUuidSessionIdProvider)
    clock: SessionClock = field(default_factory=SystemClock)

    async def handle_chat(
        self,
        *,
        request: SessionChatRequest,
        context: SessionRequestContext,
    ) -> SessionChatResult:
        started_at = perf_counter()
        session_id = self._resolve_session_id(request.session_id)
        usecase = self._resolve_usecase(request.usecase)
        request_context = build_core_request_context(
            request=request,
            context=context,
            session_id=session_id,
            default_usecase=usecase,
        )

        try:
            loaded = await self.workflow_state.load(session_id)
            prepared = prepare_state_for_chat(
                record=loaded,
                session_id=session_id,
                request_context=request_context,
                usecase=usecase,
                created_at=self.clock.now(),
            )
            orchestration_result = await self.orchestrator.run_turn(
                request=build_session_orchestration_request(
                    request_context=request_context,
                    state=prepared.state,
                    version=loaded.version,
                ),
                context=build_session_orchestration_context(request_context=request_context),
            )
            final_state = apply_orchestration_result(
                prepared.state,
                result=orchestration_result,
                conversation_context_settings=self._conversation_context_settings(),
                request_context=request_context,
                trace_id=context.trace_id,
                request_id=context.request_id,
                user_id_hash=context.user_id_hash,
                client_host=context.client_host,
                user_agent=context.user_agent,
                completed_at=self.clock.now(),
            )
            save_result = await self._save_chat_state(
                session_id=session_id,
                state=final_state,
                loaded=loaded,
                context=context,
                usecase=orchestration_result.usecase,
            )
        except WorkflowStateConflictError as exc:
            raise map_conflict_error(
                operation="chat",
                settings=self.settings.concurrency,
                error=exc,
            ) from exc
        except PersistenceWorkflowStateError as exc:
            raise SessionStateUnavailableError() from exc

        await self._record_event(
            event_name=SESSION_CREATED if prepared.loaded_empty else SESSION_RESUMED,
            trace_id=context.trace_id,
            session_id=session_id,
            user_id=context.user_id,
            usecase=orchestration_result.usecase,
            status="completed",
            duration_ms=_elapsed_ms(started_at),
            payload={
                "operation": "handle_chat",
                "loaded_empty": prepared.loaded_empty,
                "message_count_before": prepared.message_count_before,
                "message_count_after": _saved_message_count(save_result, final_state),
                "message_length": len(request.message),
                "metadata_count": len(request.metadata),
            },
            result=orchestration_result,
        )
        return _build_session_chat_result(
            result=orchestration_result,
            trace_id=context.trace_id,
            session_id=session_id,
            message_count=state_message_count(final_state),
            message_count_before=prepared.message_count_before,
        )

    async def stream_chat(
        self,
        *,
        request: SessionChatRequest,
        context: SessionRequestContext,
    ) -> AsyncIterator[SessionStreamEvent]:
        started_at = perf_counter()
        session_id = self._resolve_session_id(request.session_id)
        usecase = self._resolve_usecase(request.usecase)
        request_context = build_core_request_context(
            request=request,
            context=context,
            session_id=session_id,
            default_usecase=usecase,
        )
        loaded: WorkflowStateRecord | None = None
        prepared: PreparedSessionState | None = None
        cancellation_state: dict[str, Any] | None = None
        orchestration_result: OrchestrationResult | None = None
        accumulator: StreamAccumulator | None = None
        sequence_no = 0
        stream_completed = False

        try:
            loaded = await self.workflow_state.load(session_id)
            prepared = prepare_state_for_chat(
                record=loaded,
                session_id=session_id,
                request_context=request_context,
                usecase=usecase,
                created_at=self.clock.now(),
            )
            cancellation_state = prepared.state

            await self._record_event(
                event_name=STREAM_STARTED,
                trace_id=context.trace_id,
                session_id=session_id,
                user_id=context.user_id,
                usecase=usecase,
                status="started",
                duration_ms=0.0,
                payload={
                    "operation": "stream_chat",
                    "loaded_empty": prepared.loaded_empty,
                    "message_count_before": prepared.message_count_before,
                    "message_length": len(request.message),
                    "metadata_count": len(request.metadata),
                },
                result=None,
            )

            accumulator = StreamAccumulator(
                trace_id=context.trace_id,
                session_id=session_id,
                usecase=usecase,
            )
            async for runtime_event in self.orchestrator.stream_turn(
                request=build_session_orchestration_request(
                    request_context=request_context,
                    state=prepared.state,
                    version=loaded.version,
                ),
                context=build_session_orchestration_context(request_context=request_context),
            ):
                next_sequence_no = sequence_no + 1
                session_event = accumulator.consume(event=runtime_event, sequence_no=next_sequence_no)
                if session_event is not None:
                    sequence_no = next_sequence_no
                    yield session_event

            orchestration_result = accumulator.build_result()
            final_state = apply_orchestration_result(
                prepared.state,
                result=orchestration_result,
                conversation_context_settings=self._conversation_context_settings(),
                request_context=request_context,
                trace_id=context.trace_id,
                request_id=context.request_id,
                user_id_hash=context.user_id_hash,
                client_host=context.client_host,
                user_agent=context.user_agent,
                completed_at=self.clock.now(),
            )

            if self.settings.state.save_on_stream_completion:
                await self.workflow_state.save(
                    session_id,
                    final_state,
                    expected_version=loaded.version,
                    metadata=self._state_metadata(context=context, usecase=orchestration_result.usecase),
                )
            stream_completed = True
            cancellation_state = None

            sequence_no += 1
            yield accumulator.completion_event(
                sequence_no=sequence_no,
                duration_ms=0,
            )

            await self._record_event(
                event_name=STREAM_COMPLETED,
                trace_id=context.trace_id,
                session_id=session_id,
                user_id=context.user_id,
                usecase=orchestration_result.usecase,
                status="completed",
                duration_ms=_elapsed_ms(started_at),
                payload={
                    "operation": "stream_chat",
                    "loaded_empty": prepared.loaded_empty,
                    "message_count_before": prepared.message_count_before,
                    "message_count_after": state_message_count(final_state),
                    "chunk_count": len(accumulator.answer_parts) if accumulator is not None else 0,
                },
                result=orchestration_result,
            )
        except WorkflowStateConflictError as exc:
            raise map_conflict_error(
                operation="stream",
                settings=self.settings.concurrency,
                error=exc,
            ) from exc
        except PersistenceWorkflowStateError as exc:
            raise SessionStateUnavailableError() from exc
        except GeneratorExit:
            if stream_completed:
                raise
            if loaded is not None and cancellation_state is not None and self.settings.state.save_on_stream_cancellation:
                await self._save_interrupted_stream(
                    session_id=session_id,
                    loaded=loaded,
                    state=cancellation_state,
                    context=context,
                    usecase=usecase,
                    operation="stream",
                )
            await self._record_event(
                event_name=STREAM_CANCELLED,
                trace_id=context.trace_id,
                session_id=session_id,
                user_id=context.user_id,
                usecase=usecase,
                status="cancelled",
                duration_ms=_elapsed_ms(started_at),
                payload={
                    "operation": "stream_chat",
                    "message_count_after": (
                        state_message_count(cancellation_state)
                        if cancellation_state is not None
                        else 0
                    ),
                },
                result=orchestration_result,
            )
            raise
        except BaseException as exc:
            if isinstance(exc, asyncio.CancelledError):
                if stream_completed:
                    raise
                if (
                    loaded is not None
                    and cancellation_state is not None
                    and self.settings.state.save_on_stream_cancellation
                ):
                    await self._save_interrupted_stream(
                        session_id=session_id,
                        loaded=loaded,
                        state=cancellation_state,
                        context=context,
                        usecase=usecase,
                        operation="stream",
                    )
                await self._record_event(
                    event_name=STREAM_CANCELLED,
                    trace_id=context.trace_id,
                    session_id=session_id,
                    user_id=context.user_id,
                    usecase=usecase,
                    status="cancelled",
                    duration_ms=_elapsed_ms(started_at),
                    payload={
                        "operation": "stream_chat",
                        "message_count_after": (
                            state_message_count(cancellation_state)
                            if cancellation_state is not None
                            else 0
                        ),
                    },
                    result=orchestration_result,
                )
                raise

            if loaded is not None and cancellation_state is not None and self.settings.state.save_on_stream_failure:
                await self._save_failed_stream(
                    session_id=session_id,
                    loaded=loaded,
                    state=cancellation_state,
                    context=context,
                    usecase=usecase,
                    operation="stream",
                )
            await self._record_event(
                event_name=STREAM_FAILED,
                trace_id=context.trace_id,
                session_id=session_id,
                user_id=context.user_id,
                usecase=usecase,
                status="failed",
                duration_ms=_elapsed_ms(started_at),
                payload={
                    "operation": "stream_chat",
                    "message_count_after": (
                        state_message_count(cancellation_state) if cancellation_state is not None else 0
                    ),
                    "error_type": type(exc).__name__,
                },
                result=orchestration_result,
            )
            raise

    async def get_history(
        self,
        *,
        session_id: str,
        limit: int,
        context: SessionRequestContext,
    ) -> SessionHistoryResult:
        started_at = perf_counter()
        if not self.settings.history.enabled:
            raise SessionHistoryDisabledError()

        normalized_session_id = self._resolve_session_id(session_id)
        bounded_limit = max(1, min(limit, self.settings.defaults.max_history_limit))

        try:
            loaded = await self.workflow_state.load(normalized_session_id)
        except PersistenceWorkflowStateError as exc:
            raise SessionHistoryUnavailableError() from exc

        if self.policy_service is not None:
            await self.policy_service.require_allowed(
                build_session_policy_request(
                    action="session.read_history",
                    component=_SESSION_COMPONENT,
                    session_id=normalized_session_id,
                    user_id=context.user_id,
                    user_id_hash=context.user_id_hash,
                    usecase_name=_metadata_text(loaded.state, "usecase") or self.settings.defaults.default_usecase,
                    owner_user_id=_metadata_text(loaded.state, "user_id"),
                    owner_user_id_hash=_metadata_text(loaded.state, "user_id_hash"),
                    extra_metadata={"path": context.path, "method": context.method},
                ),
                self._build_policy_context(context=context, session_id=normalized_session_id),
            )

        result = project_session_history(
            trace_id=context.trace_id,
            session_id=normalized_session_id,
            state=loaded.state,
            limit=bounded_limit,
            settings=self.settings.history,
        )
        await self._record_history_returned(
            context=context,
            session_id=normalized_session_id,
            limit=bounded_limit,
            message_count=len(result.messages),
            truncated=result.truncated,
            duration_ms=_elapsed_ms(started_at),
        )
        return result

    async def list_sessions(
        self,
        *,
        limit: int | None,
        context: SessionRequestContext,
    ) -> SessionListResult:
        if not self.settings.management.list_enabled:
            raise SessionListDisabledError()

        resolved_limit = self.settings.management.default_list_limit if limit is None else limit
        bounded_limit = max(1, min(resolved_limit, self.settings.management.max_list_limit))

        try:
            listed = await self.workflow_state.list_sessions(limit=bounded_limit)
        except PersistenceWorkflowStateError as exc:
            raise SessionListUnavailableError() from exc

        return SessionListResult.from_workflow_result(listed, trace_id=context.trace_id)

    async def delete_session(
        self,
        *,
        session_id: str,
        context: SessionRequestContext,
    ) -> SessionDeleteResult:
        if not self.settings.management.delete_enabled:
            raise SessionDeleteDisabledError()

        normalized_session_id = self._resolve_session_id(session_id)

        try:
            deleted = await self.workflow_state.delete_session(normalized_session_id)
        except PersistenceWorkflowStateError as exc:
            raise SessionDeleteFailedError() from exc

        result = SessionDeleteResult.from_workflow_result(deleted, trace_id=context.trace_id)
        if not result.deleted:
            raise SessionNotFoundError()
        return result

    async def reset_session(
        self,
        *,
        session_id: str,
        reason: str | None,
        context: SessionRequestContext,
    ) -> SessionResetResult:
        started_at = perf_counter()
        normalized_session_id = self._resolve_session_id(session_id)
        try:
            loaded = await self.workflow_state.load(normalized_session_id)
            if self.policy_service is not None:
                await self.policy_service.require_allowed(
                    build_session_policy_request(
                        action="session.reset",
                        component=_SESSION_COMPONENT,
                        session_id=normalized_session_id,
                        user_id=context.user_id,
                        user_id_hash=context.user_id_hash,
                        usecase_name=_metadata_text(loaded.state, "usecase"),
                        owner_user_id=_metadata_text(loaded.state, "user_id"),
                        owner_user_id_hash=_metadata_text(loaded.state, "user_id_hash"),
                        extra_metadata={"reason": reason, "path": context.path, "method": context.method},
                    ),
                    self._build_policy_context(context=context, session_id=normalized_session_id),
                )
            await self.workflow_state.reset(
                normalized_session_id,
                reason=reason,
                metadata=self._state_metadata(context=context, usecase=None),
            )
        except WorkflowStateConflictError as exc:
            raise map_conflict_error(
                operation="reset",
                settings=self.settings.concurrency,
                error=exc,
            ) from exc
        except PersistenceWorkflowStateError as exc:
            raise SessionResetFailedError() from exc

        await self._record_event(
            event_name=SESSION_RESET,
            trace_id=context.trace_id,
            session_id=normalized_session_id,
            user_id=context.user_id,
            usecase=None,
            status="completed",
            duration_ms=_elapsed_ms(started_at),
            payload={"operation": "reset_session", "reason": reason},
            result=None,
        )
        return SessionResetResult(
            session_id=normalized_session_id,
            trace_id=context.trace_id,
            reset=True,
            message="Session workflow state was reset.",
            metadata={"reason": reason},
        )

    def _resolve_session_id(self, session_id: str | None) -> str:
        return resolve_session_id(
            session_id,
            generate_when_missing=self.settings.identifiers.generate_when_missing,
            id_provider=self.id_provider,
            allowed_pattern=self.settings.identifiers.allowed_pattern,
            max_length=self.settings.identifiers.max_length,
        )

    def _resolve_usecase(self, requested_usecase: str | None) -> str:
        resolved = requested_usecase or self.settings.defaults.default_usecase
        usecase = self.config.section("usecases").get(resolved)
        if not isinstance(usecase, Mapping) or not bool(usecase.get("enabled", True)):
            raise UnknownUseCaseError()
        return resolved

    async def _save_chat_state(
        self,
        *,
        session_id: str,
        state: dict[str, Any],
        loaded: WorkflowStateRecord,
        context: SessionRequestContext,
        usecase: str,
    ) -> WorkflowStateSaveResult | None:
        if not self.settings.state.save_on_chat_completion:
            return None

        return await self.workflow_state.save(
            session_id,
            state,
            expected_version=loaded.version,
            metadata=self._state_metadata(context=context, usecase=usecase),
        )

    async def _save_interrupted_stream(
        self,
        *,
        session_id: str,
        loaded: WorkflowStateRecord,
        state: dict[str, Any],
        context: SessionRequestContext,
        usecase: str,
        operation: str,
    ) -> None:
        try:
            await self.workflow_state.save(
                session_id,
                mark_stream_interrupted(
                    state,
                    conversation_context_settings=self._conversation_context_settings(),
                    interrupted_at=self.clock.now(),
                ),
                expected_version=loaded.version,
                metadata=self._state_metadata(context=context, usecase=usecase),
            )
        except WorkflowStateConflictError as exc:
            raise map_conflict_error(
                operation=operation,
                settings=self.settings.concurrency,
                error=exc,
            ) from exc

    async def _save_failed_stream(
        self,
        *,
        session_id: str,
        loaded: WorkflowStateRecord,
        state: dict[str, Any],
        context: SessionRequestContext,
        usecase: str,
        operation: str,
    ) -> None:
        try:
            await self.workflow_state.save(
                session_id,
                mark_stream_failed(
                    state,
                    conversation_context_settings=self._conversation_context_settings(),
                    failed_at=self.clock.now(),
                ),
                expected_version=loaded.version,
                metadata=self._state_metadata(context=context, usecase=usecase),
            )
        except WorkflowStateConflictError as exc:
            raise map_conflict_error(
                operation=operation,
                settings=self.settings.concurrency,
                error=exc,
            ) from exc

    def _state_metadata(
        self,
        *,
        context: SessionRequestContext,
        usecase: str | None,
    ) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "trace_id": context.trace_id,
            "request_id": context.request_id,
            "user_id": context.user_id,
        }
        if usecase is not None:
            metadata["usecase"] = usecase
        if context.user_id_hash is not None:
            metadata["user_id_hash"] = context.user_id_hash
        return metadata

    def _build_policy_context(
        self,
        *,
        context: SessionRequestContext,
        session_id: str,
    ) -> OrchestrationContext:
        request = RequestContext(
            user_id=context.user_id,
            session_id=session_id,
            message="",
            usecase=self.settings.defaults.default_usecase,
            trace_id=context.trace_id,
            metadata={
                "request_id": context.request_id,
                "user_id_hash": context.user_id_hash,
                "path": context.path,
                "method": context.method,
            },
        )
        return cast(
            OrchestrationContext,
            SimpleNamespace(
                request=request,
                config=self.config,
                runtime_metadata={
                    "usecase_name": self.settings.defaults.default_usecase,
                    "session_id": session_id,
                    "user_id": context.user_id,
                },
            ),
        )

    def _conversation_context_settings(self) -> ConversationContextSettings:
        try:
            return get_orchestration_settings(self.config).defaults.conversation_context
        except ConfigurationError:
            return ConversationContextSettings(
                enabled=False,
                mode="window",
                max_messages=12,
                max_chars=12000,
                include_assistant_messages=True,
                summary_threshold_messages=24,
                summary_max_chars=2000,
            )

    async def _record_event(
        self,
        *,
        event_name: str,
        trace_id: str,
        session_id: str,
        user_id: str,
        usecase: str | None,
        status: str,
        duration_ms: float,
        payload: dict[str, Any],
        result: OrchestrationResult | None,
    ) -> None:
        if not self._should_record_event(event_name):
            return

        await self.trace_recorder.record(
            event_type="session",
            event_name=event_name,
            component=_SESSION_COMPONENT,
            trace_id=trace_id,
            session_id=session_id,
            user_id=user_id,
            usecase=usecase,
            agent_name=None if result is None else result.agent_name,
            strategy_name=None if result is None else result.strategy_name,
            llm_profile=None if result is None else result.llm_profile,
            status=status,
            duration_ms=duration_ms,
            payload=payload,
        )

    async def _record_history_returned(
        self,
        *,
        context: SessionRequestContext,
        session_id: str,
        limit: int,
        message_count: int,
        truncated: bool,
        duration_ms: float,
    ) -> None:
        if not self.settings.tracing.record_history_returned:
            return

        await self.trace_recorder.record(
            event_type="session",
            event_name="session_history_returned",
            component=_SESSION_COMPONENT,
            trace_id=context.trace_id,
            session_id=session_id,
            user_id=context.user_id,
            status="completed",
            duration_ms=duration_ms,
            payload={
                "operation": "get_history",
                "limit": limit,
                "message_count": message_count,
                "truncated": truncated,
            },
        )

    def _should_record_event(self, event_name: str) -> bool:
        tracing = self.settings.tracing
        event_map = {
            SESSION_CREATED: tracing.record_session_created,
            SESSION_RESUMED: tracing.record_session_resumed,
            SESSION_RESET: tracing.record_session_reset,
            STREAM_STARTED: tracing.record_stream_lifecycle,
            STREAM_COMPLETED: tracing.record_stream_lifecycle,
            STREAM_CANCELLED: tracing.record_stream_lifecycle,
            STREAM_FAILED: tracing.record_stream_lifecycle,
        }
        return event_map.get(event_name, True)


class WalkingSkeletonSessionService(DefaultSessionService):
    """Backward-compatible alias retained for older tests and historical API naming."""


def _build_session_chat_result(
    *,
    result: OrchestrationResult,
    trace_id: str,
    session_id: str,
    message_count: int,
    message_count_before: int,
) -> SessionChatResult:
    base_result = orchestration_result_to_session_result(result, trace_id=trace_id)
    metadata = {
        "usecase": result.usecase,
        "message_count": message_count,
        "message_count_before": message_count_before,
    }
    return SessionChatResult(
        answer=base_result.answer,
        session_id=session_id,
        trace_id=trace_id,
        agent_name=base_result.agent_name,
        strategy_name=base_result.strategy_name,
        llm_profile=base_result.llm_profile,
        tool_calls=base_result.tool_calls,
        memory_updates=base_result.memory_updates,
        metadata=metadata,
    )


def _saved_message_count(
    save_result: WorkflowStateSaveResult | None,
    state: dict[str, Any],
) -> int:
    if save_result is not None:
        return save_result.message_count
    return state_message_count(state)


def _elapsed_ms(started_at: float) -> float:
    return max((perf_counter() - started_at) * 1000.0, 0.0)


def _metadata_text(state: dict[str, Any], key: str) -> str | None:
    metadata = state.get("metadata")
    if not isinstance(metadata, dict):
        return None
    value = metadata.get(key)
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None
