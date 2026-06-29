# Backend Policy Implementation Plan

**Document:** `backend-policy-plan.md`  
**Version:** 1.0  
**Source alignment:** `backend-policy-architecture.md`, `backend-agents-plan.md`, `backend-llm-gateway-plan.md`, `backend-memory-store-adapter-plan.md`, `backend-tooling-mcp-client-plan.md`, `backend-orchestration-plan.md`, `backend-session-service-plan.md`, `backend-observability-plan.md`, and the current backend implementation baseline  
**Repository rule:** all backend application code lives under `backend/`

---

## 1. Purpose

This plan converts the backend policy architecture into a phased implementation sequence that can be delivered in small, low-risk slices.

The plan is intentionally strict about repository boundaries:

- Backend application code belongs in `backend/`.
- Backend source modules belong in `backend/app/`.
- Backend tests belong in `backend/tests/`.
- Backend configuration files belong in `backend/config/`.
- Backend local data files belong in `backend/data/`.
- Documentation updates belong in `docs/`.
- No backend runtime, policy, gateway, observability, or test code should be placed in the repository root, `frontend/`, or `mcp/`.

For clarity, this document uses filesystem paths such as `backend/app/policy/service.py`. Python imports may still use the `app.*` package path because `backend/` is the Python project root.

This phase is not greenfield work. The repository already contains a real but intentionally narrow policy slice under `backend/`. The implementation plan therefore focuses on deepening and reorganizing the existing policy runtime instead of creating a second policy surface beside it.

All validation commands in this plan assume execution from `backend/` using `.venv\Scripts\python.exe`.

---

## 2. Review Outcomes

The policy architecture document is implementation-ready. It is strong on the boundaries that matter for this phase:

- deny-by-default authorization
- final gateway enforcement for LLM, memory, and tool operations
- explicit approval-required outcomes
- fallback hardening after denial or side effects
- trace, stream, and data-exposure controls
- redaction as defense-in-depth rather than the primary authorization mechanism
- safe auditability and testability

The review also confirms that this phase should extend the existing backend baseline rather than replace it:

- `backend/app/contracts/policy.py` already defines a provider-neutral `PolicyRequest`, `PolicyDecision`, and `PolicyService` contract used by runtime and gateway code.
- `backend/app/testing/fakes/fake_policy.py` already provides a deterministic fake policy service used across current tests.
- `backend/app/policy/service.py` and `backend/app/policy/models.py` already implement a real config-driven `DefaultPolicyService`, but only for a narrow set of orchestration, LLM, memory, and tool decisions.
- `backend/app/config/schemas.py`, `backend/app/config/validation.py`, and `backend/config/app.yaml` already expose `policy.default_profile` plus `policy.profiles.*` booleans and validate use-case policy-profile references.
- `backend/app/llm/factory.py` currently constructs the real `DefaultPolicyService` and injects it into `DefaultLLMGateway`.
- `backend/app/config/bootstrap.py` already passes that same `policy_service` into `DefaultOrchestrationRuntime` and the backend `FoundationContainer`.
- Current policy-aware tests already exist under `backend/tests/unit/llm/`, `backend/tests/unit/memory/`, `backend/tests/unit/tools/`, `backend/tests/unit/orchestration/`, `backend/tests/unit/agents/`, and `backend/tests/integration/llm/`.

The review identifies the following implementation concerns that should shape the plan:

1. **The current policy runtime is too narrow for the architecture target.**  
   `backend/app/policy/service.py` currently resolves a small profile of booleans and handles only a subset of the domains described in `backend-policy-architecture.md`.

2. **The public contract is thinner than the target architecture.**  
   `backend/app/contracts/policy.py` currently exposes a boolean `allowed` decision plus `requires_approval`, but it does not yet model normalized decision kinds, actors, scopes, evaluation context, obligations, or domain-specific request shapes.

3. **The current runtime package is not yet policy-owned end to end.**  
   The real policy service is currently built inside `backend/app/llm/factory.py`, which is the wrong long-term ownership boundary for a cross-cutting backend policy layer.

4. **Policy configuration is only partially modeled today.**  
   The current config supports `default_profile` and a few booleans, but it does not yet represent the architecture's richer domain settings for use cases, strategies, agents, LLM profiles, memory scopes, memory writes, logical tools, approval, fallback, trace exposure, stream exposure, capability exposure, health exposure, audit, or cache behavior.

