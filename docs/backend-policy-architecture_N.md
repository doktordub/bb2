# Backend Policy Architecture

**Document:** `backend-policy-architecture.md`  
**Version:** 1.0  
**Source alignment:** `backend-application-architecture.md`, `backend-foundation-architecture.md`, `backend-core-contracts-architecture.md`, `backend-configuration-architecture.md`, `backend-observability-architecture.md`, `backend-persistence-architecture.md`, `backend-sqlite-workflow-state-architecture.md`, `backend-sqlite-trace-store-architecture.md`, `backend-api-architecture.md`, `backend-session-service-architecture.md`, `backend-llm-gateway-architecture.md`, `backend-memory-store-adapter-architecture.md`, `backend-tooling-mcp-client-architecture.md`, `backend-orchestration-architecture.md`, and `backend-workflow-strategies-architecture.md`  
**Scope:** Backend policy service, policy decision contracts, identity context, route access, session access, strategy permissions, agent permissions, LLM profile permissions, memory read/write policy, tool execution policy, approval hooks, data exposure policy, trace capture policy, redaction policy, prompt/tool-result safety rules, configuration, testing strategy, and acceptance criteria for the V1 policy layer.

---

## 1. Purpose

This document defines the next implementation-focused architecture document for the backend application tier.

It follows:

1. `backend-foundation-architecture.md`
2. `backend-core-contracts-architecture.md`
3. `backend-configuration-architecture.md`
4. `backend-observability-architecture.md`
5. `backend-persistence-architecture.md`
6. `backend-sqlite-workflow-state-architecture.md`
7. `backend-sqlite-trace-store-architecture.md`
8. `backend-api-architecture.md`
9. `backend-session-service-architecture.md`
10. `backend-llm-gateway-architecture.md`
11. `backend-memory-store-adapter-architecture.md`
12. `backend-tooling-mcp-client-architecture.md`
13. `backend-orchestration-architecture.md`
14. `backend-workflow-strategies-architecture.md`
15. `backend-policy-architecture.md` ← this document

The previous workflow strategies document established that strategies shape each turn while using provider-neutral gateways and policy hooks. It also made policy denial a hard boundary: a denied strategy, agent, LLM profile, memory operation, or tool call must stop the denied action and must not fall back to a less restrictive path.

This document defines the policy layer that makes those checks consistent across the backend.

The goal is to provide a single backend-owned policy boundary for authorization, safety, data exposure, trace capture, approval requirements, and operation-level allow/deny decisions without embedding policy logic inside API routes, session service code, orchestration runtime code, strategy implementations, agents, memory adapters, LLM providers, or MCP protocol clients.

The core architecture rule is:

> `PolicyService` is the backend's decision boundary for permissions and safety policy. API routes, `SessionService`, `OrchestrationRuntime`, workflow strategies, agents, `LLMGateway`, `MemoryGateway`, and `ToolGateway` may ask policy questions, but they must not duplicate policy tables, bypass policy checks, or weaken a denial through fallback behavior.

---

## 2. Source Architecture Alignment

This document follows the established backend rules:

- The backend is one deployable application tier in V1.
- Frontend communicates with backend through REST / SSE.
- API routes are thin and delegate chat/reset behavior to `SessionService`.
- `SessionService` owns session lifecycle and workflow-state persistence.
- `SessionService` calls `OrchestrationRuntime`; it does not select agents, strategies, tools, memory stores, or LLM providers directly for normal chat behavior.
- `OrchestrationRuntime` owns per-turn execution lifecycle and strategy resolution.
- Workflow strategies own workflow shape and must use policy hooks for strategy/agent/LLM decisions.
- Agents own task-specific behavior but use `OrchestrationContext` and provider-neutral gateways.
- LLM calls remain behind `LLMGateway`.
- Long-term memory and document chunks remain behind `MemoryGateway`.
- External tools remain behind `ToolGateway`.
- MCP protocol communication remains behind `MCPClientAdapter`.
- SQLite workflow state remains behind `WorkflowStateStore`.
- SQLite traces remain behind `TraceStore` or an observability facade.
- ArcadeDB-backed memory remains behind the memory adapter and must not leak into policy checks.
- Policy decisions must be trace-correlated with the active `trace_id`.
- Policy trace events must be safe, bounded, and redacted.
- Policy must never expose raw credentials, authorization headers, OAuth/JWT tokens, provider API keys, raw prompts, raw completions, raw tool payloads, raw memory records, raw workflow state, or stack traces.

---

## 3. Refined Position in the Backend Implementation Sequence

The workflow strategies document identified policy as the next cross-cutting document. This policy document can be implemented before full agent plugins so that future agents inherit clear permissions and data-exposure rules from the beginning.

```text
Phase 1: Backend Foundation Skeleton
Phase 2: Core Contracts
Phase 3: Configuration Loader
Phase 4: Observability and Trace Foundation
Phase 5: Persistence Boundary and Store Foundations
Phase 6: SQLite Workflow State Store
Phase 7: SQLite Trace Store
Phase 8: API and Session Walking Skeleton
Phase 9: Session Service Deepening
Phase 10: LLM Gateway
Phase 11: Memory Gateway and Memory Store Adapter
Phase 12: Tool Gateway and MCP Client Adapter
Phase 13: Orchestration Runtime and Strategy Contract
Phase 14: Workflow Strategy Implementations
Phase 15: Policy Service and Safety Rules
Phase 16: Agent Plugins
Phase 17: Approval Workflow
Phase 18: Prompt Context and Injection Hardening
Phase 19: Evaluation and Hardening
Phase 20: Deployment Readiness
```

This document expands Phase 15.

The output of this phase is a backend policy layer that supports:

```text
PolicyService.can_access_route(...)
PolicyService.can_access_session(...)
PolicyService.can_reset_session(...)
PolicyService.can_run_strategy(...)
PolicyService.can_use_agent(...)
PolicyService.can_use_llm_profile(...)
PolicyService.can_read_memory(...)
PolicyService.can_write_memory(...)
PolicyService.can_execute_tool(...)
PolicyService.requires_approval(...)
PolicyService.can_capture_trace_payload(...)
PolicyService.can_expose_data(...)
PolicyService.classify_operation(...)
PolicyService.health(...)
PolicyService.capabilities(...)
```

The next document should be:

```text
backend-agents-architecture.md
```

---

## 4. Architecture Goals

The backend policy layer should be:

1. **Centralized**  
   Permission and safety decisions are made through `PolicyService`, not scattered across routes, strategies, agents, or adapters.

2. **Provider-neutral**  
   Policy reasons about logical strategies, agents, LLM profiles, memory scopes, and tool names, not concrete provider SDK objects.

3. **Configuration-driven for V1**  
   V1 policy is loaded from YAML and environment-resolved settings. A database-backed policy store can be added later behind the same service interface.

4. **Deny-by-default**  
   Unknown routes, use cases, strategies, agents, LLM profiles, memory operations, tools, and side-effect actions are denied unless explicitly allowed.

5. **Scope-aware**  
   Decisions include user, session, project, tenant, use case, strategy, agent, tool, memory type, operation, and safety level where available.

6. **Gateway-compatible**  
   `LLMGateway`, `MemoryGateway`, and `ToolGateway` can call policy using stable policy request models before provider/adapter execution.

7. **Strategy-compatible**  
   Strategies can ask policy whether they may run, invoke agents, use LLM profiles, retrieve memory, write memory, call tools, or fallback.

8. **Approval-ready**  
   V1 can mark operations as `approval_required` even before a full approval workflow exists.

9. **Trace-safe**  
   Policy decisions emit safe trace events with decision summaries, not raw data.

10. **Data-exposure-aware**  
    Policy defines what can be returned to API, streamed over SSE, written to workflow state, stored in traces, included in LLM prompts, or written to memory.

11. **Composable**  
    Common policy checks can be reused by API, session, orchestration, strategies, agents, and gateways.

12. **Testable**  
    Policy decisions can be tested deterministically with fixture identities, use cases, strategies, tools, memory records, and route definitions.

---

## 5. Non-Goals

This document should not implement:

