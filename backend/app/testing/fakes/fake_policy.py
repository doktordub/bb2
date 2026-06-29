"""In-memory fake policy service for contract-focused tests."""

from __future__ import annotations

from app.contracts.context import OrchestrationContext
from app.contracts.errors import PolicyApprovalRequiredError, PolicyDeniedError
from app.contracts.policy import PolicyDecision, PolicyRequest


class FakePolicyService:
    """Deterministic policy fake that allows, denies, or requires approval."""

    def __init__(
        self,
        allow: bool = True,
        *,
        denied_actions: set[str] | None = None,
        denied_resources: set[str] | None = None,
        approval_required_actions: set[str] | None = None,
        approval_required_resources: set[str] | None = None,
        deny_reason: str = "Denied by fake policy",
        approval_reason: str = "Approval required by fake policy",
    ) -> None:
        self.allow = allow
        self.denied_actions = set(denied_actions or ())
        self.denied_resources = set(denied_resources or ())
        self.approval_required_actions = set(approval_required_actions or ())
        self.approval_required_resources = set(approval_required_resources or ())
        self.deny_reason = deny_reason
        self.approval_reason = approval_reason
        self.requests: list[PolicyRequest] = []
        self.contexts: list[OrchestrationContext] = []

    async def evaluate(
        self,
        request: PolicyRequest,
        context: OrchestrationContext,
    ) -> PolicyDecision:
        self.requests.append(request)
        self.contexts.append(context)
        requires_approval = request.action in self.approval_required_actions
        if request.resource is not None and request.resource in self.approval_required_resources:
            requires_approval = True
        allowed = self.allow
        if request.action in self.denied_actions:
            allowed = False
        if request.resource is not None and request.resource in self.denied_resources:
            allowed = False
        if requires_approval:
            return PolicyDecision.approval_required(
                reason=self.approval_reason,
                reason_code="fake.approval_required",
                metadata={"source": "fake_policy"},
                actor=request.resolved_actor(),
                scope=request.resolved_scope(),
            )
        if not allowed:
            return PolicyDecision.deny(
                reason=self.deny_reason,
                reason_code="fake.denied",
                metadata={"source": "fake_policy"},
                actor=request.resolved_actor(),
                scope=request.resolved_scope(),
            )
        return PolicyDecision.allow(
            metadata={"source": "fake_policy"},
            actor=request.resolved_actor(),
            scope=request.resolved_scope(),
        )

    async def require_allowed(
        self,
        request: PolicyRequest,
        context: OrchestrationContext,
    ) -> None:
        decision = await self.evaluate(request, context)
        if decision.requires_approval:
            raise PolicyApprovalRequiredError(decision.safe_reason)
        if not decision.allowed:
            raise PolicyDeniedError(decision.safe_reason)