5. **Session and API policy are not first-class consumers yet.**  
   The current implementation does not yet provide explicit policy handling for session access, reset, history retrieval, API-facing capability visibility, or health/detail exposure.

6. **Gateway enforcement exists, but the rules remain metadata-heavy and ad hoc.**  
   Current LLM, memory, and tool checks work, but they should migrate to typed domain evaluators and normalized reason codes without weakening the existing final-enforcement guarantee.

7. **The recommended package layout in the architecture document should be adapted to the current repo.**  
   The existing repo already treats `backend/app/contracts/policy.py` as the public provider-neutral contract surface. The plan should keep that public contract under `backend/app/contracts/` and place runtime-only implementation details under `backend/app/policy/`.

8. **There is no dedicated policy test surface yet.**  
   The current repo has policy behavior covered indirectly through LLM, memory, tool, orchestration, and agent tests, but it does not yet have a dedicated `backend/tests/unit/policy/` or `backend/tests/integration/policy/` suite.

9. **Audit, decision caching, and policy-owned health/capabilities are still missing.**  
   The architecture calls for safe policy audit summaries, low-cardinality metrics, per-turn decision caching, and frontend-safe policy health/capability summaries, but the current runtime does not yet provide those surfaces.

---

## 3. Non-Negotiable Boundary Rules

- Treat `backend/` as the Python project root for all policy work.
- Keep public provider-neutral policy contracts under `backend/app/contracts/policy.py` unless an atomic, repo-wide contract move is explicitly required.
- Create concrete policy runtime implementation modules only under `backend/app/policy/`.
- Keep canonical policy configuration under `backend/config/app.yaml` and typed parsing/validation under `backend/app/config/`.
- Keep backend tests under `backend/tests/` and config fixtures under `backend/tests/fixtures/config/`.
- Keep documentation-only artifacts under `docs/`.
- Do not place backend policy code in the repository root, `frontend/`, or `mcp/`.
- Do not let `backend/app/policy/` import API route modules, concrete agent plugin modules, concrete strategy implementations, provider SDKs, MCP client implementations, `sqlite3`, ArcadeDB clients, `memory_store.service.MemoryService`, or frontend DTOs.
- Do not let API, session, orchestration, agent, or gateway code bypass policy by calling raw providers, raw MCP operations, raw memory adapters, or raw persistence stores directly.
- Keep `backend/app/main.py:app = create_app()` import-safe. Policy construction belongs in startup composition wiring, not import time.
- Keep gateways as the final enforcement boundaries before provider calls, memory operations, tool execution, or MCP transport.
- Deny by default and fail closed for sensitive operations when policy configuration is invalid or policy evaluation cannot complete safely.
- Never store or emit raw prompts, raw completions, raw tool payloads, raw memory records, raw workflow-state payloads, credentials, tokens, cookies, connection strings, stack traces, or hidden scratchpads in policy decisions, audit events, cache entries, or capability/health responses.
- Preserve the current API/session/orchestration/gateway architecture; policy hardening must not collapse those boundaries into a monolithic service.
- Keep test basenames unique across `backend/tests/` so Windows pytest collection does not trip over duplicate module names.

---

## 4. Phase Overview

| Phase | Name | Primary Outcome |
|---|---|---|
| 0 | [DONE] Current Policy Baseline and Repo Alignment | The repo already has a real but narrow policy service rooted under `backend/`, and this plan extends that baseline instead of treating policy as greenfield work. |
| 1 | [DONE] Policy Contracts, Decisions, and Typed Settings | The backend gains normalized policy models, richer decision semantics, typed `policy.*` settings, and startup validation aligned with the architecture. |
| 2 | [DONE] Policy Engine, Evaluators, and Policy-Owned Composition Root | Policy assembly moves into `backend/app/policy/`, domain evaluators become explicit, and startup injects policy as a true cross-cutting backend runtime. |
| 3 | [DONE] Session, Use-Case, Strategy, and Agent Policy Integration | API/session/runtime/strategy/agent paths become first-class policy consumers without bypassing gateway final checks. |
| 4 | [DONE] LLM, Memory, Tool, and Approval Policy Hardening | Gateway enforcement is upgraded to typed domain-specific checks with explicit approval-required behavior and safe obligations. |
| 5 | [DONE] Fallback, Trace, Stream, Redaction, Capability, and Health Policy | Output and exposure controls are centralized so traces, SSE, health, and capabilities remain frontend-safe and policy-governed. |
| 6 | [DONE] Audit, Decision Cache, Quality Gates, and Freeze | Safe audit summaries, per-turn cache, dedicated policy tests, import-boundary checks, README freeze notes, and full backend validation close the phase cleanly. |

