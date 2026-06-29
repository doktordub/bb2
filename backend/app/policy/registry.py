"""Registry of internal policy evaluators."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from app.contracts.policy import PolicyRequest
from app.policy.rule_evaluator import PolicyRuleEvaluator
from app.policy.rule_matcher import PolicyRuleMatcher


class PolicyRegistry:
    """Own the ordered set of internal policy evaluators."""

    def __init__(self, evaluators: Sequence[PolicyRuleEvaluator] = ()) -> None:
        self._evaluators: list[PolicyRuleEvaluator] = list(evaluators)

    @property
    def evaluators(self) -> tuple[PolicyRuleEvaluator, ...]:
        return tuple(self._evaluators)

    def register_rule(self, evaluator: PolicyRuleEvaluator) -> None:
        self._evaluators.append(evaluator)

    def extend(self, evaluators: Iterable[PolicyRuleEvaluator]) -> None:
        for evaluator in evaluators:
            self.register_rule(evaluator)

    def matching(self, request: PolicyRequest, *, matcher: PolicyRuleMatcher) -> tuple[PolicyRuleEvaluator, ...]:
        matched = [
            evaluator
            for evaluator in self._evaluators
            if matcher.matches(
                actions=evaluator.rule.actions,
                component_prefixes=evaluator.rule.component_prefixes,
                request=request,
            )
        ]
        matched.sort(key=lambda evaluator: evaluator.rule.priority)
        return tuple(matched)