# Backend Policy Architecture

**Document:** `backend-policy-architecture.md`  
**Version:** 1.0  
**Source alignment:** `backend-application-architecture.md`, `backend-foundation-architecture.md`, `backend-core-contracts-architecture.md`, `backend-configuration-architecture.md`, `backend-observability-architecture.md`, `backend-persistence-architecture.md`, `backend-sqlite-workflow-state-architecture.md`, `backend-sqlite-trace-store-architecture.md`, `backend-api-architecture.md`, `backend-session-service-architecture.md`, `backend-llm-gateway-architecture.md`, `backend-memory-store-adapter-architecture.md`, `backend-tooling-mcp-client-architecture.md`, `backend-orchestration-architecture.md`, `backend-workflow-strategies-architecture.md`, and `backend-agents-architecture.md`  
**Scope:** Policy service contract, policy domains, deny-by-default authorization, use-case access, strategy access, agent access, LLM profile access, memory scope access, memory write controls, tool authorization, approval gates, fallback policy, trace/data-exposure policy, stream-event policy, redaction integration, configuration schema, testing strategy, and acceptance criteria for the V1 backend policy layer.

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
15. `backend-agents-architecture.md`
16. `backend-policy-architecture.md` ← this document

The previous document defined the agent plugin layer. Agents are task-specific, gateway-only, configuration-driven, capability-scoped, prompt-safe, tool-safe, memory-safe, streaming-capable, traceable, testable, and replaceable.

This document defines the policy layer that constrains the API, session, orchestration runtime, strategies, agents, gateways, traces, and stream events.

The goal is to make policy decisions explicit, centralized, testable, and configuration-driven without putting business workflow logic into policy and without allowing agents, strategies, gateways, or API routes to bypass controls.

The core architecture rule is:

> **Policy decides whether an action is allowed, denied, or approval-required. Policy does not execute the action. Runtime, strategies, agents, and gateways must call policy before sensitive operations, and gateways must remain the final enforcement boundary before provider, memory, tool, or MCP calls.**

---

## 2. Source Architecture Alignment

This document follows the established backend rules:

- The backend remains one deployable application tier in V1.
- Frontend communicates with backend through REST / SSE.
- API routes remain thin and delegate chat/reset behavior to `SessionService`.
- `SessionService` owns session lifecycle, workflow-state load/save/reset, and request-to-runtime handoff.
- `OrchestrationRuntime` owns turn lifecycle, context construction, strategy resolution, cancellation, and normalized results.
- Workflow strategies own turn shape.
- Agents own task-specific work.
- Gateways own provider, memory, and tool access.
- Policy is a cross-cutting boundary that is called before sensitive choices and sensitive actions.
- LLM access remains behind `LLMGateway`.
- Memory/document access remains behind `MemoryGateway`.
- Tool execution remains behind `ToolGateway`.
- MCP protocol communication remains behind `MCPClientAdapter`.
- SQLite workflow state remains behind `WorkflowStateStore`.
- SQLite traces remain behind `TraceStore` or an observability facade.
- ArcadeDB-backed memory remains hidden behind the `memory_store` wrapper and backend `MemoryGateway`.
- Agents and strategies must not import concrete providers, MCP clients, SQLite clients, ArcadeDB clients, `memory_store`, or frontend DTOs.
- Raw prompts, raw provider responses, raw MCP payloads, raw memory records, raw workflow state documents, credentials, hidden scratchpads, planning scratchpads, stack traces, and secret-bearing error payloads must not be returned, streamed, logged, traced, or persisted by default.
- Policy decisions must be trace-correlated with the active `trace_id` using safe summaries.

---

## 3. Refined Position in the Backend Implementation Sequence

The previous document expanded Phase 15 into agent plugins. This document expands Phase 16.

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
Phase 15: Agent Plugins
Phase 16: Policy Hardening
Phase 17: Deployment Readiness
```

The output of this phase is a policy layer that supports:

```text
PolicyService.evaluate(...)
PolicyService.can_access_usecase(...)
PolicyService.can_run_strategy(...)
PolicyService.can_use_agent(...)
PolicyService.can_use_llm_profile(...)
PolicyService.can_access_memory_scope(...)
PolicyService.can_write_memory(...)
PolicyService.can_execute_tool(...)
PolicyService.requires_approval(...)
PolicyService.can_use_fallback(...)
PolicyService.can_emit_trace_payload(...)
PolicyService.can_emit_stream_event(...)
PolicyService.redact_payload(...)
PolicyRegistry.register_rule(...)
PolicyEngine.evaluate_rules(...)
PolicyDecisionCache.get(...)
PolicyAuditRecorder.record(...)
```

The next document should be:

```text
backend-deployment-architecture.md
```

---

## 4. Architecture Goals

The policy layer should be:

1. **Deny-by-default**  
   Unknown use cases, strategies, agents, LLM profiles, memory scopes, memory write operations, and tools should be denied unless explicitly allowed.

2. **Centralized but not monolithic**  
   Policy decisions should be exposed through one `PolicyService` interface, while implementation can be composed from rule evaluators, configuration, and future external policy engines.

3. **Gateway-enforced**  
   Runtime, strategies, and agents should call policy early, but gateways must enforce final operation-level checks before LLM, memory, tool, or MCP calls.

4. **Configuration-driven**  
   Use-case access, agent allowlists, strategy allowlists, LLM profile allowlists, memory scope rules, tool rules, approval requirements, fallback behavior, and trace exposure rules are configured through YAML.

5. **Context-aware**  
   Decisions should include actor, session, use case, strategy, agent, LLM profile, memory scope, tool name, action type, risk level, and request metadata where available.

6. **Traceable**  
   Policy decisions should produce safe audit summaries with decision, reason code, policy domain, resource name, and trace ID.

7. **Approval-ready**  
   V1 should support `approval_required` as a first-class decision even if full approval workflow is implemented later.

8. **Non-bypassable**  
   User metadata, LLM outputs, agent outputs, tool outputs, memory content, and router decisions must not directly grant permissions.

9. **Safe for streaming**  
   Policy controls which stream events and payload fields can leave the backend over SSE.

10. **Safe for observability**  
    Policy controls trace/log payload categories and integrates with redaction.

11. **Testable**  
    Policy decisions can be unit-tested with fixtures and fake runtime contexts without external services.

12. **Replaceable**  
    V1 can use a local YAML-backed policy engine, while future versions can replace or augment it with RBAC, ABAC, OPA, Cedar, or organization-specific policy providers.

---

## 5. Non-Goals

This document does not implement:

- Identity provider integration.
- OAuth/JWT verification internals.
- Full RBAC administration UI.
- Full ABAC policy authoring language.
- External policy engine integration.
- Human approval frontend UI.
- Approval resume workflow internals.
- Enterprise tenant management.
- Secrets management backend.
- Network-level security.
- Model safety classifier implementation.
- Full prompt-injection defense framework.
- Legal/compliance certification.
- Deployment-specific firewall, process, or container controls.

Those concerns belong to auth, approval workflow, prompt-context, deployment, hardening, compliance, and operations documents.

---

## 6. Policy Boundary

Policy sits beside orchestration, strategies, agents, gateways, observability, and configuration.

Policy owns:

- Access decisions.
- Allow/deny/approval-required decisions.
- Policy reason codes.
- Policy rule evaluation.
- Policy configuration validation.
- Safe policy decision summaries.
- Redaction policy integration.
- Trace/log/stream exposure decisions.
- Fallback permission decisions.
- Tool risk gating.
- Memory read/write scope gating.
- LLM profile permission gating.

Policy does not own:

- HTTP authentication implementation.
- Session persistence.
- Workflow-state persistence.
- LLM provider calls.
- Memory adapter calls.
- MCP protocol calls.
- Tool execution.
- Business workflow sequencing.
- Prompt construction.
- Agent task behavior.
- UI approval experience.
- Background task execution.

### 6.1 Boundary Diagram

```text
API
  -> SessionService
      -> OrchestrationRuntime
          -> PolicyService.can_access_usecase(...)
          -> PolicyService.can_run_strategy(...)
          -> WorkflowStrategy
              -> PolicyService.can_use_agent(...)
              -> AgentHandle
                  -> PolicyService.can_use_llm_profile(...)
                  -> LLMGateway
                      -> PolicyService.can_use_llm_profile(...) final check
                  -> MemoryGateway
                      -> PolicyService.can_access_memory_scope(...) final check
                      -> PolicyService.can_write_memory(...) final check
                  -> ToolGateway
                      -> PolicyService.can_execute_tool(...) final check
                      -> PolicyService.requires_approval(...) final check
              -> PolicyService.can_use_fallback(...)
          -> Observability facade
              -> PolicyService.can_emit_trace_payload(...)
              -> Redactor.redact(...)
```

### 6.2 Practical Rule

Runtime, strategies, agents, and gateways should do this:

```python
decision = await context.policy.can_execute_tool(
    request=ToolPolicyRequest(
        actor=PolicyActor(user_id=request.user_id),
        session_id=request.session_id,
        usecase=request.usecase,
        strategy_name=strategy_name,
        agent_name=agent_name,
        tool_name="project.read_file",
        action="execute",
        risk_level="read_only",
        arguments_summary={"path_kind": "project_relative"},
    )
)