---

## 5. Detailed Implementation Phases

### [DONE] Phase 0. Current Policy Baseline and Repo Alignment

**Goal**

Record the current backend policy slice so the implementation plan extends the existing repo rather than describing a second, parallel policy stack.

**Files already present**

- [DONE] `backend/app/contracts/policy.py`
- [DONE] `backend/app/testing/fakes/fake_policy.py`
- [DONE] `backend/app/policy/__init__.py`
- [DONE] `backend/app/policy/service.py`
- [DONE] `backend/app/policy/models.py`
- [DONE] `backend/app/config/schemas.py`
- [DONE] `backend/app/config/validation.py`
- [DONE] `backend/app/config/bootstrap.py`
- [DONE] `backend/app/foundation/container.py`
- [DONE] `backend/app/llm/factory.py`
- [DONE] `backend/config/app.yaml`
- [DONE] `backend/tests/unit/llm/test_gateway_policy.py`
- [DONE] `backend/tests/unit/memory/test_policy_integration.py`
- [DONE] `backend/tests/unit/tools/test_tools_gateway_policy_rules.py`
- [DONE] `backend/tests/unit/orchestration/test_strategy_policy.py`
- [DONE] `backend/tests/unit/orchestration/test_fallback_policy_behavior.py`
- [DONE] `backend/tests/unit/agents/test_agent_policy_denial.py`
- [DONE] `backend/tests/integration/llm/test_gateway_policy_denied.py`

**Implementation outcomes already in place**

- [DONE] The backend already exposes a provider-neutral policy contract through `backend/app/contracts/policy.py`.
- [DONE] The repo already has a deterministic fake policy service for tests.
- [DONE] The backend already has a real `DefaultPolicyService`, even though it is still narrow and profile-boolean-driven.
- [DONE] The backend already has a canonical `policy` section in `backend/config/app.yaml`.
- [DONE] Startup already injects a concrete `policy_service` into the live backend runtime.
- [DONE] The LLM, memory, tool, orchestration, and agent slices already have baseline policy-denial coverage.

**Current limitations that later phases must fix**

- The public policy decision model is too coarse.
- The runtime package is too small and still partially LLM-owned.
- Session/API/observability policy domains are not yet first-class.
- There is no policy audit, cache, health, or capabilities surface.
- There is no dedicated `backend/tests/unit/policy/` suite.

**Exit criteria**

- [DONE] The plan starts from the real backend baseline under `backend/` and avoids any path drift outside that tree.

### [DONE] Phase 1. Policy Contracts, Decisions, and Typed Settings

**Goal**

Deepen the public policy contract and configuration surface so later runtime work can rely on typed settings, normalized requests, and explicit decision semantics rather than ad hoc booleans.

**Files to create or update**

- [DONE] `backend/app/contracts/policy.py`
- [DONE] `backend/app/policy/models.py`
- [DONE] `backend/app/policy/decisions.py`
- [DONE] `backend/app/policy/context.py`
- [DONE] `backend/app/policy/settings.py`
- [DONE] `backend/app/policy/errors.py`
- [DONE] `backend/app/testing/fakes/fake_policy.py`
- [DONE] `backend/app/config/schemas.py`
- [DONE] `backend/app/config/validation.py`
- [DONE] `backend/app/config/view.py`
- [DONE] `backend/config/app.yaml`
- [DONE] `backend/tests/unit/policy/test_policy_contracts.py`
- [DONE] `backend/tests/unit/config/test_config_view.py`
- [DONE] `backend/tests/unit/config/test_validation.py`
- [DONE] `backend/tests/fixtures/config/policy_default_deny.yaml`
- [DONE] `backend/tests/fixtures/config/policy_usecase_allowed.yaml`
- [DONE] `backend/tests/fixtures/config/policy_invalid_unknown_reference.yaml`
- [DONE] `backend/tests/fixtures/config/policy_invalid_raw_trace.yaml`
- [DONE] `backend/tests/fixtures/config/policy_invalid_write_tool_without_approval.yaml`

