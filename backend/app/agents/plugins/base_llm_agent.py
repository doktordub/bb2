"""Shared LLM-backed agent helper for built-in assistant plugins."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from time import perf_counter
from typing import TYPE_CHECKING, Any, overload

from app.agents.base import LegacyCompatibleAgent
from app.agents.errors import AgentCancelledError, AgentConfigurationError, AgentError, AgentLLMError, AgentLimitExceededError, AgentPolicyDeniedError, AgentPromptBuildError, agent_error_from_detail, normalize_agent_error
from app.agents.models import AgentRunRequest, AgentRunResult, AgentStreamEvent, AgentWarning
from app.agents.policy import require_capability_allowed, require_capability_policy, require_policy_action
from app.agents.prompts import build_prompt_messages, resolve_system_prompt
from app.agents.result_builder import build_run_request_from_context, build_run_result, build_usage_summary, to_legacy_agent_result
from app.agents.stream_mapping import build_cancelled_event, build_completed_event, build_failed_event, build_started_event, map_llm_stream_event
from app.agents.trace_helpers import build_error_trace_summary, build_llm_trace_summary, build_prompt_trace_summary, build_request_trace_summary, build_result_trace_summary
from app.contracts.llm import LLMMessage, LLMRequest, LLMResponse, LLMResponseFormat
from app.memory.redaction import truncate_text
from app.orchestration.models import sanitize_metadata
from app.orchestration.prompt_inputs import PromptSection

if TYPE_CHECKING:
    from app.contracts.context import OrchestrationContext
    from app.contracts.results import AgentResult


_AGENT_FAILED = "agent_failed"
_AGENT_LLM_COMPLETED = "agent_llm_completed"
_AGENT_LLM_STARTED = "agent_llm_started"
_AGENT_POLICY_DENIED = "agent_policy_denied"
_AGENT_PROMPT_BUILT = "agent_prompt_built"
_AGENT_STREAMING = "streaming"
_DEFAULT_MAX_LLM_CALLS = 1
_DEFAULT_MAX_OUTPUT_CHARS = 12_000


def _read_optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


class BaseLlmAgent(LegacyCompatibleAgent):
    """Small shared helper for one-shot LLM-backed agent behaviors."""

    description = "LLM-backed agent."
    output_kind = "answer"
    stream_llm_deltas = True
    limits: object | None = None
    context_policy: object | None = None
    system_prompt_override: str | None = None
    developer_prompt: str | None = None

    def __init__(self, name: str | None = None, component: str | None = None) -> None:
        if name is not None:
            self.name = name
        self.component = component or f"agent.{self.name}"

    @overload
    async def run(self, context: "OrchestrationContext") -> "AgentResult":
        ...

    @overload
    async def run(
        self,
        *,
        request: AgentRunRequest,
        context: "OrchestrationContext",
    ) -> AgentRunResult:
        ...

    async def run(
        self,
        context: "OrchestrationContext | None" = None,
        *,
        request: AgentRunRequest | None = None,
    ) -> AgentRunResult | "AgentResult":
        if context is None:
            raise TypeError("Structured and legacy agent runs require an orchestration context.")

        resolved_request = request or build_run_request_from_context(
            context,
            agent_name=self.name,
            llm_profile=_requested_llm_profile(context, default=self.default_llm_profile),
        )
        result = await self.run_structured(request=resolved_request, context=context)
        if request is None:
            return to_legacy_agent_result(result, fallback_agent_name=self.name)
        return result

    async def run_structured(
        self,
        *,
        request: AgentRunRequest,
        context: "OrchestrationContext",
    ) -> AgentRunResult:
        require_capability_allowed(self.structured_capabilities, "answer", agent_name=self.name)
        await require_capability_policy(
            context,
            request=request,
            capability_name="answer",
            component=self.component,
            agent_name=self.name,
            metadata={"agent_type": self.type},
        )
        self._require_llm_call_budget()

        started_at = perf_counter()
        llm_profile = self.resolve_llm_profile(request)
        await self._record_trace(
            context=context,
            request=request,
            event_name="agent_started",
            status="started",
            llm_profile=llm_profile,
            payload=build_request_trace_summary(request, agent_name=self.name),
        )

        try:
            await self._require_invoke_policy(context=context, request=request)
            messages = self.build_prompt_messages_for_request(request=request, context=context)
            await self._record_trace(
                context=context,
                request=request,
                event_name=_AGENT_PROMPT_BUILT,
                llm_profile=llm_profile,
                payload=build_prompt_trace_summary(
                    request,
                    agent_name=self.name,
                    prompt_profile=self.prompt_profile,
                    message_count=len(messages),
                ),
            )

            await self._require_llm_policy(
                context=context,
                request=request,
                llm_profile=llm_profile,
                stream=False,
            )
            llm_request = self.build_llm_request(
                messages=messages,
                request=request,
                llm_profile=llm_profile,
                stream=False,
            )
            llm_request = self._finalize_llm_request(
                llm_request,
                context=context,
                llm_profile=llm_profile,
            )
            llm_started_at = perf_counter()
            await self._record_trace(
                context=context,
                request=request,
                event_name=_AGENT_LLM_STARTED,
                status="started",
                llm_profile=llm_profile,
                payload=build_llm_trace_summary(
                    llm_profile=llm_profile,
                    output_kind=self.output_kind,
                ),
            )
            response = await context.llm.complete(llm_request, context)
            llm_duration_ms = _elapsed_ms(llm_started_at)

            answer, warnings, metadata = self.normalize_response_text(response.text)
            response_profile = response.profile or llm_profile
            metadata = {
                **metadata,
                **self._response_metadata(response),
            }
            usage = build_usage_summary(
                llm_calls=1,
                input_chars=_message_char_count(messages),
                output_chars=len(answer),
            )
            result = build_run_result(
                status="completed",
                answer=answer,
                agent_name=self.name,
                llm_profile=response_profile,
                usage=usage,
                warnings=warnings,
                metadata=metadata,
            )

            await self._record_trace(
                context=context,
                request=request,
                event_name=_AGENT_LLM_COMPLETED,
                llm_profile=response_profile,
                duration_ms=float(llm_duration_ms),
                payload=build_llm_trace_summary(
                    llm_profile=response_profile,
                    output_kind=self.output_kind,
                    duration_ms=llm_duration_ms,
                    finish_reason=response.finish_reason,
                    usage=response.usage,
                ),
            )
            await self._record_trace(
                context=context,
                request=request,
                event_name="agent_completed",
                llm_profile=response_profile,
                duration_ms=float(_elapsed_ms(started_at)),
                payload={
                    **build_result_trace_summary(result),
                    "duration_ms": _elapsed_ms(started_at),
                },
            )
            return result
        except BaseException as exc:
            normalized = normalize_agent_error(exc)
            await self._record_failure(
                context=context,
                request=request,
                llm_profile=llm_profile,
                error=normalized,
                duration_ms=float(_elapsed_ms(started_at)),
            )
            if normalized is exc:
                raise
            raise normalized from exc

    async def stream(
        self,
        *,
        request: AgentRunRequest,
        context: "OrchestrationContext",
    ) -> AsyncIterator[AgentStreamEvent]:
        require_capability_allowed(self.structured_capabilities, "stream", agent_name=self.name)
        await require_capability_policy(
            context,
            request=request,
            capability_name="stream",
            component=self.component,
            agent_name=self.name,
            metadata={"agent_type": self.type, _AGENT_STREAMING: True},
        )
        self._require_llm_call_budget()

        started_at = perf_counter()
        llm_profile = self.resolve_llm_profile(request)
        yield build_started_event(
            self.name,
            metadata={
                "agent_type": self.type,
                "llm_profile": llm_profile,
            },
        )
        await self._record_trace(
            context=context,
            request=request,
            event_name="agent_started",
            status="started",
            llm_profile=llm_profile,
            payload=build_request_trace_summary(request, agent_name=self.name),
        )

        try:
            await self._require_invoke_policy(context=context, request=request)
            messages = self.build_prompt_messages_for_request(request=request, context=context)
            prompt_metadata = build_prompt_trace_summary(
                request,
                agent_name=self.name,
                prompt_profile=self.prompt_profile,
                message_count=len(messages),
            )
            yield AgentStreamEvent(
                type="agent.prompt_built",
                agent_name=self.name,
                metadata=prompt_metadata,
            )
            await self._record_trace(
                context=context,
                request=request,
                event_name=_AGENT_PROMPT_BUILT,
                llm_profile=llm_profile,
                payload=prompt_metadata,
            )

            await self._require_llm_policy(
                context=context,
                request=request,
                llm_profile=llm_profile,
                stream=True,
            )
            llm_request = self.build_llm_request(
                messages=messages,
                request=request,
                llm_profile=llm_profile,
                stream=True,
            )
            llm_request = self._finalize_llm_request(
                llm_request,
                context=context,
                llm_profile=llm_profile,
            )
            llm_started_at = perf_counter()
            await self._record_trace(
                context=context,
                request=request,
                event_name=_AGENT_LLM_STARTED,
                status="started",
                llm_profile=llm_profile,
                payload=build_llm_trace_summary(
                    llm_profile=llm_profile,
                    output_kind=self.output_kind,
                    stream=True,
                ),
            )

            answer_parts: list[str] = []
            finish_reason: str | None = None
            usage: object | None = None
            response_profile = llm_profile
            async for raw_event in context.llm.stream(llm_request, context):
                if raw_event.text:
                    answer_parts.append(raw_event.text)
                if raw_event.profile:
                    response_profile = raw_event.profile
                if raw_event.finish_reason:
                    finish_reason = raw_event.finish_reason
                if raw_event.usage is not None:
                    usage = raw_event.usage

                mapped = map_llm_stream_event(
                    self.name,
                    raw_event,
                    metadata={"llm_profile": response_profile},
                )
                if mapped is None:
                    continue
                if mapped.type == "agent.llm.delta" and not self._stream_llm_deltas_enabled():
                    continue
                if mapped.type == _AGENT_FAILED:
                    failure: AgentError = AgentLLMError()
                    if mapped.error is not None:
                        failure = agent_error_from_detail(mapped.error)
                    await self._record_failure(
                        context=context,
                        request=request,
                        llm_profile=response_profile,
                        error=failure,
                        duration_ms=float(_elapsed_ms(started_at)),
                    )
                    yield mapped
                    return
                yield mapped

            llm_duration_ms = _elapsed_ms(llm_started_at)
            answer, warnings, metadata = self.normalize_response_text("".join(answer_parts))
            metadata = {
                **metadata,
                "finish_reason": finish_reason or "stop",
            }
            usage_summary = build_usage_summary(
                llm_calls=1,
                input_chars=_message_char_count(messages),
                output_chars=len(answer),
            )
            result = build_run_result(
                status="completed",
                answer=answer,
                agent_name=self.name,
                llm_profile=response_profile,
                usage=usage_summary,
                warnings=warnings,
                metadata=metadata,
            )
            await self._record_trace(
                context=context,
                request=request,
                event_name=_AGENT_LLM_COMPLETED,
                llm_profile=response_profile,
                duration_ms=float(llm_duration_ms),
                payload=build_llm_trace_summary(
                    llm_profile=response_profile,
                    output_kind=self.output_kind,
                    duration_ms=llm_duration_ms,
                    finish_reason=finish_reason,
                    stream=True,
                    usage=usage,
                ),
            )
            await self._record_trace(
                context=context,
                request=request,
                event_name="agent_completed",
                llm_profile=response_profile,
                duration_ms=float(_elapsed_ms(started_at)),
                payload={
                    **build_result_trace_summary(result),
                    "duration_ms": _elapsed_ms(started_at),
                    _AGENT_STREAMING: True,
                },
            )
            yield build_completed_event(
                self.name,
                result=result,
                metadata={"finish_reason": finish_reason or "stop"},
            )
        except BaseException as exc:
            normalized = normalize_agent_error(exc)
            await self._record_failure(
                context=context,
                request=request,
                llm_profile=llm_profile,
                error=normalized,
                duration_ms=float(_elapsed_ms(started_at)),
            )
            if isinstance(normalized, AgentCancelledError):
                yield build_cancelled_event(self.name)
                return
            yield build_failed_event(self.name, error=normalized.to_detail())

    def resolve_llm_profile(self, request: AgentRunRequest) -> str:
        """Resolve the logical profile to use for one agent run."""

        profile = request.llm_profile or self.default_llm_profile
        if profile is None:
            raise AgentConfigurationError(
                f"Agent '{self.name}' has no LLM profile configured."
            )
        return profile

    def build_prompt_messages_for_request(
        self,
        *,
        request: AgentRunRequest,
        context: "OrchestrationContext",
    ) -> list[LLMMessage]:
        """Build provider-neutral LLM messages from the structured agent request."""

        try:
            extra_sections = list(
                self.build_extra_prompt_sections(request=request, context=context)
            )
            developer_prompt = _read_optional_text(self.developer_prompt)
            if developer_prompt is not None:
                extra_sections.insert(
                    0,
                    PromptSection(
                        title="Developer instructions",
                        body=developer_prompt,
                    ),
                )
            return build_prompt_messages(
                request,
                system_prompt=self.build_system_prompt(request=request, context=context),
                extra_sections=tuple(extra_sections),
            )
        except (TypeError, ValueError) as exc:
            raise AgentPromptBuildError(
                f"Agent '{self.name}' could not build a safe prompt."
            ) from exc

    def build_system_prompt(
        self,
        *,
        request: AgentRunRequest,
        context: "OrchestrationContext",
    ) -> str | None:
        """Resolve the built-in system prompt for this agent run."""

        _ = request
        _ = context
        explicit_system_prompt = _read_optional_text(self.system_prompt_override)
        if explicit_system_prompt is not None:
            return explicit_system_prompt
        return resolve_system_prompt(self.prompt_profile)

    def build_extra_prompt_sections(
        self,
        *,
        request: AgentRunRequest,
        context: "OrchestrationContext",
    ) -> Sequence[PromptSection]:
        """Return additional safe prompt sections to append for this agent."""

        _ = request
        _ = context
        return ()

    def build_llm_request(
        self,
        *,
        messages: Sequence[LLMMessage],
        request: AgentRunRequest,
        llm_profile: str,
        stream: bool,
    ) -> LLMRequest:
        """Build the provider-neutral LLM request for one agent turn."""

        return LLMRequest(
            component=self.component,
            profile=llm_profile,
            messages=list(messages),
            stream=stream,
            response_format=self._response_format(request),
            metadata=self._llm_request_metadata(request=request, llm_profile=llm_profile, stream=stream),
        )

    def _finalize_llm_request(
        self,
        llm_request: LLMRequest,
        *,
        context: "OrchestrationContext",
        llm_profile: str,
    ) -> LLMRequest:
        response_format = llm_request.response_format
        if response_format is None:
            return llm_request

        response_format_type = (
            response_format.type
            if isinstance(response_format, LLMResponseFormat)
            else response_format.get("type")
        )
        if response_format_type in {None, "text"}:
            return llm_request

        supports_json_schema = context.config.get(
            f"llm.profiles.{llm_profile}.supports_json_schema",
            None,
        )
        if supports_json_schema is not False:
            return llm_request

        llm_request.response_format = None
        llm_request.metadata = sanitize_metadata(
            {
                **llm_request.metadata,
                "response_format_fallback": "prompt_only",
                "requested_response_format": response_format_type,
            }
        )
        return llm_request

    def normalize_response_text(
        self,
        text: str,
    ) -> tuple[str, tuple[AgentWarning, ...], dict[str, Any]]:
        """Normalize one LLM text response into a safe answer payload."""

        max_output_chars = self._max_output_chars()
        normalized = text.strip()
        truncated = truncate_text(normalized, max_chars=max_output_chars) or ""
        warnings: tuple[AgentWarning, ...] = ()
        metadata: dict[str, Any] = {}
        if truncated != normalized:
            warnings = (
                AgentWarning(
                    code="answer_truncated",
                    message="Agent answer truncated to configured limit.",
                    metadata={"max_output_chars": max_output_chars},
                ),
            )
            metadata["truncated"] = True
        return truncated, warnings, metadata

    async def _require_invoke_policy(
        self,
        *,
        context: "OrchestrationContext",
        request: AgentRunRequest,
    ) -> None:
        await require_policy_action(
            context,
            request=request,
            action="agent.invoke",
            component=self.component,
            agent_name=self.name,
            metadata={"agent_type": self.type},
        )

    async def _require_llm_policy(
        self,
        *,
        context: "OrchestrationContext",
        request: AgentRunRequest,
        llm_profile: str,
        stream: bool,
    ) -> None:
        await require_policy_action(
            context,
            request=request,
            action="llm.stream" if stream else "llm.complete",
            component=self.component,
            agent_name=self.name,
            resource=llm_profile,
            metadata={
                "agent_type": self.type,
                "output_kind": self.output_kind,
                _AGENT_STREAMING: stream,
            },
        )

    async def _record_failure(
        self,
        *,
        context: "OrchestrationContext",
        request: AgentRunRequest,
        llm_profile: str | None,
        error: AgentError,
        duration_ms: float,
    ) -> None:
        if isinstance(error, AgentPolicyDeniedError):
            event_name = _AGENT_POLICY_DENIED
            severity = "warning"
            status = "failed"
        elif isinstance(error, AgentCancelledError):
            event_name = "agent_cancelled"
            severity = "warning"
            status = "cancelled"
        else:
            event_name = _AGENT_FAILED
            severity = "error"
            status = "failed"

        await self._record_trace(
            context=context,
            request=request,
            event_name=event_name,
            llm_profile=llm_profile,
            status=status,
            severity=severity,
            duration_ms=duration_ms,
            error=error,
            payload=build_error_trace_summary(error),
        )

    async def _record_trace(
        self,
        *,
        context: "OrchestrationContext",
        request: AgentRunRequest,
        event_name: str,
        payload: Mapping[str, Any],
        llm_profile: str | None = None,
        status: str = "completed",
        severity: str = "info",
        duration_ms: float | None = None,
        error: AgentError | None = None,
    ) -> None:
        recorder = context.observability
        if recorder is None:
            return

        error_detail = None if error is None else error.to_detail()
        await recorder.record(
            event_type="agent",
            event_name=event_name,
            component=self.component,
            status=status,
            severity=severity,
            trace_id=request.trace_id,
            session_id=request.session_id,
            user_id=request.user_id,
            usecase=request.usecase,
            agent_name=self.name,
            strategy_name=request.strategy_name,
            llm_profile=llm_profile,
            duration_ms=duration_ms,
            error_type=None if error is None else type(error).__name__,
            error_code=None if error_detail is None else error_detail.code,
            retryable=None if error_detail is None else error_detail.retryable,
            payload=payload,
        )

    def _llm_request_metadata(
        self,
        *,
        request: AgentRunRequest,
        llm_profile: str,
        stream: bool,
    ) -> dict[str, Any]:
        return sanitize_metadata(
            {
                "agent_name": self.name,
                "agent_type": self.type,
                "strategy_name": request.strategy_name,
                "usecase": request.usecase,
                "llm_profile": llm_profile,
                "output_kind": self.output_kind,
                "prompt_profile": self.prompt_profile,
                _AGENT_STREAMING: stream,
            }
        )

    def _response_format(self, request: AgentRunRequest) -> Mapping[str, Any] | None:
        output_format = request.output_format
        if output_format is None:
            return None
        if not output_format.require_json and output_format.schema_name is None:
            return None
        return {
            "type": "json_object" if output_format.require_json else "text",
            "schema_name": output_format.schema_name,
            "strict": output_format.require_json,
        }

    def _response_metadata(self, response: LLMResponse) -> dict[str, Any]:
        metadata: dict[str, Any] = {}
        if response.finish_reason is not None:
            metadata["finish_reason"] = response.finish_reason
        if response.usage is not None:
            metadata["usage_counts"] = {
                "input": response.usage.input_tokens,
                "output": response.usage.output_tokens,
                "total": response.usage.total_tokens,
            }
        return sanitize_metadata(metadata)

    def _max_llm_calls(self) -> int:
        return _read_int_attr(self.limits, "max_llm_calls", _DEFAULT_MAX_LLM_CALLS)

    def _max_output_chars(self) -> int:
        return _read_int_attr(self.limits, "max_output_chars", _DEFAULT_MAX_OUTPUT_CHARS)

    def _require_llm_call_budget(self) -> None:
        if self._max_llm_calls() < 1:
            raise AgentLimitExceededError(
                f"Agent '{self.name}' is configured with no available LLM calls."
            )

    def _stream_llm_deltas_enabled(self) -> bool:
        value = getattr(self, "stream_llm_deltas", self.metadata.get("stream_llm_deltas", True))
        return bool(value)


def _elapsed_ms(started_at: float) -> int:
    return int((perf_counter() - started_at) * 1000)


def _message_char_count(messages: Sequence[LLMMessage]) -> int:
    total = 0
    for message in messages:
        content = message.content
        if isinstance(content, str):
            total += len(content)
            continue
        for part in content:
            if part.text:
                total += len(part.text)
            if part.image_url:
                total += len(part.image_url)
            if part.json_value is not None:
                total += len(str(part.json_value))
    return total


def _read_int_attr(source: object | None, name: str, default: int) -> int:
    value = getattr(source, name, default)
    return value if isinstance(value, int) and value > 0 else default


def _requested_llm_profile(
    context: "OrchestrationContext",
    *,
    default: str | None,
) -> str | None:
    value = context.runtime_metadata.get("llm_profile")
    if isinstance(value, str):
        normalized = value.strip()
        if normalized:
            return normalized
    return default


__all__ = ["BaseLlmAgent"]