- Production identity provider integration.
- Full OAuth login flow.
- Full JWT validation strategy.
- Public user management.
- Role administration UI.
- Policy database schema.
- Distributed policy synchronization.
- Full human approval workflow UI.
- Legal/compliance workflow.
- Fine-grained document-level ACLs backed by external systems.
- Encryption key management.
- Secret vault implementation.
- Full prompt-injection defense framework.
- Full audit report generation.
- Full data export/delete privacy workflow.
- MCP server authorization internals.
- Provider-specific LLM safety systems.

Those concerns belong to future auth, approval, deployment, privacy, prompt-context, compliance, and hardening documents.

---

## 6. Policy Boundary

The policy layer sits beside the orchestration and gateway layers as a cross-cutting service.

It owns:

- Route access decisions.
- Session access/reset decisions.
- Use-case access decisions.
- Strategy execution decisions.
- Agent usage decisions.
- LLM profile usage decisions.
- Memory read/write decisions.
- Tool execution decisions.
- Side-effect classification.
- Approval-required decisions.
- Trace payload capture decisions.
- Data exposure decisions.
- Safe denial reasons.
- Safe policy decision trace summaries.

It does not own:

- API request parsing.
- Session persistence.
- Orchestration execution.
- Strategy step ordering.
- Agent task logic.
- LLM provider calls.
- Memory adapter queries.
- MCP protocol calls.
- SQLite reads/writes.
- ArcadeDB reads/writes.
- Frontend UI behavior.
- Secret retrieval.

### 6.1 Boundary Diagram

```text
Frontend
  -> API
      -> PolicyService.can_access_route
      -> SessionService
          -> PolicyService.can_access_session / can_reset_session
          -> OrchestrationRuntime
              -> PolicyService.can_run_strategy
              -> WorkflowStrategy
                  -> PolicyService.can_use_agent
                  -> PolicyService.can_use_llm_profile
                  -> AgentHandle
                      -> LLMGateway
                          -> PolicyService.can_use_llm_profile
                      -> MemoryGateway
                          -> PolicyService.can_read_memory / can_write_memory
                      -> ToolGateway
                          -> PolicyService.can_execute_tool / requires_approval
                              -> MCPClientAdapter
```

### 6.2 Practical Rule

Correct:

```python
allowed = await context.policy.can_run_strategy(
    PolicyDecisionRequest(
        subject=PolicySubject(user_id=request.user_id),
        resource=PolicyResource(kind="strategy", name=strategy_name),
        action="run",
        scope=PolicyScope(
            session_id=request.session_id,
            project_id=request.project_id,
            usecase=request.usecase,
        ),
        trace_id=request.trace_id,
    )
)
```

Avoid:

```python
if strategy_name in config["allowed_strategies"]:
    run_strategy()
```

Reason: direct config reads bypass policy composition, traceability, deny reasons, approval rules, data exposure rules, and future policy backends.

---

## 7. Recommended Package Layout

Recommended implementation layout:

```text
backend/
  app/
    policy/
      __init__.py
      service.py
      models.py
      decisions.py
      evaluator.py
      config_loader.py
      rules.py
      scopes.py
      safety.py
      approvals.py
      exposure.py
      trace_policy.py
      redaction_policy.py
      errors.py
      health.py
      capabilities.py
      fake.py

    api/
      security.py
      middleware.py
      routes_debug_traces.py

    session/
      service.py

    orchestration/
      runtime.py
      strategies/

    agents/
      base.py
      registry.py

    llm/
      gateway.py

    memory/
      gateway.py

    tools/
      gateway.py

    observability/
      events.py
      redaction.py
      trace_context.py

    config/
      schemas.py
      settings.py
      loader.py

    testing/
      fakes/
        fake_policy_service.py
```

### 7.1 Module Responsibilities

| Module | Responsibility |
|---|---|
| `service.py` | Public `PolicyService` implementation and interface. |
| `models.py` | Subject, resource, action, scope, decision, and request models. |
| `decisions.py` | Allow/deny/approval decision helpers and reason codes. |
| `evaluator.py` | Rule evaluation engine for configured V1 rules. |
| `config_loader.py` | Convert YAML policy config into typed policy settings/rules. |
| `rules.py` | Allowlist, denylist, safety-level, and use-case rule objects. |
| `scopes.py` | Scope matching and trust-boundary utilities. |
| `safety.py` | Operation classification and side-effect safety helpers. |
| `approvals.py` | Approval-required evaluation and future approval handoff models. |
| `exposure.py` | Data exposure decisions for API/SSE/prompt/state/trace/memory. |
| `trace_policy.py` | Trace capture policy and safe decision event payloads. |
| `redaction_policy.py` | Sensitive-key and payload redaction rules. |
| `errors.py` | Normalized policy errors. |
| `health.py` | Policy health/readiness status. |
| `capabilities.py` | Safe policy capability summaries. |
| `fake.py` | Deterministic fake policy service for tests. |

---

## 8. Dependency Direction Rules

Allowed:

```text
app/api/*            -> app/policy/service.py through dependency/facade
app/session/*        -> app/policy/service.py
app/orchestration/*  -> app/policy/service.py through OrchestrationContext
app/agents/*         -> app/policy/models.py through context when needed
app/llm/*            -> app/policy/service.py through interface
app/memory/*         -> app/policy/service.py through interface
app/tools/*          -> app/policy/service.py through interface
app/policy/*         -> app/config/schemas.py
app/policy/*         -> app/observability/events.py through facade
```

Avoid:

```text
app/policy/* -> app/api/routes_*.py
app/policy/* -> app/session/service.py
app/policy/* -> app/orchestration/runtime.py
app/policy/* -> app/orchestration/strategies/*
app/policy/* -> app/agents/*
app/policy/* -> app/llm/providers/*
app/policy/* -> app/tools/mcp/client_adapter.py
app/policy/* -> memory_store.service.MemoryService
app/policy/* -> sqlite3
app/policy/* -> ArcadeDB client
```

### 8.1 Policy Service Rule

Policy should be asked for decisions. It should not execute the operation.

Correct:

```text
ToolGateway -> PolicyService.can_execute_tool -> ToolGateway executes through MCPClientAdapter
```

Avoid:

```text
PolicyService -> MCPClientAdapter
PolicyService -> LLM provider
PolicyService -> MemoryStore
```

---

## 9. Policy Configuration Integration

V1 policy should be YAML-driven.

Recommended YAML:

```yaml
policy:
  enabled: true
  mode: local_config           # local_config | external_service_future
  default_decision: deny
  trace_decisions: true
  trace_allowed_decisions: false
  trace_denied_decisions: true

  identity:
    default_user_id: local_user
    allow_anonymous: true
    trusted_metadata_keys:
      - client
      - timezone
      - request_id
    denied_metadata_keys:
      - authorization
      - bearer
      - cookie
      - password
      - token
      - secret
      - api_key

  routes:
    defaults:
      require_identity: false
      allow_debug_routes: false
    allow:
      - route: POST /chat
        roles: [local_user, anonymous]
      - route: POST /chat/stream
        roles: [local_user, anonymous]
      - route: POST /sessions/{session_id}/reset
        roles: [local_user]
      - route: GET /health
        roles: [local_user, anonymous]
      - route: GET /capabilities
        roles: [local_user, anonymous]
    debug:
      enabled: false
      require_localhost: true
      roles: [developer]

  usecases:
    default:
      enabled: true
      roles: [local_user, anonymous]
      strategies: [direct_agent, retrieval_augmented, tool_assisted, fallback_answer]
      agents: [default_agent, document_qa_agent]
      llm_profiles: [default_chat, local_reasoning]
      memory:
        read: true
        write: false
        scopes: [project, user]
      tools:
        allowed: [documents.search, utility.echo]

    document_qa:
      enabled: true
      roles: [local_user]
      strategies: [retrieval_augmented, tool_assisted]
      agents: [document_qa_agent, architecture_writer_agent]
      llm_profiles: [local_reasoning, default_chat]
      memory:
        read: true
        write: false
        scopes: [project]
      tools:
        allowed: [documents.search, project.read_file]

  strategies:
    defaults:
      allow_fallback_after_policy_denial: false
      allow_planner: false
    allow:
      direct_agent:
        enabled: true
        safety_level: read_only
      retrieval_augmented:
        enabled: true
        safety_level: read_only
      tool_assisted:
        enabled: true
        safety_level: read_only
      bounded_planner:
        enabled: false
        safety_level: read_only

  agents:
    default_agent:
      enabled: true
      allowed_usecases: [default]
      allowed_strategies: [direct_agent, router]
      allowed_llm_profiles: [default_chat, local_reasoning]
    document_qa_agent:
      enabled: true
      allowed_usecases: [document_qa, default]
      allowed_strategies: [retrieval_augmented, tool_assisted]
      allowed_llm_profiles: [local_reasoning, default_chat]

  llm:
    profiles:
      default_chat:
        enabled: true
        allowed_usecases: [default, document_qa]
        max_prompt_context_bytes: 60000
        allow_tool_results_in_prompt: true
        allow_memory_results_in_prompt: true
      local_reasoning:
        enabled: true
        allowed_usecases: [default, document_qa]
        max_prompt_context_bytes: 120000
        allow_tool_results_in_prompt: true
        allow_memory_results_in_prompt: true

  memory:
    defaults:
      read_enabled: true
      write_enabled: false
      max_query_chars: 4000
      max_results: 10
      allow_cross_project_read: false
      allow_cross_user_read: false
    write_rules:
      agent_memory:
        enabled: false
        approval_required: false
      document_chunk:
        enabled: false
        managed_by_ingestion: true

  tools:
    defaults:
      deny_unknown_tools: true
      deny_discovered_unconfigured_tools: true
      approval_required_for_write: true
      approval_required_for_destructive: true
      approval_required_for_external_side_effect: true
    allow:
      documents.search:
        enabled: true
        safety_level: read_only
        allowed_usecases: [default, document_qa]
        allowed_agents: [document_qa_agent, architecture_writer_agent]
        allowed_strategies: [retrieval_augmented, tool_assisted]
        approval_required: false
      project.read_file:
        enabled: true
        safety_level: read_only
        allowed_usecases: [document_qa]
        allowed_agents: [architecture_writer_agent]
        allowed_strategies: [tool_assisted]
        approval_required: false
      utility.echo:
        enabled: true
        safety_level: read_only
        allowed_usecases: [default]
        allowed_agents: [default_agent]
        allowed_strategies: [tool_assisted]
        approval_required: false

  data_exposure:
    api:
      allow_answer_text: true
      allow_tool_summaries: true
      allow_memory_summaries: true
      allow_raw_tool_payloads: false
      allow_raw_memory_records: false
      allow_raw_workflow_state: false
      allow_trace_payloads: false
    sse:
      allow_response_deltas: true
      allow_step_summaries: true
      allow_raw_provider_chunks: false
      allow_raw_tool_payloads: false
    prompt:
      allow_memory_context: true
      allow_tool_context: true
      require_context_quoting: true
      max_context_bytes: 120000
    workflow_state:
      allow_step_summaries: true
      allow_raw_prompts: false
      allow_raw_provider_responses: false
      allow_raw_tool_payloads: false
      allow_raw_memory_records: false
    trace:
      capture_raw_arguments: false
      capture_raw_results: false
      capture_prompts: false
      capture_completions: false
      capture_denials: true

  approvals:
    enabled: false
    deny_when_required_without_approval_service: true
```

### 9.1 Configuration Validation

Policy configuration validation should fail fast when:

- Policy is enabled but `default_decision` is not `allow` or `deny`.
- A use case references an unknown strategy.
- A use case references an unknown agent.
- A use case references an unknown LLM profile.
- A use case references an unknown configured tool.
- A strategy is enabled with an unknown safety level.
- A tool is enabled without a safety level.
- A destructive or external-side-effect tool is enabled without explicit approval policy.
- `allow_fallback_after_policy_denial` is true in V1.
- Memory writes are enabled without scope rules.
- Cross-project or cross-user reads are enabled without explicit policy override.
- Trace capture of raw prompts/results is enabled outside local development.
- Debug routes are enabled without a route access policy.
- An exposure rule allows raw workflow state in API/SSE responses.

### 9.2 Deny-by-Default Rule

Recommended V1 default:

```yaml
policy:
  default_decision: deny
```

This means unknown or unconfigured resources fail closed.

---

## 10. Typed Policy Settings

Recommended dataclasses:

```python
from dataclasses import dataclass, field
from typing import Literal


PolicyDecisionValue = Literal["allow", "deny", "approval_required"]
PolicySafetyLevel = Literal["read_only", "write", "destructive", "external_side_effect"]
PolicyMode = Literal["local_config", "external_service_future"]


@dataclass(frozen=True, slots=True)
class PolicySettings:
    enabled: bool
    mode: PolicyMode
    default_decision: Literal["allow", "deny"] = "deny"
    trace_decisions: bool = True
    trace_allowed_decisions: bool = False
    trace_denied_decisions: bool = True
    identity: "IdentityPolicySettings" = field(default_factory=lambda: IdentityPolicySettings())
    routes: "RoutePolicySettings" = field(default_factory=lambda: RoutePolicySettings())
    usecases: dict[str, "UsecasePolicySettings"] = field(default_factory=dict)
    strategies: dict[str, "StrategyPolicySettings"] = field(default_factory=dict)
    agents: dict[str, "AgentPolicySettings"] = field(default_factory=dict)
    llm_profiles: dict[str, "LLMProfilePolicySettings"] = field(default_factory=dict)
    memory: "MemoryPolicySettings" = field(default_factory=lambda: MemoryPolicySettings())
    tools: dict[str, "ToolPolicySettings"] = field(default_factory=dict)
    data_exposure: "DataExposurePolicySettings" = field(default_factory=lambda: DataExposurePolicySettings())
    approvals: "ApprovalPolicySettings" = field(default_factory=lambda: ApprovalPolicySettings())
```

```python
@dataclass(frozen=True, slots=True)
class UsecasePolicySettings:
    name: str
    enabled: bool
    roles: tuple[str, ...] = ()
    strategies: tuple[str, ...] = ()
    agents: tuple[str, ...] = ()
    llm_profiles: tuple[str, ...] = ()
    tools: tuple[str, ...] = ()
    memory_read: bool = False
    memory_write: bool = False
    memory_scopes: tuple[str, ...] = ()
```

```python
@dataclass(frozen=True, slots=True)
class ToolPolicySettings:
    name: str
    enabled: bool
    safety_level: PolicySafetyLevel
    allowed_usecases: tuple[str, ...] = ()
    allowed_agents: tuple[str, ...] = ()
    allowed_strategies: tuple[str, ...] = ()
    approval_required: bool = False
    max_argument_bytes: int | None = None
    max_result_bytes: int | None = None
```

```python
@dataclass(frozen=True, slots=True)
class DataExposurePolicySettings:
    api: dict[str, bool] = field(default_factory=dict)
    sse: dict[str, bool] = field(default_factory=dict)
    prompt: dict[str, bool | int] = field(default_factory=dict)
    workflow_state: dict[str, bool] = field(default_factory=dict)
    trace: dict[str, bool] = field(default_factory=dict)
```

---

## 11. Policy Decision Model

Policy decisions should be explicit objects, not plain booleans.

Recommended model:

```python
from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    decision: Literal["allow", "deny", "approval_required"]
    code: str
    message: str
    retryable: bool = False
    reason: str | None = None
    safety_level: str | None = None
    approval_type: str | None = None
    obligations: tuple["PolicyObligation", ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def allowed(self) -> bool:
        return self.decision == "allow"
```

Recommended obligation model:

```python
@dataclass(frozen=True, slots=True)
class PolicyObligation:
    type: str
    value: Any
    reason: str | None = None
```

Example obligations:

```text
redact_arguments
redact_results
summarize_only
require_context_quoting
limit_results_to_project_scope
require_idempotency_key
record_denial_trace
hide_tool_from_capabilities
```

### 11.1 Decision Codes

Recommended decision codes:

```text
allowed
policy_disabled_but_default_allow
unknown_resource
resource_disabled
unknown_usecase
usecase_disabled
role_not_allowed
route_not_allowed
session_access_denied
session_reset_denied
strategy_not_allowed
agent_not_allowed
llm_profile_not_allowed
memory_read_denied
memory_write_denied
tool_not_allowed
tool_approval_required
tool_safety_level_denied
cross_scope_access_denied
data_exposure_denied
trace_capture_denied
metadata_contains_secret
approval_service_unavailable
```

