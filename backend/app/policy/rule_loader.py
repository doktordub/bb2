"""Default internal rule loading for the policy engine."""

from __future__ import annotations

from app.policy.agent_policy import evaluate_agent_access
from app.policy.capabilities import evaluate_capabilities_request
from app.policy.fallback_policy import evaluate_fallback_request
from app.policy.health import evaluate_health_request
from app.policy.llm_policy import evaluate_llm_request
from app.policy.memory_policy import evaluate_memory_request
from app.policy.registry import PolicyRegistry
from app.policy.rule import PolicyRule
from app.policy.rule_evaluator import CallbackPolicyRuleEvaluator
from app.policy.session_policy import evaluate_session_access
from app.policy.strategy_policy import evaluate_strategy_access
from app.policy.stream_policy import evaluate_stream_request
from app.policy.trace_policy import evaluate_trace_request
from app.policy.tool_policy import evaluate_tool_request
from app.policy.usecase_policy import evaluate_usecase_access
from app.policy.visualization_policy import evaluate_visualization_request


def load_default_policy_registry() -> PolicyRegistry:
    """Build the default internal evaluator registry for the policy engine."""

    registry = PolicyRegistry()
    registry.register_rule(
        CallbackPolicyRuleEvaluator(
            rule=PolicyRule(
                name="usecase_access",
                actions=(
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
                ),
                priority=10,
            ),
            callback=evaluate_usecase_access,
        )
    )
    registry.register_rule(
        CallbackPolicyRuleEvaluator(
            rule=PolicyRule(
                name="session_access",
                actions=("session.reset", "session.read_history"),
                component_prefixes=("session.", "app.session", "api.sessions", "app.api.routes_sessions"),
                priority=15,
            ),
            callback=evaluate_session_access,
        )
    )
    registry.register_rule(
        CallbackPolicyRuleEvaluator(
            rule=PolicyRule(
                name="strategy_access",
                actions=("orchestration.run_strategy",),
                priority=20,
            ),
            callback=evaluate_strategy_access,
        )
    )
    registry.register_rule(
        CallbackPolicyRuleEvaluator(
            rule=PolicyRule(
                name="agent_access",
                actions=("agent.invoke", "visualization.build", "visualization.retrieve"),
                priority=20,
            ),
            callback=evaluate_agent_access,
        )
    )
    registry.register_rule(
        CallbackPolicyRuleEvaluator(
            rule=PolicyRule(
                name="llm_access",
                actions=("llm.complete", "llm.stream"),
                component_prefixes=("app.llm", "llm.", "app.agents", "agents.", "agent.", "app.orchestration", "orchestration."),
                priority=30,
            ),
            callback=lambda request, context, profile, runtime_config: evaluate_llm_request(
                request,
                context,
                profile,
            ),
        )
    )
    registry.register_rule(
        CallbackPolicyRuleEvaluator(
            rule=PolicyRule(
                name="memory_access",
                actions=(
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
                ),
                component_prefixes=("app.memory", "memory.", "app.orchestration", "orchestration."),
                priority=30,
            ),
            callback=lambda request, context, profile, runtime_config: evaluate_memory_request(
                request,
                context,
                profile,
            ),
        )
    )
    registry.register_rule(
        CallbackPolicyRuleEvaluator(
            rule=PolicyRule(
                name="tool_access",
                actions=("tool.list", "tool.get", "tool.call", "tool.execute", "tool.stream_execute"),
                component_prefixes=("app.tools", "tools.", "app.orchestration", "orchestration.", "app.agents", "agents."),
                priority=30,
            ),
            callback=lambda request, context, profile, runtime_config: evaluate_tool_request(
                request,
                context,
                profile,
            ),
        )
    )
    registry.register_rule(
        CallbackPolicyRuleEvaluator(
            rule=PolicyRule(
                name="visualization_access",
                actions=("visualization.build", "visualization.retrieve"),
                component_prefixes=("app.visualization", "visualization.", "app.agents", "agents.", "app.orchestration", "orchestration."),
                priority=32,
            ),
            callback=lambda request, context, profile, runtime_config: evaluate_visualization_request(
                request,
                context,
                profile,
                runtime_config,
            ),
        )
    )
    registry.register_rule(
        CallbackPolicyRuleEvaluator(
            rule=PolicyRule(
                name="fallback_access",
                actions=("fallback.execute",),
                component_prefixes=("orchestration.", "app.orchestration"),
                priority=25,
            ),
            callback=lambda request, context, profile, runtime_config: evaluate_fallback_request(
                request,
                context,
                profile,
            ),
        )
    )
    registry.register_rule(
        CallbackPolicyRuleEvaluator(
            rule=PolicyRule(
                name="trace_access",
                actions=("trace.emit",),
                component_prefixes=(
                    "api.",
                    "app.api",
                    "observability.",
                    "app.observability",
                    "orchestration.",
                    "app.orchestration",
                    "session.",
                    "app.session",
                    "persistence.",
                    "app.persistence",
                    "agents.",
                    "app.agents",
                    "llm.",
                    "app.llm",
                    "visualization.",
                    "app.visualization",
                ),
                priority=35,
            ),
            callback=lambda request, context, profile, runtime_config: evaluate_trace_request(
                request,
                context,
                profile,
            ),
        )
    )
    registry.register_rule(
        CallbackPolicyRuleEvaluator(
            rule=PolicyRule(
                name="stream_access",
                actions=("stream.emit",),
                component_prefixes=("api.", "app.api", "session.", "app.session"),
                priority=35,
            ),
            callback=lambda request, context, profile, runtime_config: evaluate_stream_request(
                request,
                context,
                profile,
            ),
        )
    )
    registry.register_rule(
        CallbackPolicyRuleEvaluator(
            rule=PolicyRule(
                name="capabilities_access",
                actions=("capabilities.read",),
                component_prefixes=("api.", "app.api", "foundation.", "app.foundation"),
                priority=35,
            ),
            callback=lambda request, context, profile, runtime_config: evaluate_capabilities_request(
                request,
                context,
                profile,
            ),
        )
    )
    registry.register_rule(
        CallbackPolicyRuleEvaluator(
            rule=PolicyRule(
                name="health_access",
                actions=("health.read",),
                component_prefixes=("api.", "app.api", "foundation.", "app.foundation"),
                priority=35,
            ),
            callback=lambda request, context, profile, runtime_config: evaluate_health_request(
                request,
                context,
                profile,
            ),
        )
    )
    return registry
