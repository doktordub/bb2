"""Structured memory-candidate extraction agent plugin."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from time import perf_counter
from typing import Any, cast

from app.agents.errors import AgentMemoryCandidateError, AgentOutputParseError, normalize_agent_error
from app.agents.models import AgentCapabilities, AgentRunRequest, AgentRunResult, AgentWarning
from app.agents.plugins.base_llm_agent import BaseLlmAgent
from app.agents.policy import require_capability_allowed, require_capability_policy
from app.agents.prompts import build_prompt_messages, limit_prompt_sections, resolve_prompt_text
from app.agents.result_builder import build_run_result, build_usage_summary
from app.agents.trace_helpers import build_llm_trace_summary, build_memory_candidate_trace_summary, build_prompt_trace_summary, build_request_trace_summary, build_result_trace_summary
from app.contracts.context import OrchestrationContext
from app.contracts.llm import LLMMessage, LLMRequest, LLMResponseFormat
from app.memory.redaction import truncate_text
from app.orchestration.memory_intents import MemoryCandidate, MemoryCandidateScope
from app.orchestration.prompt_inputs import PromptSection

_AGENT_LLM_COMPLETED = "agent_llm_completed"
_AGENT_LLM_STARTED = "agent_llm_started"
_AGENT_PROMPT_BUILT = "agent_prompt_built"
_DEFAULT_MAX_MEMORY_CANDIDATES = 3
_DEFAULT_MAX_CONTEXT_BYTES = 32000
_DEFAULT_MAX_CONTEXT_ITEMS = 6
_ALLOWED_MEMORY_SCOPES = {
    "project_user",
    "project",
    "user",
    "tenant",
    "session",
    "agent",
    "usecase",
}


@dataclass(frozen=True, slots=True)
class _ParsedMemoryResponse:
    candidates: tuple[MemoryCandidate, ...] = ()
    warnings: tuple[AgentWarning, ...] = ()
    metadata: dict[str, Any] | None = None


class MemoryCuratorAgent(BaseLlmAgent):
    """Extract safe, bounded memory candidates without writing memory directly."""

    type = "memory_curator"
    description = "Extracts safe memory candidates for later policy-controlled writes."
    display_name = "Memory Curator Agent"
    output_kind = "memory_candidates"
    prompt_profile = "memory_curator_v1"
    stream_llm_deltas = False
    supported_strategies = ("memory_update",)
    structured_capabilities = AgentCapabilities(
        answer=False,
        review=False,
        stream=False,
        memory_read=False,
        memory_write=False,
        memory_candidate_extract=True,
        tool_intents=False,
        tool_execute=False,
        self_managed_memory=False,
        self_managed_tools=False,
    )
    metadata = {"built_in": True, "mode": "memory_candidate_extraction"}

    async def run_structured(
        self,
        *,
        request: AgentRunRequest,
        context: OrchestrationContext,
    ) -> AgentRunResult:
        require_capability_allowed(
            self.structured_capabilities,
            "memory_candidate_extract",
            agent_name=self.name,
        )
        await require_capability_policy(
            context,
            request=request,
            capability_name="memory_candidate_extract",
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
                memory_candidates=parsed.candidates,
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
                event_name="agent_memory_candidate_created",
                llm_profile=response_profile,
                payload=build_memory_candidate_trace_summary(
                    result.memory_candidates,
                    warnings=result.warnings,
                ),
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
        allowed_scopes = self._allowed_scopes(request)
        return (
            PromptSection(
                title="Allowed durable scopes",
                body="\n".join(f"- {scope_name}" for scope_name in allowed_scopes),
            ),
            PromptSection(
                title="Response contract",
                body=resolve_prompt_text(
                    "memory_curator",
                    "response_contract",
                    fallback=(
                        'Return JSON only with {"memory_candidates": [{"text": "...", '
                        '"memory_type": "...", "scope": "...", "reason": "..."}]}. '
                        "Return an empty list when nothing durable should be stored."
                    ),
                ),
            ),
            PromptSection(
                title="Curation rules",
                body=resolve_prompt_text(
                    "memory_curator",
                    "curation_rules",
                    fallback=(
                        "Keep only durable user or project facts, preferences, or follow-up details. "
                        "Do not include secrets, credentials, hidden reasoning, or one-off task steps."
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
            schema_name="memory_candidate_contract",
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
    ) -> _ParsedMemoryResponse:
        normalized_text = text.strip()
        if not normalized_text:
            raise AgentOutputParseError("Memory curator returned an empty response.")

        try:
            payload = json.loads(normalized_text)
        except json.JSONDecodeError as exc:
            raise AgentOutputParseError("Memory curator returned invalid JSON.") from exc

        raw_items = self._extract_payload_items(payload)
        limit = self._candidate_limit(request)
        allowed_scopes = self._allowed_scopes(request)
        default_scope = self._default_scope(request, allowed_scopes)
        warnings: list[AgentWarning] = []
        parsed: list[MemoryCandidate] = []
        limit_warning_added = False

        for item in raw_items:
            if len(parsed) >= limit:
                if not limit_warning_added:
                    warnings.append(
                        AgentWarning(
                            code="memory_candidate_limit_reached",
                            message="Memory curator truncated candidates to the configured limit.",
                            metadata={"max_memory_candidates": limit},
                        )
                    )
                    limit_warning_added = True
                break
            if not isinstance(item, Mapping):
                warnings.append(
                    AgentWarning(
                        code="memory_candidate_skipped",
                        message="Skipped one invalid memory candidate payload.",
                    )
                )
                continue

            try:
                parsed_candidate, candidate_warning = self._parse_candidate(
                    item,
                    request=request,
                    allowed_scopes=allowed_scopes,
                    default_scope=default_scope,
                )
            except AgentMemoryCandidateError as exc:
                warnings.append(
                    AgentWarning(
                        code="memory_candidate_skipped",
                        message=str(exc),
                    )
                )
                continue

            if candidate_warning is not None:
                warnings.append(candidate_warning)
            parsed.append(parsed_candidate)

        return _ParsedMemoryResponse(
            candidates=tuple(parsed),
            warnings=tuple(warnings),
            metadata={
                "response_mode": "memory_candidates",
                "candidate_count": len(parsed),
                "allowed_scopes": list(allowed_scopes),
            },
        )

    def _extract_payload_items(self, payload: object) -> list[object]:
        if isinstance(payload, list):
            return list(payload)
        if not isinstance(payload, Mapping):
            raise AgentOutputParseError("Memory curator returned an unsupported response shape.")

        raw_items = payload.get("memory_candidates")
        if raw_items is None:
            raw_items = payload.get("candidates")
        if raw_items is None and any(key in payload for key in ("text", "content", "value")):
            return [payload]
        if raw_items is None:
            return []
        if not isinstance(raw_items, list):
            raise AgentOutputParseError("Memory curator memory_candidates payload must be a list.")
        return list(raw_items)

    def _parse_candidate(
        self,
        item: Mapping[str, object],
        *,
        request: AgentRunRequest,
        allowed_scopes: tuple[str, ...],
        default_scope: str,
    ) -> tuple[MemoryCandidate, AgentWarning | None]:
        text = _read_optional_text(item.get("text") or item.get("content") or item.get("value"))
        if text is None:
            raise AgentMemoryCandidateError("Skipped one memory candidate without text.")

        scope = _read_optional_text(item.get("scope")) or default_scope
        if scope not in allowed_scopes:
            raise AgentMemoryCandidateError(
                "Skipped one memory candidate outside the allowed memory scopes."
            )

        truncated_text = truncate_text(text, max_chars=self._max_output_chars()) or text
        warning: AgentWarning | None = None
        if truncated_text != text:
            warning = AgentWarning(
                code="memory_candidate_truncated",
                message="Memory curator truncated one candidate to the configured limit.",
                metadata={"max_output_chars": self._max_output_chars()},
            )

        memory_type = _read_optional_text(item.get("memory_type") or item.get("type"))
        candidate = MemoryCandidate(
            text=truncated_text,
            memory_type=memory_type or _default_memory_type(scope=scope),
            scope=cast(MemoryCandidateScope, scope),
            importance=_read_optional_number(item.get("importance")),
            confidence=_read_optional_number(item.get("confidence")),
            ttl_days=_read_optional_positive_int(item.get("ttl_days")),
            reason=_read_optional_text(item.get("reason")),
            stable_key=_read_optional_text(item.get("stable_key")),
            tags=_read_tags(item.get("tags")),
            allow_retrieval=_read_optional_bool(item.get("allow_retrieval")),
            allow_llm_context=_read_optional_bool(item.get("allow_llm_context")),
            metadata={"source": "memory_curator"},
        )
        return candidate, warning

    def _candidate_limit(self, request: AgentRunRequest) -> int:
        output_limit = None if request.output_format is None else request.output_format.max_items
        if isinstance(output_limit, int) and output_limit > 0:
            return output_limit
        return _read_positive_int_attr(
            self.limits,
            "max_memory_candidates",
            _DEFAULT_MAX_MEMORY_CANDIDATES,
        )

    def _allowed_scopes(self, request: AgentRunRequest) -> tuple[str, ...]:
        configured = tuple(
            scope
            for scope in _read_text_tuple(getattr(self, "allowed_memory_scopes", ()))
            if scope in _ALLOWED_MEMORY_SCOPES
        )
        if configured:
            return configured
        if request.project_id is not None and request.user_id is not None:
            return ("project_user", "project", "user")
        if request.project_id is not None:
            return ("project",)
        if request.user_id is not None:
            return ("user",)
        return ("usecase",)

    def _default_scope(
        self,
        request: AgentRunRequest,
        allowed_scopes: tuple[str, ...],
    ) -> str:
        if request.project_id is not None and request.user_id is not None and "project_user" in allowed_scopes:
            return "project_user"
        if request.project_id is not None and "project" in allowed_scopes:
            return "project"
        if request.user_id is not None and "user" in allowed_scopes:
            return "user"
        return allowed_scopes[0]


def _default_memory_type(*, scope: str) -> str:
    return "project_fact" if scope in {"project", "project_user"} else "user_fact"


def _read_optional_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    return None


def _read_optional_number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def _read_optional_positive_int(value: object) -> int | None:
    if isinstance(value, int) and value > 0:
        return value
    return None


def _read_optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _read_positive_int_attr(source: object | None, name: str, default: int) -> int:
    value = getattr(source, name, default)
    return value if isinstance(value, int) and value > 0 else default


def _read_tags(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, str):
        return ()
    tags: list[str] = []
    for item in value:
        text = _read_optional_text(item)
        if text is not None:
            tags.append(text)
    return tuple(tags)


def _read_text_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, str):
        return ()
    items: list[str] = []
    for item in value:
        text = _read_optional_text(item)
        if text is not None:
            items.append(text)
    return tuple(items)


__all__ = ["MemoryCuratorAgent"]