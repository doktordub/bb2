"""Project-scoped logical tool-intent agent plugin."""

from __future__ import annotations

from dataclasses import replace

from app.agents.errors import AgentInputValidationError
from app.agents.models import AgentCapabilities, AgentRunRequest, AgentRunResult
from app.agents.plugins.tool_using import ToolUsingAgent
from app.agents.policy import require_project_scope
from app.agents.prompts import limit_prompt_sections, resolve_prompt_text
from app.agents.result_builder import build_run_result
from app.contracts.context import OrchestrationContext
from app.orchestration.prompt_inputs import PromptSection

_DEFAULT_MAX_CONTEXT_BYTES = 32000
_DEFAULT_MAX_CONTEXT_ITEMS = 6
_DEFAULT_MAX_TOOL_CONTEXT_ITEMS = 4


class ProjectAgent(ToolUsingAgent):
    """Answer or request logical project tools within one validated project scope."""

    type = "project_agent"
    description = "Project-scoped assistant for architecture, plan, and file-oriented work."
    display_name = "Project Agent"
    prompt_profile = "project_agent_v1"
    supported_strategies: tuple[str, ...] = (
        "direct_agent",
        "tool_assisted",
        "bounded_planner",
    )
    structured_capabilities = AgentCapabilities(
        answer=True,
        review=False,
        stream=True,
        memory_read=True,
        memory_write=False,
        memory_candidate_extract=False,
        tool_intents=True,
        tool_execute=False,
        self_managed_memory=False,
        self_managed_tools=False,
    )
    metadata = {"built_in": True, "mode": "project_scoped"}

    async def run_structured(
        self,
        *,
        request: AgentRunRequest,
        context: OrchestrationContext,
    ) -> AgentRunResult:
        require_project_scope(request, agent_name=self.name)
        bounded_request = self._bounded_request(request)
        if not bounded_request.project_id:
            raise AgentInputValidationError(
                f"Agent '{self.name}' requires an active project scope."
            )

        result = await super().run_structured(request=bounded_request, context=context)
        return build_run_result(
            status=result.status,
            answer=result.answer,
            agent_name=result.agent_name,
            llm_profile=result.llm_profile,
            tool_intents=result.tool_intents,
            memory_candidates=result.memory_candidates,
            review=result.review,
            usage=result.usage,
            output_items=result.output_items,
            warnings=result.warnings,
            metadata={
                **result.metadata,
                "project_id_present": True,
                "project_context_count": len(bounded_request.context_items),
                "project_tool_context_count": len(bounded_request.tool_context),
            },
        )

    def build_extra_prompt_sections(
        self,
        *,
        request: AgentRunRequest,
        context: OrchestrationContext,
    ) -> tuple[PromptSection, ...]:
        sections = list(super().build_extra_prompt_sections(request=request, context=context))
        sections.insert(
            0,
            PromptSection(
                title="Active project scope",
                body=(
                    f"Project ID: {request.project_id}\n"
                    f"Context items: {len(request.context_items)}\n"
                    f"Tool context items: {len(request.tool_context)}"
                ),
            ),
        )
        sections.append(
            PromptSection(
                title="Project rules",
                body=resolve_prompt_text(
                    "project_agent",
                    "project_rules",
                    fallback=(
                        "Stay within the active project scope, use only provided project context, "
                        "and request only logical backend tools from the allowlist when more project "
                        "evidence is needed. Never claim direct file or repository access."
                    ),
                ),
            )
        )
        return tuple(sections)

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
        max_tool_context_bytes = _read_positive_int_attr(
            self.limits,
            "max_prompt_context_bytes",
            _DEFAULT_MAX_CONTEXT_BYTES,
        )
        bounded_context = limit_prompt_sections(
            request.context_items,
            max_items=max_context_items,
            max_chars=max_context_bytes,
        )
        bounded_tool_context = limit_prompt_sections(
            request.tool_context,
            max_items=_DEFAULT_MAX_TOOL_CONTEXT_ITEMS,
            max_chars=max_tool_context_bytes,
        )
        return replace(
            request,
            context_items=bounded_context,
            tool_context=bounded_tool_context,
        )


def _read_positive_int_attr(source: object | None, name: str, default: int) -> int:
    value = getattr(source, name, default)
    return value if isinstance(value, int) and value > 0 else default


__all__ = ["ProjectAgent"]