### 11.2 Safe Message Rule

Policy messages may be user-visible in some cases. Keep them safe and general.

Good:

```text
This action is not allowed for the current session.
This tool requires approval before it can run.
Memory writes are disabled for this use case.
```

Avoid:

```text
User local_user cannot access tenant secret_enterprise_project because ACL rule 44 failed.
Denied because Authorization header contained Bearer eyJhbGci...
```

---

## 12. Subject, Resource, Action, and Scope Models

Recommended policy request model:

```python
@dataclass(frozen=True, slots=True)
class PolicyDecisionRequest:
    subject: "PolicySubject"
    resource: "PolicyResource"
    action: str
    scope: "PolicyScope"
    trace_id: str | None = None
    request_id: str | None = None
    evidence: "PolicyEvidence | None" = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

Recommended subject:

```python
@dataclass(frozen=True, slots=True)
class PolicySubject:
    user_id: str | None = None
    user_id_hash: str | None = None
    roles: tuple[str, ...] = ()
    auth_mode: str | None = None
    is_anonymous: bool = False
```

Recommended resource:

```python
@dataclass(frozen=True, slots=True)
class PolicyResource:
    kind: str
    name: str
    safety_level: str | None = None
    owner_user_id: str | None = None
    project_id: str | None = None
    tenant_id: str | None = None
    tags: tuple[str, ...] = ()
```

Recommended scope:

```python
@dataclass(frozen=True, slots=True)
class PolicyScope:
    session_id: str | None = None
    usecase: str | None = None
    strategy_name: str | None = None
    agent_name: str | None = None
    llm_profile: str | None = None
    tool_name: str | None = None
    memory_type: str | None = None
    user_id: str | None = None
    project_id: str | None = None
    tenant_id: str | None = None
    client: str | None = None
```

Recommended evidence:

```python
@dataclass(frozen=True, slots=True)
class PolicyEvidence:
    argument_summary: dict[str, Any] = field(default_factory=dict)
    result_summary: dict[str, Any] = field(default_factory=dict)
    data_classification: str | None = None
    estimated_bytes: int | None = None
    contains_external_side_effect: bool = False
    contains_destructive_action: bool = False
```

### 12.1 Scope Trust Rule

Policy should distinguish trusted scope from user-supplied metadata.

Trusted:

```text
RequestContext.user_id
RequestContext.session_id
RequestContext.project_id
validated API identity
configured usecase
resolved strategy name
resolved agent name
resolved logical tool name
```

Untrusted:

```text
user-provided metadata.user_id
user-provided metadata.project_id
LLM-generated tool scope
raw tool argument scope fields
frontend-provided role names
```

Do not let untrusted metadata grant access.

---

## 13. Public Policy Service Interface

Recommended protocol:

```python
from typing import Protocol


class PolicyService(Protocol):
    async def decide(self, request: PolicyDecisionRequest) -> PolicyDecision:
        ...

    async def can_access_route(self, request: "RoutePolicyRequest") -> PolicyDecision:
        ...

    async def can_access_session(self, request: "SessionPolicyRequest") -> PolicyDecision:
        ...

    async def can_reset_session(self, request: "SessionPolicyRequest") -> PolicyDecision:
        ...

    async def can_run_strategy(self, request: "StrategyPolicyRequest") -> PolicyDecision:
        ...

    async def can_use_agent(self, request: "AgentPolicyRequest") -> PolicyDecision:
        ...

    async def can_use_llm_profile(self, request: "LLMProfilePolicyRequest") -> PolicyDecision:
        ...

    async def can_read_memory(self, request: "MemoryPolicyRequest") -> PolicyDecision:
        ...

    async def can_write_memory(self, request: "MemoryPolicyRequest") -> PolicyDecision:
        ...

    async def can_execute_tool(self, request: "ToolPolicyRequest") -> PolicyDecision:
        ...

    async def requires_approval(self, request: "ApprovalPolicyRequest") -> PolicyDecision:
        ...

    async def can_capture_trace_payload(self, request: "TraceCapturePolicyRequest") -> PolicyDecision:
        ...

    async def can_expose_data(self, request: "DataExposurePolicyRequest") -> PolicyDecision:
        ...

    async def health(self) -> "PolicyHealthResult":
        ...

    async def capabilities(self) -> "PolicyCapabilitiesResult":
        ...
```

### 13.1 Decision Handling Helper

Callers should convert denial into normalized domain errors.

Example:

```python
decision = await policy.can_execute_tool(tool_policy_request)
if decision.decision == "approval_required":
    raise ToolApprovalRequiredError(code=decision.code, message=decision.message)
if not decision.allowed:
    raise ToolPolicyDeniedError(code=decision.code, message=decision.message)
```

### 13.2 Boolean Convenience Rule

Avoid exposing only boolean methods.

Bad:

```python
if await policy.is_tool_allowed(tool_name):
    ...
```

Good:

```python
decision = await policy.can_execute_tool(request)
```

Reason: callers need reason codes, obligations, approval requirements, and trace-safe metadata.

---

## 14. Route Policy

API routes can ask policy for coarse route-level access.

Recommended route policy request:

```python
@dataclass(frozen=True, slots=True)
class RoutePolicyRequest:
    subject: PolicySubject
    method: str
    route_pattern: str
    path: str
    client_host: str | None
    trace_id: str
    metadata: dict[str, object] = field(default_factory=dict)
```

### 14.1 Route Policy Defaults

Recommended V1 defaults:

```text
Allow /chat and /chat/stream in local mode for local_user and anonymous if configured.
Allow /health and /capabilities with safe output.
Allow /sessions/{session_id}/reset only for local_user by default.
Deny debug trace routes by default.
Deny unknown routes.
Do not use route policy as a substitute for operation-level policy.
```

### 14.2 Debug Route Policy

Debug trace routes must require explicit policy.

Recommended behavior:

```text
If debug routes are disabled in API config, route is unavailable before policy.
If enabled, route policy must allow subject and client_host.
Debug output still passes trace/data exposure policy.
```

---

## 15. Session Policy

Session policy protects session access and reset behavior.

Recommended session policy request:

```python
@dataclass(frozen=True, slots=True)
class SessionPolicyRequest:
    subject: PolicySubject
    session_id: str
    action: str              # read | write | reset | stream
    usecase: str | None
    owner_user_id: str | None = None
    project_id: str | None = None
    trace_id: str | None = None
```

### 15.1 V1 Session Rules

Recommended V1 rules:

```text
A synthetic local_user can access local sessions.
Anonymous access is allowed only when API config and policy allow it.
Session reset clears workflow state only.
Session reset must not delete memory, trace records, LLM config, MCP config, or policy config.
Cross-user session access is denied by default.
Cross-project session access is denied by default.
```

### 15.2 Session Reset Policy

`SessionService.reset_session` should ask policy before reset.

Correct flow:

```text
API validates session_id
API builds identity context
SessionService.can_reset_session
WorkflowStateStore.reset
Trace safe reset summary
Return reset confirmation
```

Avoid:

```text
API route directly resets workflow state without policy/session ownership check
```

---

## 16. Use-Case Policy

Use cases are the first high-level policy boundary for orchestration.

Use-case policy controls:

- Which identities may use a use case.
- Which strategies are allowed for the use case.
- Which agents are allowed for the use case.
- Which LLM profiles are allowed for the use case.
- Which tools are allowed for the use case.
- Whether memory read/write is enabled.
- Which scopes are allowed for memory and tools.

### 16.1 Use-Case Resolution Rule

Use-case resolution may happen in `SessionService` or `OrchestrationRuntime`, but policy validates the resolved use case.

Correct:

```text
Request usecase -> resolve default if missing -> PolicyService validates usecase -> runtime resolves strategy
```

Avoid:

```text
User metadata chooses arbitrary usecase that enables more tools
```

### 16.2 Unknown Use Case Rule

Unknown use cases are denied by default.

If a request has no use case, resolve to configured default before policy evaluation.

---

## 17. Strategy Policy

Strategies must be allowed before execution.

Recommended request:

```python
@dataclass(frozen=True, slots=True)
class StrategyPolicyRequest:
    subject: PolicySubject
    strategy_name: str
    usecase: str
    session_id: str
    project_id: str | None
    trace_id: str
    safety_level: str | None = None
