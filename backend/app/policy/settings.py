"""Typed policy settings resolved from validated configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

PolicyMode = Literal["enforce", "report_only"]
PolicyDefaultDecision = Literal["allow", "deny"]


@dataclass(frozen=True, slots=True)
class PolicyNamedAccessSettings:
    """Typed allowlist settings for named backend resources."""

    allowed: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PolicyLLMSettings:
    """Typed LLM policy settings for a single policy profile."""

    deny_unknown_profiles: bool = True
    allowed_profiles: tuple[str, ...] = ()
    allow_prompt_trace: bool = False
    allow_completion_trace: bool = False


@dataclass(frozen=True, slots=True)
class PolicyMemorySettings:
    """Typed memory policy settings for a single policy profile."""

    require_scope: bool = True
    allow_writes: bool = False
    allowed_read_scopes: tuple[str, ...] = ()
    allowed_write_scopes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PolicyToolSettings:
    """Typed logical-tool policy settings for a single policy profile."""

    deny_unknown_tools: bool = True
    allowed_tools: tuple[str, ...] = ()
    allow_write_tools: bool = False
    allow_destructive_tools: bool = False
    allow_external_side_effect_tools: bool = False
    allow_approval_required_tools: bool = False


@dataclass(frozen=True, slots=True)
class PolicyApprovalSettings:
    """Typed approval policy settings for a single policy profile."""

    require_approval_for_write_tools: bool = True
    require_approval_for_destructive_tools: bool = True
    require_approval_for_external_side_effect_tools: bool = True
    require_approval_for_memory_writes: bool = False


@dataclass(frozen=True, slots=True)
class PolicyFallbackSettings:
    """Typed fallback policy settings for a single policy profile."""

    allow_fallbacks: bool = True
    allow_after_denial: bool = False
    allow_after_external_side_effects: bool = False
    allowed_strategies: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PolicyTraceSettings:
    """Typed trace exposure policy settings for a single policy profile."""

    allow_trace: bool = True
    expose_raw_payloads: bool = False
    expose_prompt_text: bool = False
    expose_completion_text: bool = False


@dataclass(frozen=True, slots=True)
class PolicyStreamSettings:
    """Typed stream exposure policy settings for a single policy profile."""

    allow_stream_events: bool = True
    expose_internal_events: bool = False
    expose_raw_deltas: bool = False


@dataclass(frozen=True, slots=True)
class PolicyCapabilitySettings:
    """Typed capability exposure policy settings for a single policy profile."""

    expose_enabled: bool = True
    include_policy_profiles: bool = False
    include_denied_actions: bool = False


@dataclass(frozen=True, slots=True)
class PolicyHealthSettings:
    """Typed health exposure policy settings for a single policy profile."""

    expose_enabled: bool = True
    include_profile_names: bool = True
    include_decision_counts: bool = False


@dataclass(frozen=True, slots=True)
class PolicyAuditSettings:
    """Typed audit policy settings for a single policy profile."""

    enabled: bool = True
    include_reason_codes: bool = True
    include_actor_identifiers: bool = False
    include_resource_names: bool = True


@dataclass(frozen=True, slots=True)
class PolicyDecisionCacheSettings:
    """Typed decision-cache settings for a single policy profile."""

    enabled: bool = True
    ttl_seconds: int = 30
    max_entries: int = 1024


@dataclass(frozen=True, slots=True)
class PolicyProfileSettings:
    """Typed policy profile settings used by the backend runtime."""

    name: str
    enabled: bool = True
    mode: PolicyMode = "enforce"
    default_decision: PolicyDefaultDecision = "deny"
    fail_closed: bool = True
    deny_unknown_tools: bool = True
    deny_unknown_llm_profiles: bool = True
    require_memory_scope: bool = True
    allow_memory_writes: bool = False
    allow_write_tools: bool = False
    allow_destructive_tools: bool = False
    allow_external_side_effect_tools: bool = False
    allow_approval_required_tools: bool = False
    usecases: PolicyNamedAccessSettings = field(default_factory=PolicyNamedAccessSettings)
    strategies: PolicyNamedAccessSettings = field(default_factory=PolicyNamedAccessSettings)
    agents: PolicyNamedAccessSettings = field(default_factory=PolicyNamedAccessSettings)
    llm: PolicyLLMSettings = field(default_factory=PolicyLLMSettings)
    memory: PolicyMemorySettings = field(default_factory=PolicyMemorySettings)
    tools: PolicyToolSettings = field(default_factory=PolicyToolSettings)
    approval: PolicyApprovalSettings = field(default_factory=PolicyApprovalSettings)
    fallback: PolicyFallbackSettings = field(default_factory=PolicyFallbackSettings)
    trace: PolicyTraceSettings = field(default_factory=PolicyTraceSettings)
    stream: PolicyStreamSettings = field(default_factory=PolicyStreamSettings)
    capabilities: PolicyCapabilitySettings = field(default_factory=PolicyCapabilitySettings)
    health: PolicyHealthSettings = field(default_factory=PolicyHealthSettings)
    audit: PolicyAuditSettings = field(default_factory=PolicyAuditSettings)
    decision_cache: PolicyDecisionCacheSettings = field(default_factory=PolicyDecisionCacheSettings)


@dataclass(frozen=True, slots=True)
class PolicySettings:
    """Typed root policy settings resolved from validated configuration."""

    enabled: bool = True
    mode: PolicyMode = "enforce"
    default_profile: str = "default"
    default_decision: PolicyDefaultDecision = "deny"
    fail_closed: bool = True
    profiles: dict[str, PolicyProfileSettings] = field(default_factory=dict)