"""Internal rule descriptors used by the policy engine."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PolicyRule:
    """Describe one internal policy rule and the actions it evaluates."""

    name: str
    actions: tuple[str, ...]
    component_prefixes: tuple[str, ...] = ()
    priority: int = 100