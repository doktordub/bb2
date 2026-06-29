# Backend Orchestration Implementation Plan

**Document:** `backend-orchestration-plan.md`  
**Version:** 1.0  
**Source alignment:** `backend-orchestration-architecture.md`, `backend-session-service-plan.md`, `backend-llm-gateway-plan.md`, `backend-memory-store-adapter-plan.md`, `backend-tooling-mcp-client-plan.md`, and the current backend implementation baseline  
**Repository rule:** all backend application code lives under `backend/`

---

## 1. Purpose

This plan converts the orchestration architecture into an implementation sequence that can be delivered in small, low-risk phases.

The plan is intentionally strict about repository boundaries:

- Backend application code belongs in `backend/`.
- Backend source modules belong in `backend/app/`.
- Backend tests belong in `backend/tests/`.
- Backend configuration files belong in `backend/config/`.
- Backend local data files belong in `backend/data/`.
- Documentation updates belong in `docs/`.
- No backend orchestration, strategy, session-runtime, or gateway code should be placed in the repository root, `frontend/`, or `mcp/`.

For clarity, this document uses filesystem paths such as `backend/app/orchestration/runtime.py`. Python imports may still use the `app.*` package path because `backend/` is the Python project root.

---

## 2. Review Outcomes

The orchestration architecture document is implementation-ready and strong on boundary rules, provider neutrality, streaming safety, trace correlation, and the intended sequencing between session, LLM, memory, tooling, and later agent work.

The review also confirms that this phase is not greenfield work. The repository already contains a meaningful orchestration slice under `backend/` that should be deepened rather than replaced:

- `backend/app/orchestration/core.py` already defines a narrow `OrchestrationRuntime` protocol plus `EchoOrchestrationRuntime` and `DirectAgentOrchestrationRuntime`.
- `backend/app/testing/fakes/fake_orchestration_runtime.py` already provides a deterministic fake runtime used by session tests.
- `backend/app/session/service.py` already delegates both non-streaming and streaming chat behavior to an orchestration runtime boundary.
- `backend/app/config/bootstrap.py` already wires `DirectAgentOrchestrationRuntime` into `DefaultSessionService` during lifespan startup.
- `backend/tests/unit/orchestration/test_tooling_integration.py` already proves that the current direct runtime can execute tool calls through the real `ToolGateway` path.
- `backend/app/config/schemas.py` and `backend/app/config/validation.py` already validate top-level `usecases`, `strategies`, and `agents` definitions that the runtime depends on today.
- `backend/app/foundation/capabilities.py` already exposes enabled use cases to the API capability surface, albeit directly from configuration instead of through an orchestration-owned capability boundary.

The main implementation concerns that must be resolved during execution are:

1. **A dedicated orchestration settings surface does not exist yet.**  
   The current runtime depends on `app.active_usecase` plus top-level `usecases`, `strategies`, and `agents` sections. The architecture expects a canonical top-level `orchestration.*` section with typed defaults, strategy settings, use-case settings, limits, and safe debug toggles.

2. **The runtime interface and data ownership are still too thin.**  
   `backend/app/orchestration/core.py` exposes only `run` and `stream` over generic `RequestContext` and `WorkflowStateDocument`. The architecture requires orchestration-owned request/context/result models, `WorkflowStateDelta`, safe stream events, and public `health()` / `capabilities()` methods.

3. **`core.py` currently mixes too many responsibilities.**  
   Route resolution, configured agent loading, orchestration-context construction, streaming request assembly, and disabled-tool fallback behavior all live in one module instead of the planned split across runtime, registry, strategy, routing, events, limits, and helper modules under `backend/app/orchestration/`.

4. **The current orchestration context boundary is too permissive.**  
   `DirectAgentOrchestrationRuntime` currently injects workflow-state and trace-store interfaces into the orchestration context. The architecture instead calls for a safe workflow-state snapshot in, a safe state delta out, and trace emission through an observability facade rather than direct trace-store access.

5. **Streaming and non-streaming behavior diverge today.**  
   The current `run(...)` path delegates to `agent.run(context)`, while the current `stream(...)` path assembles its own `LLMRequest` and calls `LLMGateway.stream(...)` directly. The architecture requires both paths to flow through the same strategy/agent boundary so behavior does not drift between chat and streaming.

6. **Strategy ownership is not explicit yet.**  
   There is no `OrchestrationStrategy`, `StrategyRegistry`, `UseCaseRouter`, or built-in `backend/app/orchestration/strategies/` package. The current runtime hard-codes one direct-agent flow rather than resolving strategy behavior through a stable registry.

7. **Health and capabilities do not yet belong to orchestration.**  
   Foundation capabilities currently derive use cases directly from raw configuration, and foundation health has no orchestration-specific readiness component. The architecture requires safe orchestration-owned health and capability summaries.

