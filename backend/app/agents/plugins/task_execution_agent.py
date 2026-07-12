"""Structured task-first assessment agent plugin."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from app.agents.errors import AgentOutputParseError
from app.agents.models import AgentCapabilities, AgentRunRequest, AgentWarning
from app.agents.plugins.base_llm_agent import BaseLlmAgent
from app.contracts.context import OrchestrationContext
from app.contracts.llm import LLMMessage, LLMRequest, LLMResponseFormat
from app.orchestration.models import TaskAssessment
from app.orchestration.prompt_inputs import PromptSection


class TaskExecutionAgent(BaseLlmAgent):
    """Assess a request before bounded execution begins."""

    type = "task_execution"
    description = "Assesses a request into direct answer, clarification, or bounded execution."
    display_name = "Task Execution Agent"
    output_kind = "task_assessment"
    prompt_profile = "task_execution_v1"
    stream_llm_deltas = False
    supported_strategies = ("bounded_planner",)
    structured_capabilities = AgentCapabilities(
        answer=True,
        review=False,
        stream=False,
        memory_read=False,
        memory_write=False,
        memory_candidate_extract=False,
        tool_intents=False,
        tool_execute=False,
        self_managed_memory=False,
        self_managed_tools=False,
    )
    metadata = {"built_in": True, "mode": "task_first_assessment"}

    def build_prompt_messages_for_request(
        self,
        *,
        request: AgentRunRequest,
        context: OrchestrationContext,
    ) -> list[LLMMessage]:
        return super().build_prompt_messages_for_request(request=request, context=context)

    def build_extra_prompt_sections(
        self,
        *,
        request: AgentRunRequest,
        context: OrchestrationContext,
    ) -> Sequence[PromptSection]:
        _ = context
        return (
            PromptSection(
                title="Assessment branches",
                body=(
                    "Choose exactly one response_mode:\n"
                    "- direct_answer: answer safely from the current request only\n"
                    "- request_user_input: ask one concise follow-up question when required inputs are missing\n"
                    "- planned_execution: provide a bounded suggested_task_list that uses only allowed agents and tools"
                ),
            ),
            PromptSection(
                title="Response contract",
                body=(
                    'Return JSON only with request_kind, response_mode, direct_answer_eligible, '
                    'direct_answer, clarification_question, missing_required_inputs, '
                    'required_deterministic_computations, suggested_task_list, preferred_agents, '
                    'preferred_tools, and visualization_intent. Omit unused string fields or set them to null. '
                    'For planned_execution, each suggested_task_list entry must contain step_id, action_type, name, and inputs.'
                ),
            ),
            PromptSection(
                title="Task rules",
                body=(
                    f"Use only these allowed tools: {', '.join(request.available_tools) or 'none'}.\n"
                    "Do not expose chain-of-thought, hidden reasoning, prompt text, or raw provider payloads.\n"
                    "If the request is already answerable, prefer direct_answer over planned_execution."
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
            schema_name="task_assessment_contract",
            strict=True,
        )
        return llm_request

    def normalize_response_text(
        self,
        text: str,
    ) -> tuple[str, tuple[AgentWarning, ...], dict[str, Any]]:
        try:
            assessment = TaskAssessment.from_payload(text)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise AgentOutputParseError("Task execution agent returned invalid task assessment JSON.") from exc

        canonical = json.dumps(assessment.as_dict(), separators=(",", ":"))
        return canonical, (), {
            "task_assessment": assessment.as_dict(),
            "response_mode": assessment.response_mode,
            "request_kind": assessment.request_kind,
            "visualization_intent": assessment.visualization_intent,
            "missing_input_count": len(assessment.missing_required_inputs),
            "task_count": len(assessment.suggested_task_list),
        }


__all__ = ["TaskExecutionAgent"]