**Implementation tasks**

- [DONE] Expand `backend/app/contracts/policy.py` to introduce additive, provider-neutral policy models such as:
  - `PolicyActor`
  - `PolicyScope`
  - `PolicyEvaluationContext`
  - normalized `PolicyDecisionValue`
  - `PolicyObligation`
  - richer `PolicyDecision`
- [DONE] Keep the existing contract usable during migration so current orchestration and gateway call sites do not need a flag-day rewrite.
- [DONE] Add typed settings models under `backend/app/policy/settings.py` and `backend/app/config/view.py` for:
  - root policy enablement and mode
  - default decision and fail-closed behavior
  - use-case, strategy, and agent policy sections
  - LLM policy
  - memory read/write policy
  - logical tool and approval policy
  - fallback policy
  - trace and stream exposure policy
  - capability and health exposure policy
  - audit and decision-cache policy
- [DONE] Deepen `backend/app/config/schemas.py` and `backend/app/config/validation.py` so startup rejects invalid policy references, unsafe raw exposure settings, inconsistent approval rules, and memory-write configurations that do not satisfy scope rules.
- [DONE] Expand `backend/config/app.yaml` into the canonical source of truth for all V1 backend policy defaults while keeping every path rooted under `backend/`.
- [DONE] Deepen `backend/app/testing/fakes/fake_policy.py` so it can exercise additive decision kinds, reason codes, obligations, and approval-required flows.

**Validation**

- [DONE] Add and pass focused unit tests for the normalized policy contract and typed policy settings.
- [DONE] Run from `backend/`:
  - [DONE] `.venv\Scripts\python.exe -m pytest tests/unit/policy/test_policy_contracts.py tests/unit/config/test_config_view.py tests/unit/config/test_validation.py`
  - [DONE] `.venv\Scripts\python.exe -m ruff check app/contracts/policy.py app/policy app/config tests/unit/policy/test_policy_contracts.py tests/unit/config/test_config_view.py tests/unit/config/test_validation.py`
  - [DONE] `.venv\Scripts\python.exe -m mypy app/contracts/policy.py app/policy app/config`

**Exit criteria**

- [DONE] Policy requests and decisions are normalized enough to support all architecture domains.
- [DONE] Invalid policy fixtures fail fast at startup.
- [DONE] The canonical policy configuration surface lives fully under `backend/`.

### [DONE] Phase 2. Policy Engine, Evaluators, and Policy-Owned Composition Root

**Goal**

Turn the existing narrow service into a proper backend policy runtime with explicit evaluators, deterministic precedence rules, and policy-owned startup assembly.

**Files to create or update**

- `backend/app/policy/service.py`
- [DONE] `backend/app/policy/engine.py`
- [DONE] `backend/app/policy/registry.py`
- [DONE] `backend/app/policy/rule.py`
- [DONE] `backend/app/policy/rule_loader.py`
- [DONE] `backend/app/policy/rule_matcher.py`
- [DONE] `backend/app/policy/rule_evaluator.py`
- [DONE] `backend/app/policy/factory.py`
- [DONE] `backend/app/policy/usecase_policy.py`
- [DONE] `backend/app/policy/strategy_policy.py`
- [DONE] `backend/app/policy/agent_policy.py`
- `backend/app/config/bootstrap.py`
- `backend/app/llm/factory.py`
- `backend/app/foundation/container.py`
- `backend/app/testing/fakes/fake_policy.py`
- [DONE] `backend/tests/unit/policy/test_policy_engine.py`
- [DONE] `backend/tests/unit/policy/test_policy_rule_matcher.py`
- [DONE] `backend/tests/unit/policy/test_policy_factory.py`

**Implementation tasks**

- [DONE] Add a policy-owned runtime bundle builder under `backend/app/policy/factory.py`.
- [DONE] Move policy construction out of `backend/app/llm/factory.py` so LLM runtime consumes an injected `PolicyService` rather than owning it.
- [DONE] Implement deterministic evaluation precedence in the engine:
  - explicit deny
  - approval required
  - explicit allow
  - default deny