8. **The orchestration-specific test and fixture surface is still too small.**  
   The repository currently has only a narrow unit slice for orchestration. Dedicated `backend/tests/unit/orchestration/`, `backend/tests/integration/orchestration/`, and orchestration-specific configuration fixtures are still missing for the broader runtime, registry, streaming, and state-delta behavior described by the architecture.

9. **The architecture document has one sequencing ambiguity to resolve during freeze.**  
   Section 3 points next to `backend-workflow-strategies-architecture.md`, while the acceptance criteria mention `backend-agents-architecture.md`. This plan assumes workflow strategies are the immediate follow-on because the architecture sequence places strategy implementations before deeper agent-plugin work.

---

## 3. Non-Negotiable Boundary Rules

- Treat `backend/` as the Python project root for all orchestration work.
- Create orchestration runtime modules only under `backend/app/orchestration/`.
- Keep backend test code under `backend/tests/`.
- Keep backend configuration under `backend/config/` and backend-local data under `backend/data/`.
- Keep documentation-only artifacts under `docs/`.
- Do not place backend orchestration, strategy, session-runtime, or gateway code in the repository root, `frontend/`, or `mcp/`.
- Do not let `backend/app/orchestration/` import `backend/app/api/`, `sqlite3`, `aiosqlite`, `backend/app/persistence/sqlite_*`, `memory_store.service.MemoryService`, ArcadeDB clients, `backend/app/tools/mcp/`, or provider SDKs.
- Do not let the orchestration runtime or strategies persist workflow state directly. Only `SessionService` may save or reset workflow state through `WorkflowStateStore`.
- Do not let the orchestration runtime or strategies write directly to `TraceStore`. Safe trace/event recording must go through the observability facade or recorder layer.
- Do not let `backend/app/orchestration/` import FastAPI request/response types, route modules, or API DTOs.
- Keep the API routes thin and preserve the current HTTP and SSE contracts while orchestration internals change underneath them.
- If compatibility shims are needed during the refactor, keep them under `backend/app/orchestration/` and remove or freeze them before phase close.
- Add only the minimal configured-agent loading boundary needed for orchestration. A broader `backend/app/agents/` package and agent-plugin catalog remain the responsibility of the later agent architecture phase.

---

## 4. Phase Overview

| Phase | Name | Primary Outcome |
|---|---|---|
| 0 | [DONE] Current Orchestration Walking Skeleton Baseline | The repository already has a working session -> orchestration -> gateway vertical slice rooted under `backend/`. |
| 1 | [DONE] Orchestration Configuration and Settings Alignment | Canonical typed orchestration settings live under `backend/app/config/` and are sourced from `backend/config/app.yaml`. |
| 2 | Orchestration DTOs, Events, Errors, and State Delta | Orchestration-owned request/result/event/error models exist under `backend/app/orchestration/` and no longer depend on generic contract placeholders alone. |
| 3 | [DONE] Strategy Contract, Registry, Routing, and Minimal Agent Loader | Strategy resolution becomes explicit through registry and use-case routing instead of hard-coded logic in `core.py`. |
| 4 | [DONE] Default Runtime Split and Safe Runtime Core | A modular `DefaultOrchestrationRuntime` exposes `run_turn`, `stream_turn`, `health`, and `capabilities` without writing persistence directly. |
| 5 | [DONE] Direct Agent Strategy Migration | The current direct-agent behavior moves out of the runtime and into a consistent direct strategy for both chat and streaming. |
| 6 | [DONE] Retrieval, Tool-Assisted, and Router Strategies with Limits | Built-in V1 strategies, loop guards, and cancellation-safe runtime limits are implemented under `backend/app/orchestration/strategies/`. |
| 7 | [DONE] Health, Capabilities, and Composition Root Integration | Orchestration contributes safe readiness and capability metadata through foundation startup, health, and capability services. |
| 8 | [DONE] Session-Service State-Delta Integration | `SessionService` calls the new orchestration interface and persists returned state deltas while API behavior stays unchanged. |
| 9 | [DONE] Fakes, Fixtures, Quality Gates, and Freeze | The stable orchestration boundary is documented and verified before the workflow-strategy and agent follow-on phases. |

---

## 5. Detailed Implementation Phases

### [DONE] Phase 0. Current Orchestration Walking Skeleton Baseline

**Goal**

Record the orchestration-related work that already exists so the implementation plan extends the current backend instead of re-describing a greenfield slice.

**Files already present**

- [DONE] `backend/app/orchestration/core.py`
- [DONE] `backend/app/orchestration/__init__.py`
- [DONE] `backend/app/testing/fakes/fake_orchestration_runtime.py`
- [DONE] `backend/app/config/bootstrap.py`
- [DONE] `backend/app/session/service.py`
- [DONE] `backend/tests/unit/orchestration/test_tooling_integration.py`

**Implementation outcomes already in place**

