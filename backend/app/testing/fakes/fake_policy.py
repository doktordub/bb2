"""In-memory fake policy service for contract-focused tests."""

from __future__ import annotations

from app.contracts.context import OrchestrationContext
from app.contracts.errors import PolicyDeniedError
from app.contracts.policy import PolicyDecision, PolicyRequest


class FakePolicyService:
    """Deterministic policy fake that allows or denies all actions."""

    def __init__(self, allow: bool = True) -> None:
        self.allow = allow
        self.requests: list[PolicyRequest] = []
        self.contexts: list[OrchestrationContext] = []

    async def evaluate(
        self,
        request: PolicyRequest,
        context: OrchestrationContext,
    ) -> PolicyDecision:
        self.requests.append(request)
        self.contexts.append(context)
        return PolicyDecision(
            allowed=self.allow,
            reason=None if self.allow else "Denied by fake policy",
        )

    async def require_allowed(
        self,
        request: PolicyRequest,
        context: OrchestrationContext,
    ) -> None:
        decision = await self.evaluate(request, context)
        if not decision.allowed:
            raise PolicyDeniedError(decision.reason or "Policy denied")