```

### 17.1 Strategy Policy Rules

Recommended V1 rules:

```text
Deny unknown strategies.
Deny disabled strategies.
Deny strategies not allowed for the current use case.
Deny planner strategies unless explicitly enabled.
Deny fallback to less restrictive strategy after policy denial.
Deny strategies that require unavailable gateways unless configured fallback is safe.
```

### 17.2 Fallback Policy

Fallbacks are useful for availability failures, not policy bypass.

Allowed fallback:

```text
LLM provider unavailable -> fallback_answer strategy returns safe message
```

Denied fallback:

```text
Policy denies tool_assisted -> fallback to bounded_planner that can use same tool indirectly
```

Policy denial must not be weakened by fallback.

---

## 18. Agent Policy

Agents must be allowed before strategies invoke them.

Recommended request:

```python
@dataclass(frozen=True, slots=True)
class AgentPolicyRequest:
    subject: PolicySubject
    agent_name: str
    usecase: str
    strategy_name: str
    session_id: str
    project_id: str | None
    trace_id: str
```

### 18.1 Agent Policy Rules

Recommended V1 rules:

```text
Deny unknown agents.
Deny disabled agents.
Deny agents not allowed for the current use case.
Deny agents not allowed for the current strategy.
Deny agents that require tools or memory not allowed by the current use case.
Deny agent-provided overrides of LLM profile, tool name, or memory scope unless policy allows them.
```

### 18.2 Agent Declaration Policy

Future agent descriptors should declare:

```text
agent_name
allowed_usecases
allowed_strategies
required_llm_profiles
optional_tools
required_tools
memory_read_requirements
memory_write_requirements
safety_level
```

Policy can validate agent declarations during startup.

---

## 19. LLM Profile Policy

LLM profile policy validates profile usage before provider execution.

Recommended request:

```python
@dataclass(frozen=True, slots=True)
class LLMProfilePolicyRequest:
    subject: PolicySubject
    llm_profile: str
    usecase: str
    strategy_name: str | None
    agent_name: str | None
    session_id: str
    project_id: str | None
    estimated_prompt_bytes: int | None = None
    includes_memory_context: bool = False
    includes_tool_context: bool = False
    trace_id: str | None = None
```

### 19.1 LLM Policy Rules

Recommended V1 rules:

```text
Deny unknown LLM profiles.
Deny disabled LLM profiles.
Deny profiles not allowed for the current use case.
Deny profiles not allowed for the current agent if agent-specific policy exists.
Deny prompts that exceed profile/context byte limits.
Deny memory context in prompts if exposure policy forbids it.
Deny tool context in prompts if exposure policy forbids it.
Deny raw prompts/completions in traces by default.
```

### 19.2 Provider-Neutral Rule

Policy should evaluate logical profile names, not provider clients.

Good:

```text
llm_profile = local_reasoning
```

Avoid:

```text
provider = OpenAI client object
api_key = sk-...
```

---

## 20. Memory Policy

Memory policy controls long-term memory and document chunk access through `MemoryGateway`.

Recommended request:

```python
@dataclass(frozen=True, slots=True)
class MemoryPolicyRequest:
    subject: PolicySubject
    action: str                  # search | read | upsert | supersede | expire | forget
    memory_type: str | None
    usecase: str
    strategy_name: str | None
    agent_name: str | None
    session_id: str
    project_id: str | None
    user_id_scope: str | None
    query_summary: dict[str, object] = field(default_factory=dict)
    candidate_summary: dict[str, object] = field(default_factory=dict)
    trace_id: str | None = None
```

### 20.1 Memory Read Rules

Recommended V1 rules:

```text
Deny memory reads if memory is disabled for the use case.
Deny cross-user memory reads by default.
Deny cross-project memory reads by default.
Deny raw memory records in API/SSE/trace output by default.
Allow bounded memory summaries in strategy results when configured.
Allow memory context in prompts only when exposure policy allows it.
```

### 20.2 Memory Write Rules

Recommended V1 rules:

```text
Deny memory writes by default.
Allow memory writes only for configured use cases, strategies, and memory types.
Require explicit scope for durable writes.
Deny document chunk writes from normal chat strategies; document chunks are managed by ingestion.
Deny memory writes that contain obvious credentials.
Deny automatic tool-result-to-memory writes unless strategy and policy allow it.
```

### 20.3 Forget/Delete Policy

Forget/delete operations are high impact.

Recommended V1 behavior:

```text
Deny forget/delete by default except explicit privacy/admin flows.
Do not wire forget/delete into normal chat strategy behavior.
Session reset must not call memory forget/delete.
```

---

## 21. Tool Policy

Tool policy controls execution through `ToolGateway`.

Recommended request:

```python
@dataclass(frozen=True, slots=True)
class ToolPolicyRequest:
    subject: PolicySubject
    tool_name: str
    safety_level: str
    usecase: str
    strategy_name: str | None
    agent_name: str | None
    session_id: str
    project_id: str | None
    argument_summary: dict[str, object] = field(default_factory=dict)
    trace_id: str | None = None
    idempotency_key_present: bool = False
```

### 21.1 Tool Policy Rules

Recommended V1 rules:

```text
Deny unknown tools.
Deny disabled tools.
Deny discovered-but-unconfigured MCP tools.
Deny tools not allowed for the current use case.
Deny tools not allowed for the current strategy.
Deny tools not allowed for the current agent.
Deny destructive tools by default.
Deny external-side-effect tools by default.
Require approval for write/destructive/external-side-effect tools unless explicitly exempted.
Require idempotency key for retryable write tools.
Deny raw credentials in tool arguments.
Deny user-supplied raw MCP tool names that bypass logical tool registry.
```

### 21.2 Tool Safety Levels

Policy uses the safety levels already introduced by the tooling architecture:

| Safety Level | Meaning | V1 Policy Default |
|---|---|---|
| `read_only` | Reads data without changing downstream state. | Allow only if configured. |
| `write` | Creates or updates downstream state. | Approval required by default. |
| `destructive` | Deletes or irreversibly changes state. | Deny or approval required by explicit override. |
| `external_side_effect` | Sends email, posts, purchases, triggers external action. | Deny or approval required by explicit override. |

### 21.3 Approval-Required Tool Behavior

If a tool requires approval and no approval service exists:

```text
ToolGateway returns ToolApprovalRequiredError or ToolPolicyDeniedError.
Strategy stops the action.
SessionService may persist safe pending-approval summary only after approval workflow exists.
No MCP call is made.
```

---

## 22. Approval Policy

V1 can classify operations as requiring approval even before implementing approval workflow.

Recommended request:

```python
@dataclass(frozen=True, slots=True)
class ApprovalPolicyRequest:
    subject: PolicySubject
    operation: str
    resource: PolicyResource
    scope: PolicyScope
    safety_level: str
    trace_id: str | None = None
    evidence: PolicyEvidence | None = None
```

### 22.1 Approval Decision Rules

Recommended V1 rules:

```text
Read-only operations usually do not require approval if otherwise allowed.
Write operations require approval by default unless explicitly exempted.
Destructive operations require approval and are disabled by default.
External-side-effect operations require approval and are disabled by default.
Approval-required operations must not execute when approval service is disabled.
Approval-required operations must produce safe pending/denial summaries only.
```

### 22.2 Future Approval Workflow Handoff

A future approval workflow document may introduce:

```text
Policy marks operation approval_required.
Strategy returns pending approval state delta.
SessionService stores pending approval summary in workflow state.
Frontend displays approval request.
User approves or denies.
SessionService resumes orchestration with approval token.
ToolGateway validates approval token before execution.
```

This document only defines the policy decision boundary.

---

## 23. Data Exposure Policy

Data exposure policy controls where data may go.

Destinations:

```text
api_response
sse_event
workflow_state
trace_event
llm_prompt
memory_write
debug_route
health_response
capabilities_response
log_event
```

Recommended request:

```python
@dataclass(frozen=True, slots=True)
class DataExposurePolicyRequest:
    subject: PolicySubject
    data_kind: str
    destination: str
    usecase: str | None
    strategy_name: str | None = None
    agent_name: str | None = None
    classification: str | None = None
    estimated_bytes: int | None = None
    trace_id: str | None = None
    summary: dict[str, object] = field(default_factory=dict)