- [DONE] The session layer already delegates chat and streaming behavior to an orchestration runtime boundary.
- [DONE] Lifespan startup already wires a real orchestration runtime into `DefaultSessionService` under `backend/app/config/bootstrap.py`.
- [DONE] The current direct runtime already loads configured agents from validated backend configuration.
- [DONE] The current direct runtime already passes LLM, memory, policy, trace, and tool interfaces into an orchestration context.
- [DONE] The current tooling integration test already proves the runtime can reach the real `ToolGateway` path instead of keeping orchestration purely fake.
- [DONE] Deterministic fake orchestration behavior already exists for unit tests under `backend/app/testing/fakes/`.

**Current limitations that the next phases must fix**

- The current orchestration config surface is spread across `app.active_usecase`, top-level `usecases`, top-level `strategies`, and `agents` instead of a canonical `orchestration.*` section.
- The runtime protocol still exposes `run` and `stream` instead of `run_turn`, `stream_turn`, `health`, and `capabilities`.
- The current runtime still mixes routing, agent loading, context construction, streaming assembly, and disabled-tool behavior in `backend/app/orchestration/core.py`.
- The current runtime does not return `WorkflowStateDelta`; state application still happens entirely in the session layer from an answer/result shape.
- The current runtime passes workflow-state and trace-store interfaces into orchestration context rather than a safe state snapshot and observability recorder boundary.
- The current streaming path bypasses the direct agent path and calls `LLMGateway.stream(...)` directly.
- There is no dedicated orchestration strategy registry or built-in strategy package yet.

**Exit criteria**

- [DONE] The implementation plan starts from the real `backend/` baseline and extends it rather than replacing it.

### [DONE] Phase 1. Orchestration Configuration and Settings Alignment

**Goal**

Introduce a canonical top-level `orchestration` configuration surface and typed orchestration settings without breaking the existing backend startup flow during migration.

**Files to create or update**

- [DONE] `backend/app/config/schemas.py`
- [DONE] `backend/app/config/validation.py`
- [DONE] `backend/app/config/view.py`
- [DONE] `backend/app/orchestration/core.py`
- [DONE] `backend/config/app.yaml`
- [DONE] `backend/tests/unit/config/test_config_view.py`
- [DONE] `backend/tests/unit/config/test_loader_valid_config.py`
- [DONE] `backend/tests/unit/config/test_validation.py`
- [DONE] `backend/tests/unit/orchestration/test_tooling_integration.py`
- [DONE] `backend/tests/fixtures/config/orchestration_basic_direct.yaml`
- [DONE] `backend/tests/fixtures/config/orchestration_streaming_direct.yaml`
- [DONE] `backend/tests/fixtures/config/orchestration_retrieval_augmented.yaml`
- [DONE] `backend/tests/fixtures/config/orchestration_tool_assisted.yaml`
- [DONE] `backend/tests/fixtures/config/orchestration_router.yaml`
- [DONE] `backend/tests/fixtures/config/orchestration_disabled_strategy.yaml`
- [DONE] `backend/tests/fixtures/config/orchestration_unknown_usecase.yaml`
- [DONE] `backend/tests/fixtures/config/orchestration_limits.yaml`
- [DONE] `backend/tests/fixtures/config/orchestration_debug_unsafe_invalid.yaml`

**Implementation tasks**

- [DONE] Add a top-level `orchestration:` section in `backend/config/app.yaml` as the canonical source for:
  - enabled/default/fallback strategy settings
  - turn and stream limits
  - safe event toggles
  - strategy definitions
  - use-case definitions
  - local-only debug flags such as hidden-reasoning exposure guards
- [DONE] Add typed settings dataclasses in `backend/app/config/view.py`, such as:
  - `OrchestrationDefaultsSettings`
  - `StrategySettings`
  - `UseCaseSettings`
  - `OrchestrationSettings`
- [DONE] Add a typed accessor such as `get_orchestration_settings()` so orchestration modules stop reading raw nested config keys directly.
- [DONE] Normalize strategy `type` values to the architecture vocabulary: `echo`, `direct_agent`, `retrieval_augmented`, `tool_assisted`, and `router`.
- [DONE] Keep a bounded compatibility window for existing `app.active_usecase`, top-level `usecases`, and top-level `strategies` readers while migrating runtime and tests to the new canonical `orchestration.*` source.
- [DONE] Validate default/fallback strategy existence, disabled strategy references, positive limits, unsupported strategy types, and unsafe debug settings at config-load time.
- [DONE] Validate memory-enabled and tools-enabled strategy settings against configured backend capabilities so invalid startup combinations fail fast.
- [DONE] Keep all backend-owned config and data references explicit to `backend/config/` and `backend/data/`.

**Validation**

- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m pytest tests/unit/config/test_config_view.py tests/unit/config/test_loader_valid_config.py tests/unit/config/test_validation.py tests/unit/orchestration/test_tooling_integration.py`
- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m ruff check app/config app/orchestration tests/unit/config/test_config_view.py tests/unit/config/test_loader_valid_config.py tests/unit/config/test_validation.py tests/unit/orchestration/test_tooling_integration.py`
- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m mypy app/config app/orchestration`

**Exit criteria**

- [DONE] Typed orchestration settings are available from `backend/app/config/view.py`.
- [DONE] Invalid orchestration config fails fast during backend startup.
- [DONE] Canonical backend YAML and fixture examples reference `orchestration.*` rather than relying on scattered raw config lookups.

### [DONE] Phase 2. Orchestration DTOs, Events, Errors, and State Delta

**Goal**

Make orchestration own its request, runtime-context, result, event, error, and workflow-state-delta models instead of leaning only on generic contract types.

**Files to create or update**

- [DONE] `backend/app/orchestration/models.py`
- [DONE] `backend/app/orchestration/context.py`
- [DONE] `backend/app/orchestration/events.py`
- [DONE] `backend/app/orchestration/errors.py`
- [DONE] `backend/app/orchestration/state_delta.py`
- [DONE] `backend/app/orchestration/result_builder.py`
- [DONE] `backend/app/orchestration/__init__.py`
- [DONE] `backend/app/orchestration/core.py`
- [DONE] `backend/app/session/streaming.py`
- [DONE] `backend/app/testing/fakes/fake_orchestration_runtime.py`
- [DONE] `backend/tests/unit/orchestration/test_models.py`
- [DONE] `backend/tests/unit/orchestration/test_events.py`
- [DONE] `backend/tests/unit/orchestration/test_errors.py`
- [DONE] `backend/tests/unit/orchestration/test_state_delta.py`

**Implementation tasks**

- [DONE] Introduce orchestration-owned models such as:
   - [DONE] `OrchestrationRequest`
   - [DONE] `OrchestrationRuntimeContext`
   - [DONE] `OrchestrationResult`
   - [DONE] `OrchestrationStepSummary`
   - [DONE] `WorkflowStateSnapshot`
   - [DONE] `WorkflowStateDelta`
- [DONE] Introduce orchestration-owned stream events in `backend/app/orchestration/events.py` with a minimal V1 set:
   - [DONE] `orchestration.started`
   - [DONE] `strategy.selected`
   - [DONE] `response.delta`
   - [DONE] `response.completed`
   - [DONE] `orchestration.completed`
   - [DONE] `orchestration.error`
   - [DONE] `orchestration.cancelled`
- [DONE] Introduce normalized orchestration errors with stable error codes, retryability, and safe user-visible messages.
- [DONE] Ensure the new result and event models cannot carry raw provider payloads, raw tool payloads, raw memory records, raw workflow-state documents, credentials, hidden reasoning, or stack traces.
- [DONE] Add focused compatibility adapters only where necessary so the session layer can migrate incrementally off older `backend/app/contracts/context.py` and `backend/app/contracts/results.py` shapes.
- [DONE] Update `backend/app/testing/fakes/fake_orchestration_runtime.py` to record the new request/context inputs and emit orchestration-owned event types.

**Validation**

- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m pytest tests/unit/orchestration/test_models.py tests/unit/orchestration/test_events.py tests/unit/orchestration/test_errors.py tests/unit/orchestration/test_state_delta.py`
- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m ruff check app/orchestration app/testing/fakes/fake_orchestration_runtime.py tests/unit/orchestration`
- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m mypy app/orchestration`

**Exit criteria**

- [DONE] Orchestration-owned DTOs, events, and errors exist under `backend/app/orchestration/`.
- [DONE] The session layer can begin migrating to orchestration-owned request/result/event models without importing API DTOs or provider SDK types.
- [DONE] `WorkflowStateDelta` is available as the stable orchestration-to-session handoff model.

### [DONE] Phase 3. Strategy Contract, Registry, Routing, and Minimal Agent Loader

**Goal**

Make strategy resolution explicit through a registry and use-case router instead of keeping it hard-coded inside one runtime class.

**Files to create or update**

- [DONE] `backend/app/orchestration/strategy.py`
- [DONE] `backend/app/orchestration/strategy_registry.py`
- [DONE] `backend/app/orchestration/usecase_router.py`
- [DONE] `backend/app/orchestration/registry.py`
- [DONE] `backend/app/policy/service.py`
- [DONE] `backend/tests/unit/orchestration/test_strategy_registry.py`
- [DONE] `backend/tests/unit/orchestration/test_usecase_router.py`
- [DONE] `backend/tests/unit/orchestration/test_strategy_policy.py`

**Implementation tasks**

