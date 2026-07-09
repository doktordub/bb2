"""Session-facing orchestration runtime implementations and compatibility adapters."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field, replace
import logging
from time import perf_counter
from typing import Any, Protocol, TypeVar

from app.contracts.agents import AgentPlugin
from app.config.view import (
    OrchestrationSettings,
    build_runtime_redactor,
    get_agents_settings,
    get_observability_settings,
    get_orchestration_settings,
)
from app.contracts.config import ConfigurationView
from app.contracts.context import OrchestrationContext, RequestContext
from app.contracts.health import HEALTH_OK
from app.contracts.llm import LLMGateway
from app.contracts.memory import MemoryGateway
from app.contracts.policy import PolicyRequest, PolicyService
from app.contracts.results import OrchestrationResult as LegacyOrchestrationResult
from app.contracts.results import StreamEvent
from app.contracts.state import WorkflowStateDocument, WorkflowStateStore
from app.contracts.tools import (
    ToolCallRequest,
    ToolCapabilitiesResult,
    ToolErrorDetail,
    ToolExecutionRequest,
    ToolExecutionResult,
    ToolGateway,
    ToolHealthResult,
    ToolListResult,
    ToolResultSummary,
    ToolScopes,
    ToolSpec,
    ToolStreamEvent,
)
from app.contracts.trace import STRATEGY_SELECTED, TraceStore
from app.observability.tracing import RecorderTraceStoreAdapter, TraceRecorder
from app.orchestration.capabilities import (
    OrchestrationCapabilitiesResult,
    OrchestrationUseCaseCapability,
    build_orchestration_capabilities,
)
from app.orchestration.cancellation import raise_if_cancelled
from app.orchestration.context import build_orchestration_request, build_runtime_context
from app.orchestration.errors import OrchestrationCancelledError, OrchestrationError, normalize_orchestration_error
from app.orchestration.events import OrchestrationStreamEvent
from app.orchestration.fallback import FallbackDecision, enforce_fallback_policy
from app.orchestration.health import OrchestrationHealthResult, build_orchestration_health
from app.orchestration.limits import OrchestrationLimitTracker
from app.orchestration.models import (
    ConversationMessage,
    MemorySearchSummary,
    MemoryUpdateSummary,
    OrchestrationRequest,
    OrchestrationResult,
    OrchestrationRuntimeContext,
    OrchestrationStepSummary,
)
from app.orchestration.registry import AgentRegistry
from app.orchestration.result_builder import build_orchestration_result, orchestration_result_to_contract
from app.orchestration.state_delta import WorkflowStateDelta
from app.orchestration.stream_mapping import map_stream_event
from app.orchestration.strategy_factory import build_strategy_registry
from app.orchestration.strategy_registry import StrategyDescriptor, StrategyRegistry
from app.orchestration.trace_helpers import (
    build_completed_trace_payload,
    build_fallback_trace_payload,
    build_failure_trace_payload,
    build_selected_trace_payload,
    build_started_trace_payload,
)
from app.orchestration.usecase_router import ResolvedUseCaseRoute, UseCaseRouter
from app.policy.usecase_policy import build_usecase_policy_request

ORCHESTRATION_COMPONENT = "orchestration.runtime"
ORCHESTRATION_STARTED = "orchestration_started"
ORCHESTRATION_COMPLETED = "orchestration_completed"
ORCHESTRATION_FAILED = "orchestration_failed"
ORCHESTRATION_CANCELLED = "orchestration_cancelled"
ORCHESTRATION_FALLBACK_USED = "strategy_fallback_used"

logger = logging.getLogger(__name__)

_RuntimeT = TypeVar("_RuntimeT", bound="DefaultOrchestrationRuntime")


class OrchestrationRuntime(Protocol):
    """Public orchestration runtime boundary plus temporary phase-4 compatibility methods."""

    async def run_turn(
        self,
        *,
        request: OrchestrationRequest,
        context: OrchestrationRuntimeContext,
    ) -> OrchestrationResult:
        ...

    def stream_turn(
        self,
        *,
        request: OrchestrationRequest,
        context: OrchestrationRuntimeContext,
    ) -> AsyncIterator[OrchestrationStreamEvent]:
        ...

    async def health(self) -> OrchestrationHealthResult:
        ...

    async def capabilities(self) -> OrchestrationCapabilitiesResult:
        ...

    async def run(
        self,
        *,
        request: RequestContext,
        state: WorkflowStateDocument,
    ) -> LegacyOrchestrationResult:
        ...

    def stream(
        self,
        *,
        request: RequestContext,
        state: WorkflowStateDocument,
    ) -> AsyncIterator[StreamEvent | OrchestrationStreamEvent]:
        ...


@dataclass(slots=True)
class EchoOrchestrationRuntime:
    """Temporary echo runtime that also satisfies the phase-4 public interface."""

    answer_prefix: str = "Echo: "
    agent_name: str = "fake_session_agent"
    strategy_name: str = "fake_direct_strategy"
    llm_profile: str = "fake_local_profile"
    default_usecase: str = "default_chat"

    async def run_turn(
        self,
        *,
        request: OrchestrationRequest,
        context: OrchestrationRuntimeContext,
    ) -> OrchestrationResult:
        _ = context
        return self._build_result(request=request, finish_reason="stop", duration_ms=0)

    async def stream_turn(
        self,
        *,
        request: OrchestrationRequest,
        context: OrchestrationRuntimeContext,
    ) -> AsyncIterator[OrchestrationStreamEvent]:
        _ = context
        result = self._build_result(request=request, finish_reason="stop", duration_ms=0)
        yield OrchestrationStreamEvent.started(
            trace_id=request.trace_id,
            session_id=request.session_id,
            metadata={"usecase": result.usecase},
        )
        yield OrchestrationStreamEvent.strategy_selected(
            trace_id=request.trace_id,
            session_id=request.session_id,
            strategy_name=self.strategy_name,
            usecase=result.usecase,
            agent_name=self.agent_name,
            llm_profile=self.llm_profile,
        )
        for chunk in _chunk_text(result.answer):
            yield OrchestrationStreamEvent.response_delta(
                trace_id=request.trace_id,
                session_id=request.session_id,
                text=chunk,
            )
        yield OrchestrationStreamEvent.completed(
            trace_id=request.trace_id,
            session_id=request.session_id,
            result=result,
            metadata={
                "agent_name": self.agent_name,
                "strategy_name": self.strategy_name,
                "llm_profile": self.llm_profile,
            },
        )
        yield OrchestrationStreamEvent.response_completed(
            trace_id=request.trace_id,
            session_id=request.session_id,
            finish_reason=result.finish_reason,
        )

    async def health(self) -> OrchestrationHealthResult:
        return OrchestrationHealthResult(
            status=HEALTH_OK,
            enabled=True,
            registry_ready=True,
            default_strategy=self.strategy_name,
            fallback_strategy=self.strategy_name,
            configured_strategy_count=1,
            enabled_strategy_count=1,
            registered_strategy_count=1,
            configured_usecase_count=1,
            enabled_usecase_count=1,
            configured_agent_count=1,
            agent_registry_status=HEALTH_OK,
            strategies=(),
            metadata={"runtime": "echo"},
        )

    async def capabilities(self) -> OrchestrationCapabilitiesResult:
        return OrchestrationCapabilitiesResult(
            enabled=True,
            default_strategy=self.strategy_name,
            fallback_strategy=self.strategy_name,
            usecases=[
                OrchestrationUseCaseCapability(
                    name=self.default_usecase,
                    display_name=None,
                    description=None,
                    strategy=self.strategy_name,
                    strategy_type="echo",
                    streaming_supported=True,
                    agent=self.agent_name,
                    llm_profile=self.llm_profile,
                    memory_enabled=False,
                    tools_enabled=False,
                    metadata={"runtime": "echo"},
                )
            ],
            strategies=[
                StrategyDescriptor(
                    name=self.strategy_name,
                    type="echo",
                    enabled=True,
                    allowed_usecases=(self.default_usecase,),
                    default_agent=self.agent_name,
                    llm_profile=self.llm_profile,
                    description="Echo compatibility runtime.",
                    metadata={"runtime": "echo"},
                )
            ],
            metadata={"runtime": "echo"},
        )

    async def run(
        self,
        *,
        request: RequestContext,
        state: WorkflowStateDocument,
    ) -> LegacyOrchestrationResult:
        runtime_result = await self.run_turn(
            request=build_orchestration_request(request=request, state=state),
            context=build_runtime_context(request),
        )
        return orchestration_result_to_contract(runtime_result)

    async def stream(
        self,
        *,
        request: RequestContext,
        state: WorkflowStateDocument,
    ) -> AsyncIterator[OrchestrationStreamEvent]:
        async for event in self.stream_turn(
            request=build_orchestration_request(request=request, state=state),
            context=build_runtime_context(request),
        ):
            yield event

    def _build_result(
        self,
        *,
        request: OrchestrationRequest,
        finish_reason: str,
        duration_ms: int,
    ) -> OrchestrationResult:
        usecase = request.usecase or self.default_usecase
        answer = f"{self.answer_prefix}{request.message}"
        step_summary = OrchestrationStepSummary(
            step_id=f"{self.strategy_name}:1",
            step_type="strategy",
            status="completed",
            duration_ms=duration_ms,
            safe_message="Echo strategy completed.",
            metadata={"strategy_name": self.strategy_name, "agent_name": self.agent_name},
        )
        state_delta = WorkflowStateDelta(
            append_messages=[
                ConversationMessage(
                    role="assistant",
                    content=answer,
                    metadata={
                        "agent_name": self.agent_name,
                        "strategy_name": self.strategy_name,
                    },
                )
            ],
            set_active_usecase=usecase,
            set_active_agent=self.agent_name,
            append_step_summaries=[step_summary],
            metadata_patch={
                "last_strategy": self.strategy_name,
                "last_agent": self.agent_name,
                "last_llm_profile": self.llm_profile,
            },
        )
        return build_orchestration_result(
            answer=answer,
            session_id=request.session_id,
            trace_id=request.trace_id,
            usecase=usecase,
            strategy_name=self.strategy_name,
            agent_name=self.agent_name,
            llm_profile=self.llm_profile,
            steps=[step_summary],
            state_delta=state_delta,
            finish_reason=finish_reason,
            duration_ms=duration_ms,
            metadata={"request_id": request.metadata.get("request_id"), "source": "echo_runtime"},
        )


@dataclass(slots=True)
class DefaultOrchestrationRuntime:
    """Phase-4 orchestration runtime that no longer receives persistence stores in context."""

    config: ConfigurationView
    llm_gateway: LLMGateway
    memory: MemoryGateway
    trace_recorder: TraceRecorder
    policy_service: PolicyService
    agent_registry: AgentRegistry
    strategy_registry: StrategyRegistry
    usecase_router: UseCaseRouter
    tools: ToolGateway = field(default_factory=lambda: _DisabledToolGateway())
    settings: OrchestrationSettings = field(init=False)

    def __post_init__(self) -> None:
        self.settings = get_orchestration_settings(self.config)

    @classmethod
    def from_config(
        cls: type[_RuntimeT],
        *,
        config: ConfigurationView,
        llm_gateway: LLMGateway,
        memory: MemoryGateway,
        state: WorkflowStateStore | None = None,
        trace: TraceStore | None = None,
        trace_recorder: TraceRecorder | None = None,
        policy_service: PolicyService,
        tools: ToolGateway | None = None,
    ) -> _RuntimeT:
        _ = state
        agent_registry = AgentRegistry.from_config(config)
        strategy_registry = build_strategy_registry(config)
        recorder = trace_recorder
        if recorder is None:
            if trace is None:
                raise ValueError("A trace store or trace recorder is required.")
            recorder = TraceRecorder(
                store=trace,
                settings=get_observability_settings(config),
                redactor=build_runtime_redactor(config),
            )
        return cls(
            config=config,
            llm_gateway=llm_gateway,
            memory=memory,
            trace_recorder=recorder,
            policy_service=policy_service,
            agent_registry=agent_registry,
            strategy_registry=strategy_registry,
            usecase_router=UseCaseRouter(config),
            tools=tools or _DisabledToolGateway(),
        )

    async def run_turn(
        self,
        *,
        request: OrchestrationRequest,
        context: OrchestrationRuntimeContext,
    ) -> OrchestrationResult:
        started_at = perf_counter()
        route: ResolvedUseCaseRoute | None = None
        limit_tracker: OrchestrationLimitTracker | None = None
        try:
            raise_if_cancelled(context.cancellation_token)
            await self._require_usecase_access(request=request, runtime=context)
            route = self._resolve_route(request)
            limit_tracker = OrchestrationLimitTracker.from_settings(self.settings, route.resolved_strategy.settings)
            limit_tracker.mark_turn_started()
            orchestration_context = self._build_context(
                request=request,
                runtime=context,
                route=route,
                limits=limit_tracker,
            )
            await self._record_runtime_event(
                event_name=ORCHESTRATION_STARTED,
                request=request,
                runtime=context,
                route=route,
                payload=build_started_trace_payload(
                    limits=limit_tracker,
                    state_version=None if request.workflow_state is None else request.workflow_state.version,
                ),
                status="started",
            )
            await self.policy_service.require_allowed(
                self._strategy_policy_request(route),
                orchestration_context,
            )
            await self._record_runtime_event(
                event_name=STRATEGY_SELECTED,
                request=request,
                runtime=context,
                route=route,
                payload=build_selected_trace_payload(strategy_source=route.resolved_strategy.source),
            )
            legacy_result = await route.resolved_strategy.strategy.run(
                context=orchestration_context,
                agents=self._strategy_agents(route),
            )
            raise_if_cancelled(context.cancellation_token)
            duration_ms = _elapsed_ms(started_at)
            runtime_result = self._build_runtime_result(
                request=request,
                runtime=context,
                route=route,
                legacy_result=legacy_result,
                finish_reason=_read_finish_reason(legacy_result.metadata),
                duration_ms=duration_ms,
            )
            await self._record_runtime_event(
                event_name=ORCHESTRATION_COMPLETED,
                request=request,
                runtime=context,
                route=route,
                duration_ms=float(duration_ms),
                payload=build_completed_trace_payload(runtime_result),
            )
            return runtime_result
        except Exception as exc:
            normalized = normalize_orchestration_error(exc)
            fallback = await self._try_fallback(
                request=request,
                runtime=context,
                route=route,
                limits=limit_tracker,
                error=normalized,
                started_at=started_at,
            )
            if fallback is not None:
                fallback_result, fallback_route, decision = fallback
                assert route is not None
                await self._record_runtime_event(
                    event_name=ORCHESTRATION_FALLBACK_USED,
                    request=request,
                    runtime=context,
                    route=fallback_route,
                    status="completed",
                    severity="warning",
                    duration_ms=float(fallback_result.duration_ms or _elapsed_ms(started_at)),
                    error=normalized,
                    payload=build_fallback_trace_payload(
                        failed_strategy=decision.failed_strategy or route.strategy_name,
                        fallback_strategy=decision.fallback_strategy or fallback_route.strategy_name,
                        reason=decision.reason,
                        error_code=decision.error.code,
                        retryable=decision.error.retryable,
                    ),
                )
                await self._record_runtime_event(
                    event_name=ORCHESTRATION_COMPLETED,
                    request=request,
                    runtime=context,
                    route=fallback_route,
                    duration_ms=float(fallback_result.duration_ms or _elapsed_ms(started_at)),
                    payload=build_completed_trace_payload(fallback_result),
                )
                return fallback_result
            duration_ms = _elapsed_ms(started_at)
            await self._record_runtime_event(
                event_name=(ORCHESTRATION_CANCELLED if isinstance(normalized, OrchestrationCancelledError) else ORCHESTRATION_FAILED),
                request=request,
                runtime=context,
                route=route,
                duration_ms=float(duration_ms),
                status="cancelled" if isinstance(normalized, OrchestrationCancelledError) else "failed",
                severity="warning" if isinstance(normalized, OrchestrationCancelledError) else "error",
                error=normalized,
                payload=build_failure_trace_payload(),
            )
            if normalized is exc:
                raise
            raise normalized from exc

    async def stream_turn(
        self,
        *,
        request: OrchestrationRequest,
        context: OrchestrationRuntimeContext,
    ) -> AsyncIterator[OrchestrationStreamEvent]:
        started_at = perf_counter()
        route: ResolvedUseCaseRoute | None = None
        runtime_result: OrchestrationResult | None = None
        answer_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        metadata: dict[str, Any] = {}
        finish_reason = "stop"
        agent_name: str | None = None
        llm_profile: str | None = None
        limit_tracker: OrchestrationLimitTracker | None = None

        try:
            raise_if_cancelled(context.cancellation_token)
            await self._require_usecase_access(request=request, runtime=context)
            route = self._resolve_route(request)
            limit_tracker = OrchestrationLimitTracker.from_settings(self.settings, route.resolved_strategy.settings)
            limit_tracker.mark_stream_started()
            orchestration_context = self._build_context(
                request=request,
                runtime=context,
                route=route,
                limits=limit_tracker,
            )
            await self._record_runtime_event(
                event_name=ORCHESTRATION_STARTED,
                request=request,
                runtime=context,
                route=route,
                payload=build_started_trace_payload(
                    limits=limit_tracker,
                    state_version=None if request.workflow_state is None else request.workflow_state.version,
                ),
                status="started",
            )
            limit_tracker.mark_stream_event()
            yield OrchestrationStreamEvent.started(
                trace_id=request.trace_id,
                session_id=request.session_id,
                metadata={"usecase": route.usecase.name},
            )

            await self.policy_service.require_allowed(
                self._strategy_policy_request(route),
                orchestration_context,
            )
            await self._record_runtime_event(
                event_name=STRATEGY_SELECTED,
                request=request,
                runtime=context,
                route=route,
                payload=build_selected_trace_payload(strategy_source=route.resolved_strategy.source),
            )
            limit_tracker.mark_stream_event()
            yield OrchestrationStreamEvent.strategy_selected(
                trace_id=request.trace_id,
                session_id=request.session_id,
                strategy_name=route.strategy_name,
                usecase=route.usecase.name,
                agent_name=route.agent_name,
                llm_profile=route.llm_profile,
                metadata={"strategy_source": route.resolved_strategy.source},
            )

            async for raw_event in route.resolved_strategy.strategy.stream(
                context=orchestration_context,
                agents=self._strategy_agents(route),
            ):
                raise_if_cancelled(context.cancellation_token)

                mapped = map_stream_event(
                    raw_event,
                    trace_id=request.trace_id,
                    session_id=request.session_id,
                )
                if mapped.answer_delta is not None:
                    answer_parts.append(mapped.answer_delta)
                if mapped.tool_call is not None:
                    tool_calls.append(dict(mapped.tool_call))
                if mapped.runtime_result is not None:
                    runtime_result = mapped.runtime_result
                if mapped.agent_name is not None:
                    agent_name = mapped.agent_name
                if mapped.llm_profile is not None:
                    llm_profile = mapped.llm_profile
                if mapped.finish_reason is not None:
                    finish_reason = mapped.finish_reason
                if mapped.metadata_patch:
                    metadata.update(dict(mapped.metadata_patch))

                if mapped.should_stop:
                    duration_ms = _elapsed_ms(started_at)
                    event_name = ORCHESTRATION_CANCELLED if mapped.terminal_cancelled else ORCHESTRATION_FAILED
                    await self._record_runtime_event(
                        event_name=event_name,
                        request=request,
                        runtime=context,
                        route=route,
                        duration_ms=float(duration_ms),
                        status="cancelled" if mapped.terminal_cancelled else "failed",
                        severity="warning" if mapped.terminal_cancelled else "error",
                        error=mapped.terminal_error,
                        payload=build_failure_trace_payload(),
                    )
                    for event in mapped.emitted_events:
                        limit_tracker.mark_stream_event()
                        yield event
                    return

                for event in mapped.emitted_events:
                    limit_tracker.mark_stream_event()
                    yield event

            duration_ms = _elapsed_ms(started_at)
            runtime_result = self._build_stream_result(
                request=request,
                runtime=context,
                route=route,
                answer_parts=answer_parts,
                tool_calls=tool_calls,
                runtime_result=runtime_result,
                agent_name=agent_name,
                llm_profile=llm_profile,
                finish_reason=finish_reason,
                duration_ms=duration_ms,
                metadata=metadata,
            )
            await self._record_runtime_event(
                event_name=ORCHESTRATION_COMPLETED,
                request=request,
                runtime=context,
                route=route,
                duration_ms=float(duration_ms),
                payload=build_completed_trace_payload(runtime_result),
            )
            limit_tracker.mark_stream_event()
            yield OrchestrationStreamEvent.completed(
                trace_id=request.trace_id,
                session_id=request.session_id,
                result=runtime_result,
                metadata={
                    "agent_name": runtime_result.agent_name,
                    "strategy_name": runtime_result.strategy_name,
                    "llm_profile": runtime_result.llm_profile,
                },
            )
            limit_tracker.mark_stream_event()
            yield OrchestrationStreamEvent.response_completed(
                trace_id=request.trace_id,
                session_id=request.session_id,
                finish_reason=runtime_result.finish_reason,
                duration_ms=duration_ms,
            )
        except Exception as exc:
            normalized = normalize_orchestration_error(exc)
            fallback = await self._try_fallback(
                request=request,
                runtime=context,
                route=route,
                limits=limit_tracker,
                error=normalized,
                started_at=started_at,
                response_started=bool(answer_parts or tool_calls or runtime_result is not None),
            )
            if fallback is not None:
                fallback_result, fallback_route, decision = fallback
                assert route is not None
                await self._record_runtime_event(
                    event_name=ORCHESTRATION_FALLBACK_USED,
                    request=request,
                    runtime=context,
                    route=fallback_route,
                    status="completed",
                    severity="warning",
                    duration_ms=float(fallback_result.duration_ms or _elapsed_ms(started_at)),
                    error=normalized,
                    payload=build_fallback_trace_payload(
                        failed_strategy=decision.failed_strategy or route.strategy_name,
                        fallback_strategy=decision.fallback_strategy or fallback_route.strategy_name,
                        reason=decision.reason,
                        error_code=decision.error.code,
                        retryable=decision.error.retryable,
                    ),
                )
                await self._record_runtime_event(
                    event_name=ORCHESTRATION_COMPLETED,
                    request=request,
                    runtime=context,
                    route=fallback_route,
                    duration_ms=float(fallback_result.duration_ms or _elapsed_ms(started_at)),
                    payload=build_completed_trace_payload(fallback_result),
                )
                yield OrchestrationStreamEvent.strategy_selected(
                    trace_id=request.trace_id,
                    session_id=request.session_id,
                    strategy_name=fallback_route.strategy_name,
                    usecase=fallback_route.usecase.name,
                    agent_name=fallback_result.agent_name or fallback_route.agent_name,
                    llm_profile=fallback_result.llm_profile or fallback_route.llm_profile,
                    metadata=_read_fallback_metadata(fallback_result.metadata),
                )
                yield OrchestrationStreamEvent.response_delta(
                    trace_id=request.trace_id,
                    session_id=request.session_id,
                    text=fallback_result.answer,
                    metadata=_read_fallback_metadata(fallback_result.metadata),
                )
                yield OrchestrationStreamEvent.completed(
                    trace_id=request.trace_id,
                    session_id=request.session_id,
                    result=fallback_result,
                    metadata={
                        "agent_name": fallback_result.agent_name,
                        "strategy_name": fallback_result.strategy_name,
                        "llm_profile": fallback_result.llm_profile,
                        **_read_fallback_metadata(fallback_result.metadata),
                    },
                )
                yield OrchestrationStreamEvent.response_completed(
                    trace_id=request.trace_id,
                    session_id=request.session_id,
                    finish_reason=fallback_result.finish_reason,
                    duration_ms=fallback_result.duration_ms,
                    metadata=_read_fallback_metadata(fallback_result.metadata),
                )
                return
            duration_ms = _elapsed_ms(started_at)
            event_name = ORCHESTRATION_CANCELLED if isinstance(normalized, OrchestrationCancelledError) else ORCHESTRATION_FAILED
            await self._record_runtime_event(
                event_name=event_name,
                request=request,
                runtime=context,
                route=route,
                duration_ms=float(duration_ms),
                status="cancelled" if isinstance(normalized, OrchestrationCancelledError) else "failed",
                severity="warning" if isinstance(normalized, OrchestrationCancelledError) else "error",
                error=normalized,
                payload=build_failure_trace_payload(),
            )
            if isinstance(normalized, OrchestrationCancelledError):
                yield OrchestrationStreamEvent.cancelled(
                    trace_id=request.trace_id,
                    session_id=request.session_id,
                )
                return
            yield OrchestrationStreamEvent.error_event(
                trace_id=request.trace_id,
                session_id=request.session_id,
                error=normalized,
            )

    async def health(self) -> OrchestrationHealthResult:
        return build_orchestration_health(
            self.settings,
            strategy_registry=self.strategy_registry,
            agent_registry=self.agent_registry,
            agent_settings=get_agents_settings(self.config),
        )

    async def capabilities(self) -> OrchestrationCapabilitiesResult:
        return build_orchestration_capabilities(
            self.settings,
            strategy_registry=self.strategy_registry,
            agent_registry=self.agent_registry,
            agent_settings=get_agents_settings(self.config),
        )

    async def run(
        self,
        *,
        request: RequestContext,
        state: WorkflowStateDocument,
    ) -> LegacyOrchestrationResult:
        runtime_result = await self.run_turn(
            request=build_orchestration_request(request=request, state=state),
            context=build_runtime_context(request),
        )
        return orchestration_result_to_contract(runtime_result)

    async def stream(
        self,
        *,
        request: RequestContext,
        state: WorkflowStateDocument,
    ) -> AsyncIterator[OrchestrationStreamEvent]:
        async for event in self.stream_turn(
            request=build_orchestration_request(request=request, state=state),
            context=build_runtime_context(request),
        ):
            yield event

    def _resolve_route(self, request: OrchestrationRequest) -> ResolvedUseCaseRoute:
        return self.usecase_router.resolve(
            self._build_legacy_request(request),
            strategy_registry=self.strategy_registry,
        )

    async def _require_usecase_access(
        self,
        *,
        request: OrchestrationRequest,
        runtime: OrchestrationRuntimeContext,
    ) -> None:
        usecase_name = _read_optional_text(request.usecase)
        if usecase_name is None:
            return
        await self.policy_service.require_allowed(
            build_usecase_policy_request(
                component=ORCHESTRATION_COMPONENT,
                usecase_name=usecase_name,
                session_id=request.session_id,
                user_id=request.user_id,
                strategy_name=_read_optional_text(request.metadata.get("requested_strategy")),
                llm_profile=_read_optional_text(request.metadata.get("llm_profile")),
                extra_metadata={"request_id": runtime.request_id, "trace_id": request.trace_id},
            ),
            OrchestrationContext(
                request=self._build_legacy_request(request),
                llm=self.llm_gateway,
                memory=self.memory,
                state=request.workflow_state,
                tools=self.tools,
                trace=RecorderTraceStoreAdapter(self.trace_recorder),
                policy=self.policy_service,
                config=self.config,
                runtime_metadata={
                    "usecase_name": usecase_name,
                    "project_id": runtime.project_id,
                    "tenant_id": runtime.tenant_id,
                    "request_id": runtime.request_id,
                },
                runtime=runtime,
                settings=self.settings,
            ),
        )

    def _build_context(
        self,
        *,
        request: OrchestrationRequest,
        runtime: OrchestrationRuntimeContext,
        route: ResolvedUseCaseRoute,
        limits: OrchestrationLimitTracker,
    ) -> OrchestrationContext:
        return OrchestrationContext(
            request=self._build_legacy_request(request),
            llm=self.llm_gateway,
            memory=self.memory,
            state=request.workflow_state,
            tools=self.tools,
            trace=RecorderTraceStoreAdapter(self.trace_recorder),
            policy=self.policy_service,
            config=self.config,
            runtime_metadata={
                "agent_name": route.agent_name,
                "strategy_name": route.strategy_name,
                "usecase_name": route.usecase.name,
                "usecase": route.usecase.name,
                "llm_profile": route.llm_profile,
                "strategy_source": route.resolved_strategy.source,
                "project_id": runtime.project_id,
                "tenant_id": runtime.tenant_id,
                "request_id": runtime.request_id,
                "limits": limits.as_dict(),
            },
            runtime=runtime,
            settings=self.settings,
            strategy_settings=route.resolved_strategy.settings,
            observability=self.trace_recorder,
            limits=limits,
            metadata={
                "strategy_registry": self.strategy_registry,
                "state_version": None if request.workflow_state is None else request.workflow_state.version,
                "client": runtime.client,
            },
        )

    def _strategy_agents(self, route: ResolvedUseCaseRoute) -> list[AgentPlugin]:
        ordered_names: list[str] = []
        if route.agent_name in self.agent_registry.agents:
            ordered_names.append(route.agent_name)
        for agent_name in sorted(self.agent_registry.agents):
            if agent_name not in ordered_names:
                ordered_names.append(agent_name)
        return [self.agent_registry.require(agent_name) for agent_name in ordered_names]

    def _build_runtime_result(
        self,
        *,
        request: OrchestrationRequest,
        runtime: OrchestrationRuntimeContext,
        route: ResolvedUseCaseRoute,
        legacy_result: LegacyOrchestrationResult,
        finish_reason: str,
        duration_ms: int,
    ) -> OrchestrationResult:
        step_summary = self._build_step_summary(
            route=route,
            agent_name=legacy_result.agent_name or route.agent_name,
            llm_profile=legacy_result.llm_profile or route.llm_profile,
            duration_ms=duration_ms,
            safe_message="Orchestration turn completed.",
        )
        strategy_steps = _read_step_summaries(legacy_result.metadata)
        all_steps = [step_summary, *strategy_steps]
        state_delta = self._build_state_delta(
            request=request,
            route=route,
            legacy_result=legacy_result,
            step_summaries=all_steps,
        )
        return build_orchestration_result(
            answer=legacy_result.answer,
            session_id=request.session_id,
            trace_id=request.trace_id,
            usecase=route.usecase.name,
            strategy_name=legacy_result.strategy_name or route.strategy_name,
            agent_name=legacy_result.agent_name or route.agent_name,
            llm_profile=legacy_result.llm_profile or route.llm_profile,
            steps=all_steps,
            tool_calls=legacy_result.tool_calls,
            memory_searches=_read_memory_search_summaries(legacy_result.metadata),
            memory_updates=legacy_result.memory_updates,
            citations=legacy_result.citations,
            state_delta=state_delta,
            finish_reason=finish_reason,
            duration_ms=duration_ms,
            metadata={
                **dict(legacy_result.metadata),
                "request_id": runtime.request_id,
                "strategy_source": route.resolved_strategy.source,
                "state_version": None if request.workflow_state is None else request.workflow_state.version,
            },
        )

    def _build_stream_result(
        self,
        *,
        request: OrchestrationRequest,
        runtime: OrchestrationRuntimeContext,
        route: ResolvedUseCaseRoute,
        answer_parts: list[str],
        tool_calls: list[dict[str, Any]],
        runtime_result: OrchestrationResult | None,
        agent_name: str | None,
        llm_profile: str | None,
        finish_reason: str,
        duration_ms: int,
        metadata: dict[str, Any],
    ) -> OrchestrationResult:
        if runtime_result is not None:
            return build_orchestration_result(
                answer="".join(answer_parts) or runtime_result.answer,
                session_id=runtime_result.session_id,
                trace_id=runtime_result.trace_id,
                usecase=runtime_result.usecase,
                strategy_name=runtime_result.strategy_name,
                agent_name=runtime_result.agent_name,
                llm_profile=runtime_result.llm_profile,
                steps=runtime_result.steps,
                tool_calls=runtime_result.tool_calls,
                memory_searches=runtime_result.memory_searches,
                memory_updates=runtime_result.memory_updates,
                citations=runtime_result.citations,
                state_delta=runtime_result.state_delta,
                finish_reason=finish_reason,
                duration_ms=duration_ms,
                metadata={**dict(runtime_result.metadata), **dict(metadata)},
            )

        legacy_result = LegacyOrchestrationResult(
            answer="".join(answer_parts),
            session_id=request.session_id,
            trace_id=request.trace_id,
            agent_name=agent_name or route.agent_name,
            strategy_name=route.strategy_name,
            llm_profile=llm_profile or route.llm_profile,
            tool_calls=[dict(item) for item in tool_calls],
            metadata=dict(metadata),
        )
        return self._build_runtime_result(
            request=request,
            runtime=runtime,
            route=route,
            legacy_result=legacy_result,
            finish_reason=finish_reason,
            duration_ms=duration_ms,
        )

    def _build_state_delta(
        self,
        *,
        request: OrchestrationRequest,
        route: ResolvedUseCaseRoute,
        legacy_result: LegacyOrchestrationResult,
        step_summaries: list[OrchestrationStepSummary],
    ) -> WorkflowStateDelta:
        llm_profile = legacy_result.llm_profile or route.llm_profile
        memory_updates = _read_memory_update_summaries(legacy_result.memory_updates)
        metadata_patch = {
            key: value
            for key, value in {
                "last_strategy": legacy_result.strategy_name or route.strategy_name,
                "last_agent": legacy_result.agent_name or route.agent_name,
                "last_llm_profile": llm_profile,
                "memory_update_count": len(memory_updates) if memory_updates else None,
                "last_memory_updates": [item.as_legacy_dict() for item in memory_updates] if memory_updates else None,
                **_read_planner_metadata(legacy_result.metadata),
                **_read_fallback_metadata(legacy_result.metadata),
            }.items()
            if value is not None
        }
        message_metadata = {
            "agent_name": legacy_result.agent_name or route.agent_name,
            "strategy_name": legacy_result.strategy_name or route.strategy_name,
            "llm_profile": llm_profile,
            **({"memory_update_count": len(memory_updates)} if memory_updates else {}),
            **_read_planner_metadata(legacy_result.metadata),
            **_read_fallback_metadata(legacy_result.metadata),
        }
        return WorkflowStateDelta(
            append_messages=[
                ConversationMessage(
                    role="assistant",
                    content=legacy_result.answer,
                    metadata=message_metadata,
                )
            ],
            set_active_usecase=route.usecase.name,
            set_active_agent=legacy_result.agent_name or route.agent_name,
            append_step_summaries=list(step_summaries),
            metadata_patch=metadata_patch,
        )

    def _build_step_summary(
        self,
        *,
        route: ResolvedUseCaseRoute,
        agent_name: str,
        llm_profile: str | None,
        duration_ms: int,
        safe_message: str,
    ) -> OrchestrationStepSummary:
        return OrchestrationStepSummary(
            step_id=f"{route.strategy_name}:1",
            step_type="strategy",
            status="completed",
            duration_ms=duration_ms,
            safe_message=safe_message,
            metadata={
                "agent_name": agent_name,
                "strategy_name": route.strategy_name,
                "llm_profile": llm_profile,
                "strategy_source": route.resolved_strategy.source,
            },
        )

    def _strategy_policy_request(self, route: ResolvedUseCaseRoute) -> PolicyRequest:
        return PolicyRequest(
            action="orchestration.run_strategy",
            component=ORCHESTRATION_COMPONENT,
            resource=route.strategy_name,
            scope={
                "usecase_name": route.usecase.name,
                "strategy_name": route.strategy_name,
                "agent_name": route.agent_name,
            },
            metadata={
                "strategy_source": route.resolved_strategy.source,
                "llm_profile": route.llm_profile,
            },
        )

    async def _try_fallback(
        self,
        *,
        request: OrchestrationRequest,
        runtime: OrchestrationRuntimeContext,
        route: ResolvedUseCaseRoute | None,
        limits: OrchestrationLimitTracker | None,
        error: OrchestrationError,
        started_at: float,
        response_started: bool = False,
    ) -> tuple[OrchestrationResult, ResolvedUseCaseRoute, FallbackDecision] | None:
        if route is None or limits is None:
            return None

        fallback_strategy_name = (
            route.resolved_strategy.settings.fallback_strategy
            or self.settings.defaults.fallback_strategy
        )
        primary_context = self._build_context(
            request=request,
            runtime=runtime,
            route=route,
            limits=limits,
        )
        decision = await enforce_fallback_policy(
            context=primary_context,
            error=error,
            failed_strategy=route.strategy_name,
            fallback_strategy=fallback_strategy_name,
            side_effect_pending=_error_side_effect_pending(error),
            response_started=response_started,
            fallback_requires_broader_permissions=self._fallback_requires_broader_permissions(
                route=route,
                fallback_strategy_name=fallback_strategy_name,
            ),
        )
        if not decision.allowed or decision.fallback_strategy is None:
            return None

        try:
            fallback_route = self._resolve_fallback_route(
                route=route,
                strategy_name=decision.fallback_strategy,
            )
            fallback_request = self._build_fallback_request(
                request=request,
                route=route,
                fallback_route=fallback_route,
                decision=decision,
            )
            fallback_context = self._build_context(
                request=fallback_request,
                runtime=runtime,
                route=fallback_route,
                limits=limits,
            )
            await self.policy_service.require_allowed(
                self._strategy_policy_request(fallback_route),
                fallback_context,
            )
            await self._record_runtime_event(
                event_name=STRATEGY_SELECTED,
                request=request,
                runtime=runtime,
                route=fallback_route,
                payload=build_selected_trace_payload(strategy_source=fallback_route.resolved_strategy.source),
            )
            legacy_result = await fallback_route.resolved_strategy.strategy.run(
                context=fallback_context,
                agents=self._strategy_agents(fallback_route),
            )
            raise_if_cancelled(runtime.cancellation_token)
            duration_ms = _elapsed_ms(started_at)
            runtime_result = self._build_runtime_result(
                request=fallback_request,
                runtime=runtime,
                route=fallback_route,
                legacy_result=legacy_result,
                finish_reason=_read_finish_reason(legacy_result.metadata),
                duration_ms=duration_ms,
            )
            logger.warning(
                "Primary orchestration strategy degraded to fallback answer",
                extra={
                    "component": ORCHESTRATION_COMPONENT,
                    "event_type": ORCHESTRATION_FALLBACK_USED,
                    "status": "degraded",
                    "details": {
                        "trace_id": request.trace_id,
                        "session_id": request.session_id,
                        "usecase": request.usecase,
                        "failed_strategy": decision.failed_strategy or route.strategy_name,
                        "fallback_strategy": decision.fallback_strategy or fallback_route.strategy_name,
                        "fallback_reason": decision.reason,
                        "failed_error_code": decision.error.code,
                        "failed_retryable": decision.error.retryable,
                        "fallback_answer_source": runtime_result.metadata.get("answer_source"),
                        "fallback_llm_error": runtime_result.metadata.get("fallback_llm_error"),
                    },
                },
            )
            return runtime_result, fallback_route, decision
        except Exception:
            return None

    def _fallback_requires_broader_permissions(
        self,
        *,
        route: ResolvedUseCaseRoute,
        fallback_strategy_name: str | None,
    ) -> bool:
        if fallback_strategy_name is None or fallback_strategy_name == route.strategy_name:
            return False

        fallback_settings = self.settings.strategies.get(fallback_strategy_name)
        if fallback_settings is None:
            return True

        primary_settings = route.resolved_strategy.settings
        if fallback_settings.tools_enabled and not primary_settings.tools_enabled:
            return True
        if fallback_settings.memory_enabled and not primary_settings.memory_enabled:
            return True
        if fallback_settings.memory_write_enabled and not primary_settings.memory_write_enabled:
            return True
        if fallback_settings.require_policy_approval and not primary_settings.require_policy_approval:
            return True

        fallback_tool_allowlist = set(fallback_settings.tools.allowed_tools)
        primary_tool_allowlist = set(primary_settings.tools.allowed_tools)
        if fallback_tool_allowlist and not fallback_tool_allowlist.issubset(primary_tool_allowlist):
            return True

        return False

    def _resolve_fallback_route(
        self,
        *,
        route: ResolvedUseCaseRoute,
        strategy_name: str,
    ) -> ResolvedUseCaseRoute:
        resolved_strategy = self.strategy_registry.resolve(
            strategy_name=strategy_name,
            usecase=route.usecase.name,
            source="fallback",
        )
        agent_name = route.agent_name
        llm_profile = (
            resolved_strategy.settings.llm_profile
            or route.usecase.llm_profile
            or _read_optional_text(self.config.get(f"agents.{agent_name}.llm_profile"))
            or _read_optional_text(self.config.get("llm.defaults.profile"))
        )
        return ResolvedUseCaseRoute(
            usecase=route.usecase,
            resolved_strategy=resolved_strategy,
            agent_name=agent_name,
            llm_profile=llm_profile,
        )

    def _build_fallback_request(
        self,
        *,
        request: OrchestrationRequest,
        route: ResolvedUseCaseRoute,
        fallback_route: ResolvedUseCaseRoute,
        decision: FallbackDecision,
    ) -> OrchestrationRequest:
        metadata = {
            **dict(request.metadata),
            "fallback_used": True,
            "fallback_reason": decision.reason,
            "failed_strategy": route.strategy_name,
            "fallback_strategy": fallback_route.strategy_name,
            "failed_error_code": decision.error.code,
            "failed_retryable": decision.error.retryable,
        }
        return replace(request, metadata=metadata)

    async def _record_runtime_event(
        self,
        *,
        event_name: str,
        request: OrchestrationRequest,
        runtime: OrchestrationRuntimeContext,
        route: ResolvedUseCaseRoute | None,
        status: str = "completed",
        severity: str = "info",
        duration_ms: float | None = None,
        error: OrchestrationError | BaseException | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        normalized = None if error is None else normalize_orchestration_error(error)
        await self.trace_recorder.record(
            event_type="orchestration",
            event_name=event_name,
            component=ORCHESTRATION_COMPONENT,
            status=status,
            severity=severity,
            trace_id=request.trace_id,
            session_id=request.session_id,
            user_id=request.user_id,
            usecase=request.usecase or (None if route is None else route.usecase.name),
            agent_name=None if route is None else route.agent_name,
            strategy_name=None if route is None else route.strategy_name,
            llm_profile=None if route is None else route.llm_profile,
            duration_ms=duration_ms,
            error_type=None if normalized is None else type(normalized).__name__,
            error_code=None if normalized is None else normalized.code,
            retryable=None if normalized is None else normalized.retryable,
            payload={
                **({} if payload is None else dict(payload)),
                "request_id": runtime.request_id,
            },
        )

    @staticmethod
    def _build_legacy_request(request: OrchestrationRequest) -> RequestContext:
        return RequestContext(
            user_id=request.user_id,
            session_id=request.session_id,
            message=request.message,
            usecase=request.usecase,
            trace_id=request.trace_id,
            metadata={**dict(request.metadata), "request_id": request.metadata.get("request_id")},
        )


@dataclass(slots=True)
class DirectAgentOrchestrationRuntime(DefaultOrchestrationRuntime):
    """Compatibility class name preserved while the default runtime surface is introduced."""


def _read_memory_search_summaries(metadata: Mapping[str, Any]) -> list[MemorySearchSummary]:
    raw_items = metadata.get("memory_searches")
    if not isinstance(raw_items, list):
        return []

    summaries: list[MemorySearchSummary] = []
    for item in raw_items:
        if not isinstance(item, Mapping):
            continue
        summaries.append(MemorySearchSummary.from_mapping(item))
    return summaries


def _read_memory_update_summaries(items: list[dict[str, Any]]) -> list[MemoryUpdateSummary]:
    summaries: list[MemoryUpdateSummary] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        summaries.append(MemoryUpdateSummary.from_mapping(item))
    return summaries


def _read_step_summaries(metadata: Mapping[str, Any]) -> list[OrchestrationStepSummary]:
    raw_items = metadata.get("steps")
    if not isinstance(raw_items, list):
        return []

    summaries: list[OrchestrationStepSummary] = []
    for item in raw_items:
        if not isinstance(item, Mapping):
            continue
        summaries.append(OrchestrationStepSummary.from_mapping(item))
    return summaries


def _read_fallback_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in metadata.items()
        if key in {
            "fallback_used",
            "fallback_reason",
            "failed_strategy",
            "fallback_strategy",
            "failed_error_code",
            "failed_retryable",
            "answer_source",
        }
    }


def _read_planner_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in metadata.items()
        if key in {
            "planner_source",
            "plan_id",
            "plan_step_count",
            "executed_step_count",
            "plan_actions",
            "safe_goal",
        }
    }


def _error_side_effect_pending(error: OrchestrationError) -> bool:
    value = error.metadata.get("side_effect_may_have_started")
    if isinstance(value, bool):
        return value
    return False


class _DisabledToolGateway:
    async def list_tools(
        self,
        context: OrchestrationContext,
        filters: object | None = None,
    ) -> ToolListResult:
        _ = context
        _ = filters
        return ToolListResult(tools=[])

    async def get_tool(
        self,
        tool_name: str,
        context: OrchestrationContext,
    ) -> ToolSpec | None:
        _ = context
        _ = tool_name
        return None

    async def execute(
        self,
        request: ToolExecutionRequest,
        context: OrchestrationContext,
    ) -> ToolExecutionResult:
        _ = context
        return ToolExecutionResult(
            tool_name=request.tool_name,
            status="failed",
            summary=ToolResultSummary(
                safe_message="Tool execution is not enabled in this runtime."
            ),
            error_detail=ToolErrorDetail(
                code="tool_disabled",
                message="Tool execution is not enabled in this runtime.",
            ),
        )

    async def stream_execute(
        self,
        request: ToolExecutionRequest,
        context: OrchestrationContext,
    ) -> AsyncIterator[ToolStreamEvent]:
        _ = context
        yield ToolStreamEvent.error_event(
            tool_name=request.tool_name,
            error=ToolErrorDetail(
                code="tool_disabled",
                message="Tool execution is not enabled in this runtime.",
            ),
        )

    async def health(self) -> ToolHealthResult:
        return ToolHealthResult(
            status="disabled",
            tooling_enabled=False,
            mcp_configured=False,
            mcp_status="not_configured",
            tools_configured=0,
            tools_discovered=0,
            tools_enabled=0,
            registry_status="disabled",
        )

    async def capabilities(self) -> ToolCapabilitiesResult:
        return ToolCapabilitiesResult(
            enabled=False,
            mcp_configured=False,
            streaming_supported=False,
            available_logical_tools=[],
        )

    async def call_tool(
        self,
        request: ToolCallRequest,
        context: OrchestrationContext,
    ) -> ToolExecutionResult:
        return await self.execute(
            ToolExecutionRequest(
                tool_name=request.tool_name,
                arguments=request.arguments,
                scopes=ToolScopes(),
                stream=request.stream,
                metadata=request.metadata,
            ),
            context,
        )


def _elapsed_ms(started_at: float) -> int:
    return max(int((perf_counter() - started_at) * 1000), 0)


def _read_finish_reason(metadata: dict[str, Any]) -> str:
    finish_reason = metadata.get("finish_reason")
    if isinstance(finish_reason, str) and finish_reason.strip():
        return finish_reason.strip()
    return "stop"


def _read_optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _read_optional_delta_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    if value == "":
        return None
    return value


def _chunk_text(text: str) -> tuple[str, ...]:
    midpoint = max(len(text) // 2, 1)
    chunks = tuple(chunk for chunk in (text[:midpoint], text[midpoint:]) if chunk)
    return chunks or (text,)