```

### 23.1 Data Kind Categories

Recommended V1 categories:

```text
answer_text
response_delta
step_summary
tool_summary
tool_raw_arguments
tool_raw_result
memory_summary
memory_raw_record
workflow_state_summary
workflow_state_raw
trace_summary
trace_payload
llm_prompt
llm_completion
provider_raw_response
credential
stack_trace
health_summary
capability_summary
```

### 23.2 Exposure Matrix

Recommended V1 default matrix:

| Data Kind | API | SSE | Workflow State | Trace | LLM Prompt | Memory Write |
|---|---:|---:|---:|---:|---:|---:|
| Answer text | yes | yes | summary/full by session policy | no raw by default | no | optional no |
| Step summary | yes | yes | yes | yes | no | no |
| Tool summary | yes | yes | yes | yes | maybe selected | no |
| Raw tool arguments | no | no | no | no | no | no |
| Raw tool result | no | no | no | no | selected only if safe | no by default |
| Memory summary | yes | yes | yes | yes | yes if allowed | no |
| Raw memory record | no | no | no | no | selected/quoted only if allowed | no |
| Raw workflow state | no | no | no | no | no | no |
| Trace payload | debug only | no | no | yes | no | no |
| LLM prompt | no | no | no | no | n/a | no |
| LLM completion | answer only | delta/answer only | summary/full by session policy | no raw by default | no | no |
| Credentials | no | no | no | no | no | no |
| Stack traces | no | no | no | local debug only after redaction | no | no |

### 23.3 Prompt Context Exposure

Memory and tool outputs can be useful prompt context, but they must be treated as untrusted data.

Policy obligations may require:

```text
quote_context
summarize_context
strip_credentials
limit_context_bytes
include_source_labels
mark_tool_output_untrusted
mark_memory_output_untrusted
```

---

## 24. Trace Capture Policy

Trace capture policy controls what can be recorded in the trace store.

Recommended request:

```python
@dataclass(frozen=True, slots=True)
class TraceCapturePolicyRequest:
    subject: PolicySubject
    event_name: str
    payload_kind: str
    usecase: str | None
    contains_prompt: bool = False
    contains_completion: bool = False
    contains_tool_payload: bool = False
    contains_memory_record: bool = False
    contains_credentials: bool = False
    estimated_bytes: int | None = None
    trace_id: str | None = None
```

### 24.1 Trace Capture Defaults

Recommended V1 defaults:

```text
Capture request/session/strategy/tool/memory/LLM summaries.
Capture policy denials as safe reason codes.
Capture error type/code, not stack trace, by default.
Do not capture raw prompts.
Do not capture raw completions.
Do not capture raw tool arguments/results.
Do not capture raw memory records.
Do not capture credentials.
Do not capture raw workflow state.
```

### 24.2 Safe Policy Decision Trace Event

Example:

```json
{
  "event_name": "policy_decision",
  "trace_id": "trace_...",
  "payload": {
    "decision": "deny",
    "code": "tool_approval_required",
    "resource_kind": "tool",
    "resource_name": "calendar.create_event",
    "action": "execute",
    "usecase": "default",
    "strategy_name": "tool_assisted",
    "agent_name": "calendar_agent",
    "safety_level": "external_side_effect"
  }
}
```

Unsafe:

```json
{
  "raw_arguments": {"Authorization": "Bearer ..."},
  "raw_tool_result": "...",
  "raw_prompt": "...",
  "stack_trace": "..."
}
```

---

## 25. Redaction Policy

Redaction policy defines sensitive keys and payload fragments.

Default sensitive fragments:

```text
api_key
authorization
bearer
client_secret
connection_string
cookie
credential
jwt
key
password
refresh_token
secret
token
```

### 25.1 Redaction Rule

Redaction is not authorization.

Use both:

```text
Policy decides whether data can be exposed.
Redactor transforms data when exposure is allowed but sensitive fields must be hidden.
```

Avoid:

```text
Expose everything because redaction exists.
```

### 25.2 Metadata Secret Rule

Metadata containing obvious secret-like keys should be rejected at trust boundaries when possible.

Relevant boundaries:

```text
API request metadata
session metadata
strategy metadata
tool arguments
memory write candidates
trace payloads
LLM prompt context metadata
```

---

## 26. Operation Classification

Policy should classify operations before making decisions.

Recommended model:

```python
@dataclass(frozen=True, slots=True)
class OperationClassification:
    operation: str
    safety_level: str
    data_classification: str | None = None
    has_external_side_effect: bool = False
    has_destructive_effect: bool = False
    approval_recommended: bool = False
    idempotency_required: bool = False
```

### 26.1 Classification Examples

| Operation | Safety Level | Notes |
|---|---|---|
| `strategy.run:direct_agent` | `read_only` | Produces answer only. |
| `memory.search` | `read_only` | Scope-limited retrieval. |
| `memory.upsert:agent_memory` | `write` | Durable memory change. |
| `tool.execute:documents.search` | `read_only` | Tool reads external/search data. |
| `tool.execute:calendar.create_event` | `external_side_effect` | External event creation. |
| `tool.execute:filesystem.delete_file` | `destructive` | File deletion. |
| `session.reset` | `write` | Clears workflow state only. |
| `debug.trace.read` | `read_only` | Sensitive debug exposure. |

### 26.2 Classification Source

Policy can use:

```text
configured resource safety_level
operation action name
tool registry safety_level
agent descriptor safety_level
memory action type
route pattern
evidence flags
```

Do not infer safety level from untrusted user text alone.

---

## 27. Prompt Injection and Tool Result Safety

Policy does not replace prompt-context hardening, but it sets required guardrails.

Recommended policy obligations for tool/memory context in prompts:

```text
quote_context
label_context_source
mark_context_untrusted
strip_credentials
limit_context_bytes
prevent_context_from_overriding_system_instructions
```

### 27.1 Tool/Memory Text Rule

Tool and memory result text must be treated as data, not instructions.

Strategies and agents should never allow retrieved text to override:

```text
system instructions
developer instructions
policy decisions
agent role instructions
tool allowlists
LLM profile policy
memory write policy
approval requirements
```

### 27.2 Future Prompt Context Dependency

A future `backend-prompt-context-architecture.md` should define exact prompt assembly templates and quote formatting. This policy document only defines the required permission and obligation model.

---

## 28. Policy Integration by Layer

### 28.1 API Integration

API should use policy for:

```text
route access
protected debug route access
metadata secret checks through validation/redaction policy
safe capability exposure
safe health exposure
```

API should not use policy to:

```text
select agents
select strategies
select LLM profiles
execute tools
search memory
```

Those happen downstream.

### 28.2 Session Service Integration

`SessionService` should use policy for:

```text
session access
session reset
session history exposure if enabled
safe state summary exposure
```

`SessionService` should not use policy to bypass runtime strategy selection.

### 28.3 Orchestration Runtime Integration

`OrchestrationRuntime` should use policy for:

```text
usecase access
strategy execution
fallback permission
runtime-level data exposure summaries
```

### 28.4 Workflow Strategy Integration

Strategies should use policy for:

```text
agent usage
LLM profile usage before constructing expensive prompts
memory read/write intent before gateway calls when useful
tool intent execution path before gateway calls when useful
fallback decisions
state-delta exposure decisions
```

Gateway-specific checks still happen inside gateways.

### 28.5 Agent Integration

Agents should use policy through context when they need to:

```text
choose among allowed LLM profiles
choose optional tools
request memory writes
include tool/memory context in prompts
```

Agents must not embed their own static allowlists that bypass policy.

### 28.6 LLM Gateway Integration

`LLMGateway` should use policy for:

```text
llm profile access
prompt context byte limits
whether memory/tool context can be included
trace capture of prompt/completion summaries
```

### 28.7 Memory Gateway Integration

`MemoryGateway` should use policy for:

```text
memory search/read
memory upsert/promote/supersede/contradict/expire/forget
scope validation
memory result exposure summaries
```

### 28.8 Tool Gateway Integration

`ToolGateway` should use policy for:

```text
tool execution
safety-level handling
approval-required decisions
argument/result exposure rules
idempotency requirements
trace capture summaries
```

---

## 29. Policy Evaluation Algorithm

Recommended evaluation order:

```text
1. Validate policy request shape.
2. Normalize subject, resource, action, and scope.
3. Reject obvious secret-like metadata if present.
4. Classify operation safety level.
5. Check global policy enabled/default mode.
6. Check resource exists and is enabled.
7. Check usecase exists and is enabled when applicable.
8. Check subject role/identity access.
9. Check scope constraints: user, session, project, tenant.
10. Check resource-specific allowlist/denylist.
11. Check safety-level restrictions.
12. Check approval requirement.
13. Attach obligations.
14. Emit safe policy decision trace event if configured.
15. Return PolicyDecision.
```

### 29.1 Deny Precedence

Deny should win over allow.

Example:

```text
Use case allows tool `calendar.create_event`.
Tool policy marks it external_side_effect requiring approval.
Approval service is disabled.
Decision: approval_required or deny, not allow.
```

### 29.2 Approval Precedence

`approval_required` should be returned only when the operation would otherwise be allowed after approval.

If the operation is not allowed at all, return `deny`.

---

## 30. Policy Errors

Recommended errors:

```python
class PolicyError(Exception): ...
class PolicyConfigurationError(PolicyError): ...
class PolicyDecisionError(PolicyError): ...
class PolicyDeniedError(PolicyError): ...
class PolicyApprovalRequiredError(PolicyError): ...
class PolicyUnavailableError(PolicyError): ...
class PolicyMalformedRequestError(PolicyError): ...
```

### 30.1 Error Mapping by Caller

| Caller | Policy Error Mapping |
|---|---|
| API | `403 policy_denied`, `401/403` future auth, `503 policy_unavailable`. |
| SessionService | Session error or reset denied error. |
| OrchestrationRuntime | `OrchestrationPolicyDeniedError`. |
| Strategy | `StrategyPolicyDeniedError`. |
| LLMGateway | `LLMPolicyDeniedError`. |
| MemoryGateway | `MemoryPolicyDeniedError`. |
| ToolGateway | `ToolPolicyDeniedError` or `ToolApprovalRequiredError`. |

### 30.2 Error Safety Rule

Policy errors must not include:

```text
raw request bodies
raw prompts
raw completions
raw tool arguments
raw tool results
raw memory records
credentials
full stack traces
private config values
```

---

## 31. Health Integration

Policy should expose safe health.

Recommended result:

```python
@dataclass(frozen=True, slots=True)
class PolicyHealthResult:
    status: str
    enabled: bool
    mode: str
    rules_loaded: int
    usecases_loaded: int
    strategies_loaded: int
    agents_loaded: int
    llm_profiles_loaded: int
    tools_loaded: int
    data_exposure_configured: bool
    approvals_enabled: bool
    metadata: dict[str, object] = field(default_factory=dict)