- [DONE] Add an `OrchestrationStrategy` protocol with `run(...)` and `stream(...)` methods.
- [DONE] Add `StrategyRegistry.register(...)`, `resolve(...)`, and `list(...)` with safe descriptor output.
- [DONE] Add a use-case router that resolves use case, strategy, default agent, and LLM profile with conservative fallback order.
- [DONE] Add normalized unknown/disabled use-case and strategy errors.
- [DONE] Add strategy-level policy checks to `backend/app/policy/service.py`, such as denying disabled or unauthorized strategies before execution begins.
- [DONE] Move configured-agent loading out of `backend/app/orchestration/core.py` into a focused loader/registry helper under `backend/app/orchestration/`.
- [DONE] Keep the configured-agent loader intentionally narrow in this phase; do not expand it into a full agent-plugin framework yet.

**Validation**

- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m pytest tests/unit/orchestration/test_strategy_registry.py tests/unit/orchestration/test_usecase_router.py tests/unit/orchestration/test_strategy_policy.py`
- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m ruff check app/orchestration app/policy tests/unit/orchestration`
- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m mypy app/orchestration app/policy`

**Exit criteria**

- [DONE] Strategy resolution goes through `StrategyRegistry` and `UseCaseRouter` instead of hard-coded runtime branching.
- [DONE] Unknown or disabled strategies fail through normalized orchestration errors.
- [DONE] A minimal agent-loading boundary exists without prematurely broadening the agent scope of this phase.

### [DONE] Phase 4. Default Runtime Split and Safe Runtime Core

**Goal**

Split `backend/app/orchestration/core.py` into the architecture-aligned runtime modules and introduce a stable `DefaultOrchestrationRuntime` surface.

**Files to create or update**

- [DONE] `backend/app/orchestration/runtime.py`
- [DONE] `backend/app/orchestration/limits.py`
- [DONE] `backend/app/orchestration/cancellation.py`
- [DONE] `backend/app/orchestration/health.py`
- [DONE] `backend/app/orchestration/capabilities.py`
- [DONE] `backend/app/orchestration/core.py`
- [DONE] `backend/app/orchestration/__init__.py`
- [DONE] `backend/app/observability/tracing.py`
- [DONE] `backend/tests/unit/orchestration/test_runtime.py`
- [DONE] `backend/tests/unit/orchestration/test_runtime_streaming.py`
- [DONE] `backend/tests/unit/orchestration/test_runtime_no_direct_persistence.py`

**Implementation tasks**

- [DONE] Introduce `DefaultOrchestrationRuntime` with:
   - [DONE] `run_turn(...)`
   - [DONE] `stream_turn(...)`
   - [DONE] `health()`
   - [DONE] `capabilities()`
- [DONE] Split the current `core.py` responsibilities into dedicated runtime, limits, cancellation, health, and capabilities modules.
- [DONE] Keep `backend/app/orchestration/core.py` only as a temporary compatibility shim while imports are migrated to the new modules.
- [DONE] Build `OrchestrationContext` from typed request data, runtime context, typed orchestration settings, safe workflow-state snapshot, gateways, policy, observability recorder, and limit tracking.
- [DONE] Stop passing workflow-state store and trace-store interfaces directly into orchestration context.
- [DONE] Emit safe runtime lifecycle events for start, strategy selection, completion, failure, and cancellation.
- [DONE] Build final results through `backend/app/orchestration/result_builder.py` and return `WorkflowStateDelta` instead of mutating or persisting workflow state directly.
- [DONE] Add basic turn and stream counters early so later strategy work can enforce limits consistently.

**Validation**

- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m pytest tests/unit/orchestration/test_runtime.py tests/unit/orchestration/test_runtime_streaming.py tests/unit/orchestration/test_runtime_no_direct_persistence.py`
- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m ruff check app/orchestration app/observability/tracing.py tests/unit/orchestration`
- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m mypy app/orchestration`

**Exit criteria**

- [DONE] `DefaultOrchestrationRuntime` exposes the architecture-required public interface.
- [DONE] The runtime no longer writes persistence directly or hands persistence stores to strategies.
- [DONE] The orchestration package structure matches the intended long-term ownership more closely than the current single-file `core.py` design.

### [DONE] Phase 5. Direct Agent Strategy Migration

**Goal**

Move the current direct-agent behavior out of the runtime and into a dedicated direct strategy with consistent non-streaming and streaming behavior.

**Files to create or update**

- [DONE] `backend/app/orchestration/strategies/__init__.py`
- [DONE] `backend/app/orchestration/strategies/echo.py`
- [DONE] `backend/app/orchestration/strategies/direct_agent.py`
- [DONE] `backend/app/orchestration/strategy_registry.py`
- [DONE] `backend/app/orchestration/runtime.py`
- [DONE] `backend/tests/unit/orchestration/test_direct_agent_strategy.py`
- [DONE] `backend/tests/integration/orchestration/test_direct_runtime_with_fake_llm.py`
- [DONE] `backend/tests/integration/orchestration/test_direct_runtime_streaming.py`

**Implementation tasks**

