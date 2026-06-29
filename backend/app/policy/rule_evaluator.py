"""Internal evaluator protocol and callback wrapper for policy rules."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from inspect import isawaitable
from typing import Protocol

from app.contracts.config import ConfigurationView
from app.contracts.context import OrchestrationContext
from app.contracts.policy import PolicyDecision, PolicyRequest
from app.policy.rule import PolicyRule
from app.policy.settings import PolicyProfileSettings

PolicyEvaluatorCallback = Callable[
    [PolicyRequest, OrchestrationContext, PolicyProfileSettings, ConfigurationView],
    PolicyDecision | None | Awaitable[PolicyDecision | None],
]


class PolicyRuleEvaluator(Protocol):
    """Typed evaluator contract used by the internal policy engine."""

    @property
    def rule(self) -> PolicyRule:
        ...

    async def evaluate(
        self,
        request: PolicyRequest,
        context: OrchestrationContext,
        profile: PolicyProfileSettings,
        config: ConfigurationView,
    ) -> PolicyDecision | None:
        ...


@dataclass(frozen=True, slots=True)
class CallbackPolicyRuleEvaluator:
    """Adapter that turns a callback into a rule evaluator."""

    rule: PolicyRule
    callback: PolicyEvaluatorCallback

    async def evaluate(
        self,
        request: PolicyRequest,
        context: OrchestrationContext,
        profile: PolicyProfileSettings,
        config: ConfigurationView,
    ) -> PolicyDecision | None:
        result = self.callback(request, context, profile, config)
        if isawaitable(result):
            return await result
        return result