```

Recommended `/health` section:

```json
{
  "policy": {
    "status": "ok",
    "enabled": true,
    "mode": "local_config",
    "usecases_loaded": 2,
    "strategies_loaded": 5,
    "tools_loaded": 3,
    "approvals_enabled": false
  }
}
```

### 31.1 Health Safety Rule

Health must not expose:

```text
private route allowlist details when sensitive
raw policy expressions that reveal internals
user IDs
session IDs
credentials
secrets
raw debug rule payloads
```

---

## 32. Capabilities Integration

Policy may contribute safe capability summaries.

Recommended capability section:

```json
{
  "policy": {
    "enabled": true,
    "mode": "local_config",
    "approvals_enabled": false,
    "debug_routes_allowed": false,
    "memory_writes_enabled": false,
    "external_side_effect_tools_enabled": false
  }
}
```

### 32.1 Capability Safety Rule

Capabilities may expose high-level feature flags.

Do not expose:

```text
full ACLs
private user lists
internal role mappings
credential policy internals
raw rule expressions
private endpoint information
```

---

## 33. Composition Root Integration

The composition root builds policy before services that depend on it.

Recommended startup sequence:

```text
1. Load settings and YAML configuration.
2. Build redactor and observability recorder.
3. Validate policy configuration.
4. Build PolicyService.
5. Build persistence stores.
6. Build LLMGateway with policy dependency.
7. Build MemoryGateway with policy dependency.
8. Build ToolGateway with policy dependency.
9. Build agent registry and strategy registry with policy-aware descriptors.
10. Build OrchestrationRuntime with policy dependency.
11. Build SessionService with policy/runtime/store dependencies.
12. Build HealthService and CapabilityService with policy dependency.
13. Build API app.
14. Log redacted policy startup summary.
```

### 33.1 Composition Example

```python
def build_policy_service(config, observability) -> PolicyService:
    policy_settings = validate_policy_settings(config.policy)
    evaluator = ConfigPolicyEvaluator(settings=policy_settings)
    return DefaultPolicyService(
        settings=policy_settings,
        evaluator=evaluator,
        observability=observability,
        redactor=observability.redactor,
    )