- [DONE] Move the direct-agent path from `DirectAgentOrchestrationRuntime` into `DirectAgentStrategy`.
- [DONE] Add `EchoStrategy` as the walking-skeleton/local fallback strategy instead of keeping echo behavior only as a special runtime implementation.
- [DONE] Make both chat and streaming direct paths flow through the same strategy/agent boundary so the current `run(...)` versus `stream(...)` divergence disappears.
- [DONE] Resolve LLM profiles from a policy-gated request override when present, then the configured use case / strategy / agent path, and finally the gateway default.
- [DONE] Produce safe step summaries, agent metadata, and finish reasons without exposing raw prompts or provider payloads.
- [DONE] Keep memory and tools disabled by default unless strategy settings explicitly enable them.

**Validation**

- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m pytest tests/unit/orchestration/test_direct_agent_strategy.py tests/integration/orchestration/test_direct_runtime_with_fake_llm.py tests/integration/orchestration/test_direct_runtime_streaming.py`
- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m ruff check app/orchestration tests/unit/orchestration/test_direct_agent_strategy.py tests/integration/orchestration`
- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m mypy app/orchestration`

**Exit criteria**

- [DONE] The current direct response path is implemented as a strategy, not hard-coded runtime logic.
- [DONE] Streaming and non-streaming direct turns are behaviorally aligned.
- [DONE] The direct strategy can run without memory or tools and still stay provider-neutral.

### [DONE] Phase 6. Retrieval, Tool-Assisted, and Router Strategies with Limits

**Goal**

Implement the built-in V1 strategies and the runtime guardrails that keep them bounded, policy-aware, and cancellation-safe.

**Files to create or update**

- [DONE] `backend/app/orchestration/strategies/retrieval_augmented.py`
- [DONE] `backend/app/orchestration/strategies/tool_assisted.py`
- [DONE] `backend/app/orchestration/strategies/router.py`
- [DONE] `backend/app/orchestration/limits.py`
- [DONE] `backend/app/orchestration/cancellation.py` reused as the shared cancellation checkpoint helper for the new strategy loops.
- [DONE] `backend/app/policy/service.py` continued to provide the strategy/tool/LLM gating used by the new strategies without requiring a separate phase-6 code change.
- [DONE] `backend/tests/unit/orchestration/test_retrieval_strategy.py`
- [DONE] `backend/tests/unit/orchestration/test_tool_assisted_strategy.py`
- [DONE] `backend/tests/unit/orchestration/test_router_strategy.py`
- [DONE] `backend/tests/unit/orchestration/test_limits.py`
- [DONE] `backend/tests/unit/orchestration/test_cancellation.py`
- [DONE] `backend/tests/integration/orchestration/test_retrieval_runtime_with_fake_memory.py`
- [DONE] `backend/tests/integration/orchestration/test_tool_runtime_with_fake_tools.py`
- [DONE] `backend/tests/integration/orchestration/test_router_runtime.py`

**Implementation tasks**

- [DONE] Implemented `RetrievalAugmentedStrategy` so it searches through `MemoryGateway`, selects bounded safe context, and synthesizes an answer without exposing raw memory records.
- [DONE] Implemented `ToolAssistedStrategy` so tool use flows through provider-neutral `ToolIntent`, `ToolExecutionRequest`, and `ToolGateway` only.
- [DONE] Implemented `RouterStrategy` as config/rule-based first, with optional LLM classification only when explicitly configured and policy-approved.
- [DONE] Enforced orchestration limits for:
   - [DONE] max steps
   - [DONE] max tool calls
   - [DONE] max memory searches
   - [DONE] max LLM calls
   - [DONE] max turn duration
   - [DONE] max stream duration
- [DONE] Added loop guards so tool-assisted flows cannot repeat identical calls forever or escalate into uncontrolled LLM-tool cycles.
- [DONE] Added cancellation propagation for streaming and long-running gateway calls where supported.
- [DONE] Kept durable memory writes explicit and policy-gated rather than automatic side effects of tool or LLM responses.

**Validation**

- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m pytest tests/unit/orchestration/test_retrieval_strategy.py tests/unit/orchestration/test_tool_assisted_strategy.py tests/unit/orchestration/test_router_strategy.py tests/unit/orchestration/test_limits.py tests/unit/orchestration/test_cancellation.py tests/integration/orchestration/test_retrieval_runtime_with_fake_memory.py tests/integration/orchestration/test_tool_runtime_with_fake_tools.py tests/integration/orchestration/test_router_runtime.py`
- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m ruff check app/orchestration app/policy tests/unit/orchestration tests/integration/orchestration`
- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m mypy app/orchestration app/policy`

**Exit criteria**

- [DONE] The built-in V1 strategies exist under `backend/app/orchestration/strategies/`.
- [DONE] Tool, memory, and routing behavior is bounded by runtime limits and policy checks.
- [DONE] Cancellation and loop-guard behavior are verified through focused tests.

### [DONE] Phase 7. Health, Capabilities, and Composition Root Integration

**Goal**