- [DONE] Split evaluator responsibilities into domain modules so the policy service does not remain one long conditional block.
- [DONE] Keep the public `PolicyService` facade narrow and stable while allowing the implementation to grow behind it.
- [DONE] Keep startup import-safe and build policy during backend composition in `backend/app/config/bootstrap.py`.
- [DONE] Preserve the current backend runtime path while migrating existing gateway/orchestration policy checks to the new engine.

**Validation**

- [DONE] Add and pass focused engine and factory tests.
- Run from `backend/`:
  - [DONE] `.venv\Scripts\python.exe -m pytest tests/unit/policy/test_policy_engine.py tests/unit/policy/test_policy_rule_matcher.py tests/unit/policy/test_policy_factory.py tests/unit/orchestration/test_strategy_policy.py tests/unit/agents/test_agent_policy_denial.py`
  - [DONE] `.venv\Scripts\python.exe -m ruff check app/policy app/config/bootstrap.py app/llm/factory.py app/foundation/container.py tests/unit/policy`
  - [DONE] `.venv\Scripts\python.exe -m mypy app/policy app/config/bootstrap.py app/llm/factory.py app/foundation/container.py`

**Exit criteria**

- [DONE] Policy is assembled from `backend/app/policy/` rather than being LLM-owned.
- [DONE] Domain evaluators and precedence rules are explicit and independently testable.
- [DONE] Current policy-aware runtime behavior remains intact during the migration.

### [DONE] Phase 3. Session, Use-Case, Strategy, and Agent Policy Integration

**Goal**

Make API/session/runtime/strategy/agent policy checks first-class and typed, without weakening the gateway final-enforcement boundary.

**Files to create or update**

- [DONE] `backend/app/policy/session_policy.py`
- [DONE] `backend/app/policy/usecase_policy.py`
- [DONE] `backend/app/policy/strategy_policy.py`
- [DONE] `backend/app/policy/agent_policy.py`
- [DONE] `backend/app/session/service.py`
- [DONE] `backend/app/session/history.py`
- [DONE] `backend/app/api/routes_sessions.py`
- [DONE] `backend/app/api/routes_capabilities.py`
- [DONE] `backend/app/api/routes_health.py`
- [DONE] `backend/app/orchestration/runtime.py`
- [DONE] `backend/app/orchestration/strategies/router.py`
- [DONE] `backend/app/orchestration/strategies/direct_agent.py`
- [DONE] `backend/app/orchestration/strategy_steps.py`
- [DONE] `backend/tests/unit/policy/test_session_policy.py`
- [DONE] `backend/tests/unit/policy/test_usecase_policy.py`
- [DONE] `backend/tests/unit/policy/test_strategy_policy.py`
- [DONE] `backend/tests/unit/policy/test_agent_policy.py`
- [DONE] `backend/tests/integration/policy/test_session_reset_policy.py`
- [DONE] `backend/tests/integration/policy/test_runtime_usecase_denied.py`
- [DONE] `backend/tests/integration/policy/test_router_strategy_filtering.py`

**Implementation tasks**

- [DONE] Add explicit session-domain evaluation for session access, reset, and history retrieval under `backend/app/session/` rather than in route handlers.
- [DONE] Upgrade orchestration runtime checks to use typed use-case and strategy policy requests with normalized reason codes.
- [DONE] Ensure router candidate filtering is policy-driven and cannot silently select denied strategies.
- [DONE] Add typed agent-policy checks for agent invocation and capability use while preserving the existing `OrchestrationContext` boundary.
- [DONE] Keep API routes thin: they may consult policy only for direct route/access visibility concerns, but they should still delegate session operations to `SessionService`.
- [DONE] Ensure policy denials do not trigger bypass paths such as alternate agents, direct provider calls, or tool execution outside the strategy/gateway path.

**Validation**

- [DONE] Add and pass focused session/runtime/agent policy tests.
- Run from `backend/`:
  - [DONE] `.venv\Scripts\python.exe -m pytest tests/unit/policy/test_session_policy.py tests/unit/policy/test_usecase_policy.py tests/unit/policy/test_agent_policy.py tests/unit/orchestration/test_strategy_policy.py tests/unit/orchestration/test_strategy_policy_denial.py tests/unit/agents/test_base_llm_agent.py tests/unit/session/test_session_reset.py tests/unit/session/test_session_history.py tests/integration/policy/test_session_reset_policy.py`
  - [DONE] `.venv\Scripts\python.exe -m ruff check app/policy app/session app/orchestration app/agents tests/unit/policy tests/integration/policy tests/unit/session tests/unit/agents/test_base_llm_agent.py tests/unit/orchestration/test_strategy_policy.py tests/unit/orchestration/test_strategy_policy_denial.py`
  - [DONE] `.venv\Scripts\python.exe -m mypy app/policy app/session app/orchestration app/agents`

