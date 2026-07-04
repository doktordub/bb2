"""Structured bounded reviewer agent plugin."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from time import perf_counter
from typing import Any

from app.agents.errors import AgentOutputParseError, AgentReviewError, normalize_agent_error
from app.agents.models import AgentCapabilities, AgentReviewResult, AgentRunRequest, AgentRunResult, AgentWarning
from app.agents.plugins.base_llm_agent import BaseLlmAgent
from app.agents.policy import require_capability_allowed, require_capability_policy
from app.agents.prompts import build_prompt_messages, limit_prompt_sections, resolve_prompt_lines, resolve_prompt_text
from app.agents.result_builder import build_run_result, build_usage_summary
from app.agents.trace_helpers import build_llm_trace_summary, build_prompt_trace_summary, build_request_trace_summary, build_result_trace_summary, build_review_trace_summary
from app.contracts.context import OrchestrationContext
from app.contracts.llm import LLMMessage, LLMRequest, LLMResponseFormat
from app.memory.redaction import truncate_text
from app.orchestration.prompt_inputs import PromptSection

_AGENT_LLM_COMPLETED = "agent_llm_completed"
_AGENT_LLM_STARTED = "agent_llm_started"
_AGENT_PROMPT_BUILT = "agent_prompt_built"
_DEFAULT_MAX_CONTEXT_BYTES = 32000
_DEFAULT_MAX_CONTEXT_ITEMS = 6
_DEFAULT_MAX_REVIEW_FINDINGS = 5
_DEFAULT_MAX_FINDING_CHARS = 240


@dataclass(frozen=True, slots=True)
class _ParsedReviewResponse:
    review: AgentReviewResult
    warnings: tuple[AgentWarning, ...] = ()
    metadata: dict[str, Any] | None = None


class ReviewerAgent(BaseLlmAgent):
    """Review bounded candidate output and return safe findings only."""

    type = "reviewer"
    description = "Reviews bounded candidate output for quality, safety, and completeness."
    display_name = "Reviewer Agent"
    output_kind = "review"
    prompt_profile = "reviewer_v1"
    stream_llm_deltas = False
    supported_strategies = ("bounded_planner", "direct_agent")
    structured_capabilities = AgentCapabilities(
        answer=False,
        review=True,
        stream=False,
        memory_read=False,
        memory_write=False,
        memory_candidate_extract=False,
        tool_intents=False,
        tool_execute=False,
        self_managed_memory=False,
        self_managed_tools=False,
    )
    metadata = {"built_in": True, "mode": "bounded_review"}

    async def run_structured(
        self,
        *,
        request: AgentRunRequest,
        context: OrchestrationContext,
    ) -> AgentRunResult:
        require_capability_allowed(self.structured_capabilities, "review", agent_name=self.name)
        await require_capability_policy(
            context,
            request=request,
            capability_name="review",
            component=self.component,
            agent_name=self.name,
            metadata={"agent_type": self.type},
        )
        self._require_llm_call_budget()

        bounded_request = self._bounded_request(request)
        started_at = perf_counter()
        llm_profile = self.resolve_llm_profile(bounded_request)
        await self._record_trace(
            context=context,
            request=bounded_request,
            event_name="agent_started",
            status="started",
            llm_profile=llm_profile,
            payload=build_request_trace_summary(bounded_request, agent_name=self.name),
        )

        try:
            await self._require_invoke_policy(context=context, request=bounded_request)
            messages = self.build_prompt_messages_for_request(
                request=bounded_request,
                context=context,
            )
            await self._record_trace(
                context=context,
                request=bounded_request,
                event_name=_AGENT_PROMPT_BUILT,
                llm_profile=llm_profile,
                payload=build_prompt_trace_summary(
                    bounded_request,
                    agent_name=self.name,
                    prompt_profile=self.prompt_profile,
                    message_count=len(messages),
                ),
            )

            await self._require_llm_policy(
                context=context,
                request=bounded_request,
                llm_profile=llm_profile,
                stream=False,
            )
            llm_request = self.build_llm_request(
                messages=messages,
                request=bounded_request,
                llm_profile=llm_profile,
                stream=False,
            )
            llm_started_at = perf_counter()
            await self._record_trace(
                context=context,
                request=bounded_request,
                event_name=_AGENT_LLM_STARTED,
                status="started",
                llm_profile=llm_profile,
                payload=build_llm_trace_summary(
                    llm_profile=llm_profile,
                    output_kind=self.output_kind,
                ),
            )
            response = await context.llm.complete(llm_request, context)
            llm_duration_ms = int((perf_counter() - llm_started_at) * 1000)

            parsed = self._parse_response(response.text, request=bounded_request)
            response_profile = response.profile or llm_profile
            result = build_run_result(
                status="completed",
                answer=None,
                agent_name=self.name,
                llm_profile=response_profile,
                review=parsed.review,
                usage=build_usage_summary(
                    llm_calls=1,
                    input_chars=sum(len(message.content) for message in messages if isinstance(message.content, str)),
                    output_chars=len(response.text),
                ),
                warnings=parsed.warnings,
                metadata={
                    **(parsed.metadata or {}),
                    **self._response_metadata(response),
                },
            )

            await self._record_trace(
                context=context,
                request=bounded_request,
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
                request=bounded_request,
                event_name="agent_review_completed",
                llm_profile=response_profile,
                payload=build_review_trace_summary(parsed.review),
            )
            await self._record_trace(
                context=context,
                request=bounded_request,
                event_name="agent_completed",
                llm_profile=response_profile,
                duration_ms=float(int((perf_counter() - started_at) * 1000)),
                payload={
                    **build_result_trace_summary(result),
                    "duration_ms": int((perf_counter() - started_at) * 1000),
                },
            )
            return result
        except BaseException as exc:
            normalized = normalize_agent_error(exc)
            await self._record_failure(
                context=context,
                request=bounded_request,
                llm_profile=llm_profile,
                error=normalized,
                duration_ms=float(int((perf_counter() - started_at) * 1000)),
            )
            if normalized is exc:
                raise
            raise normalized from exc

    def build_prompt_messages_for_request(
        self,
        *,
        request: AgentRunRequest,
        context: OrchestrationContext,
    ) -> list[LLMMessage]:
        bounded_request = self._bounded_request(request)
        return build_prompt_messages(
            bounded_request,
            system_prompt=self.build_system_prompt(request=bounded_request, context=context),
            extra_sections=self.build_extra_prompt_sections(
                request=bounded_request,
                context=context,
            ),
        )

    def build_extra_prompt_sections(
        self,
        *,
        request: AgentRunRequest,
        context: OrchestrationContext,
    ) -> tuple[PromptSection, ...]:
        _ = context
        criteria = request.constraints or resolve_prompt_lines(
            "reviewer",
            "default_criteria",
            fallback=(
                "Check correctness against provided context.",
                "Call out important omissions or risks.",
                "Keep findings short and actionable.",
            ),
        )
        return (
            PromptSection(
                title="Review criteria",
                body="\n".join(f"- {criterion}" for criterion in criteria),
            ),
            PromptSection(
                title="Response contract",
                body=resolve_prompt_text(
                    "reviewer",
                    "response_contract",
                    fallback=(
                        'Return JSON only with {"passed": true|false, "score": 0.0-1.0, '
                        '"findings": ["..."], "suggested_revision": "..."}. '
                        "Use a small bounded findings list and omit suggested_revision when not needed."
                    ),
                ),
            ),
            PromptSection(
                title="Review rules",
                body=resolve_prompt_text(
                    "reviewer",
                    "review_rules",
                    fallback=(
                        "Do not reveal chain-of-thought or hidden scratchpads. Return only safe findings, "
                        "an optional score, and an optional suggested revision."
                    ),
                ),
            ),
        )

    def build_llm_request(
        self,
        *,
        messages: Sequence[LLMMessage],
        request: AgentRunRequest,
        llm_profile: str,
        stream: bool,
    ) -> LLMRequest:
        llm_request = super().build_llm_request(
            messages=messages,
            request=request,
            llm_profile=llm_profile,
            stream=stream,
        )
        llm_request.response_format = LLMResponseFormat(
            type="json_object",
            schema_name="review_contract",
            strict=True,
        )
        return llm_request

    def _bounded_request(self, request: AgentRunRequest) -> AgentRunRequest:
        max_context_items = _read_positive_int_attr(
            self.context_policy,
            "max_context_items",
            _DEFAULT_MAX_CONTEXT_ITEMS,
        )
        max_context_bytes = _read_positive_int_attr(
            self.context_policy,
            "max_context_bytes",
            _DEFAULT_MAX_CONTEXT_BYTES,
        )
        bounded_context = limit_prompt_sections(
            request.context_items,
            max_items=max_context_items,
            max_chars=max_context_bytes,
        )
        return replace(request, context_items=bounded_context)

    def _parse_response(
        self,
        text: str,
        *,
        request: AgentRunRequest,
    ) -> _ParsedReviewResponse:
        normalized_text = text.strip()
        if not normalized_text:
            raise AgentOutputParseError("Reviewer returned an empty response.")

        try:
            payload = json.loads(normalized_text)
        except json.JSONDecodeError as exc:
            raise AgentOutputParseError("Reviewer returned invalid JSON.") from exc

        if isinstance(payload, Mapping) and isinstance(payload.get("review"), Mapping):
            payload = payload["review"]
        if not isinstance(payload, Mapping):
            raise AgentOutputParseError("Reviewer returned an unsupported response shape.")

        review, warnings = self._build_review(payload, request=request)
        return _ParsedReviewResponse(
            review=review,
            warnings=tuple(warnings),
            metadata={
                "response_mode": "review",
                "review_passed": review.passed,
                "finding_count": len(review.findings),
            },
        )

    def _build_review(
        self,
        payload: Mapping[str, object],
        *,
        request: AgentRunRequest,
    ) -> tuple[AgentReviewResult, list[AgentWarning]]:
        passed = payload.get("passed")
        if not isinstance(passed, bool):
            raise AgentReviewError("Reviewer response is missing a boolean passed value.")

        score = _read_optional_number(payload.get("score"))
        if score is not None and score > 1:
            score = min(score / 10.0, 1.0)

        findings_raw = payload.get("findings")
        warnings: list[AgentWarning] = []
        findings: list[str] = []
        if isinstance(findings_raw, Sequence) and not isinstance(findings_raw, str):
            limit = self._finding_limit(request)
            for item in findings_raw[:limit]:
                text = _read_optional_text(item)
                if text is None:
                    continue
                truncated = truncate_text(text, max_chars=_DEFAULT_MAX_FINDING_CHARS) or text
                if truncated != text:
                    warnings.append(
                        AgentWarning(
                            code="review_finding_truncated",
                            message="Reviewer truncated one finding to the safe limit.",
                            metadata={"max_chars": _DEFAULT_MAX_FINDING_CHARS},
                        )
                    )
                findings.append(truncated)
            if len(findings_raw) > limit:
                warnings.append(
                    AgentWarning(
                        code="review_findings_limited",
                        message="Reviewer truncated findings to the configured limit.",
                        metadata={"max_findings": limit},
                    )
                )

        suggested_revision = _read_optional_text(payload.get("suggested_revision"))
        if suggested_revision is not None:
            normalized_suggested_revision, suggestion_warnings, _ = self.normalize_response_text(
                suggested_revision
            )
            warnings.extend(suggestion_warnings)
            suggested_revision = normalized_suggested_revision

        status = _read_optional_text(payload.get("status")) or "completed"
        metadata = {
            "criteria_count": len(request.constraints),
            "suggested_revision_present": suggested_revision is not None,
        }
        return (
            AgentReviewResult(
                status=status,
                passed=passed,
                score=score,
                findings=tuple(findings),
                suggested_revision=suggested_revision,
                metadata=metadata,
            ),
            warnings,
        )

    def _finding_limit(self, request: AgentRunRequest) -> int:
        output_limit = None if request.output_format is None else request.output_format.max_items
        if isinstance(output_limit, int) and output_limit > 0:
            return output_limit
        return _DEFAULT_MAX_REVIEW_FINDINGS


def _read_optional_number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def _read_optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _read_positive_int_attr(source: object | None, name: str, default: int) -> int:
    value = getattr(source, name, default)
    return value if isinstance(value, int) and value > 0 else default


__all__ = ["ReviewerAgent"]