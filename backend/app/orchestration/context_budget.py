"""Helpers for building bounded prompt context blocks."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.orchestration.models import sanitize_metadata


@dataclass(frozen=True, slots=True)
class ContextBudget:
    """Byte and item limits for safe prompt-context construction."""

    max_bytes: int
    max_items: int | None = None

    def __post_init__(self) -> None:
        if self.max_bytes <= 0:
            raise ValueError("Context budget max_bytes must be positive.")
        if self.max_items is not None and self.max_items <= 0:
            raise ValueError("Context budget max_items must be positive when provided.")


@dataclass(frozen=True, slots=True)
class ContextBudgetItem:
    """One text block eligible for inclusion in a bounded context window."""

    text: str
    label: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "text", _normalize_text(self.text))
        object.__setattr__(self, "label", _normalize_optional_text(self.label))
        object.__setattr__(self, "metadata", sanitize_metadata(self.metadata))

    def render(self) -> str:
        if self.label is None:
            return self.text
        return f"{self.label} {self.text}".strip()


@dataclass(frozen=True, slots=True)
class BudgetedContext:
    """Result of applying a context budget to candidate text blocks."""

    text: str
    item_count: int
    used_bytes: int
    truncated: bool
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "text", _normalize_text(self.text))
        object.__setattr__(self, "item_count", max(self.item_count, 0))
        object.__setattr__(self, "used_bytes", max(self.used_bytes, 0))
        object.__setattr__(self, "metadata", sanitize_metadata(self.metadata))


def budget_context_items(
    items: list[ContextBudgetItem],
    *,
    budget: ContextBudget,
    prefix: str | None = None,
    empty_text: str = "No context.",
) -> BudgetedContext:
    """Return a bounded text block composed from the provided candidate items."""

    selected_lines: list[str] = []
    used_bytes = 0
    item_count = 0
    truncated = False
    max_items = budget.max_items if budget.max_items is not None else len(items)

    for candidate in items[:max_items]:
        rendered = candidate.render()
        if not rendered:
            continue

        candidate_bytes = len(rendered.encode("utf-8"))
        if used_bytes + candidate_bytes <= budget.max_bytes:
            selected_lines.append(rendered)
            used_bytes += candidate_bytes
            item_count += 1
            continue

        remaining_bytes = budget.max_bytes - used_bytes
        if remaining_bytes <= 0:
            truncated = True
            break

        clipped = _truncate_to_bytes(rendered, remaining_bytes)
        if clipped:
            selected_lines.append(clipped)
            used_bytes += len(clipped.encode("utf-8"))
            item_count += 1
        truncated = True
        break

    if not selected_lines:
        return BudgetedContext(
            text=empty_text,
            item_count=0,
            used_bytes=0,
            truncated=False,
            metadata={} if prefix is None else {"prefix": prefix},
        )

    lines: list[str] = []
    if prefix is not None:
        lines.append(prefix)
    lines.extend(selected_lines)
    return BudgetedContext(
        text="\n".join(lines),
        item_count=item_count,
        used_bytes=used_bytes,
        truncated=truncated,
        metadata={} if prefix is None else {"prefix": prefix},
    )


def _truncate_to_bytes(value: str, max_bytes: int) -> str:
    if max_bytes <= 0:
        return ""
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value
    if max_bytes <= 3:
        return encoded[:max_bytes].decode("utf-8", errors="ignore")
    clipped = encoded[: max_bytes - 3].decode("utf-8", errors="ignore").rstrip()
    if not clipped:
        return "..."
    return f"{clipped}..."


def _normalize_text(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("Context text must be a string.")
    normalized = value.strip()
    if not normalized:
        raise ValueError("Context text must not be empty.")
    return normalized


def _normalize_optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None