**Exit criteria**

- [DONE] Session access and reset are policy-aware.
- [DONE] Runtime route resolution and router candidate selection are policy-governed.
- [DONE] Agent invocation respects typed policy checks without bypassing gateway enforcement.

### [DONE] Phase 4. LLM, Memory, Tool, and Approval Policy Hardening

**Goal**

Replace the current narrow, metadata-heavy gateway checks with typed, domain-specific policy enforcement for LLM, memory, tool, and approval behavior.

**Files to create or update**

- [DONE] `backend/app/policy/llm_policy.py`
- [DONE] `backend/app/policy/memory_policy.py`
- [DONE] `backend/app/policy/tool_policy.py`
- [DONE] `backend/app/policy/approval_policy.py`
- [DONE] `backend/app/llm/gateway.py`
- [DONE] `backend/app/memory/gateway.py`
- [DONE] `backend/app/tools/gateway.py`
- [DONE] `backend/app/orchestration/tool_intents.py`
- [DONE] `backend/app/orchestration/memory_intents.py`
- [DONE] `backend/app/api/errors.py`
- [DONE] `backend/tests/unit/policy/test_llm_policy.py`
- [DONE] `backend/tests/unit/policy/test_memory_policy.py`
- [DONE] `backend/tests/unit/policy/test_tool_policy.py`
- [DONE] `backend/tests/unit/policy/test_approval_policy.py`
- [DONE] `backend/tests/integration/policy/test_llm_profile_denied.py`
- [DONE] `backend/tests/integration/policy/test_tool_approval_required.py`

**Implementation tasks**

- [DONE] Add explicit LLM policy evaluators for profile access, streaming permission, input/output budget checks, and fallback-profile authorization.
- [DONE] Add explicit memory read/write evaluators for scope ownership, project/global boundaries, explicit intent requirements, sensitive-memory defaults, and per-turn write limits.
- [DONE] Add explicit logical-tool evaluators for list/get/execute/stream actions, risk levels, approval rules, and safe obligations such as result truncation or idempotency requirements.
- [DONE] Ensure raw MCP tool names stay denied outside the tool-adapter boundary.
- [DONE] Return normalized `approval_required` decisions for risky operations without executing those operations.
- [DONE] Keep the gateways as the final enforcement boundary immediately before provider, memory-adapter, or MCP execution.
- [DONE] Preserve the existing gateway/unit coverage while migrating to typed requests and normalized reason codes.

**Validation**

- [DONE] Add and pass focused gateway-policy tests plus adjacent regression suites.
- Run from `backend/`:
  - [DONE] `.venv\Scripts\python.exe -m pytest tests/unit/policy/test_llm_policy.py tests/unit/policy/test_memory_policy.py tests/unit/policy/test_tool_policy.py tests/unit/policy/test_approval_policy.py tests/unit/llm/test_gateway_policy.py tests/unit/memory/test_policy_integration.py tests/unit/tools/test_tools_gateway_policy_rules.py tests/unit/api/test_error_mapping.py tests/integration/llm/test_gateway_policy_denied.py tests/integration/policy/test_llm_profile_denied.py tests/integration/policy/test_tool_approval_required.py`
  - `.venv\Scripts\python.exe -m ruff check app/policy app/llm app/memory app/tools app/api/errors.py tests/unit/policy tests/unit/llm/test_gateway_policy.py tests/unit/memory/test_policy_integration.py tests/unit/tools/test_tools_gateway_policy_rules.py tests/unit/api/test_error_mapping.py tests/integration/policy tests/integration/llm/test_gateway_policy_denied.py`
  - `.venv\Scripts\python.exe -m mypy app/policy app/llm app/memory app/tools app/api/errors.py`

**Exit criteria**

- [DONE] LLM, memory, and tool final enforcement uses typed policy evaluators.
- [DONE] Unknown or unsafe resources are denied by default.
- [DONE] Approval-required operations stop before any side effect is executed.

### [DONE] Phase 5. Fallback, Trace, Stream, Redaction, Capability, and Health Policy