if decision.is_denied:
    raise ToolPolicyDeniedError(decision.safe_reason)

if decision.requires_approval:
    return PendingApprovalSummary.from_policy_decision(decision)
```

They should not do this:

```python
if request.metadata.get("allow_tools"):
    await raw_mcp_client.call_tool(tool_name, arguments)
```

---

## 7. Enforcement Model

Policy enforcement should happen at multiple layers.

| Layer | Policy Responsibility | Example |
|---|---|---|
| API | Basic request shape and identity metadata handoff. | Reject missing/invalid session identity if required. |
| Session | Session ownership and reset permissions. | User can reset only sessions they own. |
| Runtime | Use-case and strategy permission. | User can run `document_qa` but not `admin_ops`. |
| Strategy | Agent, fallback, planner, and memory/tool phase permission. | Router can only select policy-allowed strategies. |
| Agent | Agent-level profile/capability permission before requesting gateway operations. | `reviewer_agent` cannot request memory writes. |
| LLMGateway | Final LLM profile/provider permission. | `local_fast` allowed; `expensive_reasoning` denied. |
| MemoryGateway | Final memory scope and write permission. | Project memory read allowed; global memory write denied. |
| ToolGateway | Final logical tool permission and approval requirement. | `documents.search` allowed; `email.send` approval-required. |
| Observability | Trace/log/stream exposure policy and redaction. | Raw prompts are blocked from traces. |

### 7.1 Final Enforcement Boundary

The closest gateway to the sensitive operation is the final enforcement boundary:

```text
LLMGateway before provider call
MemoryGateway before memory_store / ArcadeDB adapter call
ToolGateway before MCPClientAdapter call
Trace/observability facade before trace/log emission
SessionService before workflow-state reset
```

Earlier checks improve UX and fail faster, but they do not replace final gateway enforcement.

### 7.2 Deny-by-Default Rule

Deny when:

- No matching policy rule exists.
- The resource is unknown.
- The actor is missing when identity is required.
- The use case is unknown or disabled.
- The strategy, agent, LLM profile, memory scope, or tool is disabled.
- A request tries to use a raw provider, raw MCP tool, raw database scope, or raw filesystem path outside the logical abstraction.
- A policy rule cannot be evaluated safely.
- Policy configuration is invalid.
- Policy state is unavailable and fail-open is not explicitly configured for a non-sensitive read-only path.

---

## 8. Recommended Package Layout

Recommended implementation layout:

```text
backend/
  app/
    policy/
      __init__.py
      service.py
      engine.py
      registry.py
      models.py
      settings.py
      errors.py
      decisions.py
      context.py
      rule.py
      rule_loader.py
      rule_matcher.py
      rule_evaluator.py
      scopes.py
      reasons.py
      redaction_policy.py
      stream_policy.py
      trace_policy.py
      approval_policy.py
      fallback_policy.py
      memory_policy.py
      tool_policy.py
      llm_policy.py
      agent_policy.py
      strategy_policy.py
      session_policy.py
      usecase_policy.py
      audit.py
      decision_cache.py
      health.py
      capabilities.py

    observability/
      redaction.py
      trace_context.py
      events.py

    testing/
      fakes/
        fake_policy_service.py
        fake_policy_engine.py
        fake_policy_audit.py
