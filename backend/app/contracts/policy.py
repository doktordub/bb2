"""Policy service contracts for gateway and runtime operations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Protocol, cast

if TYPE_CHECKING:
    from app.contracts.context import OrchestrationContext

PolicyAction = Literal[
    "orchestration.run_strategy",
    "agent.invoke",
    "llm.complete",
    "llm.stream",
    "visualization.build",
    "visualization.retrieve",
    "memory.search",
    "memory.get",
    "memory.upsert",
    "memory.promote",
    "memory.supersede",
    "memory.contradict",
    "memory.expire",
    "memory.forget",
    "memory.ingest_document",
    "memory.delete_by_scope",
    "memory.export_by_scope",
    "memory.stats",
    "tool.list",
    "tool.get",
    "tool.call",
    "tool.execute",
    "tool.stream_execute",
    "state.load",
    "state.save",
    "state.reset",
    "session.reset",
    "session.read_history",
    "fallback.execute",
    "trace.emit",
    "stream.emit",
    "health.read",
    "capabilities.read",
]
PolicyDecisionValue = Literal["allow", "deny", "approval_required"]
PolicyActorType = Literal["anonymous", "user", "service", "system", "agent"]
PolicyObligationKind = Literal[
    "audit",
    "limit_output",
    "mask_identity",
    "omit_payload",
    "redact",
    "require_approval",
]
PolicyExposureLevel = Literal["none", "metadata", "summary"]


@dataclass(slots=True)
class PolicyActor:
    """Normalized caller identity for policy evaluation."""

    actor_type: PolicyActorType = "anonymous"
    actor_id: str | None = None
    user_id: str | None = None
    tenant_id: str | None = None
    session_id: str | None = None
    roles: tuple[str, ...] = ()
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PolicyScope:
    """Normalized resource and ownership scope for policy evaluation."""

    tenant_id: str | None = None
    project_id: str | None = None
    user_id: str | None = None
    session_id: str | None = None
    usecase_name: str | None = None
    strategy_name: str | None = None
    agent_name: str | None = None
    memory_scope: str | None = None
    resource_id: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PolicyEvaluationContext:
    """Normalized request metadata used to explain a policy decision."""

    trace_id: str | None = None
    request_id: str | None = None
    usecase_name: str | None = None
    strategy_name: str | None = None
    agent_name: str | None = None
    llm_profile: str | None = None
    tool_name: str | None = None
    risk_level: str | None = None
    exposure_level: PolicyExposureLevel = "summary"
    tags: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PolicyObligation:
    """Structured follow-up requirement attached to a policy decision."""

    kind: PolicyObligationKind
    target: str | None = None
    value: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PolicyRequest:
    """Normalized policy evaluation request.

    ``scope`` and ``metadata`` remain the compatibility surface for existing
    callers. Typed actor and evaluation fields are additive for later phases.
    """

    action: PolicyAction
    component: str
    resource: str | None = None
    scope: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    actor: PolicyActor | None = None
    evaluation: PolicyEvaluationContext | None = None

    def resolved_actor(self) -> PolicyActor:
        """Return a normalized actor view even for legacy callers."""

        if self.actor is not None:
            return self.actor

        user_id = _read_optional_text(self.scope.get("user_id"))
        actor_type = _read_optional_text(self.metadata.get("actor_type"))
        resolved_actor_type: PolicyActorType
        if actor_type not in {"anonymous", "user", "service", "system", "agent"}:
            resolved_actor_type = "user" if user_id is not None else "anonymous"
        else:
            resolved_actor_type = cast(PolicyActorType, actor_type)
        return PolicyActor(
            actor_type=resolved_actor_type,
            actor_id=_read_optional_text(self.metadata.get("actor_id")) or user_id,
            user_id=user_id,
            tenant_id=_read_optional_text(self.scope.get("tenant_id")),
            session_id=_read_optional_text(self.scope.get("session_id")),
            roles=_read_text_tuple(self.metadata.get("roles")),
            attributes=_read_mapping(self.metadata.get("actor_attributes")),
        )

    def resolved_scope(self) -> PolicyScope:
        """Return a normalized scope view even for legacy callers."""

        return PolicyScope(
            tenant_id=_read_optional_text(self.scope.get("tenant_id")),
            project_id=_read_optional_text(self.scope.get("project_id")),
            user_id=_read_optional_text(self.scope.get("user_id")),
            session_id=_read_optional_text(self.scope.get("session_id")),
            usecase_name=(
                _read_optional_text(self.scope.get("usecase_name"))
                or _read_optional_text(self.scope.get("usecase"))
            ),
            strategy_name=_read_optional_text(self.scope.get("strategy_name")),
            agent_name=_read_optional_text(self.scope.get("agent_name")),
            memory_scope=_read_optional_text(self.scope.get("memory_scope")),
            resource_id=self.resource,
            attributes=dict(self.scope),
        )

    def resolved_evaluation(self) -> PolicyEvaluationContext:
        """Return a normalized evaluation context for the current request."""

        if self.evaluation is not None:
            return self.evaluation

        scope = self.resolved_scope()
        return PolicyEvaluationContext(
            trace_id=_read_optional_text(self.metadata.get("trace_id")),
            request_id=_read_optional_text(self.metadata.get("request_id")),
            usecase_name=scope.usecase_name,
            strategy_name=scope.strategy_name,
            agent_name=scope.agent_name,
            llm_profile=(
                self.resource if self.action in {"llm.complete", "llm.stream"} else None
            ),
            tool_name=(
                self.resource
                if self.action in {"tool.get", "tool.call", "tool.execute", "tool.stream_execute"}
                else _read_optional_text(self.metadata.get("tool_name"))
            ),
            risk_level=_read_optional_text(self.metadata.get("risk_level")),
            exposure_level=_read_exposure_level(self.metadata.get("exposure_level")),
            tags=_read_text_tuple(self.metadata.get("tags")),
            metadata=dict(self.metadata),
        )


@dataclass(slots=True)
class PolicyDecision:
    """Result of evaluating whether an action is allowed."""

    allowed: bool
    reason: str | None = None
    requires_approval: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    decision: PolicyDecisionValue | None = None
    reason_code: str | None = None
    obligations: tuple[PolicyObligation, ...] = ()
    actor: PolicyActor | None = None
    scope: PolicyScope | None = None

    def __post_init__(self) -> None:
        if self.decision is None:
            if self.requires_approval:
                self.decision = "approval_required"
            else:
                self.decision = "allow" if self.allowed else "deny"

        if self.decision == "allow":
            self.allowed = True
            self.requires_approval = False
        elif self.decision == "approval_required":
            self.allowed = False
            self.requires_approval = True
        else:
            self.allowed = False
            self.requires_approval = False

    @property
    def is_allowed(self) -> bool:
        return self.decision == "allow"

    @property
    def is_denied(self) -> bool:
        return self.decision == "deny"

    @property
    def is_approval_required(self) -> bool:
        return self.decision == "approval_required"

    @property
    def safe_reason(self) -> str:
        if self.reason:
            return self.reason
        if self.reason_code:
            return self.reason_code
        if self.requires_approval:
            return "Approval required by policy."
        return "Policy denied."

    @classmethod
    def allow(
        cls,
        *,
        reason: str | None = None,
        reason_code: str | None = None,
        metadata: dict[str, Any] | None = None,
        obligations: tuple[PolicyObligation, ...] = (),
        actor: PolicyActor | None = None,
        scope: PolicyScope | None = None,
    ) -> PolicyDecision:
        return cls(
            allowed=True,
            reason=reason,
            metadata=dict(metadata or {}),
            decision="allow",
            reason_code=reason_code,
            obligations=obligations,
            actor=actor,
            scope=scope,
        )

    @classmethod
    def deny(
        cls,
        *,
        reason: str | None = None,
        reason_code: str | None = None,
        metadata: dict[str, Any] | None = None,
        obligations: tuple[PolicyObligation, ...] = (),
        actor: PolicyActor | None = None,
        scope: PolicyScope | None = None,
    ) -> PolicyDecision:
        return cls(
            allowed=False,
            reason=reason,
            metadata=dict(metadata or {}),
            decision="deny",
            reason_code=reason_code,
            obligations=obligations,
            actor=actor,
            scope=scope,
        )

    @classmethod
    def approval_required(
        cls,
        *,
        reason: str | None = None,
        reason_code: str | None = None,
        metadata: dict[str, Any] | None = None,
        obligations: tuple[PolicyObligation, ...] = (),
        actor: PolicyActor | None = None,
        scope: PolicyScope | None = None,
    ) -> PolicyDecision:
        return cls(
            allowed=False,
            reason=reason,
            requires_approval=True,
            metadata=dict(metadata or {}),
            decision="approval_required",
            reason_code=reason_code,
            obligations=obligations,
            actor=actor,
            scope=scope,
        )


class PolicyService(Protocol):
    """Policy contract used to gate orchestration actions."""

    async def evaluate(
        self,
        request: PolicyRequest,
        context: OrchestrationContext,
    ) -> PolicyDecision:
        ...

    async def require_allowed(
        self,
        request: PolicyRequest,
        context: OrchestrationContext,
    ) -> None:
        ...


def _read_optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _read_text_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
        return ()
    normalized: list[str] = []
    for item in value:
        text = _read_optional_text(item)
        if text is not None and text not in normalized:
            normalized.append(text)
    return tuple(normalized)


def _read_mapping(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return dict(value)


def _read_exposure_level(value: object) -> PolicyExposureLevel:
    normalized = _read_optional_text(value)
    if normalized in {"none", "metadata", "summary"}:
        return cast(PolicyExposureLevel, normalized)
    return "summary"