**Goal**

Centralize safe-output and safe-exposure rules so orchestration fallback, observability, SSE, health, and capabilities all respect the same backend policy layer.

**Files to create or update**

- [DONE] `backend/app/policy/fallback_policy.py`
- [DONE] `backend/app/policy/trace_policy.py`
- [DONE] `backend/app/policy/stream_policy.py`
- [DONE] `backend/app/policy/redaction_policy.py`
- [DONE] `backend/app/policy/capabilities.py`
- [DONE] `backend/app/policy/health.py`
- [DONE] `backend/app/orchestration/fallback.py`
- [DONE] `backend/app/observability/tracing.py`
- [DONE] `backend/app/observability/redaction.py`
- [DONE] `backend/app/observability/events.py`
- [DONE] `backend/app/api/sse.py`
- [DONE] `backend/app/api/routes_capabilities.py`
- [DONE] `backend/app/api/routes_health.py`
- [DONE] `backend/app/api/errors.py`
- [DONE] `backend/tests/unit/policy/test_fallback_policy.py`
- [DONE] `backend/tests/unit/policy/test_trace_policy.py`
- [DONE] `backend/tests/unit/policy/test_stream_policy.py`
- [DONE] `backend/tests/unit/policy/test_redaction_policy.py`
- [DONE] `backend/tests/unit/policy/test_capability_exposure_policy.py`
- [DONE] `backend/tests/unit/policy/test_health_exposure_policy.py`
- [DONE] `backend/tests/integration/policy/test_trace_payload_policy.py`
- [DONE] `backend/tests/integration/policy/test_stream_payload_policy.py`
- [DONE] `backend/tests/integration/policy/test_capabilities_exposure_policy.py`

**Implementation tasks**

- [DONE] Add fallback-policy evaluation that denies fallback after policy denial and after possible side-effect execution unless the architecture explicitly allows a safe degraded path.
- [DONE] Add trace-policy and stream-policy checks so raw prompts, completions, provider chunks, tool payloads, memory records, stack traces, and hidden scratchpads stay denied by default.
- [DONE] Integrate redaction as an obligation layer after category policy, not as a substitute for allow/deny decisions.
- [DONE] Add capability and health exposure policy so frontend-facing responses remain low detail, secret-safe, and consistent with the architecture's data-exposure rules.
- [DONE] Ensure workflow-state summaries, error payloads, and SSE messages remain safe-summary-only unless policy explicitly allows more detail.

**Validation**

- [DONE] Add and pass focused observability and SSE policy tests.
- Run from `backend/`:
  - [DONE] `.venv\Scripts\python.exe -m pytest tests/unit/policy/test_fallback_policy.py tests/unit/policy/test_trace_policy.py tests/unit/policy/test_stream_policy.py tests/unit/policy/test_redaction_policy.py tests/unit/policy/test_capability_exposure_policy.py tests/unit/policy/test_health_exposure_policy.py tests/unit/api/test_sse_formatting.py tests/unit/orchestration/test_fallback_policy_behavior.py tests/integration/policy/test_trace_payload_policy.py tests/integration/policy/test_stream_payload_policy.py tests/integration/policy/test_capabilities_exposure_policy.py`
  - [DONE] `.venv\Scripts\python.exe -m ruff check app/policy app/observability app/api app/orchestration tests/unit/policy tests/integration/policy`
  - [DONE] `.venv\Scripts\python.exe -m mypy app/policy app/observability app/api app/orchestration`

**Exit criteria**

- [DONE] Fallback behavior cannot weaken policy denial.
- [DONE] Traces and SSE payloads are policy-filtered and redacted by default.
- [DONE] Health and capabilities expose only frontend-safe policy-governed details.

### [DONE] Phase 6. Audit, Decision Cache, Quality Gates, and Freeze

**Goal**

Finish the backend policy layer with safe auditability, low-risk decision caching, dedicated test surfaces, import-boundary enforcement, and full-backend freeze validation.

**Files to create or update**

