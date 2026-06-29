"""Helpers for building safe prompt inputs from bounded sections."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from app.contracts.llm import LLMMessage
from app.orchestration.models import sanitize_metadata


@dataclass(frozen=True, slots=True)
class PromptSection:
    """One titled prompt section safe for LLM inputs."""

    title: str
    body: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "title", _normalize_text(self.title))
        object.__setattr__(self, "body", _normalize_text(self.body))
        object.__setattr__(self, "metadata", sanitize_metadata(self.metadata))

    def render(self) -> str:
        return f"{self.title}:\n{self.body}"


def render_prompt_sections(sections: Sequence[PromptSection]) -> str:
    return "\n\n".join(section.render() for section in sections)


def build_prompt_messages(
    *,
    user_request: str,
    sections: Sequence[PromptSection] = (),
    system_prompt: str | None = None,
) -> list[LLMMessage]:
    messages: list[LLMMessage] = []
    if system_prompt is not None:
        messages.append(LLMMessage(role="system", content=_normalize_text(system_prompt)))

    user_parts: list[str] = []
    rendered_sections = render_prompt_sections(sections)
    if rendered_sections:
        user_parts.append(rendered_sections)
    user_parts.append(f"User request:\n{_normalize_text(user_request)}")
    messages.append(LLMMessage(role="user", content="\n\n".join(user_parts)))
    return messages


def _normalize_text(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("Prompt text must be a string.")
    normalized = value.strip()
    if not normalized:
        raise ValueError("Prompt text must not be empty.")
    return normalized