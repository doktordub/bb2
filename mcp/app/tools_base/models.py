"""Core descriptor models for MCP tool plugins."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


RiskLevel = Literal[
    "read_only",
    "write",
    "destructive",
    "external_side_effect",
    "credential_access",
]
ToolStatus = Literal["experimental", "beta", "stable", "deprecated"]
ToolHealthState = Literal["ok", "degraded", "error"]


@dataclass(frozen=True, slots=True)
class CapabilityDescriptor:
    """Describes one capability exposed by a tool plugin."""

    name: str
    type: str
    description: str
    risk_level: RiskLevel
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ToolDescriptor:
    """Describes one MCP tool registration exposed by a plugin."""

    name: str
    description: str
    capability: str
    risk_level: RiskLevel
    input_schema: Literal["auto"] | dict[str, Any]
    output_schema: str | dict[str, Any] | None = None
    timeout_seconds: int | None = None
    max_result_bytes: int | None = None
    tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ToolHealth:
    """Bounded health result returned by a tool plugin."""

    state: ToolHealthState
    details: dict[str, Any] = field(default_factory=dict)