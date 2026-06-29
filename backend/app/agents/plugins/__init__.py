"""Built-in structured agent plugins."""

from __future__ import annotations

from importlib import import_module
from typing import Any


_LAZY_EXPORTS = {
	"BaseLlmAgent": ("app.agents.plugins.base_llm_agent", "BaseLlmAgent"),
	"DocumentQaAgent": ("app.agents.plugins.document_qa", "DocumentQaAgent"),
	"GeneralAssistantAgent": ("app.agents.plugins.general_assistant", "GeneralAssistantAgent"),
	"MemoryCuratorAgent": ("app.agents.plugins.memory_curator", "MemoryCuratorAgent"),
	"ProjectAgent": ("app.agents.plugins.project_agent", "ProjectAgent"),
	"ReviewerAgent": ("app.agents.plugins.reviewer", "ReviewerAgent"),
	"ToolUsingAgent": ("app.agents.plugins.tool_using", "ToolUsingAgent"),
}


def __getattr__(name: str) -> Any:
	if name not in _LAZY_EXPORTS:
		raise AttributeError(name)
	module_name, attribute_name = _LAZY_EXPORTS[name]
	module = import_module(module_name)
	return getattr(module, attribute_name)

__all__ = [
	"BaseLlmAgent",
	"DocumentQaAgent",
	"GeneralAssistantAgent",
	"MemoryCuratorAgent",
	"ProjectAgent",
	"ReviewerAgent",
	"ToolUsingAgent",
]