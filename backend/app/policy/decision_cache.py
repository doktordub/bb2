"""Safe in-memory decision cache for repeated policy evaluations."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import json
from typing import Any

from app.contracts.context import OrchestrationContext
from app.contracts.policy import PolicyDecision, PolicyObligation, PolicyRequest
from app.policy.context import resolve_policy_context
from app.policy.settings import PolicyDecisionCacheSettings

_SAFE_METADATA_KEYS = frozenset(
    {
        "policy_profile",
        "rule",
        "resource",
        "payload_category",
        "scope_type",
        "safety_level",
        "fallback_blocked",
        "tool_known",
        "tool_enabled",
        "tool_supports_streaming",
        "tool_approval_required",
        "stream_requested",
        "memory_scope_type",
        "memory_scope_present",
        "memory_write",
        "memory_admin",
        "memory_type",
        "stable_key_present",
        "allow_retrieval",
        "allow_llm_context",
        "memory_intent_explicit",
        "memory_sensitivity",
        "event_name",
        "event_type",
        "field_names",
        "provider",
        "tool_group",
        "configured",
    }
)


@dataclass(frozen=True, slots=True)
class CachedPolicyDecision:
    """Stored cache entry for one safe policy decision."""

    decision: PolicyDecision
    expires_at: datetime


class PolicyDecisionCache:
    """Bounded per-process cache for repeatable, safe policy decisions."""

    def __init__(self, settings: PolicyDecisionCacheSettings) -> None:
        self._settings = settings
        self._entries: OrderedDict[str, CachedPolicyDecision] = OrderedDict()
        self._hits = 0
        self._misses = 0
        self._evictions = 0

    @property
    def enabled(self) -> bool:
        return self._settings.enabled

    def get(self, request: PolicyRequest, context: OrchestrationContext, *, profile_name: str) -> PolicyDecision | None:
        if not self.enabled:
            self._misses += 1
            return None

        key = build_policy_cache_key(request, context, profile_name=profile_name)
        entry = self._entries.get(key)
        if entry is None:
            self._misses += 1
            return None

        if entry.expires_at <= datetime.now(UTC):
            self._entries.pop(key, None)
            self._misses += 1
            return None

        self._entries.move_to_end(key)
        self._hits += 1
        return entry.decision

    def put(
        self,
        request: PolicyRequest,
        context: OrchestrationContext,
        *,
        profile_name: str,
        decision: PolicyDecision,
    ) -> PolicyDecision:
        if not self.enabled:
            return decision

        key = build_policy_cache_key(request, context, profile_name=profile_name)
        cached_decision = sanitize_policy_decision_for_storage(decision)
        self._entries[key] = CachedPolicyDecision(
            decision=cached_decision,
            expires_at=datetime.now(UTC) + timedelta(seconds=max(self._settings.ttl_seconds, 1)),
        )
        self._entries.move_to_end(key)
        self._trim()
        return cached_decision

    def snapshot(self) -> dict[str, int | bool]:
        self._purge_expired()
        return {
            "enabled": self.enabled,
            "size": len(self._entries),
            "max_entries": self._settings.max_entries,
            "ttl_seconds": self._settings.ttl_seconds,
            "hits": self._hits,
            "misses": self._misses,
            "evictions": self._evictions,
        }

    def _trim(self) -> None:
        self._purge_expired()
        max_entries = max(self._settings.max_entries, 0)
        while len(self._entries) > max_entries:
            self._entries.popitem(last=False)
            self._evictions += 1

    def _purge_expired(self) -> None:
        now = datetime.now(UTC)
        expired_keys = [key for key, value in self._entries.items() if value.expires_at <= now]
        for key in expired_keys:
            self._entries.pop(key, None)


def build_policy_cache_key(
    request: PolicyRequest,
    context: OrchestrationContext,
    *,
    profile_name: str,
) -> str:
    """Build a low-risk cache key from stable policy request dimensions."""

    resolved = resolve_policy_context(request)
    evaluation = resolved.evaluation
    safe_payload = {
        "action": request.action,
        "component": request.component,
        "resource": _hash_optional_text(request.resource),
        "profile": profile_name,
        "trace_id": _hash_optional_text(evaluation.trace_id or getattr(context.request, "trace_id", None)),
        "usecase": _hash_optional_text(evaluation.usecase_name),
        "strategy_name": _hash_optional_text(evaluation.strategy_name),
        "agent_name": _hash_optional_text(evaluation.agent_name),
        "risk_level": _hash_optional_text(evaluation.risk_level),
        "tags": tuple(sorted(evaluation.tags)),
        "actor_roles": tuple(sorted(resolved.actor.roles)),
        "actor_type": resolved.actor.actor_type,
        "scope_hash": _hash_mapping(
            {
                "tenant_id": resolved.scope.tenant_id,
                "project_id": resolved.scope.project_id,
                "user_id": resolved.scope.user_id,
                "session_id": resolved.scope.session_id,
                "usecase_name": resolved.scope.usecase_name,
                "strategy_name": resolved.scope.strategy_name,
                "agent_name": resolved.scope.agent_name,
                "memory_scope": resolved.scope.memory_scope,
            }
        ),
        "metadata_hash": _hash_mapping(_safe_metadata_for_key(request.metadata)),
        "context_usecase": _hash_optional_text(getattr(context.request, "usecase", None)),
    }
    serialized = json.dumps(safe_payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def sanitize_policy_decision_for_storage(decision: PolicyDecision) -> PolicyDecision:
    """Return a safe decision copy suitable for cache storage."""

    return PolicyDecision(
        allowed=decision.allowed,
        reason=decision.reason,
        requires_approval=decision.requires_approval,
        metadata=_safe_metadata_for_storage(decision.metadata),
        decision=decision.decision,
        reason_code=decision.reason_code,
        obligations=tuple(_sanitize_obligation(item) for item in decision.obligations),
        actor=None,
        scope=None,
    )


def _sanitize_obligation(obligation: PolicyObligation) -> PolicyObligation:
    return PolicyObligation(
        kind=obligation.kind,
        target=_normalize_safe_text(obligation.target),
        value=_sanitize_value(obligation.value),
        metadata=_safe_metadata_for_storage(obligation.metadata),
    )


def _safe_metadata_for_storage(metadata: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in metadata.items():
        normalized_key = str(key)
        if normalized_key not in _SAFE_METADATA_KEYS:
            continue
        result[normalized_key] = _sanitize_value(value)
    return result


def _safe_metadata_for_key(metadata: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in metadata.items():
        normalized_key = str(key)
        if normalized_key not in _SAFE_METADATA_KEYS:
            continue
        result[normalized_key] = _sanitize_value(value)
    return result


def _sanitize_value(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return _normalize_safe_text(value)
    if isinstance(value, Mapping):
        return {str(key): _sanitize_value(item) for key, item in value.items()}
    if isinstance(value, tuple | list | set | frozenset):
        return [_sanitize_value(item) for item in value]
    return str(type(value).__name__)


def _hash_mapping(mapping: Mapping[str, Any]) -> str:
    normalized = json.dumps(mapping, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _hash_optional_text(value: object) -> str | None:
    normalized = _normalize_safe_text(value)
    if normalized is None:
        return None
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _normalize_safe_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None