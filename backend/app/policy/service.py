"""Concrete policy-service facade over the internal policy engine."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from time import perf_counter

from app.config.view import get_policy_settings
from app.contracts.config import ConfigurationView
from app.contracts.context import OrchestrationContext
from app.contracts.errors import PolicyDeniedError
from app.contracts.policy import PolicyDecision, PolicyRequest
from app.observability.metrics import MetricsRecorder, NoopMetricsRecorder
from app.policy.approval_policy import raise_for_approval_required
from app.policy.audit import PolicyAuditRecorder
from app.policy.decision_cache import PolicyDecisionCache
from app.policy.engine import DefaultPolicyEngine
from app.policy.rule_loader import load_default_policy_registry
from app.policy.settings import (
    PolicyAuditSettings,
    PolicyDecisionCacheSettings,
    PolicyProfileSettings,
)


@dataclass(frozen=True, slots=True)
class PolicyServiceHealth:
    """Safe summary of the live policy runtime state."""

    configured: bool
    healthy: bool
    enabled: bool
    mode: str
    default_profile: str
    profile_count: int
    rule_count: int
    cache: dict[str, int | bool]
    audit: dict[str, object]


class DefaultPolicyService:
    """Provider-neutral policy facade used by runtime and gateway code."""

    def __init__(
        self,
        config: ConfigurationView,
        *,
        engine: DefaultPolicyEngine | None = None,
        metrics: MetricsRecorder | None = None,
    ) -> None:
        self._config = config
        self._settings = get_policy_settings(config)
        self._engine = engine or DefaultPolicyEngine(
            config=config,
            settings=self._settings,
            registry=load_default_policy_registry(),
        )
        self._decision_caches: dict[str, PolicyDecisionCache] = {}
        self._audit_recorders: dict[str, PolicyAuditRecorder] = {}
        self._metrics = metrics or NoopMetricsRecorder()

    @property
    def engine(self) -> DefaultPolicyEngine:
        return self._engine

    async def health(self) -> PolicyServiceHealth:
        cache_snapshot = self._cache_health_snapshot()
        audit_snapshot = self._audit_health_snapshot()
        return PolicyServiceHealth(
            configured=True,
            healthy=True,
            enabled=self._settings.enabled,
            mode=self._settings.mode,
            default_profile=self._settings.default_profile or "default",
            profile_count=len(self._settings.profiles),
            rule_count=len(self._engine.registry.evaluators),
            cache=cache_snapshot,
            audit=audit_snapshot,
        )

    async def evaluate(
        self,
        request: PolicyRequest,
        context: OrchestrationContext,
    ) -> PolicyDecision:
        profile = self._engine._resolve_policy_profile(request, context)
        cache = self._decision_cache_for_profile(profile)
        audit = self._audit_recorder_for_profile(profile)
        cached = cache.get(request, context, profile_name=profile.name)
        domain = _policy_domain(request.action)
        action = request.action
        if cached is not None:
            self._metrics.increment(
                "backend.policy.cache.hits.total",
                tags={"component": request.component, "operation": action},
            )
            self._record_decision_metrics(request=request, decision=cached, duration_ms=0)
            return cached

        self._metrics.increment(
            "backend.policy.cache.misses.total",
            tags={"component": request.component, "operation": action},
        )
        started_at = perf_counter()
        decision = await self._engine.evaluate(request, context)
        duration_ms = int((perf_counter() - started_at) * 1000)
        cached_decision = cache.put(
            request,
            context,
            profile_name=profile.name,
            decision=decision,
        )
        audit.record(request, context, decision=decision)
        self._record_decision_metrics(request=request, decision=decision, duration_ms=duration_ms)
        self._metrics.timing(
            "backend.policy.evaluation.duration_ms",
            duration_ms,
            tags={"component": request.component, "operation": action, "provider": domain},
        )
        return cached_decision

    async def require_allowed(
        self,
        request: PolicyRequest,
        context: OrchestrationContext,
    ) -> None:
        decision = await self.evaluate(request, context)
        if decision.requires_approval:
            raise_for_approval_required(decision)
        if not decision.allowed:
            raise PolicyDeniedError(decision.reason or "Policy denied")

    def _record_decision_metrics(
        self,
        *,
        request: PolicyRequest,
        decision: PolicyDecision,
        duration_ms: int,
    ) -> None:
        decision_value = decision.decision or ("allow" if decision.allowed else "deny")
        tags = {
            "component": request.component,
            "operation": request.action,
            "provider": _policy_domain(request.action),
            "success": "true" if decision.allowed else "false",
        }
        if decision_value == "deny":
            self._metrics.increment("backend.policy.denials.total", tags=tags)
        elif decision_value == "approval_required":
            self._metrics.increment("backend.policy.approvals_required.total", tags=tags)
        if decision.obligations:
            self._metrics.increment(
                "backend.policy.obligations.total",
                value=len(decision.obligations),
                tags=tags,
            )

    def _decision_cache_for_profile(self, profile: PolicyProfileSettings) -> PolicyDecisionCache:
        cache = self._decision_caches.get(profile.name)
        if cache is None:
            cache = PolicyDecisionCache(profile.decision_cache)
            self._decision_caches[profile.name] = cache
        return cache

    def _audit_recorder_for_profile(self, profile: PolicyProfileSettings) -> PolicyAuditRecorder:
        recorder = self._audit_recorders.get(profile.name)
        if recorder is None:
            recorder = PolicyAuditRecorder(profile.audit)
            self._audit_recorders[profile.name] = recorder
        return recorder

    def _cache_health_snapshot(self) -> dict[str, int | bool]:
        if not self._decision_caches:
            default_profile_name = self._settings.default_profile or "default"
            profile = self._settings.profiles.get(default_profile_name)
            if profile is None:
                profile = self._fallback_profile(default_profile_name)
            snapshot = PolicyDecisionCache(profile.decision_cache).snapshot()
            return {
                **snapshot,
                "profile_count": 1,
            }

        snapshots = [cache.snapshot() for cache in self._decision_caches.values()]
        enabled = any(bool(item["enabled"]) for item in snapshots)
        max_entries = sum(int(item["max_entries"]) for item in snapshots)
        size = sum(int(item["size"]) for item in snapshots)
        hits = sum(int(item["hits"]) for item in snapshots)
        misses = sum(int(item["misses"]) for item in snapshots)
        evictions = sum(int(item["evictions"]) for item in snapshots)
        ttl_seconds = max((int(item["ttl_seconds"]) for item in snapshots), default=0)
        return {
            "enabled": enabled,
            "profile_count": len(snapshots),
            "size": size,
            "max_entries": max_entries,
            "ttl_seconds": ttl_seconds,
            "hits": hits,
            "misses": misses,
            "evictions": evictions,
        }

    def _audit_health_snapshot(self) -> dict[str, object]:
        if not self._audit_recorders:
            default_profile_name = self._settings.default_profile or "default"
            profile = self._settings.profiles.get(default_profile_name)
            if profile is None:
                profile = self._fallback_profile(default_profile_name)
            return PolicyAuditRecorder(profile.audit).snapshot()

        decision_counts = Counter({"allow": 0, "deny": 0, "approval_required": 0})
        event_count = 0
        enabled = False
        last_event: dict[str, object] | None = None
        for recorder in self._audit_recorders.values():
            snapshot = recorder.snapshot()
            enabled = enabled or bool(snapshot["enabled"])
            event_count += int(snapshot["event_count"])
            for decision, count in dict(snapshot["decision_counts"]).items():
                decision_counts[str(decision)] += int(count)
            candidate = snapshot.get("last_event")
            if isinstance(candidate, dict):
                if last_event is None or str(candidate.get("recorded_at", "")) > str(last_event.get("recorded_at", "")):
                    last_event = dict(candidate)
        return {
            "enabled": enabled,
            "event_count": event_count,
            "decision_counts": dict(decision_counts),
            "last_event": last_event,
        }

    def _fallback_profile(self, profile_name: str) -> PolicyProfileSettings:
        return PolicyProfileSettings(
            name=profile_name,
            enabled=self._settings.enabled,
            mode=self._settings.mode,
            default_decision=self._settings.default_decision,
            fail_closed=self._settings.fail_closed,
            audit=PolicyAuditSettings(),
            decision_cache=PolicyDecisionCacheSettings(),
        )


def _policy_domain(action: str) -> str:
    if "." not in action:
        return action
    return action.split(".", 1)[0]