- [DONE] `backend/app/policy/audit.py`
- [DONE] `backend/app/policy/decision_cache.py`
- [DONE] `backend/app/policy/service.py`
- [DONE] `backend/app/config/bootstrap.py`
- [DONE] `backend/app/foundation/health.py`
- [DONE] `backend/app/foundation/capabilities.py`
- [DONE] `backend/app/testing/fakes/fake_policy.py`
- [DONE] `backend/tests/unit/policy/test_policy_audit.py`
- [DONE] `backend/tests/unit/policy/test_decision_cache.py`
- [DONE] `backend/tests/unit/policy/test_import_boundaries.py`
- [DONE] `backend/tests/integration/policy/test_startup_policy.py`
- [DONE] `backend/tests/fixtures/config/policy_default_deny.yaml`
- [DONE] `backend/tests/fixtures/config/policy_tools_approval_required.yaml`
- [DONE] `backend/tests/fixtures/config/policy_memory_write_safe.yaml`
- [DONE] `backend/tests/fixtures/config/policy_trace_safe_summary_only.yaml`
- [DONE] `backend/tests/fixtures/config/policy_stream_safe_summary_only.yaml`
- [DONE] `backend/README.md`
- [DONE] `docs/backend-policy-plan.md`

**Implementation tasks**

- [DONE] Add a per-turn decision cache that never stores raw payloads, secrets, or high-cardinality keys.
- [DONE] Add a safe audit recorder that writes only bounded decision summaries and safe tags.
- [DONE] Add policy-owned metrics with low-cardinality labels only.
- [DONE] Add import-boundary tests to ensure `backend/app/policy/` does not depend on provider SDKs, MCP clients, SQLite clients, ArcadeDB clients, `memory_store`, concrete strategy implementations, concrete agent plugins, or frontend DTOs.
- [DONE] Ensure startup builds policy before LLM, memory, tool, orchestration, API health, and API capabilities consumers.
- [DONE] Document the frozen policy boundary and handoff to the deployment-readiness phase in `backend/README.md`.

**Validation**

- [DONE] Add and pass dedicated policy unit and integration suites plus full backend quality gates.
- Run from `backend/`:
  - [DONE] `.venv\Scripts\python.exe -m pytest tests/unit/policy tests/integration/policy tests/unit/test_health.py tests/unit/test_capabilities.py tests/unit/test_app_factory.py`
  - [DONE] `.venv\Scripts\python.exe -m ruff check .`
  - [DONE] `.venv\Scripts\python.exe -m mypy app`

**Exit criteria**

- [DONE] Policy audit events contain only safe summaries.
- [DONE] Policy caching is safe and bounded.
- [DONE] Import boundaries prevent policy from reaching forbidden concrete dependencies.
- [DONE] The full backend validation gate passes from `backend/`.
- [DONE] The policy layer is ready to hand off to deployment-readiness work under `docs/backend-deployment-architecture.md`.

---

## 6. Sequencing Notes

- Do not begin Phase 3 until Phase 1 and Phase 2 have stabilized the policy contract and startup wiring.
- Do not widen gateway behavior in Phase 4 until typed policy settings and evaluator registration are in place.
- Do not attempt approval workflow execution in this phase. V1 policy hardening stops at `approval_required` decisions and safe pending-approval summaries.
- Keep compatibility shims small and temporary. If `backend/app/contracts/policy.py` grows additive fields, the old narrow call sites should migrate incrementally and then converge on the normalized request/decision surface.
- Prefer extending the current fake policy entrypoint at `backend/app/testing/fakes/fake_policy.py` over creating multiple competing fake-policy modules unless the split clearly reduces coupling.

---

## 7. Definition of Done

This plan is complete when all of the following are true:

- The backend policy layer remains fully rooted under `backend/`.
- `backend/app/contracts/policy.py` exposes a stable provider-neutral contract surface.
- `backend/app/policy/` owns the concrete runtime, settings, engine, evaluators, audit, and cache behavior.
- Unknown use cases, strategies, agents, LLM profiles, memory scopes, memory writes, and logical tools are denied by default.
- `backend/app/session/`, `backend/app/orchestration/`, `backend/app/llm/`, `backend/app/memory/`, `backend/app/tools/`, and `backend/app/observability/` all consume policy without bypassing their existing boundaries.
- Gateway final enforcement is preserved for provider, memory, and tool execution.
- Trace, stream, capability, and health exposure remain safe-summary-first and policy-governed.
- Approval-required actions stop before side effects.
- Policy audit and cache surfaces never retain raw payloads or secrets.
- Dedicated policy fixtures and test suites exist under `backend/tests/`.
- Full backend validation passes from `backend/`.