Make orchestration contribute its own safe readiness and capability metadata through foundation startup rather than leaving that responsibility to raw config readers.

**Files to create or update**

- [DONE] `backend/app/orchestration/health.py`
- [DONE] `backend/app/orchestration/capabilities.py`
- [DONE] `backend/app/config/bootstrap.py`
- [DONE] `backend/app/foundation/container.py`
- [DONE] `backend/app/foundation/capabilities.py`
- [DONE] `backend/app/foundation/health.py`
- [DONE] `backend/tests/unit/orchestration/test_orchestration_health_summary.py`
- [DONE] `backend/tests/unit/orchestration/test_orchestration_capabilities_summary.py`
- [DONE] `backend/tests/integration/test_startup_orchestration.py`

**Implementation tasks**

- [DONE] Add `OrchestrationHealthResult` with safe readiness data such as enabled/default/fallback strategy, registry readiness, and configured strategy counts.
- [DONE] Add `OrchestrationCapabilitiesResult` with safe use-case and strategy descriptors for API-facing capability aggregation.
- [DONE] Update `backend/app/config/bootstrap.py` so startup constructs strategy registry, strategies, and `DefaultOrchestrationRuntime` explicitly rather than instantiating one direct runtime class only.
- [DONE] Update `backend/app/foundation/container.py` if needed so the runtime is available for startup diagnostics and test wiring.
- [DONE] Update `backend/app/foundation/capabilities.py` to consume orchestration-owned capability data instead of deriving use cases directly from raw config.
- [DONE] Update `backend/app/foundation/health.py` so the backend health payload includes an orchestration component.
- [DONE] Emit a redacted orchestration startup summary that reports safe counts and enabled/default/fallback strategy names without exposing prompts, endpoints, credentials, or database paths.

**Validation**

- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m pytest tests/unit/orchestration/test_orchestration_health_summary.py tests/unit/orchestration/test_orchestration_capabilities_summary.py tests/integration/test_startup_orchestration.py tests/unit/test_capabilities.py tests/unit/test_health.py`
- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m ruff check app/orchestration app/config/bootstrap.py app/foundation tests/unit/orchestration tests/integration/test_startup_orchestration.py tests/unit/test_capabilities.py tests/unit/test_health.py`
- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m mypy app/orchestration app/config/bootstrap.py app/foundation`

**Exit criteria**

- [DONE] Orchestration readiness appears in backend health without leaking unsafe details.
- [DONE] Safe orchestration capabilities reach the API capability surface through the orchestration boundary instead of raw config shortcuts.
- [DONE] Startup wiring follows the architecture sequence closely enough to support later workflow-strategy and agent phases.

### [DONE] Phase 8. Session-Service State-Delta Integration

**Goal**

Migrate `SessionService` to the new orchestration interface while keeping session ownership of persistence, reset, history, and API-facing contracts intact.

**Files to create or update**

- [DONE] `backend/app/session/service.py`
- [DONE] `backend/app/session/lifecycle.py`
- [DONE] `backend/app/session/streaming.py`
- [DONE] `backend/app/session/mapping.py`
- [DONE] `backend/app/testing/fakes/fake_orchestration_runtime.py`
- [DONE] `backend/tests/unit/session/test_session_handle_chat.py`
- [DONE] `backend/tests/unit/session/test_session_stream_chat.py`
- [DONE] `backend/tests/integration/session/test_session_with_sqlite_workflow_state_store.py`
- [DONE] `backend/tests/integration/session/test_session_streaming_finalization.py`
- [DONE] `backend/tests/integration/test_api_walking_skeleton.py`

**Implementation tasks**

- [DONE] Build `OrchestrationRequest` and `OrchestrationRuntimeContext` from session request data, request context, and loaded workflow-state snapshot.
- [DONE] Replace `orchestrator.run(...)` and `orchestrator.stream(...)` calls with `run_turn(...)` and `stream_turn(...)`.
- [DONE] Persist runtime-returned `WorkflowStateDelta` through session lifecycle helpers instead of assuming orchestration mutated the full state document in place.
- [DONE] Map `OrchestrationStreamEvent` into `SessionStreamEvent` without leaking orchestration internals into the SSE wire format.
- [DONE] Preserve optimistic concurrency, reset semantics, safe history projection, and the current API route contracts.
- [DONE] Remove the remaining default dependence on `EchoOrchestrationRuntime` once the real runtime interface is stable and fully wired.

**Validation**

- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m pytest tests/unit/session/test_session_handle_chat.py tests/unit/session/test_session_stream_chat.py tests/integration/session/test_session_with_sqlite_workflow_state_store.py tests/integration/session/test_session_streaming_finalization.py tests/integration/test_api_walking_skeleton.py`
- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m ruff check app/session app/orchestration app/testing/fakes/fake_orchestration_runtime.py tests/unit/session tests/integration/session tests/integration/test_api_walking_skeleton.py`
- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m mypy app/session app/orchestration`

