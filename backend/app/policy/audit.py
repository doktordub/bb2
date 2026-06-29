"""Safe audit summaries for policy evaluations."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
from typing import Any

from app.contracts.context import OrchestrationContext
from app.contracts.policy import PolicyDecision, PolicyRequest
from app.policy.context import resolve_policy_context
from app.policy.settings import PolicyAuditSettings

_MAX_AUDIT_EVENTS = 256


@dataclass(frozen=True, slots=True)
class PolicyAuditEvent:
    """Bounded, safe summary of one policy decision."""

    recorded_at: datetime
    trace_id: str | None
    domain: str
    action: str
    decision: str
    reason_code: str | None
    resource: str | None
    resource_hash: str | None
    policy_profile: str | None
    rule_id: str | None
    risk_level: str | None
    actor_hash: str | None
    scope_hash: str | None


class PolicyAuditRecorder:
    """Record safe, bounded in-memory policy audit events."""

    def __init__(self, settings: PolicyAuditSettings) -> None:
        self._settings = settings
        self._events: deque[PolicyAuditEvent] = deque(maxlen=_MAX_AUDIT_EVENTS)

    @property
    def enabled(self) -> bool:
        return self._settings.enabled

    def record(
        self,
        request: PolicyRequest,
        context: OrchestrationContext,
        *,
        decision: PolicyDecision,
    ) -> PolicyAuditEvent | None:
        if not self.enabled:
            return None

        resolved = resolve_policy_context(request)
        resource = request.resource if self._settings.include_resource_names else None
        actor_hash = None
        if self._settings.include_actor_identifiers:
            actor_hash = _hash_optional_text(resolved.actor.actor_id or resolved.actor.user_id)

        event = PolicyAuditEvent(
            recorded_at=datetime.now(UTC),
            trace_id=resolved.evaluation.trace_id or getattr(context.request, "trace_id", None),
            domain=_policy_domain_from_action(request.action),
            action=request.action,
            decision=decision.decision or ("allow" if decision.allowed else "deny"),
            reason_code=decision.reason_code if self._settings.include_reason_codes else None,
            resource=resource,
            resource_hash=_hash_optional_text(request.resource),
            policy_profile=_optional_text(decision.metadata.get("policy_profile")),
            rule_id=_optional_text(decision.metadata.get("rule")),
            risk_level=resolved.evaluation.risk_level,
            actor_hash=actor_hash,
            scope_hash=_hash_mapping(
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
        )
        self._events.append(event)
        return event

    def snapshot(self) -> dict[str, Any]:
        latest = self._events[-1] if self._events else None
        decision_counts = {"allow": 0, "deny": 0, "approval_required": 0}
        for event in self._events:
            decision_counts[event.decision] = decision_counts.get(event.decision, 0) + 1
        return {
            "enabled": self.enabled,
            "event_count": len(self._events),
            "decision_counts": decision_counts,
            "last_event": None if latest is None else _event_payload(latest),
        }

    def events(self) -> tuple[PolicyAuditEvent, ...]:
        return tuple(self._events)


def _event_payload(event: PolicyAuditEvent) -> dict[str, Any]:
    return {
        "recorded_at": event.recorded_at.isoformat(),
        "trace_id": event.trace_id,
        "domain": event.domain,
        "action": event.action,
        "decision": event.decision,
        "reason_code": event.reason_code,
        "resource": event.resource,
        "resource_hash": event.resource_hash,
        "policy_profile": event.policy_profile,
        "rule_id": event.rule_id,
        "risk_level": event.risk_level,
        "actor_hash": event.actor_hash,
        "scope_hash": event.scope_hash,
    }


def _policy_domain_from_action(action: str) -> str:
    if "." not in action:
        return action
    return action.split(".", 1)[0]


def _hash_mapping(mapping: Mapping[str, Any]) -> str:
    import json

    normalized = json.dumps(mapping, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _hash_optional_text(value: object) -> str | None:
    text = _optional_text(value)
    if text is None:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None