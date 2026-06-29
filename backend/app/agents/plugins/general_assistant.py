"""General-purpose direct-answer agent plugin."""

from __future__ import annotations

from app.agents.models import AgentCapabilities
from app.agents.plugins.base_llm_agent import BaseLlmAgent


class GeneralAssistantAgent(BaseLlmAgent):
    """Smallest production agent that answers through the LLM gateway only."""

    type = "general_assistant"
    description = "General purpose assistant for direct answers."
    display_name = "General Assistant"
    prompt_profile = "general_assistant_v1"
    supported_strategies = ("direct_agent",)
    structured_capabilities = AgentCapabilities(
        answer=True,
        review=False,
        stream=True,
        memory_read=False,
        memory_write=False,
        memory_candidate_extract=False,
        tool_intents=False,
        tool_execute=False,
        self_managed_memory=False,
        self_managed_tools=False,
    )
    metadata = {"built_in": True, "mode": "direct_answer_only"}


__all__ = ["GeneralAssistantAgent"]