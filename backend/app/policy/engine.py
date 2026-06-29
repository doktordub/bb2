"""Internal policy engine that evaluates registered rules with explicit precedence."""

from __future__ import annotations

from app.contracts.config import ConfigurationView
from app.contracts.context import OrchestrationContext
from app.contracts.policy import PolicyActor, PolicyScope
from app.contracts.policy import PolicyDecision, PolicyRequest
from app.policy.context import resolve_policy_context, resolve_scope_value
from app.policy.registry import PolicyRegistry
from app.policy.rule_evaluator import PolicyRuleEvaluator
from app.policy.rule_matcher import PolicyRuleMatcher
from app.policy.settings import PolicyProfileSettings, PolicySettings


class DefaultPolicyEngine:
    """Evaluate policy requests through explicit registered rule evaluators."""

    def __init__(
        self,
        *,
        config: ConfigurationView,
        settings: PolicySettings,
        registry: PolicyRegistry,
        matcher: PolicyRuleMatcher | None = None,
    ) -> None:
        self._config = config
        self._settings = settings
        self._registry = registry
        self._matcher = matcher or PolicyRuleMatcher()

    @property
    def registry(self) -> PolicyRegistry:
        return self._registry

    async def evaluate(
        self,
        request: PolicyRequest,
        context: OrchestrationContext,
    ) -> PolicyDecision:
        profile = self._resolve_policy_profile(request, context)
        resolved_context = resolve_policy_context(request)
        decisions: list[PolicyDecision] = []

        for evaluator in self._registry.matching(request, matcher=self._matcher):
            decision = await self._evaluate_one(
                evaluator=evaluator,
                request=request,
                context=context,
                profile=profile,
                actor=resolved_context.actor,
                scope=resolved_context.scope,
            )
            if decision is not None:
                decisions.append(decision)

        for decision_kind in ("deny", "approval_required", "allow"):
            for decision in decisions:
                if decision.decision == decision_kind:
                    return decision

        if profile.default_decision == "allow":
            return PolicyDecision.allow(
                reason_code="policy.default_allow",
                metadata={"policy_profile": profile.name},
                actor=resolved_context.actor,
                scope=resolved_context.scope,
            )
        return PolicyDecision.deny(
            reason="Policy denied by default.",
            reason_code="policy.default_deny",
            metadata={"policy_profile": profile.name},
            actor=resolved_context.actor,
            scope=resolved_context.scope,
        )

    async def _evaluate_one(
        self,
        *,
        evaluator: PolicyRuleEvaluator,
        request: PolicyRequest,
        context: OrchestrationContext,
        profile: PolicyProfileSettings,
        actor: PolicyActor,
        scope: PolicyScope,
    ) -> PolicyDecision | None:
        decision = await evaluator.evaluate(request, context, profile, self._config)
        if decision is None:
            return None
        metadata = dict(decision.metadata)
        metadata.setdefault("policy_profile", profile.name)
        metadata.setdefault("rule", evaluator.rule.name)
        return PolicyDecision(
            allowed=decision.allowed,
            reason=decision.reason,
            requires_approval=decision.requires_approval,
            metadata=metadata,
            decision=decision.decision,
            reason_code=decision.reason_code,
            obligations=decision.obligations,
            actor=decision.actor or actor,
            scope=decision.scope or scope,
        )

    def _resolve_policy_profile(
        self,
        request: PolicyRequest,
        context: OrchestrationContext,
    ) -> PolicyProfileSettings:
        context_request = getattr(context, "request", context)
        usecase_name = resolve_scope_value(
            request,
            context,
            key="usecase_name",
            fallback=resolve_scope_value(
                request,
                context,
                key="usecase",
                fallback=getattr(context_request, "usecase", None),
            ),
        )
        policy_profile_name = None
        if usecase_name is not None:
            policy_profile_name = _read_optional_str(self._config.get(f"usecases.{usecase_name}.policy_profile"))
            if policy_profile_name is None:
                policy_profile_name = _read_optional_str(
                    self._config.get(f"orchestration.usecases.{usecase_name}.policy_profile")
                )

        resolved_profile_name = policy_profile_name or self._settings.default_profile or "default"
        resolved = self._settings.profiles.get(resolved_profile_name)
        if resolved is not None:
            return resolved
        return PolicyProfileSettings(
            name=resolved_profile_name,
            enabled=self._settings.enabled,
            mode=self._settings.mode,
            default_decision=self._settings.default_decision,
            fail_closed=self._settings.fail_closed,
        )


def _read_optional_str(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None