**Exit criteria**

- [DONE] `SessionService` uses the architecture-aligned orchestration runtime interface.
- [DONE] Session code continues to own workflow-state persistence while orchestration owns turn execution.
- [DONE] API chat and streaming behavior remain stable while orchestration internals are refactored underneath them.

### [DONE] Phase 9. Fakes, Fixtures, Quality Gates, and Freeze

**Goal**

Freeze the stable orchestration boundary with deterministic fakes, dedicated fixtures, focused unit/integration coverage, and clear handoff documentation for the next backend phases.

**Files to create or update**

- [DONE] `backend/app/testing/fakes/fake_strategy.py`
- [DONE] `backend/app/testing/fakes/fake_orchestration_runtime.py`
- [DONE] `backend/tests/fixtures/config/orchestration_basic_direct.yaml`
- [DONE] `backend/tests/fixtures/config/orchestration_streaming_direct.yaml`
- [DONE] `backend/tests/fixtures/config/orchestration_retrieval_augmented.yaml`
- [DONE] `backend/tests/fixtures/config/orchestration_tool_assisted.yaml`
- [DONE] `backend/tests/fixtures/config/orchestration_router.yaml`
- [DONE] `backend/tests/fixtures/config/orchestration_unknown_usecase.yaml`
- [DONE] `backend/tests/fixtures/config/orchestration_disabled_strategy.yaml`
- [DONE] `backend/tests/fixtures/config/orchestration_policy_denied.yaml`
- [DONE] `backend/tests/fixtures/config/orchestration_limits.yaml`
- [DONE] `backend/tests/fixtures/config/orchestration_debug_unsafe_invalid.yaml`
- [DONE] `backend/tests/unit/orchestration/`
- [DONE] `backend/tests/integration/orchestration/`
- [DONE] `backend/README.md`
- [DONE] `docs/backend-orchestration-plan.md`

**Implementation tasks**

- [DONE] Add deterministic fakes for strategy execution and any orchestration-specific observability helpers needed for tests.
- [DONE] Expand orchestration fixtures so config, routing, limits, retrieval, tooling, and policy-denial cases can all run repeatably under `backend/tests/fixtures/config/`.
- [DONE] Add dedicated unit coverage for config parsing, registry resolution, runtime behavior, state-delta building, event safety, direct/retrieval/tool/router strategies, limits, cancellation, health, and capabilities.
- [DONE] Add dedicated integration coverage for the vertical slices described by the architecture, including session-runtime boundary, runtime-memory integration, runtime-tool integration, safe trace/event recording, and state-delta persistence.
- [DONE] Add opt-in local integration tests for real LLM, memory, and tooling backends only behind deterministic fixtures and explicit enablement.
- [DONE] Update `backend/README.md` to record the stable orchestration boundary, canonical `backend/app/orchestration/` package ownership, validation commands, and explicit deferrals.
- [DONE] Resolve the architecture handoff note so workflow-strategy and agent follow-on documents are sequenced consistently.

**Validation**

- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m pytest`
- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m ruff check .`
- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m mypy app`

**Exit criteria**

- [DONE] The orchestration boundary is documented, validated, and stable under `backend/`.
- [DONE] Dedicated fake and fixture coverage exists for orchestration-specific behavior.
- [DONE] The backend is ready for the workflow-strategy follow-on and the later agent-plugin deepening phase.

---

## 6. Acceptance Criteria

This plan is complete when:

- The canonical orchestration configuration surface lives under `backend/config/app.yaml` and is exposed through typed helpers in `backend/app/config/`.
- The stable orchestration package lives under `backend/app/orchestration/` with dedicated runtime, strategy, registry, routing, event, error, limits, and capability modules.
- `DefaultOrchestrationRuntime` exposes `run_turn`, `stream_turn`, `health`, and `capabilities`.
- Built-in `echo`, `direct_agent`, `retrieval_augmented`, `tool_assisted`, and `router` strategies are implemented under `backend/app/orchestration/strategies/`.
- Orchestration returns `WorkflowStateDelta` and does not persist workflow state directly.
- `SessionService` remains the only session-facing owner of workflow-state load/save/reset while delegating turn execution to the orchestration runtime.
- Orchestration and strategies call LLM, memory, and tools only through `LLMGateway`, `MemoryGateway`, and `ToolGateway`.
- Orchestration health and capabilities are surfaced safely through the backend foundation layer.
- Raw prompts, raw provider responses, raw tool payloads, raw memory records, credentials, hidden reasoning, and stack traces are not returned, streamed, logged, or traced by default.
- Dedicated unit and integration coverage exists under `backend/tests/unit/orchestration/` and `backend/tests/integration/orchestration/`.
- Validation passes from `backend/` with `.venv\Scripts\python.exe -m pytest`, `.venv\Scripts\python.exe -m ruff check .`, and `.venv\Scripts\python.exe -m mypy app`.