```

### 33.2 Redacted Startup Summary

Safe:

```json
{
  "event": "policy_configured",
  "enabled": true,
  "mode": "local_config",
  "default_decision": "deny",
  "usecases_loaded": 2,
  "tools_loaded": 3,
  "approvals_enabled": false
}
```

Unsafe:

```json
{
  "raw_policy_yaml": "...",
  "private_roles": ["..."],
  "tokens": "..."
}
```

---

## 34. Testing Strategy

### 34.1 Unit Tests

| Test | Purpose |
|---|---|
| Policy settings validate | Proves config shape and fail-fast behavior. |
| Default deny unknown route | Prevents accidental route exposure. |
| Default deny unknown use case | Prevents arbitrary usecase escalation. |
| Strategy allowlist works | Proves strategy policy. |
| Strategy denial blocks fallback bypass | Enforces denial boundary. |
| Agent allowlist works | Proves agent policy. |
| LLM profile allowlist works | Proves profile policy. |
| Prompt context limit enforced | Prevents oversized prompt exposure. |
| Memory read scope enforced | Prevents cross-scope reads. |
| Memory write denied by default | Protects durable memory. |
| Tool allowlist works | Proves logical tool policy. |
| Discovered unknown tool denied | Preserves tooling architecture rule. |
| Write tool requires approval | Proves side-effect handling. |
| Destructive tool denied by default | Protects destructive actions. |
| External-side-effect tool denied by default | Protects outbound actions. |
| Approval required without service does not execute | Proves approval boundary. |
| Raw trace capture denied by default | Protects trace store. |
| Raw workflow state exposure denied | Protects API/session boundaries. |
| Secret-like metadata rejected | Protects credentials. |
| Policy decision trace is safe | Proves observability safety. |

### 34.2 Integration Tests

| Test | Purpose |
|---|---|
| API route policy denies debug routes | Proves API/policy integration. |
| Session reset policy is checked | Proves session integration. |
| Runtime checks strategy policy | Proves orchestration integration. |
| Strategy checks agent policy | Proves strategy/agent boundary. |
| LLMGateway denies disallowed profile | Proves gateway policy integration. |
| MemoryGateway denies cross-project read | Proves memory scope enforcement. |
| ToolGateway denies unallowed tool | Proves tool execution boundary. |
| ToolGateway returns approval-required for write tool | Proves approval hook. |
| Policy denial emits safe trace event | Proves trace integration. |
| Capabilities hide policy internals | Proves frontend-safe capability output. |

### 34.3 Fixture Configs

Recommended fixtures:

```text
tests/fixtures/config/policy_basic_allow.yaml
tests/fixtures/config/policy_default_deny.yaml
tests/fixtures/config/policy_debug_routes_disabled.yaml
tests/fixtures/config/policy_strategy_denied.yaml
tests/fixtures/config/policy_agent_denied.yaml
tests/fixtures/config/policy_llm_profile_denied.yaml
tests/fixtures/config/policy_memory_read_scope_denied.yaml
tests/fixtures/config/policy_memory_write_denied.yaml
tests/fixtures/config/policy_tool_read_only_allowed.yaml
tests/fixtures/config/policy_tool_write_approval_required.yaml
tests/fixtures/config/policy_destructive_tool_denied.yaml
tests/fixtures/config/policy_trace_raw_capture_invalid.yaml
tests/fixtures/config/policy_cross_scope_invalid.yaml
```

---

## 35. Recommended Implementation Order

### Step 1: Add Policy Models and Decisions

Deliverables:

- `PolicySubject`
- `PolicyResource`
- `PolicyScope`
- `PolicyEvidence`
- `PolicyDecisionRequest`
- `PolicyDecision`
- `PolicyObligation`
- normalized policy errors

Success criteria:

- Decision objects are serializable and safe.
- Deny/approval decisions carry reason codes and obligations.

### Step 2: Add Policy Settings and Validation

Deliverables:

- typed policy settings
- YAML loader integration
- fail-fast validation
- deny-by-default behavior

Success criteria:

- Valid policy fixtures load.
- Invalid cross-references fail.
- Unsafe raw trace capture config fails outside local mode.

### Step 3: Add Config Policy Evaluator

Deliverables:

- `ConfigPolicyEvaluator`
- allowlist/denylist matching
- role/usecase/resource/scope matching
- safety-level classification

Success criteria:

- Route, strategy, agent, LLM, memory, and tool rules evaluate deterministically.

### Step 4: Add Default PolicyService

Deliverables:

- `decide`
- typed convenience methods
- safe trace decision events
- health/capabilities

Success criteria:

- Callers can use policy through one service interface.
- Policy decisions emit safe trace summaries when configured.

### Step 5: Wire API and Session Policy

Deliverables:

- route access checks for protected/debug routes
- session access/reset checks
- debug trace exposure checks

Success criteria:

- Debug routes remain denied by default.
- Session reset checks policy before workflow state reset.

### Step 6: Wire Runtime and Strategy Policy

Deliverables:

- use-case access check
- strategy execution check
- fallback denial rule
- agent usage check from strategies

Success criteria:

- Policy denial prevents strategy execution.
- Fallback cannot bypass denial.

### Step 7: Wire Gateway Policy

Deliverables:

- LLM profile checks in `LLMGateway`
- memory read/write checks in `MemoryGateway`
- tool execution/approval checks in `ToolGateway`

Success criteria:

- Disallowed LLM profile, memory operation, and tool call fail before provider/adapter execution.

### Step 8: Add Data Exposure and Trace Policy

Deliverables:

- `can_expose_data`
- `can_capture_trace_payload`
- policy obligations for summaries/redaction/context quoting

Success criteria:

- Raw prompts, completions, tool payloads, memory records, and workflow state are denied by default for API/SSE/trace exposure.

### Step 9: Add Fake Policy Service

Deliverables:

- `FakePolicyService.allow_all_safe()`
- `FakePolicyService.deny(...)`
- fixture-driven fake decisions

Success criteria:

- API/session/orchestration/gateway tests can use deterministic policy behavior.

### Step 10: Add Policy Tests and Documentation Examples

Deliverables:

- unit tests
- integration tests
- fixture configs
- policy examples in docs

Success criteria:

- Policy behavior is covered before agent plugin implementation.

---

## 36. Acceptance Criteria

This architecture is complete when:

- `PolicyService` exposes stable decision methods for route, session, strategy, agent, LLM profile, memory, tool, approval, trace capture, and data exposure policy.
- Policy decisions are explicit objects with `allow`, `deny`, or `approval_required` states.
- Policy is deny-by-default for unknown resources.
- V1 policy is loaded from YAML through the configuration layer.
- Policy configuration validates cross-references to known use cases, strategies, agents, LLM profiles, and tools.
- API debug routes are denied by default.
- Session reset requires policy approval and clears workflow state only.
- Orchestration runtime checks use-case and strategy policy.
- Workflow strategies check agent and LLM profile policy where appropriate.
- `LLMGateway` checks LLM profile policy before provider calls.
- `MemoryGateway` checks memory read/write policy before adapter calls.
- `ToolGateway` checks tool execution and approval policy before MCP calls.
- Unknown tools are denied.
- Discovered but unconfigured MCP tools are denied.
- Memory writes are denied by default.
- Destructive and external-side-effect tools are denied or approval-required by default.
- Approval-required operations do not execute when no approval service exists.
- Policy denial cannot be bypassed through fallback to a less restrictive strategy.
- Raw prompts are not traced by default.
- Raw completions are not traced by default.
- Raw tool arguments/results are not traced by default.
- Raw memory records are not traced by default.
- Raw workflow state is not returned by API/SSE or trace debug output by default.
- Credentials and secret-like metadata are rejected or redacted at policy-relevant boundaries.
- Policy trace events contain safe decision summaries only.
- Health and capabilities include safe policy summaries only.
- Fake policy service tests can run without external identity, database, LLM, memory, or MCP systems.
- The backend is ready for the next document: `backend-agents-architecture.md`.

---

## 37. Anti-Patterns to Avoid

Avoid these during implementation:

- Spreading policy checks as ad hoc `if` statements across strategies and gateways.
- Letting API routes select agents, strategies, LLM profiles, or tools.
- Letting user metadata assign trusted roles, user IDs, project IDs, or scopes.
- Allowing unknown use cases by default.
- Allowing unknown tools by default.
- Letting discovered MCP tools become callable without policy review.
- Treating redaction as a replacement for authorization.
- Returning raw workflow state from API routes.
- Streaming raw provider chunks directly to the frontend.
- Tracing raw prompts, completions, memory records, or tool payloads by default.
- Logging credentials or auth headers.
- Falling back to a less restrictive strategy after policy denial.
- Allowing planners to invent tool names, agent names, LLM profiles, or memory scopes.
- Allowing write/destructive/external-side-effect tools without explicit approval policy.
- Executing approval-required operations when no approval service exists.
- Embedding provider-specific policy in provider adapters.
- Having `PolicyService` call LLM providers, memory adapters, MCP clients, SQLite, or ArcadeDB.
- Treating tool or memory result text as trusted instructions.
- Exposing full policy ACLs in `/capabilities`.
- Exposing policy internals or private rule details in `/health`.

---

## 38. Future Documents That Depend on This Policy Layer

| Future Document | Dependency |
|---|---|
| `backend-agents-architecture.md` | Agents declare capabilities and operate within policy-controlled use cases, strategies, tools, memory, and LLM profiles. |
| `backend-approval-workflow-architecture.md` | Approval workflow consumes `approval_required` policy decisions and validates approval tokens before side-effect execution. |
| `backend-prompt-context-architecture.md` | Prompt assembly implements data-exposure obligations such as context quoting, source labels, and untrusted-context boundaries. |
| `backend-auth-identity-architecture.md` | Replaces local/synthetic identity extraction with production identity while preserving `PolicySubject`. |
| `backend-privacy-architecture.md` | Defines export/delete/forget workflows and privacy controls built on memory/session/trace policy. |
| `backend-evaluation-architecture.md` | Evaluates policy compliance, denied-action handling, data exposure, and unsafe fallback prevention. |
| `backend-deployment-architecture.md` | Defines environment-specific policy settings, debug-route controls, secrets handling, and service-to-service trust. |
| `backend-hardening-architecture.md` | Defines production security review, rate limits, audit logging, and incident response controls. |

---

## 39. Summary

`backend-policy-architecture.md` defines the backend's centralized policy layer for authorization, safety, approval requirements, trace capture, and data exposure decisions.

It preserves all previously established boundaries: API remains thin, `SessionService` owns session lifecycle, `OrchestrationRuntime` owns turn lifecycle, workflow strategies own step ordering, `LLMGateway` owns model access, `MemoryGateway` owns memory access, `ToolGateway` owns tool execution, and `MCPClientAdapter` remains the only backend component that speaks MCP protocol.

The most important implementation rule is:

> **Policy is the decision boundary, not the execution engine. Every backend layer may ask `PolicyService` whether an action is allowed, approval-required, or denied, but execution remains with the owning service or gateway, and policy denial must never be weakened by fallback, provider-specific shortcuts, or raw adapter access.**
