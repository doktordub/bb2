"""Capability helpers for the structured agent layer."""

from __future__ import annotations

from dataclasses import fields

from app.agents.errors import AgentCapabilityError
from app.agents.models import AgentCapabilities

_CAPABILITY_FIELD_NAMES = tuple(field.name for field in fields(AgentCapabilities))


def capabilities_from_settings(settings: object) -> AgentCapabilities:
    """Coerce config-shaped capability settings into the agent capability model."""

    if isinstance(settings, AgentCapabilities):
        return validate_capabilities(settings)

    defaults = AgentCapabilities()
    values: dict[str, bool] = {}
    for field_name in _CAPABILITY_FIELD_NAMES:
        values[field_name] = bool(getattr(settings, field_name, getattr(defaults, field_name)))
    return validate_capabilities(AgentCapabilities(**values))


def validate_capabilities(capabilities: AgentCapabilities) -> AgentCapabilities:
    """Validate the local invariants for one capability set."""

    if capabilities.self_managed_tools and not capabilities.tool_execute:
        raise AgentCapabilityError("Self-managed tool mode requires tool_execute.")
    if capabilities.self_managed_memory and not (
        capabilities.memory_read or capabilities.memory_write
    ):
        raise AgentCapabilityError(
            "Self-managed memory mode requires memory_read or memory_write."
        )
    return capabilities


def require_capability(
    capabilities: AgentCapabilities,
    capability_name: str,
    *,
    agent_name: str | None = None,
) -> None:
    """Raise when a disabled or unknown capability is requested."""

    if capability_name not in _CAPABILITY_FIELD_NAMES:
        raise AgentCapabilityError(f"Unknown agent capability: {capability_name}.")
    if not getattr(capabilities, capability_name):
        target = agent_name or "unknown"
        raise AgentCapabilityError(
            f"Agent {target} does not allow capability {capability_name}."
        )


def capability_summary(capabilities: AgentCapabilities) -> dict[str, bool]:
    """Return a JSON-safe capability summary."""

    return {
        field_name: bool(getattr(capabilities, field_name))
        for field_name in _CAPABILITY_FIELD_NAMES
    }


def capability_labels(capabilities: AgentCapabilities) -> tuple[str, ...]:
    """Return the enabled capability labels safe for API exposure."""

    return tuple(
        field_name
        for field_name in _CAPABILITY_FIELD_NAMES
        if getattr(capabilities, field_name)
    )


def streaming_supported(capabilities: AgentCapabilities) -> bool:
    """Return whether one agent supports safe streaming."""

    return capabilities.stream


def tools_required(capabilities: AgentCapabilities) -> bool:
    """Return whether one agent requires direct tool access."""

    return capabilities.tool_execute or capabilities.self_managed_tools


def memory_required(capabilities: AgentCapabilities) -> bool:
    """Return whether one agent requires direct memory access."""

    return (
        capabilities.memory_read
        or capabilities.memory_write
        or capabilities.self_managed_memory
    )


__all__ = [
    "capabilities_from_settings",
    "capability_labels",
    "capability_summary",
    "memory_required",
    "require_capability",
    "streaming_supported",
    "tools_required",
    "validate_capabilities",
]