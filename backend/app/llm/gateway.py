"""Concrete default implementation of the public provider-neutral LLM gateway."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import replace
import logging
from time import perf_counter
from typing import Literal, TypeAlias

from app.config.view import get_llm_settings, get_observability_settings
from app.contracts.config import ConfigurationView
from app.contracts.context import OrchestrationContext
from app.contracts.llm import (
    LLMHealthResult,
    LLMProfileSummary,
    LLMRequest,
    LLMResponse,
    LLMStreamEvent,
)
from app.contracts.policy import PolicyService
from app.contracts.trace import (
    LLM_CALL_COMPLETED,
    LLM_CALL_FAILED,
    LLM_CALL_STARTED,
    LLM_FALLBACK_SELECTED,
    LLM_POLICY_CHECKED,
    LLM_PROFILE_RESOLVED,
    LLM_RETRY_SCHEDULED,
    LLM_STREAM_CANCELLED,
    LLM_STREAM_COMPLETED,
    LLM_STREAM_STARTED,
)
from app.llm.errors import LLMRuntimeError
from app.llm.health import build_health_result, build_profile_summaries
from app.llm.models import ProviderLLMResponse, ProviderLLMStreamEvent, ResolvedLLMRequest
from app.llm.profile_resolver import LLMProfileResolver
from app.llm.provider_registry import ProviderRegistry
from app.llm.redaction import summarize_error, summarize_provider_response, summarize_request
from app.llm.retry import is_fallback_eligible, is_retryable_error, normalize_runtime_error
from app.llm.streaming import StreamAssembly, normalize_stream_event, update_stream_assembly
from app.llm.token_budget import enforce_token_budget
from app.observability.metrics import MetricsRecorder, NoopMetricsRecorder
from app.observability.redaction import Redactor
from app.observability.tracing import TraceRecorder
from app.policy.llm_policy import build_llm_policy_request

LLMPolicyAction: TypeAlias = Literal["llm.complete", "llm.stream"]


class DefaultLLMGateway:
    """Provider-neutral gateway that resolves logical profiles at runtime."""

    def __init__(
        self,
        *,
        config: ConfigurationView,
        registry: ProviderRegistry,
        profile_resolver: LLMProfileResolver,
        policy_service: PolicyService,
        metrics: MetricsRecorder | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._config = config
        self._registry = registry
        self._profile_resolver = profile_resolver
        self._policy_service = policy_service
        self._metrics = metrics or NoopMetricsRecorder()
        self._logger = logger or logging.getLogger(__name__)

    async def complete(
        self,
        request: LLMRequest,
        context: OrchestrationContext,
    ) -> LLMResponse:
        resolved = self._profile_resolver.resolve(request=request, context=context)
        recorder = self._build_trace_recorder(context)
        await self._record_resolution(recorder=recorder, resolved=resolved)
        budget = enforce_token_budget(resolved)
        await self._authorize(action="llm.complete", resolved=resolved, context=context, recorder=recorder)

        execution_plan = self._build_execution_plan(resolved=resolved, request=request, context=context)
        last_error: LLMRuntimeError | None = None

        for index, current_resolved in enumerate(execution_plan):
            if index > 0:
                await self._record_fallback(
                    recorder=recorder,
                    previous=execution_plan[index - 1],
                    resolved=current_resolved,
                    error=last_error,
                )
                await self._authorize(
                    action="llm.complete",
                    resolved=current_resolved,
                    context=context,
                    recorder=recorder,
                    fallback_from_profile=execution_plan[index - 1].profile_name,
                )

            adapter = self._registry.get(current_resolved.provider_name)
            attempts = current_resolved.max_retries + 1
            for attempt_index in range(attempts):
                started_at = perf_counter()
                await self._record_call_started(
                    recorder=recorder,
                    resolved=current_resolved,
                    operation="complete",
                    attempt=attempt_index + 1,
                    budget=budget,
                )
                try:
                    provider_response = await adapter.complete(current_resolved)
                    response = self._build_response(
                        response=provider_response,
                        resolved=current_resolved,
                    )
                    duration_ms = int((perf_counter() - started_at) * 1000)
                    await self._record_call_completed(
                        recorder=recorder,
                        resolved=current_resolved,
                        response=provider_response,
                        duration_ms=duration_ms,
                    )
                    self._record_metric_success(
                        operation="complete",
                        resolved=current_resolved,
                        duration_ms=duration_ms,
                    )
                    return response
                except BaseException as exc:
                    error = normalize_runtime_error(exc)
                    duration_ms = int((perf_counter() - started_at) * 1000)
                    if is_retryable_error(error) and attempt_index + 1 < attempts:
                        await self._record_retry(
                            recorder=recorder,
                            resolved=current_resolved,
                            attempt=attempt_index + 2,
                            error=error,
                        )
                        continue

                    await self._record_call_failed(
                        recorder=recorder,
                        resolved=current_resolved,
                        error=error,
                        duration_ms=duration_ms,
                    )
                    self._record_metric_failure(
                        operation="complete",
                        resolved=current_resolved,
                        duration_ms=duration_ms,
                        error=error,
                    )
                    last_error = error
                    if not is_fallback_eligible(error):
                        raise error
                    break

        if last_error is None:
            raise RuntimeError("LLM execution plan exhausted without a result.")
        raise last_error

    async def stream(
        self,
        request: LLMRequest,
        context: OrchestrationContext,
    ) -> AsyncIterator[LLMStreamEvent]:
        resolved = self._profile_resolver.resolve(request=request, context=context)
        recorder = self._build_trace_recorder(context)
        await self._record_resolution(recorder=recorder, resolved=resolved)
        budget = enforce_token_budget(resolved)
        await self._authorize(action="llm.stream", resolved=resolved, context=context, recorder=recorder)

        execution_plan = self._build_execution_plan(resolved=resolved, request=request, context=context)
        last_error: LLMRuntimeError | None = None

        for index, current_resolved in enumerate(execution_plan):
            if index > 0:
                await self._record_fallback(
                    recorder=recorder,
                    previous=execution_plan[index - 1],
                    resolved=current_resolved,
                    error=last_error,
                )
                await self._authorize(
                    action="llm.stream",
                    resolved=current_resolved,
                    context=context,
                    recorder=recorder,
                    fallback_from_profile=execution_plan[index - 1].profile_name,
                )

            adapter = self._registry.get(current_resolved.provider_name)
            attempts = current_resolved.max_retries + 1
            for attempt_index in range(attempts):
                started_at = perf_counter()
                await self._record_call_started(
                    recorder=recorder,
                    resolved=current_resolved,
                    operation="stream",
                    attempt=attempt_index + 1,
                    budget=budget,
                )
                assembly = StreamAssembly()
                saw_delta = False
                completed = False
                try:
                    async for provider_event in adapter.stream(current_resolved):
                        if provider_event.type == "started":
                            await recorder.record(
                                event_type="llm",
                                event_name=LLM_STREAM_STARTED,
                                component=current_resolved.component,
                                status="started",
                                llm_profile=current_resolved.profile_name,
                                provider=current_resolved.provider_name,
                                model=current_resolved.model,
                                payload={"attempt": attempt_index + 1},
                            )

                        update_stream_assembly(event=provider_event, assembly=assembly)
                        normalized = normalize_stream_event(event=provider_event, resolved=current_resolved)
                        if provider_event.type == "delta":
                            saw_delta = True
                        if provider_event.type == "completed":
                            completed = True
                        yield normalized

                    if not completed:
                        synthesized = normalize_stream_event(
                            event=ProviderLLMStreamEvent.completed(
                                tool_calls=assembly.tool_calls,
                                finish_reason=assembly.finish_reason,
                                reasoning=assembly.reasoning,
                                usage=assembly.usage,
                            ),
                            resolved=current_resolved,
                        )
                        yield synthesized

                    duration_ms = int((perf_counter() - started_at) * 1000)
                    await recorder.record(
                        event_type="llm",
                        event_name=LLM_STREAM_COMPLETED,
                        component=current_resolved.component,
                        status="completed",
                        llm_profile=current_resolved.profile_name,
                        provider=current_resolved.provider_name,
                        model=current_resolved.model,
                        duration_ms=float(duration_ms),
                        payload=summarize_provider_response(
                            ProviderLLMResponse(
                                text=assembly.text,
                                tool_calls=list(assembly.tool_calls),
                                finish_reason=assembly.finish_reason,
                                reasoning=dict(assembly.reasoning),
                                usage=assembly.usage,
                            ),
                            include_text=current_resolved.trace_completions,
                        ),
                    )
                    self._record_metric_success(
                        operation="stream",
                        resolved=current_resolved,
                        duration_ms=duration_ms,
                    )
                    return
                except asyncio.CancelledError as exc:
                    error = normalize_runtime_error(exc, streaming=True)
                    await recorder.record(
                        event_type="llm",
                        event_name=LLM_STREAM_CANCELLED,
                        component=current_resolved.component,
                        status="cancelled",
                        llm_profile=current_resolved.profile_name,
                        provider=current_resolved.provider_name,
                        model=current_resolved.model,
                        payload=summarize_error(error),
                    )
                    raise error
                except BaseException as exc:
                    error = normalize_runtime_error(exc, streaming=True)
                    duration_ms = int((perf_counter() - started_at) * 1000)
                    if saw_delta:
                        await self._record_call_failed(
                            recorder=recorder,
                            resolved=current_resolved,
                            error=error,
                            duration_ms=duration_ms,
                        )
                        yield LLMStreamEvent(
                            type="error",
                            profile=current_resolved.profile_name,
                            provider=current_resolved.provider_name,
                            model=current_resolved.model,
                            error=error.as_error_detail(),
                        )
                        self._record_metric_failure(
                            operation="stream",
                            resolved=current_resolved,
                            duration_ms=duration_ms,
                            error=error,
                        )
                        return

                    if is_retryable_error(error) and attempt_index + 1 < attempts:
                        await self._record_retry(
                            recorder=recorder,
                            resolved=current_resolved,
                            attempt=attempt_index + 2,
                            error=error,
                        )
                        continue

                    await self._record_call_failed(
                        recorder=recorder,
                        resolved=current_resolved,
                        error=error,
                        duration_ms=duration_ms,
                    )
                    self._record_metric_failure(
                        operation="stream",
                        resolved=current_resolved,
                        duration_ms=duration_ms,
                        error=error,
                    )
                    last_error = error
                    if not is_fallback_eligible(error):
                        raise error
                    break

        if last_error is None:
            raise RuntimeError("LLM streaming execution plan exhausted without a result.")
        raise last_error

    async def health(self) -> LLMHealthResult:
        settings = get_llm_settings(self._config)
        return await build_health_result(settings=settings, registry=self._registry)

    async def list_profiles(self) -> list[LLMProfileSummary]:
        settings = get_llm_settings(self._config)
        return build_profile_summaries(settings)

    def _build_execution_plan(
        self,
        *,
        resolved: ResolvedLLMRequest,
        request: LLMRequest,
        context: OrchestrationContext,
    ) -> list[ResolvedLLMRequest]:
        plan = [resolved]
        for fallback_profile in resolved.profile.fallback_profiles:
            fallback_request = replace(request, profile=fallback_profile)
            plan.append(self._profile_resolver.resolve(request=fallback_request, context=context))
        return plan

    async def _authorize(
        self,
        *,
        action: LLMPolicyAction,
        resolved: ResolvedLLMRequest,
        context: OrchestrationContext,
        recorder: TraceRecorder,
        fallback_from_profile: str | None = None,
    ) -> None:
        policy_request = build_llm_policy_request(
            action=action,
            resolved=resolved,
            context=context,
            fallback_from_profile=fallback_from_profile,
        )
        decision = await self._policy_service.evaluate(policy_request, context)
        status = "completed" if decision.allowed else "failed"
        await recorder.record(
            event_type="llm",
            event_name=LLM_POLICY_CHECKED,
            component=resolved.component,
            status=status,
            severity="warning" if not decision.allowed else "info",
            llm_profile=resolved.profile_name,
            provider=resolved.provider_name,
            model=resolved.model,
            payload={
                "allowed": decision.allowed,
                "reason": decision.reason,
                "reason_code": decision.reason_code,
                "policy_profile": decision.metadata.get("policy_profile"),
                "fallback_from_profile": fallback_from_profile,
            },
        )
        if not decision.allowed:
            from app.llm.errors import LLMPolicyDeniedError

            raise LLMPolicyDeniedError(
                decision.reason or "LLM profile is denied by policy.",
                metadata={"profile": resolved.profile_name, **decision.metadata},
            )

    def _build_response(
        self,
        *,
        response: ProviderLLMResponse,
        resolved: ResolvedLLMRequest,
    ) -> LLMResponse:
        return LLMResponse(
            text=response.text,
            profile=resolved.profile_name,
            provider=resolved.provider_name,
            model=resolved.model,
            tool_calls=list(response.tool_calls),
            finish_reason=response.finish_reason,
            reasoning=dict(response.reasoning),
            usage=response.usage,
            raw_id=response.raw_id,
            metadata=dict(response.metadata),
        )

    async def _record_resolution(
        self,
        *,
        recorder: TraceRecorder,
        resolved: ResolvedLLMRequest,
    ) -> None:
        await recorder.record(
            event_type="llm",
            event_name=LLM_PROFILE_RESOLVED,
            component=resolved.component,
            llm_profile=resolved.profile_name,
            provider=resolved.provider_name,
            model=resolved.model,
            payload={
                "resolution_source": resolved.resolution_source,
                "agent_name": resolved.agent_name,
                "strategy_name": resolved.strategy_name,
                "usecase_name": resolved.usecase_name,
            },
        )

    async def _record_call_started(
        self,
        *,
        recorder: TraceRecorder,
        resolved: ResolvedLLMRequest,
        operation: str,
        attempt: int,
        budget: dict[str, int | None],
    ) -> None:
        await recorder.record(
            event_type="llm",
            event_name=LLM_CALL_STARTED,
            component=resolved.component,
            status="started",
            llm_profile=resolved.profile_name,
            provider=resolved.provider_name,
            model=resolved.model,
            payload={
                **summarize_request(resolved.request, resolved=resolved),
                **budget,
                "operation": operation,
                "attempt": attempt,
            },
        )

    async def _record_call_completed(
        self,
        *,
        recorder: TraceRecorder,
        resolved: ResolvedLLMRequest,
        response: ProviderLLMResponse,
        duration_ms: int,
    ) -> None:
        await recorder.record(
            event_type="llm",
            event_name=LLM_CALL_COMPLETED,
            component=resolved.component,
            status="completed",
            llm_profile=resolved.profile_name,
            provider=resolved.provider_name,
            model=resolved.model,
            duration_ms=float(duration_ms),
            payload=summarize_provider_response(
                response,
                include_text=resolved.trace_completions,
            ),
        )

    async def _record_call_failed(
        self,
        *,
        recorder: TraceRecorder,
        resolved: ResolvedLLMRequest,
        error: LLMRuntimeError,
        duration_ms: int,
    ) -> None:
        await recorder.record(
            event_type="llm",
            event_name=LLM_CALL_FAILED,
            component=resolved.component,
            status="failed",
            severity="error",
            llm_profile=resolved.profile_name,
            provider=resolved.provider_name,
            model=resolved.model,
            duration_ms=float(duration_ms),
            error_type=type(error).__name__,
            error_code=getattr(error, "code", None),
            retryable=getattr(error, "retryable", None),
            payload=summarize_error(error),
        )

    async def _record_retry(
        self,
        *,
        recorder: TraceRecorder,
        resolved: ResolvedLLMRequest,
        attempt: int,
        error: LLMRuntimeError,
    ) -> None:
        await recorder.record(
            event_type="llm",
            event_name=LLM_RETRY_SCHEDULED,
            component=resolved.component,
            status="degraded",
            llm_profile=resolved.profile_name,
            provider=resolved.provider_name,
            model=resolved.model,
            error_type=type(error).__name__,
            error_code=getattr(error, "code", None),
            retryable=getattr(error, "retryable", None),
            payload={"attempt": attempt},
        )

    async def _record_fallback(
        self,
        *,
        recorder: TraceRecorder,
        previous: ResolvedLLMRequest,
        resolved: ResolvedLLMRequest,
        error: LLMRuntimeError | None,
    ) -> None:
        await recorder.record(
            event_type="llm",
            event_name=LLM_FALLBACK_SELECTED,
            component=resolved.component,
            status="degraded",
            llm_profile=resolved.profile_name,
            provider=resolved.provider_name,
            model=resolved.model,
            error_type=None if error is None else type(error).__name__,
            error_code=None if error is None else getattr(error, "code", None),
            payload={
                "from_profile": previous.profile_name,
                "to_profile": resolved.profile_name,
            },
        )

    def _build_trace_recorder(self, context: OrchestrationContext) -> TraceRecorder:
        settings = get_observability_settings(self._config)
        return TraceRecorder(
            store=context.trace,
            settings=settings,
            redactor=Redactor(
                redact_secrets=settings.redact_secrets,
                max_chars=settings.max_trace_payload_chars,
            ),
            logger=self._logger,
        )

    def _record_metric_success(
        self,
        *,
        operation: str,
        resolved: ResolvedLLMRequest,
        duration_ms: int,
    ) -> None:
        tags = {
            "component": resolved.component,
            "provider": resolved.provider_name,
            "profile": resolved.profile_name,
            "operation": operation,
            "success": "true",
        }
        self._metrics.increment("backend.llm.calls.total", tags=tags)
        self._metrics.timing("backend.llm.calls.duration_ms", duration_ms, tags=tags)

    def _record_metric_failure(
        self,
        *,
        operation: str,
        resolved: ResolvedLLMRequest,
        duration_ms: int,
        error: LLMRuntimeError,
    ) -> None:
        tags = {
            "component": resolved.component,
            "provider": resolved.provider_name,
            "profile": resolved.profile_name,
            "operation": operation,
            "success": "false",
            "error_type": type(error).__name__,
        }
        self._metrics.increment("backend.llm.calls.total", tags=tags)
        self._metrics.increment("backend.llm.calls.errors", tags=tags)
        self._metrics.timing("backend.llm.calls.duration_ms", duration_ms, tags=tags)