```

### 8.1 Module Responsibilities

| Module | Responsibility |
|---|---|
| `service.py` | Public `PolicyService` implementation and facade. |
| `engine.py` | Rule evaluation engine. |
| `registry.py` | Registers domain-specific policy evaluators. |
| `models.py` | Shared policy request/result models. |
| `settings.py` | Typed policy configuration models. |
| `errors.py` | Policy error taxonomy. |
| `decisions.py` | Decision helpers and reason codes. |
| `context.py` | Policy evaluation context builder. |
| `rule.py` | Rule model and matcher primitives. |
| `rule_loader.py` | YAML policy rule loader. |
| `rule_matcher.py` | Actor/resource/action/scope matcher. |
| `rule_evaluator.py` | Deterministic rule evaluator. |
| `scopes.py` | Memory, project, session, tenant, and tool scope helpers. |
| `redaction_policy.py` | Payload category and field-level redaction rules. |
| `stream_policy.py` | SSE event type and field exposure rules. |
| `trace_policy.py` | Trace/log payload category allow/deny rules. |
| `approval_policy.py` | Approval-required decision helpers. |
| `fallback_policy.py` | Fallback/degradation policy rules. |
| `memory_policy.py` | Memory read/write policy evaluator. |
| `tool_policy.py` | Tool execution and tool-risk evaluator. |
| `llm_policy.py` | LLM profile/provider policy evaluator. |
| `agent_policy.py` | Agent permission evaluator. |
| `strategy_policy.py` | Strategy permission evaluator. |
| `session_policy.py` | Session access/reset evaluator. |
| `usecase_policy.py` | Use-case access evaluator. |
| `audit.py` | Safe policy audit event writer. |
| `decision_cache.py` | Optional per-turn cache for repeated safe decisions. |
| `health.py` | Safe policy health summaries. |
| `capabilities.py` | Frontend-safe policy/capability summaries. |

---

## 9. Dependency Direction Rules

Allowed:

```text
app/api/* -> app/policy/service.py through SessionService or request context
app/session/* -> app/policy/service.py for session access/reset checks
app/orchestration/* -> app/policy/service.py through OrchestrationContext
app/orchestration/strategies/* -> app/policy/service.py through OrchestrationContext
app/agents/* -> app/policy/service.py through OrchestrationContext
app/llm/gateway.py -> app/policy/service.py
app/memory/gateway.py -> app/policy/service.py
app/tools/gateway.py -> app/policy/service.py
app/observability/* -> app/policy/redaction_policy.py through facade
app/policy/* -> app/config schemas/settings
app/policy/* -> app/observability safe audit facade
```

Avoid:

```text
app/policy/* -> app/api routes
app/policy/* -> app/session service internals
app/policy/* -> concrete LLM provider SDKs
app/policy/* -> MCPClientAdapter
app/policy/* -> raw MCP server calls
app/policy/* -> sqlite3 direct queries for workflow state
app/policy/* -> ArcadeDB client
app/policy/* -> memory_store.service.MemoryService
app/policy/* -> concrete agent plugin classes
app/policy/* -> concrete strategy implementations
app/policy/* -> frontend DTOs
```

### 9.1 Policy-to-Configuration Rule

Policy may read typed configuration models prepared by the configuration layer.

Policy should not parse arbitrary YAML inside request paths unless the configuration loader has already validated it.

### 9.2 Policy-to-Observability Rule

Policy may write safe audit summaries through an observability/audit facade.

Policy must not write raw policy inputs that contain prompts, tool arguments, memory contents, credentials, or raw provider payloads.

---

## 10. Policy Domains

V1 policy should define these domains:

| Domain | Purpose |
|---|---|
| `session` | Controls session load/reset/history access. |
| `usecase` | Controls which use cases an actor can run. |
| `strategy` | Controls strategy selection and routing. |
| `agent` | Controls agent selection and agent capability use. |
| `llm` | Controls LLM profile/provider/model usage. |
| `memory_read` | Controls memory/document search and retrieval scopes. |
| `memory_write` | Controls memory creation, update, supersede, forget, and delete-by-scope. |
| `tool` | Controls logical tool listing and execution. |
| `approval` | Marks sensitive operations as approval-required. |
| `fallback` | Controls fallback/degraded behavior. |
| `trace` | Controls trace/log payload categories. |
| `stream` | Controls SSE event exposure. |
| `capabilities` | Controls what frontend-safe capabilities are exposed. |
| `health` | Controls what readiness/health information is exposed. |
| `data_exposure` | Controls response metadata, state summaries, and returned payload categories. |

### 10.1 Domain Separation Rule

Policies should not be collapsed into one broad `allow_all` flag.

For example:

```text
allow strategy != allow agent != allow tool != allow memory write
```

A user may be allowed to run `document_qa`, use `document_qa_agent`, and search project documents, but still be denied memory writes and external side-effect tools.

---

## 11. Policy Decision Model

Every policy call should return a normalized decision.

```python
from dataclasses import dataclass, field
from typing import Literal


PolicyDecisionValue = Literal["allow", "deny", "approval_required"]
PolicyEffect = Literal["read", "write", "execute", "emit", "reset", "select"]


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    decision: PolicyDecisionValue
    domain: str
    action: PolicyEffect
    resource: str | None = None
    reason_code: str = "unspecified"
    safe_reason: str | None = None
    approval_type: str | None = None
    rule_id: str | None = None
    risk_level: str | None = None
    obligations: tuple["PolicyObligation", ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)

    @property
    def is_allowed(self) -> bool:
        return self.decision == "allow"

    @property
    def is_denied(self) -> bool:
        return self.decision == "deny"

    @property
    def requires_approval(self) -> bool:
        return self.decision == "approval_required"
```

### 11.1 Obligations

Policy can return obligations that callers must apply before proceeding.

```python
@dataclass(frozen=True, slots=True)
class PolicyObligation:
    type: str
    value: object | None = None
```

Recommended V1 obligations:

```text
redact_fields
truncate_payload
record_audit_event
require_idempotency_key
require_approval_summary
limit_context_bytes
limit_result_count
force_safe_metadata_only
disable_streaming_payload
```

### 11.2 Decision Safety Rule

Safe decision metadata may include:

```text
policy domain
resource logical name
action
reason code
rule id
risk level
approval type
truncated true/false
```

Decision metadata must not include:

```text
raw prompt
raw tool arguments
raw tool result
raw memory text
raw memory record
raw provider response
credentials
API keys
OAuth tokens
JWTs
stack traces
hidden scratchpads
```

---

## 12. Policy Request Models

### 12.1 Actor Model

```python
@dataclass(frozen=True, slots=True)
class PolicyActor:
    user_id: str | None = None
    tenant_id: str | None = None
    roles: tuple[str, ...] = ()
    groups: tuple[str, ...] = ()
    service_account: str | None = None
    authenticated: bool = False
    metadata: dict[str, object] = field(default_factory=dict)
```

### 12.2 Evaluation Context

```python
@dataclass(frozen=True, slots=True)
class PolicyEvaluationContext:
    trace_id: str
    session_id: str | None
    request_id: str | None = None
    usecase: str | None = None
    strategy_name: str | None = None
    agent_name: str | None = None
    actor: PolicyActor | None = None
    project_id: str | None = None
    environment: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)
```

### 12.3 Generic Policy Request

```python
@dataclass(frozen=True, slots=True)
class PolicyRequest:
    context: PolicyEvaluationContext
    domain: str
    action: PolicyEffect
    resource: str | None = None
    scope: "PolicyScope | None" = None
    risk_level: str | None = None
    payload_summary: dict[str, object] = field(default_factory=dict)
```

### 12.4 Scope Model

```python
@dataclass(frozen=True, slots=True)
class PolicyScope:
    user_id: str | None = None
    tenant_id: str | None = None
    project_id: str | None = None
    session_id: str | None = None
    memory_namespace: str | None = None
    document_collection: str | None = None
    labels: tuple[str, ...] = ()
```

### 12.5 Payload Summary Rule

Policy request payloads should include summaries, not raw payloads.

Safe payload summary:

```json
{
  "argument_keys": ["path", "limit"],
  "argument_size_bytes": 248,
  "path_kind": "project_relative",
  "result_limit": 5
}
```

Unsafe payload summary:

```json
{
  "raw_prompt": "...",
  "raw_file_contents": "...",
  "authorization": "Bearer ...",
  "api_key": "..."
}
```

---

## 13. Policy Service Contract

Recommended public protocol:

```python
from typing import Protocol


class PolicyService(Protocol):
    async def evaluate(self, request: PolicyRequest) -> PolicyDecision: ...

    async def can_access_session(self, request: "SessionPolicyRequest") -> PolicyDecision: ...
    async def can_reset_session(self, request: "SessionPolicyRequest") -> PolicyDecision: ...
    async def can_access_usecase(self, request: "UsecasePolicyRequest") -> PolicyDecision: ...
    async def can_run_strategy(self, request: "StrategyPolicyRequest") -> PolicyDecision: ...
    async def can_use_agent(self, request: "AgentPolicyRequest") -> PolicyDecision: ...
    async def can_use_llm_profile(self, request: "LLMPolicyRequest") -> PolicyDecision: ...
    async def can_access_memory_scope(self, request: "MemoryReadPolicyRequest") -> PolicyDecision: ...
    async def can_write_memory(self, request: "MemoryWritePolicyRequest") -> PolicyDecision: ...
    async def can_execute_tool(self, request: "ToolPolicyRequest") -> PolicyDecision: ...
    async def requires_approval(self, request: "ApprovalPolicyRequest") -> PolicyDecision: ...
    async def can_use_fallback(self, request: "FallbackPolicyRequest") -> PolicyDecision: ...
    async def can_emit_trace_payload(self, request: "TracePolicyRequest") -> PolicyDecision: ...
    async def can_emit_stream_event(self, request: "StreamPolicyRequest") -> PolicyDecision: ...
    async def can_expose_capability(self, request: "CapabilityPolicyRequest") -> PolicyDecision: ...
    async def can_expose_health(self, request: "HealthPolicyRequest") -> PolicyDecision: ...

    def redact_payload(self, *, domain: str, payload: dict[str, object]) -> dict[str, object]: ...
    async def health(self) -> "PolicyHealthResult": ...
```

### 13.1 Service Rules

`PolicyService` should:

- Return normalized decisions.
- Fail closed for sensitive operations.
- Provide safe reason codes.
- Record safe audit summaries when configured.
- Support deterministic unit tests.
- Avoid external network dependency in V1.
- Avoid importing concrete agents, strategies, provider SDKs, MCP clients, SQLite clients, ArcadeDB clients, or frontend DTOs.

`PolicyService` should not:

- Execute tools.
- Search memory.
- Call LLMs.
- Persist workflow state.
- Render API responses.
- Build prompts.
- Parse raw provider responses.
- Decide answer content.

---

## 14. Policy Configuration Integration

Policy configuration should be loaded and validated by the configuration layer before application startup completes.

Recommended YAML:

```yaml
policy:
  enabled: true
  mode: local_yaml
  default_decision: deny
  fail_closed: true
  audit_decisions: true
  cache_decisions_per_turn: true

  actors:
    anonymous:
      authenticated: false
      default_roles: [guest]
    authenticated_user:
      authenticated: true
      default_roles: [user]

  usecases:
    default:
      enabled: true
      allowed_roles: [user, admin]
    document_qa:
      enabled: true
      allowed_roles: [user, admin]
      required_scope: project
    project_work:
      enabled: true
      allowed_roles: [user, admin]
      required_scope: project
    admin_ops:
      enabled: false
      allowed_roles: [admin]

  strategies:
    direct_agent:
      enabled: true
      allowed_usecases: [default, document_qa, project_work]
      allowed_roles: [user, admin]
    retrieval_augmented:
      enabled: true
      allowed_usecases: [document_qa, project_work]
      allowed_roles: [user, admin]
    tool_assisted:
      enabled: true
      allowed_usecases: [project_work]
      allowed_roles: [user, admin]
    bounded_planner:
      enabled: false
      allowed_roles: [admin]
    memory_update:
      enabled: true
      allowed_roles: [user, admin]
      require_explicit_user_intent: true

  agents:
    general_assistant_agent:
      enabled: true
      allowed_usecases: [default]
      allowed_llm_profiles: [default_reasoning, local_fast]
      allowed_tools: []
      memory_read: false
      memory_write: false
    document_qa_agent:
      enabled: true
      allowed_usecases: [document_qa]
      allowed_llm_profiles: [research_reasoning, local_fast]
      memory_read: true
      memory_write: false
      allowed_tools: []
    project_agent:
      enabled: true
      allowed_usecases: [project_work]
      allowed_llm_profiles: [tool_reasoning, default_reasoning]
      memory_read: true
      memory_write: false
      allowed_tools:
        - documents.search
        - project.read_file
    memory_curator_agent:
      enabled: true
      allowed_usecases: [default, project_work]
      allowed_llm_profiles: [memory_curator]
      memory_read: true
      memory_write: true
      allowed_tools: []

  llm:
    profiles:
      local_fast:
        enabled: true
        allowed_roles: [user, admin]
        max_input_bytes: 64000
        max_output_tokens: 2048
        allow_streaming: true
      default_reasoning:
        enabled: true
        allowed_roles: [user, admin]
        max_input_bytes: 64000
        max_output_tokens: 4096
        allow_streaming: true
      research_reasoning:
        enabled: true
        allowed_roles: [user, admin]
        max_input_bytes: 96000
        max_output_tokens: 4096
        allow_streaming: true
      expensive_reasoning:
        enabled: false
        allowed_roles: [admin]

  memory:
    read:
      default_decision: deny
      allowed_scopes:
        - scope: user
          allowed_roles: [user, admin]
          require_owner_match: true
        - scope: project
          allowed_roles: [user, admin]
          require_project_id: true
        - scope: global
          allowed_roles: [admin]
    write:
      default_decision: deny
      allow_user_preferences: true
      allow_project_facts: true
      allow_document_chunks: false
      require_explicit_user_intent_for_user_preferences: true
      require_project_scope_for_project_facts: true
      sensitive_memory_behavior: deny
      max_candidates_per_turn: 3
      max_writes_per_turn: 1

  tools:
    default_decision: deny
    logical_tools:
      documents.search:
        enabled: true
        risk_level: read_only
        allowed_usecases: [document_qa, project_work]
        allowed_agents: [project_agent]
        approval: none
        max_result_count: 10
      project.read_file:
        enabled: true
        risk_level: read_only
        allowed_usecases: [project_work]
        allowed_agents: [project_agent]
        approval: none
        path_policy: project_relative_only
      project.write_file:
        enabled: false
        risk_level: write
        allowed_usecases: [project_work]
        allowed_agents: [project_agent]
        approval: required
      email.send:
        enabled: false
        risk_level: external_side_effect
        allowed_agents: []
        approval: required

  approval:
    enabled: true
    default_for_risk_levels:
      read_only: none
      write: required
      destructive: required
      external_side_effect: required
      credential_access: deny
    unsupported_approval_behavior: deny

  fallback:
    enabled: true
    deny_after_policy_denial: true
    deny_after_possible_side_effect: true
    allowed_failure_types:
      - memory_unavailable
      - llm_timeout
      - tool_unavailable

  tracing:
    enabled: true
    default_payload_policy: safe_summary_only
    allow_raw_prompts: false
    allow_raw_completions: false
    allow_raw_tool_payloads: false
    allow_raw_memory_records: false
    allow_stack_traces: false
    redact_secrets: true

  streaming:
    enabled: true
    default_event_policy: safe_summary_only
    allow_response_delta: true
    allow_tool_summaries: true
    allow_memory_summaries: true
    allow_raw_provider_chunks: false
    allow_raw_tool_payloads: false
    allow_raw_memory_records: false

  capabilities:
    expose_policy_mode: false
    expose_enabled_usecases: true
    expose_safe_tool_names: true
    expose_raw_tool_schemas: false
    expose_llm_provider_details: false
```

### 14.1 Configuration Validation Rules

Startup validation should fail when:

- `policy.enabled` is false in a production profile without explicit override.
- `default_decision` is not `deny` for sensitive domains.
- A policy references unknown use cases, strategies, agents, tools, or LLM profiles.
- A strategy is enabled but policy denies all use cases that can select it.
- An agent is enabled but policy denies all strategies/use cases that can invoke it.
- A tool is enabled but has no risk level.
- A write/destructive/external-side-effect tool does not specify approval behavior.
- A memory write policy allows writes without scope rules.
- Sensitive memory behavior is missing.
- Trace policy allows raw prompts or raw tool payloads in a non-development profile.
- Streaming policy allows raw provider chunks directly.
- Fallback policy allows fallback after policy denial.

---

## 15. Typed Policy Settings

Recommended dataclasses:

```python
from dataclasses import dataclass, field
from typing import Literal


DecisionMode = Literal["allow", "deny", "approval_required"]
RiskLevel = Literal["read_only", "write", "destructive", "external_side_effect", "credential_access"]


@dataclass(frozen=True, slots=True)
class PolicyRootSettings:
    enabled: bool = True
    mode: str = "local_yaml"
    default_decision: DecisionMode = "deny"
    fail_closed: bool = True
    audit_decisions: bool = True
    cache_decisions_per_turn: bool = True
    usecases: dict[str, "UsecasePolicySettings"] = field(default_factory=dict)
    strategies: dict[str, "StrategyPolicySettings"] = field(default_factory=dict)
    agents: dict[str, "AgentPolicySettings"] = field(default_factory=dict)
    llm: "LLMPolicySettings" = field(default_factory=lambda: LLMPolicySettings())
    memory: "MemoryPolicySettings" = field(default_factory=lambda: MemoryPolicySettings())
    tools: "ToolPolicySettings" = field(default_factory=lambda: ToolPolicySettings())
    approval: "ApprovalPolicySettings" = field(default_factory=lambda: ApprovalPolicySettings())
    fallback: "FallbackPolicySettings" = field(default_factory=lambda: FallbackPolicySettings())
    tracing: "TracePolicySettings" = field(default_factory=lambda: TracePolicySettings())
    streaming: "StreamPolicySettings" = field(default_factory=lambda: StreamPolicySettings())
    capabilities: "CapabilityPolicySettings" = field(default_factory=lambda: CapabilityPolicySettings())


@dataclass(frozen=True, slots=True)
class UsecasePolicySettings:
    enabled: bool = True
    allowed_roles: tuple[str, ...] = ("user",)
    required_scope: str | None = None


@dataclass(frozen=True, slots=True)
class StrategyPolicySettings:
    enabled: bool = True
    allowed_usecases: tuple[str, ...] = ()
    allowed_roles: tuple[str, ...] = ("user",)


@dataclass(frozen=True, slots=True)
class AgentPolicySettings:
    enabled: bool = True
    allowed_usecases: tuple[str, ...] = ()
    allowed_llm_profiles: tuple[str, ...] = ()
    allowed_tools: tuple[str, ...] = ()
    memory_read: bool = False
    memory_write: bool = False


@dataclass(frozen=True, slots=True)
class LLMProfilePolicySettings:
    enabled: bool = True
    allowed_roles: tuple[str, ...] = ("user",)
    max_input_bytes: int = 64000
    max_output_tokens: int = 4096
    allow_streaming: bool = True


@dataclass(frozen=True, slots=True)
class LLMPolicySettings:
    default_decision: DecisionMode = "deny"
    profiles: dict[str, LLMProfilePolicySettings] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MemoryPolicySettings:
    default_decision: DecisionMode = "deny"
    read: dict[str, object] = field(default_factory=dict)
    write: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class LogicalToolPolicySettings:
    enabled: bool = True
    risk_level: RiskLevel = "read_only"
    allowed_usecases: tuple[str, ...] = ()
    allowed_agents: tuple[str, ...] = ()
    approval: Literal["none", "required", "deny"] = "none"
    path_policy: str | None = None
    max_result_count: int | None = None


@dataclass(frozen=True, slots=True)
class ToolPolicySettings:
    default_decision: DecisionMode = "deny"
    logical_tools: dict[str, LogicalToolPolicySettings] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ApprovalPolicySettings:
    enabled: bool = True
    unsupported_approval_behavior: DecisionMode = "deny"
    default_for_risk_levels: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class FallbackPolicySettings:
    enabled: bool = True
    deny_after_policy_denial: bool = True
    deny_after_possible_side_effect: bool = True
    allowed_failure_types: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TracePolicySettings:
    enabled: bool = True
    default_payload_policy: str = "safe_summary_only"
    allow_raw_prompts: bool = False
    allow_raw_completions: bool = False
    allow_raw_tool_payloads: bool = False
    allow_raw_memory_records: bool = False
    allow_stack_traces: bool = False
    redact_secrets: bool = True


@dataclass(frozen=True, slots=True)
class StreamPolicySettings:
    enabled: bool = True
    default_event_policy: str = "safe_summary_only"
    allow_response_delta: bool = True
    allow_tool_summaries: bool = True
    allow_memory_summaries: bool = True
    allow_raw_provider_chunks: bool = False
    allow_raw_tool_payloads: bool = False
    allow_raw_memory_records: bool = False


@dataclass(frozen=True, slots=True)
class CapabilityPolicySettings:
    expose_policy_mode: bool = False
    expose_enabled_usecases: bool = True
    expose_safe_tool_names: bool = True
    expose_raw_tool_schemas: bool = False
    expose_llm_provider_details: bool = False
```

---

## 16. Rule Evaluation Model

V1 should use deterministic local rule evaluation.

Recommended evaluation order:

```text
1. Validate request shape.
2. Build normalized policy evaluation context.
3. Verify policy service is enabled.
4. Resolve policy domain evaluator.
5. Match resource-specific rule.
6. Check enabled/disabled status.
7. Check actor authentication when required.
8. Check role/group/service account constraints.
9. Check use-case constraints.
10. Check strategy/agent constraints.
11. Check scope ownership/project/tenant constraints.
12. Check risk-level and approval constraints.
13. Attach obligations.
14. Produce safe decision.
15. Emit safe audit event when configured.
```

### 16.1 Rule Match Model

```python
@dataclass(frozen=True, slots=True)
class PolicyRule:
    rule_id: str
    domain: str
    action: str
    resource: str | None
    effect: PolicyDecisionValue
    allowed_roles: tuple[str, ...] = ()
    allowed_usecases: tuple[str, ...] = ()
    allowed_agents: tuple[str, ...] = ()
    allowed_strategies: tuple[str, ...] = ()
    required_scope: str | None = None
    risk_level: str | None = None
    obligations: tuple[PolicyObligation, ...] = ()
    reason_code: str = "rule_matched"
```

### 16.2 Precedence Rule

Recommended precedence:

```text
explicit deny > approval_required > explicit allow > default deny
```

Deny should win over allow.

Approval-required should not be treated as allow.

---

## 17. Session Policy

Session policy controls access to session state operations.

### 17.1 Session Policy Checks

Recommended checks:

```text
can_access_session
can_reset_session
can_read_session_history
can_append_session_message
can_clear_pending_approval
```

### 17.2 Session Reset Rule

Session reset may clear workflow state only.

Policy must not allow session reset to delete:

```text
long-term user memories
project memories
document chunks
global knowledge records
trace records by default
LLM profile configuration
MCP/tool configuration
```

### 17.3 Session Access Request

```python
@dataclass(frozen=True, slots=True)
class SessionPolicyRequest:
    context: PolicyEvaluationContext
    session_id: str
    action: Literal["read", "reset", "append", "history"]
    owner_user_id: str | None = None
```

---

## 18. Use-Case Policy

Use-case policy controls whether a request can enter a configured use case.

### 18.1 Use-Case Request

```python
@dataclass(frozen=True, slots=True)
class UsecasePolicyRequest:
    context: PolicyEvaluationContext
    usecase: str
    action: Literal["run", "stream", "list"] = "run"
```

### 18.2 Use-Case Rules

- Unknown use cases are denied.
- Disabled use cases are denied.
- Actor role/group constraints must pass.
- Scope requirements must pass.
- A use case may allow streaming while another denies it.
- Use-case access does not imply strategy, agent, LLM, memory, or tool access.

---

## 19. Strategy Policy

Strategy policy controls strategy execution and routing.

### 19.1 Strategy Request

```python
@dataclass(frozen=True, slots=True)
class StrategyPolicyRequest:
    context: PolicyEvaluationContext
    strategy_name: str
    usecase: str
    action: Literal["run", "route_to", "fallback_to"] = "run"
```

### 19.2 Strategy Rules

- Unknown strategies are denied.
- Disabled strategies are denied.
- Router may choose only policy-allowed candidate strategies.
- Bounded planner should be disabled by default unless explicitly enabled.
- Memory-update strategy requires memory write policy checks.
- Fallback strategy requires fallback policy checks.
- Policy denial must stop execution and must not trigger fallback to a less restrictive strategy.

### 19.3 Router Rule

Router strategy must treat user-requested strategy names as hints at most.

A user must not be able to select arbitrary strategy, agent, LLM profile, memory scope, or tool through request metadata.

---

## 20. Agent Policy

Agent policy controls agent selection and agent capability use.

### 20.1 Agent Request

```python
@dataclass(frozen=True, slots=True)
class AgentPolicyRequest:
    context: PolicyEvaluationContext
    agent_name: str
    usecase: str
    strategy_name: str | None = None
    action: Literal["invoke", "stream", "list", "use_capability"] = "invoke"
    capability: str | None = None
```

### 20.2 Agent Rules

- Unknown agents are denied.
- Disabled agents are denied.
- Agent must be allowed for the active use case.
- Agent must be allowed for the active strategy when strategy constraints exist.
- Agent capability grants do not bypass gateway checks.
- Agent tool allowlists are logical tool names only, not MCP method names.
- Agent LLM profile allowlists are logical profile names only, not provider/model names.

### 20.3 Agent Capability Rule

Agent-declared capabilities are descriptive.

Policy grants are authoritative.

```text
AgentDescriptor.capabilities tells what the agent can do.
PolicySettings tells what the agent may do for this request.
Gateway policy checks enforce final permissions.
```

---

## 21. LLM Policy

LLM policy controls which logical model profiles can be used.

### 21.1 LLM Request

```python
@dataclass(frozen=True, slots=True)
class LLMPolicyRequest:
    context: PolicyEvaluationContext
    profile: str
    action: Literal["complete", "stream", "embed", "rerank", "classify"]
    requested_by: Literal["runtime", "strategy", "agent", "gateway"]
    input_bytes: int | None = None
    max_output_tokens: int | None = None
```

### 21.2 LLM Rules

- Unknown profiles are denied.
- Disabled profiles are denied.
- Provider/model details are not directly selectable by agents or users.
- Agent/strategy profile allowlists must be enforced.
- Input size and output token limits must be enforced before gateway call.
- Streaming must be allowed by profile policy.
- Fallback profile selection must pass policy.
- Expensive, external, or experimental profiles can require admin role or be disabled in V1.

### 21.3 LLM Gateway Final Enforcement

`LLMGateway` must call policy after profile resolution and before provider adapter invocation.

This prevents:

- Direct profile escalation by strategies.
- Agent-selected profile escalation.
- Router-selected profile escalation.
- Fallback profile escalation.
- Provider/model leakage through raw request metadata.

---

## 22. Memory Read Policy

Memory read policy controls memory and document retrieval scopes.

### 22.1 Memory Read Request

```python
@dataclass(frozen=True, slots=True)
class MemoryReadPolicyRequest:
    context: PolicyEvaluationContext
    action: Literal["search", "retrieve", "expand_graph"]
    scope: PolicyScope
    include_user_memories: bool = True
    include_project_memories: bool = True
    include_document_chunks: bool = True
    include_global_memories: bool = False
    query_summary: dict[str, object] = field(default_factory=dict)
```

### 22.2 Memory Read Rules

- Unknown memory namespaces are denied.
- Missing scope is denied.
- User memory read requires owner match unless explicitly elevated.
- Project memory read requires project scope.
- Global memory read requires explicit admin or service policy.
- Document chunk retrieval requires collection/project permission.
- Graph expansion must be bounded and scope-preserving.
- Retrieved memory text is untrusted data and must not become instructions.

### 22.3 Memory Gateway Final Enforcement

`MemoryGateway.search`, `MemoryGateway.retrieve`, and graph expansion calls must perform final policy checks before calling `MemoryStoreAdapter`.

---

## 23. Memory Write Policy

Memory write policy controls durable memory creation and lifecycle actions.

### 23.1 Memory Write Request

```python
@dataclass(frozen=True, slots=True)
class MemoryWritePolicyRequest:
    context: PolicyEvaluationContext
    action: Literal["upsert", "promote", "supersede", "contradict", "expire", "forget", "delete_by_scope"]
    scope: PolicyScope
    memory_type: str
    candidate_count: int = 1
    explicit_user_intent: bool = False
    sensitivity_summary: dict[str, object] = field(default_factory=dict)
```

### 23.2 Memory Write Rules

- Unknown memory type is denied.
- Missing scope is denied.
- User preference writes should require explicit user intent or configured automatic-memory behavior.
- Project fact writes require project scope.
- Document chunk writes are ingestion operations, not agent memory writes, and should be denied from normal chat agents.
- Sensitive memory behavior should default to deny unless explicitly configured.
- Memory writes are bounded by candidate count and write count per turn.
- Delete-by-scope requires elevated permission or explicit administrative workflow.
- Memory writes must go through `MemoryGateway` only.

### 23.3 Sensitive Memory Rule

V1 should support conservative behavior:

```text
sensitive_memory_behavior: deny
```

Alternative future values:

```text
allow_with_explicit_user_request
approval_required
redact_then_store
```

The strategy/agent should not make final sensitive-memory decisions itself. It should pass a safe sensitivity summary to policy and `MemoryGateway`.

---

## 24. Tool Policy

Tool policy controls logical tool listing and execution.

### 24.1 Tool Request

```python
@dataclass(frozen=True, slots=True)
class ToolPolicyRequest:
    context: PolicyEvaluationContext
    tool_name: str
    action: Literal["list", "describe", "execute"] = "execute"
    risk_level: str | None = None
    arguments_summary: dict[str, object] = field(default_factory=dict)
    idempotency_key_present: bool = False
```

### 24.2 Tool Rules

- Unknown tools are denied.
- Disabled tools are denied.
- Tool names must be logical backend tool names, not raw MCP method names.
- Tool must be allowed for the active use case.
- Tool must be allowed for the active agent.
- Tool risk level must be known.
- Tool arguments must satisfy tool schema and policy argument restrictions.
- Read-only tools may be allowed without approval.
- Write/destructive/external-side-effect tools require approval or are denied.
- Credential-access tools are denied in V1 unless explicitly handled by a future approval/secret workflow.
- Tool result payloads are untrusted data.

### 24.3 Tool Risk Levels

Recommended V1 risk levels:

| Risk Level | Meaning | Default |
|---|---|---|
| `read_only` | Reads bounded data without external side effects. | May allow. |
| `write` | Modifies project-local state or files. | Approval-required or deny. |
| `destructive` | Deletes or overwrites data. | Approval-required or deny. |
| `external_side_effect` | Sends email, posts, purchases, opens tickets, or calls external action. | Approval-required or deny. |
| `credential_access` | Reads or handles secrets/tokens. | Deny in V1. |

### 24.4 Tool Gateway Final Enforcement

`ToolGateway.execute` must perform final policy checks before `MCPClientAdapter` invocation.

Strategies and agents may create `ToolIntent`, but a tool intent is never permission to execute.

---

## 25. Approval Policy

Approval policy controls operations that cannot execute immediately.

### 25.1 Approval Request

```python
@dataclass(frozen=True, slots=True)
class ApprovalPolicyRequest:
    context: PolicyEvaluationContext
    domain: str
    action: str
    resource: str
    risk_level: str
    safe_description: str
    idempotency_key_present: bool = False
```

### 25.2 Approval Decision

Approval policy can return:

```text
allow
deny
approval_required
```

V1 should support `approval_required` as a normalized outcome but should not implement the full approval lifecycle unless that phase has been implemented.

### 25.3 Approval-Required Behavior

When approval is required and approval workflow is not implemented:

```text
1. Do not execute the operation.
2. Return a `PendingApprovalSummary` or normalized approval-required error.
3. Persist only safe pending summary if session policy allows.
4. Do not store raw tool arguments, raw prompts, credentials, or raw payloads in workflow state.
5. Do not retry through fallback as if the operation succeeded.
```

### 25.4 Pending Approval Summary

```python
@dataclass(frozen=True, slots=True)
class PendingApprovalSummary:
    approval_type: str
    domain: str
    action: str
    resource: str
    risk_level: str
    safe_description: str
    expires_at: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)
```

---

## 26. Fallback Policy

Fallback policy controls whether a failed strategy/gateway path can degrade to another path.

### 26.1 Fallback Request

```python
@dataclass(frozen=True, slots=True)
class FallbackPolicyRequest:
    context: PolicyEvaluationContext
    failed_strategy: str | None
    fallback_strategy: str | None
    failure_type: str
    policy_denied: bool = False
    side_effect_may_have_started: bool = False
    fallback_requires_broader_permissions: bool = False
```

### 26.2 Fallback Rules

Allow fallback only when:

- Fallback is enabled.
- Failure type is configured as degradable.
- No policy denial caused the failure.
- No external side effect may have partially started.
- Fallback does not require broader permissions.
- Fallback is configured for the use case.
- Fallback strategy itself passes strategy policy.

Deny fallback when:

- The primary failure was policy denial.
- Approval was required but not granted.
- A side-effect operation may have partially executed.
- Fallback would hide a data integrity problem.
- Fallback would execute a less restricted or broader strategy.
- Fallback would create an unbounded retry loop.

---

## 27. Data Exposure Policy

Data exposure policy controls what can leave internal boundaries.

### 27.1 Exposure Domains

```text
api_response
sse_stream
trace_event
structured_log
workflow_state_delta
health_response
capabilities_response
error_response
```

### 27.2 Safe by Default

Allowed by default:

```text
safe answer text
safe step summaries
strategy name
agent name
logical tool name
memory result count
memory update count
fallback used flag
policy reason code
safe error code
trace id
```

Denied by default:

```text
raw prompts
raw system/developer messages
raw provider responses
raw MCP payloads
raw tool arguments unless specifically redacted and summarized
raw tool results
raw memory records
raw embedding vectors
raw workflow state documents
credentials
provider API keys
OAuth tokens
JWTs
local file paths if sensitive
stack traces
hidden chain-of-thought
planning scratchpads
```

### 27.3 Data Exposure Request

```python
@dataclass(frozen=True, slots=True)
class DataExposurePolicyRequest:
    context: PolicyEvaluationContext
    exposure_domain: str
    payload_category: str
    field_names: tuple[str, ...] = ()
    destination: str | None = None
```

---

## 28. Trace and Audit Policy

Trace policy controls trace payload categories.

Audit policy records safe policy decisions.

### 28.1 Trace Policy Request

```python
@dataclass(frozen=True, slots=True)
class TracePolicyRequest:
    context: PolicyEvaluationContext
    event_name: str
    payload_category: str
    field_names: tuple[str, ...] = ()
```

### 28.2 Safe Policy Audit Event

```json
{
  "event_name": "policy_decision",
  "trace_id": "trace_...",
  "payload": {
    "domain": "tool",
    "action": "execute",
    "resource": "project.read_file",
    "decision": "allow",
    "reason_code": "tool_allowed_for_agent_and_usecase",
    "risk_level": "read_only",
    "rule_id": "tool.project.read_file.allow.project_agent"
  }
}
```

### 28.3 Unsafe Policy Audit Event

```json
{
  "raw_prompt": "...",
  "raw_tool_arguments": {...},
  "raw_memory_text": "...",
  "authorization": "Bearer ...",
  "stack_trace": "..."
}
```

### 28.4 Trace Capture Rule

Trace capture is not a bypass around data exposure.

If a payload is not safe for API response, it is usually not safe for trace/log storage either unless a specific secure diagnostics mode exists and is explicitly enabled outside V1 defaults.

---

## 29. Stream Policy

Stream policy controls SSE event type and field exposure.

### 29.1 Stream Policy Request

```python
@dataclass(frozen=True, slots=True)
class StreamPolicyRequest:
    context: PolicyEvaluationContext
    event_type: str
    payload_category: str
    field_names: tuple[str, ...] = ()
```

### 29.2 Allowed Stream Events

Allowed safe event types:

```text
request.accepted
session.loaded
strategy.started
strategy.step.started
strategy.step.completed
agent.started
agent.completed
memory.search.started
memory.search.completed
tool.started
tool.completed
response.delta
response.metadata
strategy.completed
strategy.failed
strategy.cancelled
```

### 29.3 Denied Stream Payloads

Stream policy should deny:

```text
raw provider chunks before normalization
raw prompts
raw hidden scratchpads
raw MCP responses
raw tool arguments unless safe-summary fields only
raw memory records
raw workflow state
credentials
stack traces
```

### 29.4 Response Delta Rule

`response.delta` may stream assistant-visible answer text after gateway/agent normalization.

It must not stream raw provider deltas that contain provider metadata, tool call payloads, hidden reasoning, or raw system/developer content.

---

## 30. Redaction Integration

Policy should work with the observability redactor.

Recommended flow:

```text
1. Caller asks policy if payload category may be emitted.
2. Policy returns allow/deny and redaction obligations.
3. Redactor applies field-level and pattern-level redaction.
4. Observability/API/SSE emits redacted payload.
5. Safe audit event records exposure decision if configured.
```

### 30.1 Redaction Categories

Recommended categories:

```text
credential
secret
api_key
oauth_token
jwt
connection_string
raw_prompt
raw_completion
raw_tool_payload
raw_memory_record
raw_workflow_state
file_path
email_address
user_identifier
stack_trace
```

### 30.2 Redaction Rule

Redaction is defense-in-depth.

A payload category denied by policy should not be emitted merely because redaction exists.

---

## 31. Prompt and Tool-Output Injection Policy

This document does not define the full prompt-context architecture, but it sets policy requirements.

### 31.1 Untrusted Data Rule

The following are untrusted data:

```text
user messages
retrieved memory text
document chunks
tool results
MCP tool descriptions if remote-controlled
web/external API data
LLM planner output
LLM router output
LLM tool-intent output
```

### 31.2 Policy Controls

Policy should support:

- Denying tools that expose unbounded external content.
- Requiring context byte limits.
- Requiring result count limits.
- Requiring project-relative path controls.
- Requiring approval for write/destructive/external-side-effect tools.
- Denying tool outputs from granting new permissions.
- Denying memory/tool text from selecting agents, strategies, LLM profiles, or tools.

### 31.3 Future Prompt-Context Document

A future `backend-prompt-context-architecture.md` should define detailed prompt assembly, context quoting, instruction hierarchy, and prompt-injection handling.

---

## 32. Capability and Health Policy

Capabilities and health endpoints should expose only safe metadata.

### 32.1 Capability Policy

Expose by default:

```text
enabled use-case display names
streaming support
safe tool display names when configured
safe agent display names when configured
feature flags
```

Do not expose by default:

```text
policy rules
role mappings
raw tool schemas if sensitive
provider URLs
provider model names if sensitive
MCP endpoints
API keys
memory database paths
SQLite paths
approval internals
```

### 32.2 Health Policy

Expose by default:

```text
policy configured true/false
policy healthy true/false
policy mode safe label
last validation status
rule count summary
```

Do not expose:

```text
full policy YAML
secrets
internal allowlists if sensitive
raw provider details
MCP endpoint values
filesystem paths
```

---

## 33. Error Model

Recommended policy errors:

```python
class PolicyError(Exception):
    code: str
    retryable: bool = False


class PolicyConfigurationError(PolicyError): ...
class PolicyEvaluationError(PolicyError): ...
class PolicyDomainUnknownError(PolicyError): ...
class PolicyResourceUnknownError(PolicyError): ...
class PolicyDeniedError(PolicyError): ...
class PolicyApprovalRequiredError(PolicyError): ...
class PolicyUnavailableError(PolicyError): ...
class PolicyObligationError(PolicyError): ...
class PolicyAuditError(PolicyError): ...
```

### 33.1 Error Mapping

| Error | Retryable | Behavior |
|---|---:|---|
| `PolicyConfigurationError` | false | Fail startup or fail closed. |
| `PolicyEvaluationError` | false | Fail closed for sensitive actions. |
| `PolicyDomainUnknownError` | false | Deny. |
| `PolicyResourceUnknownError` | false | Deny. |
| `PolicyDeniedError` | false | Stop action; no weaker fallback. |
| `PolicyApprovalRequiredError` | false | Return pending approval summary if supported. |
| `PolicyUnavailableError` | true/false | Fail closed unless safe non-sensitive read path explicitly allows degradation. |
| `PolicyObligationError` | false | Stop action if obligations cannot be applied. |
| `PolicyAuditError` | true/false | Do not leak payload; fail closed if audit is mandatory. |

### 33.2 Error Safety Rule

Policy errors returned to API/session/runtime should include:

```text
safe error code
policy domain
logical resource name when safe
safe reason code
trace id
```

Policy errors should not include:

```text
raw rule file contents
raw payload
raw prompt
raw tool arguments
raw provider response
credentials
stack traces
```

---

## 34. Observability Integration

Policy should emit safe trace/audit events through the observability facade.

Recommended events:

| Event | Emitted By | Notes |
|---|---|---|
| `policy_decision` | `PolicyService` | Safe decision summary. |
| `policy_denied` | `PolicyService` / caller | Denied domain/action/resource. |
| `policy_approval_required` | `PolicyService` | Approval type and risk level. |
| `policy_config_loaded` | composition root | Safe rule counts only. |
| `policy_config_invalid` | composition root | Safe validation error code. |
| `policy_obligation_applied` | caller/redactor | Obligation type only. |
| `policy_fallback_denied` | fallback helper | Safe reason. |
| `policy_trace_payload_denied` | observability facade | Payload category denied. |
| `policy_stream_event_denied` | SSE mapper | Event category denied. |

### 34.1 Metrics

Recommended metrics:

```text
backend.policy.decisions.total
backend.policy.denials.total
backend.policy.approvals_required.total
backend.policy.evaluation.duration_ms
backend.policy.errors.total
backend.policy.cache.hits.total
backend.policy.cache.misses.total
backend.policy.obligations.total
```

Allowed metric tags:

```text
domain
action
resource_kind
decision
reason_code
risk_level
usecase
strategy_name
agent_name
environment
```

Avoid metric tags:

```text
raw user id
session id
trace id
message text
prompt text
tool arguments
memory text
provider URL
API key
file path
```

---

## 35. Decision Cache

A small per-turn decision cache can reduce repeated policy checks.

### 35.1 Cache Scope

```text
per request / per turn only
not durable
not shared across users
not shared across sessions
not shared across policy reloads
```

### 35.2 Cache Key

Recommended safe cache key fields:

```text
domain
action
resource
usecase
strategy_name
agent_name
actor role hash
scope hash
risk_level
policy_config_version
```

Do not include raw prompts, raw tool arguments, raw memory text, or credentials in cache keys.

### 35.3 Cache Invalidation

Invalidate when:

- Policy config version changes.
- Actor/session changes.
- Use case/strategy/agent changes.
- Scope changes.
- Tool risk/argument policy changes.
- Approval state changes.

---

## 36. Composition Root Integration

The composition root builds policy before gateways, strategies, agents, runtime, and session service.

Recommended startup sequence:

```text
1. Load environment variables.
2. Load YAML configuration.
3. Validate typed configuration, including policy settings.
4. Build observability and redactor.
5. Build policy rule engine.
6. Build PolicyService.
7. Build TraceStore and observability facades with policy-aware redaction.
8. Build LLMGateway with PolicyService.
9. Build MemoryGateway with PolicyService.
10. Build ToolGateway with PolicyService.
11. Build AgentRegistry with PolicyService available through context.
12. Build StrategyRegistry with PolicyService available through context.
13. Build OrchestrationRuntime with PolicyService.
14. Build SessionService with PolicyService where session checks are needed.
15. Register API routes.
16. Log redacted policy startup summary.
```

### 36.1 Composition Example

```python
def build_policy_service(config, observability, redactor) -> PolicyService:
    rule_engine = LocalPolicyEngine(
        settings=config.policy,
        evaluators=[
            UsecasePolicyEvaluator(config.policy),
            StrategyPolicyEvaluator(config.policy),
            AgentPolicyEvaluator(config.policy),
            LLMPolicyEvaluator(config.policy),
            MemoryPolicyEvaluator(config.policy),
            ToolPolicyEvaluator(config.policy),
            ApprovalPolicyEvaluator(config.policy),
            FallbackPolicyEvaluator(config.policy),
            TracePolicyEvaluator(config.policy),
            StreamPolicyEvaluator(config.policy),
        ],
    )

    return DefaultPolicyService(
        settings=config.policy,
        engine=rule_engine,
        audit=PolicyAuditRecorder(observability),
        redactor=redactor,
    )
```

### 36.2 Redacted Startup Summary

Safe:

```json
{
  "event": "policy_configured",
  "policy_enabled": true,
  "mode": "local_yaml",
  "default_decision": "deny",
  "domains_configured": 13,
  "tool_rules": 4,
  "llm_profile_rules": 4,
  "memory_write_default": "deny"
}
```

Unsafe:

```json
{
  "raw_policy_yaml": "...",
  "provider_api_key": "...",
  "mcp_endpoint": "...",
  "database_path": "..."
}
```

---

## 37. Integration With Existing Modules

### 37.1 API Integration

API routes should:

- Validate DTO shape.
- Attach identity/session metadata.
- Delegate to `SessionService`.
- Avoid direct LLM/tool/memory decisions.

API routes may call policy only for API-boundary concerns such as capability visibility or direct route access.

### 37.2 Session Integration

`SessionService` should call policy for:

```text
session access
session reset
session history retrieval
pending approval state access when implemented
```

### 37.3 Runtime Integration

`OrchestrationRuntime` should call policy for:

```text
use-case access
strategy execution
streaming permission
request-level data exposure constraints
```

### 37.4 Strategy Integration

Strategies should call policy for:

```text
agent selection
router candidates
planner enablement
fallback decisions
memory update phase permission
tool phase permission before asking agent to create tool intents
```

Gateway final checks still apply.

### 37.5 Agent Integration

Agents should call policy or rely on strategy/gateway checks for:

```text
agent capability use
LLM profile use
memory candidate generation
self-managed tool calls if allowed
stream event emission
```

Agents must not interpret policy denial as a reason to bypass via another provider/tool.

### 37.6 LLM Gateway Integration

`LLMGateway` should call policy for:

```text
profile access
streaming permission
input byte limits
output token limits
fallback profile permission
trace payload category
```

### 37.7 Memory Gateway Integration

`MemoryGateway` should call policy for:

```text
search scope
retrieval scope
graph expansion scope
upsert/promote/supersede/contradict/expire/forget/delete-by-scope
candidate count and write count limits
sensitive memory behavior
```

### 37.8 Tool Gateway Integration

`ToolGateway` should call policy for:

```text
tool listing
tool description exposure
tool execution
risk level behavior
approval requirements
idempotency requirements
argument policy restrictions
result exposure obligations
```

### 37.9 Observability Integration

Observability should call policy/redaction for:

```text
trace event payload categories
structured log fields
error payloads
metrics tags
SSE stream payloads
health/capability responses
```

---

## 38. Testing Strategy

### 38.1 Unit Tests

| Test | Purpose |
|---|---|
| Unknown use case denied | Enforces deny-by-default. |
| Disabled use case denied | Enforces config enablement. |
| Allowed use case passes | Proves basic allow. |
| Unknown strategy denied | Prevents router bypass. |
| Disabled planner denied | Keeps planner disabled by default. |
| Router candidate policy-filtered | Prevents arbitrary strategy selection. |
| Unknown agent denied | Prevents plugin bypass. |
| Agent outside use case denied | Enforces use-case scope. |
| Unknown LLM profile denied | Prevents model escalation. |
| Disabled LLM profile denied | Enforces config. |
| LLM input bytes above limit denied | Enforces budget. |
| Memory read without scope denied | Prevents cross-scope memory access. |
| User memory owner mismatch denied | Protects user memory. |
| Project memory without project denied | Protects project scope. |
| Global memory denied to user role | Protects global scope. |
| Memory write without explicit intent denied | Protects durable memory. |
| Sensitive memory denied by default | Enforces conservative V1. |
| Unknown tool denied | Protects MCP boundary. |
| Raw MCP tool name denied | Enforces logical tool names. |
| Read-only tool allowed for allowed agent | Proves positive path. |
| Write tool approval-required | Proves approval gate. |
| Destructive tool denied without approval | Protects side effects. |
| Fallback denied after policy denial | Prevents policy weakening. |
| Trace raw prompt denied | Protects observability. |
| Stream raw tool payload denied | Protects SSE. |
| Redaction obligation applied | Proves defense-in-depth. |
| Policy audit event is safe | Prevents payload leakage. |
| Policy unavailable fails closed | Protects sensitive operations. |

### 38.2 Integration Tests

| Test | Purpose |
|---|---|
| API -> Session denies unauthorized reset | Proves session policy. |
| Runtime denies disabled use case | Proves runtime policy. |
| Router filters denied strategy | Proves strategy policy. |
| Direct strategy invokes allowed agent | Proves agent policy. |
| LLMGateway denies disallowed profile | Proves final LLM enforcement. |
| MemoryGateway denies cross-project read | Proves final memory enforcement. |
| MemoryGateway denies sensitive write | Proves memory write policy. |
| ToolGateway denies unknown logical tool | Proves final tool enforcement. |
| ToolGateway returns approval-required for write tool | Proves approval path. |
| Observability drops raw prompt trace field | Proves trace policy. |
| SSE mapper drops raw provider chunk field | Proves stream policy. |
| Fallback not allowed after policy denial | Proves fallback policy. |
| Capabilities hide provider/MCP details | Proves capability policy. |

### 38.3 Dependency Boundary Tests

Add import-boundary tests:

```text
policy must not import app/api routes
policy must not import concrete agent plugins
policy must not import concrete strategies
policy must not import provider SDKs
policy must not import MCP clients
policy must not import sqlite3 for workflow state
policy must not import ArcadeDB clients
policy must not import memory_store.service.MemoryService
policy must not import frontend DTOs
agents must not bypass policy/gateway with provider SDKs
strategies must not bypass policy/gateway with provider SDKs or MCP clients
gateways must call policy before provider/memory/tool execution
```

### 38.4 Fixture Configs

Recommended fixtures:

```text
tests/fixtures/config/policy_default_deny.yaml
tests/fixtures/config/policy_usecase_allowed.yaml
tests/fixtures/config/policy_strategy_router.yaml
tests/fixtures/config/policy_agents_basic.yaml
tests/fixtures/config/policy_llm_profiles.yaml
tests/fixtures/config/policy_memory_read_scopes.yaml
tests/fixtures/config/policy_memory_write_safe.yaml
tests/fixtures/config/policy_tools_read_only.yaml
tests/fixtures/config/policy_tools_approval_required.yaml
tests/fixtures/config/policy_fallback.yaml
tests/fixtures/config/policy_trace_safe_summary_only.yaml
tests/fixtures/config/policy_stream_safe_summary_only.yaml
tests/fixtures/config/policy_invalid_raw_trace.yaml
tests/fixtures/config/policy_invalid_write_tool_without_approval.yaml
tests/fixtures/config/policy_invalid_memory_write_without_scope.yaml
```

---

## 39. Recommended Implementation Order

### Step 1: Add Policy Models and Decisions

Deliverables:

- `PolicyActor`
- `PolicyScope`
- `PolicyEvaluationContext`
- `PolicyRequest`
- `PolicyDecision`
- `PolicyObligation`
- policy reason codes

Success criteria:

- Models compile.
- Decisions serialize to safe dictionaries.
- No raw payload is required for a policy decision.

### Step 2: Add Typed Policy Settings

Deliverables:

- `PolicyRootSettings`
- domain-specific settings classes
- YAML loading integration
- startup validation

Success criteria:

- Valid policy fixtures load.
- Invalid policy fixtures fail fast.
- Default decision is deny.

### Step 3: Add Local Policy Engine

Deliverables:

- `PolicyRule`
- `LocalPolicyEngine`
- rule matcher
- evaluator registry
- precedence handling

Success criteria:

- Explicit deny beats allow.
- Approval-required is not treated as allow.
- Unknown resource defaults to deny.

### Step 4: Add PolicyService Facade

Deliverables:

- `PolicyService` protocol
- `DefaultPolicyService`
- domain-specific convenience methods
- safe audit integration

Success criteria:

- Runtime and gateways can call one facade.
- Fake policy service can be used in tests.

### Step 5: Add Use-Case, Strategy, and Agent Policy

Deliverables:

- use-case evaluator
- strategy evaluator
- agent evaluator
- router candidate policy helper

Success criteria:

- Disabled use cases are denied.
- Router cannot select denied strategies.
- Agent invocation requires allowed use case and strategy.

### Step 6: Add LLM Policy Integration

Deliverables:

- LLM profile evaluator
- max input/output limit checks
- streaming permission checks
- LLM gateway final enforcement

Success criteria:

- Disallowed profile is denied at gateway.
- Fallback profile must pass policy.
- Streaming can be denied per profile.

### Step 7: Add Memory Policy Integration

Deliverables:

- memory read evaluator
- memory write evaluator
- memory scope helpers
- sensitive memory behavior rules
- MemoryGateway final enforcement

Success criteria:

- Cross-scope reads are denied.
- Sensitive memory writes are denied by default.
- Memory writes go through policy and `MemoryGateway` only.

### Step 8: Add Tool and Approval Policy Integration

Deliverables:

- logical tool evaluator
- risk-level model
- approval-required decision
- ToolGateway final enforcement
- pending approval summary model

Success criteria:

- Unknown tools denied.
- Raw MCP names denied.
- Read-only tools can run when allowed.
- Write/destructive/external-side-effect tools return approval-required or deny.

### Step 9: Add Fallback Policy

Deliverables:

- fallback evaluator
- side-effect-aware fallback checks
- policy-denial fallback guard

Success criteria:

- Fallback denied after policy denial.
- Fallback denied after possible side effect.
- Degraded fallback allowed only for configured failure types.

### Step 10: Add Trace, Stream, and Data Exposure Policy

Deliverables:

- trace payload evaluator
- stream event evaluator
- data exposure evaluator
- redaction obligations
- observability integration
- SSE mapper integration

Success criteria:

- Raw prompts are denied in traces.
- Raw provider chunks are denied in SSE.
- Health/capability responses do not leak secrets or endpoints.

### Step 11: Add Decision Cache and Audit

Deliverables:

- per-turn decision cache
- safe audit recorder
- policy metrics

Success criteria:

- Cache never stores raw payloads.
- Audit events include safe decision summaries only.
- Metrics use safe tags only.

### Step 12: Wire Policy Through Composition Root

Deliverables:

- build policy before gateways/runtime
- inject policy into gateways
- inject policy into runtime context
- add fake policy service for tests

Success criteria:

- `API -> SessionService -> OrchestrationRuntime -> Strategy -> Agent -> Gateway` path is policy-aware.
- Gateways enforce final checks.
- Existing API/session contracts remain unchanged.

---

## 40. Acceptance Criteria

This architecture is complete when:

- `backend-policy-architecture.md` hardens the backend after `backend-agents-architecture.md` without changing the API/session/orchestration/agent/gateway boundaries.
- Policy is exposed through a narrow `PolicyService` interface.
- Policy decisions return normalized `allow`, `deny`, or `approval_required` results.
- Unknown use cases, strategies, agents, LLM profiles, memory scopes, memory write operations, and tools are denied by default.
- Policy settings are YAML-driven and validated at startup.
- Use-case policy controls which use cases an actor can run.
- Strategy policy controls strategy execution and router candidates.
- Agent policy controls agent invocation and agent capability use.
- LLM policy controls logical LLM profile usage, streaming, and budget constraints.
- `LLMGateway` performs final LLM policy enforcement before provider calls.
- Memory read policy controls user/project/global/document scopes.
- Memory write policy controls memory lifecycle operations and sensitive memory behavior.
- `MemoryGateway` performs final memory policy enforcement before `memory_store` adapter calls.
- Tool policy controls logical tool listing and execution.
- Raw MCP tool names are denied outside the tool adapter boundary.
- `ToolGateway` performs final tool policy enforcement before `MCPClientAdapter` calls.
- Write, destructive, external-side-effect, and credential-access tools are approval-required or denied by default.
- Approval-required actions are not executed until an approval workflow exists and approval is granted.
- Fallback policy prevents fallback after policy denial or possible side-effect execution.
- Trace policy prevents raw prompts, raw completions, raw tool payloads, raw memory records, raw workflow state documents, credentials, stack traces, hidden scratchpads, and planning scratchpads from being traced by default.
- Stream policy prevents raw provider chunks, raw tool payloads, raw memory records, credentials, and hidden scratchpads from being streamed.
- Data exposure policy controls API responses, SSE payloads, trace events, logs, workflow-state deltas, health responses, capabilities responses, and error responses.
- Redaction is integrated as defense-in-depth and does not convert denied payload categories into allowed payloads.
- Policy audit events contain only safe summaries.
- Policy metrics use safe low-cardinality tags.
- Policy supports per-turn decision caching without storing raw payloads.
- Policy service does not import concrete provider SDKs, MCP clients, SQLite clients, ArcadeDB clients, `memory_store`, concrete strategy classes, concrete agent plugin classes, or frontend DTOs.
- Runtime, strategies, agents, LLM gateway, memory gateway, tool gateway, session service, and observability can all be tested with fake policy service implementations.
- Integration tests verify that denied operations stop before provider, memory, tool, or MCP adapter calls.
- The backend is ready for the next document: `backend-deployment-architecture.md`.

---

## 41. Anti-Patterns to Avoid

Avoid these during implementation:

- Using a global `allow_all` policy switch in normal V1 runtime.
- Letting user metadata choose arbitrary use case, strategy, agent, LLM profile, memory scope, or tool.
- Treating an agent capability declaration as permission.
- Treating an LLM tool intent as permission.
- Treating a router decision as permission.
- Letting fallback bypass policy denial.
- Letting gateway calls proceed after policy returns `approval_required`.
- Allowing raw MCP tool names in strategy or agent code.
- Allowing agents or strategies to call provider SDKs directly.
- Allowing policy to execute tools, search memory, call LLMs, or persist workflow state.
- Logging raw prompts for debugging by default.
- Tracing raw tool payloads or raw memory records by default.
- Streaming raw provider chunks directly to the frontend.
- Storing raw approval payloads in workflow state.
- Storing credentials in policy decisions, audit events, or cache keys.
- Caching policy decisions across users or sessions.
- Exposing full policy YAML through health or capabilities endpoints.
- Allowing memory writes without scope.
- Allowing sensitive memories by default.
- Allowing destructive/external-side-effect tools without approval.
- Making policy depend on concrete agent classes or concrete strategy classes.
- Making policy parse unvalidated YAML during request execution.
- Making policy unavailable errors fail open for sensitive actions.

---

## 42. Future Documents That Depend on This Policy Layer

| Future Document | Dependency |
|---|---|
| `backend-deployment-architecture.md` | Uses policy mode, environment profile, safe defaults, secret boundaries, and process topology. |
| `backend-approval-workflow-architecture.md` | Builds on `approval_required` decisions and `PendingApprovalSummary`. |
| `backend-prompt-context-architecture.md` | Builds on untrusted data rules, context exposure limits, and prompt/data separation. |
| `backend-hardening-architecture.md` | Extends policy with production auth, rate limits, tenant isolation, secure diagnostics, and operations controls. |
| `backend-evaluation-architecture.md` | Tests policy behavior, denial correctness, fallback behavior, and safety regressions. |
| `backend-admin-architecture.md` | Future UI/API for managing policy settings and approvals. |
| `backend-secrets-architecture.md` | Defines secret access policy and credential-bearing tool constraints. |

---

## 43. Summary

`backend-policy-architecture.md` defines the policy-hardening layer for the backend application tier.

It preserves the established architecture: API remains thin, `SessionService` owns session lifecycle, `OrchestrationRuntime` owns turn lifecycle, workflow strategies own workflow shape, agents own task-specific behavior, `LLMGateway` owns model access, `MemoryGateway` owns memory/document access, `ToolGateway` owns tool execution, and `MCPClientAdapter` remains the only backend component that speaks MCP protocol.

The most important implementation rule is:

> **Policy is the authorization and exposure decision layer, not an execution layer. Every sensitive operation must be checked before it runs, gateways must enforce final checks, denial must fail closed, approval-required must not execute, and no fallback may weaken policy restrictions.**
