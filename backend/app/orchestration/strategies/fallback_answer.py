"""Safe fallback-answer orchestration strategy."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
import logging
from time import perf_counter
from typing import Any

from app.agents.prompts import resolve_prompt_text
from app.contracts.agents import AgentPlugin
from app.contracts.context import OrchestrationContext
from app.contracts.llm import LLMRequest
from app.contracts.results import OrchestrationResult as LegacyOrchestrationResult
from app.contracts.results import StreamEvent
from app.orchestration.errors import normalize_orchestration_error
from app.orchestration.events import OrchestrationStreamEvent
from app.orchestration.message_catalog import default_message_template_service
from app.orchestration.prompt_inputs import PromptSection, build_prompt_messages
from app.orchestration.strategy_steps import build_step_summary, finalize_strategy_result, run_llm_completion_step

_FALLBACK_COMPONENT = "orchestration.strategy.fallback_answer"
_DEFAULT_FALLBACK_MESSAGE = "I could not complete the full workflow, but here is the safest answer I can provide."
_FALLBACK_LLM_FAILED = "fallback_llm_failed"

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class FallbackAnswerStrategy:
    """Return a safe fallback answer without using memory or tools."""

    name: str = "fallback_answer"

    async def run(
        self,
        *,
        context: OrchestrationContext,
        agents: Sequence[AgentPlugin],
    ) -> LegacyOrchestrationResult:
        _ = agents
        started_at = perf_counter()
        strategy_name = _runtime_value(context, "strategy_name") or self.name
        agent_name = _runtime_value(context, "agent_name")
        llm_profile = _resolve_llm_profile(context)
        static_message = _static_message(context)
        failure_metadata = _read_failure_metadata(context)
        answer = static_message
        answer_source = "static"
        llm_error_code: str | None = None
        resolved_profile: str | None = None

        if llm_profile is not None:
            try:
                response = await run_llm_completion_step(
                    context,
                    component=_FALLBACK_COMPONENT,
                    request=LLMRequest(
                        component=_FALLBACK_COMPONENT,
                        profile=llm_profile,
                        messages=_build_fallback_messages(
                            message=context.request.message,
                            static_message=static_message,
                            failure_metadata=failure_metadata,
                        ),
                        metadata={
                            "fallback_used": True,
                            "failed_strategy": failure_metadata.get("failed_strategy"),
                            "fallback_reason": failure_metadata.get("fallback_reason"),
                        },
                    ),
                    agent_name=agent_name,
                    strategy_name=strategy_name,
                )
                answer = _safe_answer_text(response.text, static_message)
                answer_source = "llm"
                resolved_profile = response.profile
            except Exception as exc:
                normalized = normalize_orchestration_error(exc)
                llm_error_code = normalized.code
                await _record_fallback_llm_failure(
                    context=context,
                    strategy_name=strategy_name,
                    llm_profile=llm_profile,
                    failure_metadata=failure_metadata,
                    error=normalized,
                )

        duration_ms = max(int((perf_counter() - started_at) * 1000), 0)
        step_summary = build_step_summary(
            step_id=f"{strategy_name}:fallback",
            step_type="fallback",
            status="completed",
            duration_ms=duration_ms,
            safe_message=(
                "Fallback answer generated through the configured LLM profile."
                if answer_source == "llm"
                else "Static fallback answer returned."
            ),
            metadata={
                "answer_source": answer_source,
                "failed_strategy": failure_metadata.get("failed_strategy"),
                "fallback_reason": failure_metadata.get("fallback_reason"),
                "failed_error_code": failure_metadata.get("failed_error_code"),
            },
        )
        metadata = {
            "finish_reason": "fallback",
            "fallback_used": True,
            "fallback_reason": failure_metadata.get("fallback_reason") or "degradable_failure",
            "failed_strategy": failure_metadata.get("failed_strategy"),
            "failed_error_code": failure_metadata.get("failed_error_code"),
            "failed_retryable": failure_metadata.get("failed_retryable"),
            "answer_source": answer_source,
        }
        if llm_error_code is not None:
            metadata["fallback_llm_error"] = llm_error_code

        strategy_result = finalize_strategy_result(
            answer=answer,
            agent_name=agent_name,
            llm_profile=resolved_profile,
            finish_reason="fallback",
            steps=[step_summary],
            metadata=metadata,
        )
        return strategy_result.to_legacy_result(
            session_id=context.request.session_id,
            trace_id=context.request.trace_id or "unknown_trace",
            strategy_name=strategy_name,
        )

    async def stream(
        self,
        *,
        context: OrchestrationContext,
        agents: Sequence[AgentPlugin],
    ) -> AsyncIterator[StreamEvent | OrchestrationStreamEvent]:
        result = await self.run(context=context, agents=agents)

        if result.answer:
            yield OrchestrationStreamEvent.response_delta(
                trace_id=result.trace_id or "unknown_trace",
                session_id=result.session_id,
                text=result.answer,
                metadata=_fallback_stream_metadata(result.metadata),
            )

        yield StreamEvent(
            event_type="agent_summary",
            data={
                "agent_name": result.agent_name,
                "strategy_name": result.strategy_name,
                "llm_profile": result.llm_profile,
                **{key: value for key, value in result.metadata.items() if key != "finish_reason"},
            },
        )

        yield OrchestrationStreamEvent.response_completed(
            trace_id=result.trace_id or "unknown_trace",
            session_id=result.session_id,
            finish_reason=_read_finish_reason(result.metadata),
            metadata=_fallback_stream_metadata(result.metadata),
        )


def _build_fallback_messages(
    *,
    message: str,
    static_message: str,
    failure_metadata: Mapping[str, Any],
) -> list[Any]:
    sections = [
        PromptSection(
            title="Fallback guidance",
            body=resolve_prompt_text(
                "fallback_answer",
                "guidance",
                fallback=(
                    "Provide a short, safe fallback answer. Acknowledge uncertainty when needed, "
                    "do not mention internal errors, and do not imply that unavailable memory, tools, "
                    "or side effects succeeded."
                ),
            ),
        ),
        PromptSection(
            title="Primary workflow summary",
            body=(
                f"Failed strategy: {failure_metadata.get('failed_strategy') or 'unknown'}\n"
                f"Failure type: {failure_metadata.get('failed_error_code') or 'unknown'}\n"
                f"Fallback reason: {failure_metadata.get('fallback_reason') or 'degradable_failure'}"
            ),
        ),
        PromptSection(
            title="Safe fallback baseline",
            body=static_message,
        ),
    ]
    return build_prompt_messages(
        user_request=message,
        sections=sections,
        system_prompt=resolve_prompt_text(
            "fallback_answer",
            "llm_system_prompt",
            fallback=(
                "You are generating a safe fallback answer for a partially degraded workflow. "
                "Keep the answer concise, honest about limitations, and free of internal implementation details."
            ),
        ),
    )


def _read_failure_metadata(context: OrchestrationContext) -> dict[str, Any]:
    metadata = context.request.metadata
    return {
        "failed_strategy": _read_optional_text(metadata.get("failed_strategy")),
        "failed_error_code": _read_optional_text(metadata.get("failed_error_code")),
        "failed_retryable": bool(metadata.get("failed_retryable", False)),
        "fallback_reason": _read_optional_text(metadata.get("fallback_reason")),
    }


def _resolve_llm_profile(context: OrchestrationContext) -> str | None:
    if context.strategy_settings is not None and context.strategy_settings.llm_profile is not None:
        return context.strategy_settings.llm_profile
    runtime_profile = _runtime_value(context, "llm_profile")
    if runtime_profile is not None:
        return runtime_profile
    return _read_optional_text(context.config.get("llm.defaults.profile"))


def _static_message(context: OrchestrationContext) -> str:
    if context.strategy_settings is not None and context.strategy_settings.message is not None:
        return context.strategy_settings.message
    return default_message_template_service().get_text(
        "fallback_answer",
        "default_message",
        fallback=_DEFAULT_FALLBACK_MESSAGE,
    )


def _safe_answer_text(value: object, fallback: str) -> str:
    if not isinstance(value, str):
        return fallback
    normalized = value.strip()
    if not normalized:
        return fallback
    return normalized


def _fallback_stream_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in metadata.items()
        if key in {"fallback_used", "fallback_reason", "failed_strategy", "failed_error_code", "answer_source"}
    }


async def _record_fallback_llm_failure(
    *,
    context: OrchestrationContext,
    strategy_name: str,
    llm_profile: str | None,
    failure_metadata: Mapping[str, Any],
    error: object,
) -> None:
    error_code = _read_optional_text(getattr(error, "code", None)) or "orchestration_error"
    retryable = bool(getattr(error, "retryable", False))
    logger.warning(
        "Fallback LLM generation failed; returning static fallback answer",
        extra={
            "component": _FALLBACK_COMPONENT,
            "event_type": _FALLBACK_LLM_FAILED,
            "status": "degraded",
            "details": {
                "trace_id": context.request.trace_id,
                "session_id": context.request.session_id,
                "usecase": context.request.usecase,
                "strategy_name": strategy_name,
                "llm_profile": llm_profile,
                "failed_strategy": failure_metadata.get("failed_strategy"),
                "failed_error_code": failure_metadata.get("failed_error_code"),
                "fallback_reason": failure_metadata.get("fallback_reason"),
                "fallback_llm_error": error_code,
                "retryable": retryable,
            },
        },
    )

    recorder = context.observability
    if recorder is None:
        return

    try:
        await recorder.record(
            event_type="orchestration",
            event_name=_FALLBACK_LLM_FAILED,
            component=_FALLBACK_COMPONENT,
            status="degraded",
            severity="warning",
            trace_id=context.request.trace_id,
            session_id=context.request.session_id,
            user_id=context.request.user_id,
            usecase=context.request.usecase,
            agent_name=_runtime_value(context, "agent_name"),
            strategy_name=strategy_name,
            llm_profile=llm_profile,
            error_type=type(error).__name__,
            error_code=error_code,
            retryable=retryable,
            payload={
                "answer_source": "static",
                "failed_strategy": failure_metadata.get("failed_strategy"),
                "failed_error_code": failure_metadata.get("failed_error_code"),
                "fallback_reason": failure_metadata.get("fallback_reason"),
            },
        )
    except Exception:
        return


def _runtime_value(context: OrchestrationContext, key: str) -> str | None:
    return _read_optional_text(context.runtime_metadata.get(key))


def _read_finish_reason(metadata: Mapping[str, Any]) -> str:
    finish_reason = _read_optional_text(metadata.get("finish_reason"))
    return finish_reason or "fallback"


def _read_optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None