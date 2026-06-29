# Backend Workflow Strategies Implementation Plan

**Document:** `backend-workflow-strategies-plan.md`  
**Version:** 1.0  
**Source alignment:** `backend-workflow-strategies-architecture.md`, `backend-orchestration-plan.md`, `backend-session-service-plan.md`, `backend-memory-store-adapter-plan.md`, `backend-tooling-mcp-client-plan.md`, and the current backend implementation baseline  
**Repository rule:** all backend application code lives under `backend/`

---

## 1. Purpose

This plan converts the workflow-strategies architecture into an implementation sequence that can be delivered in small, low-risk phases.

The plan is intentionally strict about repository boundaries:

- Backend application code belongs in `backend/`.
- Backend source modules belong in `backend/app/`.
- Backend tests belong in `backend/tests/`.
- Backend configuration files belong in `backend/config/`.
- Backend local data files belong in `backend/data/`.
- Documentation updates belong in `docs/`.
- No backend workflow-strategy, orchestration, memory, tool, or agent-runtime code should be placed in the repository root, `frontend/`, or `mcp/`.

For clarity, this document uses filesystem paths such as `backend/app/orchestration/strategies/fallback_answer.py`. Python imports may still use the `app.*` package path because `backend/` is the Python project root.

---

## 2. Review Outcomes

The workflow-strategies architecture document is implementation-ready. It is strong on gateway-only execution, workflow-state delta ownership, safe streaming, bounded loops, fallback discipline, policy integration, and test expectations.

The review also confirms that this phase is not greenfield work. The repository already contains a meaningful workflow-strategy slice under `backend/` that should be deepened rather than replaced:

- `backend/app/orchestration/strategy.py` already defines a minimal runtime strategy protocol.
- `backend/app/orchestration/strategy_registry.py`, `backend/app/orchestration/registry.py`, and `backend/app/orchestration/usecase_router.py` already provide explicit strategy registration, configured agent lookup, and use-case routing.
- `backend/app/orchestration/runtime.py` already resolves configured strategies and registers built-in runtime strategies.
- `backend/app/orchestration/models.py`, `backend/app/orchestration/events.py`, `backend/app/orchestration/errors.py`, `backend/app/orchestration/limits.py`, `backend/app/orchestration/result_builder.py`, `backend/app/orchestration/state_delta.py`, `backend/app/orchestration/health.py`, and `backend/app/orchestration/capabilities.py` already provide a substantial runtime support surface.
- `backend/app/orchestration/strategies/direct_agent.py`, `backend/app/orchestration/strategies/retrieval_augmented.py`, `backend/app/orchestration/strategies/tool_assisted.py`, `backend/app/orchestration/strategies/router.py`, and `backend/app/orchestration/strategies/echo.py` already exist.
- `backend/app/config/schemas.py`, `backend/app/config/validation.py`, `backend/app/config/view.py`, and `backend/config/app.yaml` already support the current orchestration strategy catalog and typed settings view.
- `backend/tests/unit/orchestration/` already covers strategy registry behavior, routing, limits, cancellation, runtime behavior, direct strategy behavior, retrieval behavior, tool-assisted behavior, router behavior, and orchestration health/capabilities summaries.
- `backend/tests/integration/orchestration/` already proves direct, retrieval, tool, and router behavior through the runtime with fake gateways.
- `backend/tests/fixtures/config/orchestration_*.yaml` already provides fixture-backed coverage for the current catalog.

The main implementation concerns that must be resolved during execution are:

1. **The supported strategy catalog stops short of the architecture target.**  
   Current config parsing and runtime registration support `echo`, `direct_agent`, `retrieval_augmented`, `tool_assisted`, and `router`. The architecture-required `fallback_answer`, `memory_update`, and `bounded_planner` strategy types are not yet supported under `backend/app/config/` or `backend/app/orchestration/`.

2. **Strategy construction still happens inline inside the runtime.**  
   `backend/app/orchestration/runtime.py` still owns `build_strategy_registry(...)` and `_build_strategy(...)` directly. The architecture calls for a dedicated `StrategyFactory` boundary so strategy construction, validation, and startup reporting are not mixed into runtime execution code.

3. **The public strategy contract is still thinner than the architecture target.**  
   `backend/app/orchestration/strategy.py` currently exposes `run(context, agents)` and `stream(context, agents)` over the broader orchestration context and returns orchestration-level result/event shapes. The architecture expects a richer strategy-owned request/result/event boundary plus strategy-level health/capability reporting.

4. **The typed strategy settings surface is only partial.**  
   `backend/app/config/view.py` already provides typed defaults plus strategy memory/tool settings for the current catalog, but it does not yet model the full architecture surface for memory writes, fallback behavior, planner settings, tool loop limits, max memory writes, max context bytes, or strategy-level streaming metadata controls.

5. **The strategy support modules recommended by the architecture do not exist yet.**  
   There is no dedicated `backend/app/orchestration/strategy_factory.py`, `backend/app/orchestration/strategy_steps.py`, `backend/app/orchestration/context_budget.py`, `backend/app/orchestration/prompt_inputs.py`, `backend/app/orchestration/tool_intents.py`, `backend/app/orchestration/memory_intents.py`, `backend/app/orchestration/fallback.py`, `backend/app/orchestration/stream_mapping.py`, or `backend/app/orchestration/trace_helpers.py`.

6. **The existing strategies need one more hardening pass before the missing catalog items are added.**  
   Direct, retrieval, tool-assisted, and router strategies already exist, but planner, fallback, and memory-write behavior should not be added until the shared step-running, safe context-bounding, safe intent validation, and streaming helpers are explicit and reusable.

7. **The default backend config still points fallback at `direct_agent`.**  
   `backend/config/app.yaml` currently uses `orchestration.defaults.fallback_strategy: direct_agent`. That is a practical placeholder for the current baseline, but the architecture expects a real `fallback_answer` strategy once the fallback path is implemented and validated.

8. **The current quality gate does not yet cover the full architecture catalog.**  
   The repository already tests direct, retrieval, tool-assisted, and router behavior, but it does not yet cover fallback-answer behavior, memory-update writes, bounded-planner validation, invalid raw MCP tool names, planner-schema rejection, or fallback-after-policy-denial behavior.

9. **Equivalent existing module names should be extended in place where practical.**  
   The architecture document uses names such as `strategy_result_builder.py` and `strategy_limits.py`, while the current repository already has `backend/app/orchestration/result_builder.py` and `backend/app/orchestration/limits.py`. This plan should extend the current backend files where they already match the architectural responsibility instead of renaming files solely for cosmetic parity.

---

## 3. Non-Negotiable Boundary Rules

- Treat `backend/` as the Python project root for all workflow-strategy work.
- Create workflow-strategy runtime modules only under `backend/app/orchestration/`.
- Keep backend strategy tests under `backend/tests/`.
- Keep backend configuration under `backend/config/` and backend-local data under `backend/data/`.
- Keep documentation-only artifacts under `docs/`.
- Do not place backend strategy, runtime, gateway, or state code in the repository root, `frontend/`, or `mcp/`.
- Do not let `backend/app/orchestration/strategies/` import `backend/app/api/`, `backend/app/session/`, `sqlite3`, `aiosqlite`, `memory_store.service.MemoryService`, ArcadeDB clients, MCP client implementations, or LLM provider SDKs.
- Do not let strategies persist workflow state directly. Only `SessionService` may save or reset workflow state through `WorkflowStateStore`.
- Do not let strategies or step helpers write directly to `TraceStore`. Safe trace recording must continue to flow through the observability recorder or facade.
- Do not let strategy modules import FastAPI request/response types, route modules, or frontend DTOs.
- Keep API and session contracts stable while workflow-strategy internals deepen underneath them.
- Reuse and extend existing backend/orchestration modules when they already match the architecture responsibility. Avoid renaming current files only to mirror the architecture document.
- Keep `EchoStrategy` and compatibility runtime shims limited to compatibility and test support; they should not expand into the primary user-facing workflow catalog.

---

## 4. Phase Overview

| Phase | Name | Primary Outcome |
|---|---|---|
| 0 | [DONE] Current Workflow-Strategy Baseline | The repository already has a working strategy baseline under `backend/app/orchestration/` with direct, retrieval, tool-assisted, router, and compatibility echo paths. |
| 1 | [DONE] Strategy Config Surface and Catalog Expansion | The orchestration config layer supports the full workflow-strategy catalog and validates missing planner/fallback/memory-write constraints at startup. |
| 2 | [DONE] Strategy Contract, Factory, and Shared Support Modules | Strategy construction, step execution, intent validation, context bounding, and safe stream mapping are factored out of the runtime into stable backend-owned modules. |
| 3 | [DONE] Direct, Retrieval, Tool, and Router Alignment | The existing built-in strategies are refactored to use the shared helpers and fully align with the architecture rules before new strategies are added. |
| 4 | [DONE] Fallback Answer Strategy | A real `fallback_answer` strategy exists and handles degradable failures without weakening policy. |
| 5 | [DONE] Memory Update Strategy | Durable memory-write behavior is implemented through `MemoryGateway` and policy hooks only. |
| 6 | [DONE] Bounded Planner Strategy | A disabled-by-default planner/executor strategy exists with strict schema validation and step limits. |
| 7 | [DONE] Strategy Health, Capabilities, and Composition Root Completion | Startup, runtime health, and capability reporting expose the full strategy catalog safely through the existing backend composition root. |
| 8 | [DONE] Quality Gates and Freeze | Dependency-boundary tests, fixture coverage, and full backend validation freeze the workflow-strategy layer before the next architecture phase. |

---

## 5. Detailed Implementation Phases

### [DONE] Phase 0. Current Workflow-Strategy Baseline

**Goal**

Record the workflow-strategy work that already exists so the plan extends the real backend under `backend/` instead of re-describing a greenfield slice.

**Files already present**

- [DONE] `backend/app/orchestration/strategy.py`
- [DONE] `backend/app/orchestration/strategy_registry.py`
- [DONE] `backend/app/orchestration/registry.py`
- [DONE] `backend/app/orchestration/usecase_router.py`
- [DONE] `backend/app/orchestration/runtime.py`
- [DONE] `backend/app/orchestration/core.py`
- [DONE] `backend/app/orchestration/models.py`
- [DONE] `backend/app/orchestration/events.py`
- [DONE] `backend/app/orchestration/errors.py`
- [DONE] `backend/app/orchestration/limits.py`
- [DONE] `backend/app/orchestration/result_builder.py`
- [DONE] `backend/app/orchestration/state_delta.py`
- [DONE] `backend/app/orchestration/health.py`
- [DONE] `backend/app/orchestration/capabilities.py`
- [DONE] `backend/app/orchestration/strategies/direct_agent.py`
- [DONE] `backend/app/orchestration/strategies/retrieval_augmented.py`
- [DONE] `backend/app/orchestration/strategies/tool_assisted.py`
- [DONE] `backend/app/orchestration/strategies/router.py`
- [DONE] `backend/app/orchestration/strategies/echo.py`
- [DONE] `backend/tests/unit/orchestration/`
- [DONE] `backend/tests/integration/orchestration/`
- [DONE] `backend/tests/fixtures/config/orchestration_basic_direct.yaml`
- [DONE] `backend/tests/fixtures/config/orchestration_retrieval_augmented.yaml`
- [DONE] `backend/tests/fixtures/config/orchestration_tool_assisted.yaml`
- [DONE] `backend/tests/fixtures/config/orchestration_router.yaml`

**Implementation outcomes already in place**

- [DONE] The orchestration runtime already resolves configured strategies through a strategy registry under `backend/app/orchestration/`.
- [DONE] The current backend already ships direct-agent, retrieval-augmented, tool-assisted, router, and echo compatibility strategy implementations under `backend/app/orchestration/strategies/`.
- [DONE] Typed orchestration settings already exist under `backend/app/config/` for the current strategy catalog.
- [DONE] Runtime health and capability summaries already exist for the current orchestration slice.
- [DONE] Unit and integration tests already cover the current direct/retrieval/tool/router baseline under `backend/tests/`.
- [DONE] Session and API layers already run through the orchestration runtime without importing concrete strategies directly.

**Current limitations that the next phases must fix**

- The full architecture catalog is not yet supported.
- Strategy construction still lives inline in the runtime.
- The public strategy contract is still thinner than the architecture target.
- Shared step-runner, intent, fallback, context-budget, and stream-mapping helpers are not factored out yet.
- `fallback_answer`, `memory_update`, and `bounded_planner` do not exist yet under `backend/app/orchestration/strategies/`.
- The default backend config still points `fallback_strategy` to `direct_agent`.
- The full fallback, memory-write, and planner quality gates do not exist yet.

**Exit criteria**

- [DONE] The implementation plan starts from the real `backend/` workflow-strategy baseline and extends it rather than replacing it.

### [DONE] Phase 1. Strategy Config Surface and Catalog Expansion

**Goal**

Expand the current orchestration config layer so it can describe and validate the full workflow-strategy catalog defined by the architecture.

**Files to create or update**

- [DONE] `backend/app/config/schemas.py`
- [DONE] `backend/app/config/validation.py`
- [DONE] `backend/app/config/view.py`
- [DONE] `backend/config/app.yaml`
- [DONE] `backend/tests/unit/config/test_config_view.py`
- [DONE] `backend/tests/unit/config/test_validation.py`
- [DONE] `backend/tests/unit/orchestration/test_orchestration_fixture_examples.py`
- [DONE] `backend/tests/fixtures/config/orchestration_fallback_answer.yaml`
- [DONE] `backend/tests/fixtures/config/orchestration_memory_update.yaml`
- [DONE] `backend/tests/fixtures/config/orchestration_bounded_planner_disabled.yaml`
- [DONE] `backend/tests/fixtures/config/orchestration_invalid_missing_fallback.yaml`
- [DONE] `backend/tests/fixtures/config/orchestration_invalid_raw_mcp_tool.yaml`
- [DONE] `backend/tests/fixtures/config/orchestration_invalid_unbounded_planner.yaml`

**Implementation tasks**

- [DONE] Extend the supported orchestration strategy type surface from the current set to include `fallback_answer`, `memory_update`, and `bounded_planner`.
- [DONE] Deepen `StrategySettings`, `OrchestrationDefaultsSettings`, and adjacent typed config models so they can represent:
   - [DONE] fallback behavior
   - [DONE] memory-write limits and approval flags
   - [DONE] planner profiles and planner step limits
   - [DONE] tool loop iteration limits
   - [DONE] context-budget limits
   - [DONE] strategy-level safe metadata and streaming controls
- [DONE] Preserve compatibility for the current `backend/config/app.yaml` and `backend/tests/fixtures/config/orchestration_*.yaml` layout while adding the richer fields.
- [DONE] Keep the current fixture naming convention rooted in `backend/tests/fixtures/config/orchestration_*.yaml` instead of introducing a second fixture family unless there is a concrete need to split them.
- [DONE] Add startup validation for:
   - [DONE] missing or disabled fallback strategy references
   - [DONE] missing or disabled planner/fallback/memory-update strategies selected by defaults or use cases
   - [DONE] planner configurations without bounded step limits
   - [DONE] router candidates that reference unknown or disabled strategies
   - [DONE] tool settings that expose raw MCP tool names instead of logical backend tool names
   - [DONE] memory-update settings that allow writes without the required memory/policy path
   - [DONE] negative or zero values for new bounded limits where the architecture requires positive integers
- [DONE] Keep backend-local path references explicit to `backend/config/` and `backend/data/`.

**Validation**

- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m pytest tests/unit/config/test_config_view.py tests/unit/config/test_validation.py tests/unit/orchestration/test_orchestration_fixture_examples.py`
- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m ruff check app/config tests/unit/config/test_config_view.py tests/unit/config/test_validation.py tests/unit/orchestration/test_orchestration_fixture_examples.py`
- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m mypy app/config`

**Exit criteria**

- [DONE] The full workflow-strategy catalog can be described by typed settings under `backend/app/config/`.
- [DONE] Invalid fallback, planner, memory-write, and routing combinations fail fast during backend startup.
- [DONE] Canonical backend YAML remains rooted under `backend/config/` and fixture coverage exists under `backend/tests/fixtures/config/`.

### [DONE] Phase 2. Strategy Contract, Factory, and Shared Support Modules

**Goal**

Deepen the current strategy boundary so the runtime no longer owns strategy construction details and strategy implementations can share reusable safe helper modules.

**Files to create or update**

- [DONE] `backend/app/orchestration/strategy.py`
- [DONE] `backend/app/orchestration/strategy_factory.py`
- [DONE] `backend/app/orchestration/strategy_steps.py`
- [DONE] `backend/app/orchestration/context_budget.py`
- [DONE] `backend/app/orchestration/prompt_inputs.py`
- [DONE] `backend/app/orchestration/tool_intents.py`
- [DONE] `backend/app/orchestration/memory_intents.py`
- [DONE] `backend/app/orchestration/fallback.py`
- [DONE] `backend/app/orchestration/stream_mapping.py`
- [DONE] `backend/app/orchestration/trace_helpers.py`
- [DONE] `backend/app/orchestration/models.py` (reused without code changes)
- [DONE] `backend/app/orchestration/events.py` (reused without code changes)
- [DONE] `backend/app/orchestration/errors.py`
- [DONE] `backend/app/orchestration/result_builder.py` (reused without code changes)
- [DONE] `backend/app/orchestration/runtime.py`
- [DONE] `backend/app/orchestration/core.py`
- [DONE] `backend/tests/unit/orchestration/test_strategy_factory.py`
- [DONE] `backend/tests/unit/orchestration/test_strategy_steps.py`
- [DONE] `backend/tests/unit/orchestration/test_tool_intents.py`
- [DONE] `backend/tests/unit/orchestration/test_memory_intents.py`
- [DONE] `backend/tests/unit/orchestration/test_stream_mapping.py`

**Implementation tasks**

- [DONE] Move inline strategy construction out of `backend/app/orchestration/runtime.py` into a dedicated `backend/app/orchestration/strategy_factory.py`.
- [DONE] Keep `backend/app/orchestration/runtime.py` focused on runtime orchestration, strategy resolution, fallback dispatch, cancellation, and safe result/event mapping.
- [DONE] Deepen the public strategy contract so the strategy layer has a stable request/result/event boundary that can carry the architecture-required safe fields without leaking provider payloads.
- [DONE] Preserve compatibility for the current session-facing runtime surface. Add compatibility adapters rather than forcing API or session rewrites.
- [DONE] Add reusable step helpers for agent, LLM, memory-search, memory-write, tool-call, and finalization flows.
- [DONE] Add explicit safe helper modules for:
   - [DONE] prompt input shaping
   - [DONE] context budgeting
   - [DONE] tool-intent normalization and validation
   - [DONE] memory-intent normalization and validation
   - [DONE] stream-event mapping
   - [DONE] trace payload shaping
   - [DONE] fallback decision helpers
- [DONE] Prefer extending the existing `backend/app/orchestration/result_builder.py`, `backend/app/orchestration/limits.py`, `backend/app/orchestration/health.py`, and `backend/app/orchestration/capabilities.py` modules where they already match the architecture responsibility.
- [DONE] Keep `backend/app/orchestration/core.py` aligned as a compatibility shim if the public import surface still depends on it.

**Validation**

- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m pytest tests/unit/orchestration/test_strategy_factory.py tests/unit/orchestration/test_strategy_steps.py tests/unit/orchestration/test_tool_intents.py tests/unit/orchestration/test_memory_intents.py tests/unit/orchestration/test_stream_mapping.py tests/unit/orchestration/test_errors.py tests/unit/orchestration/test_models.py`
- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m ruff check app/orchestration tests/unit/orchestration`
- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m mypy app/orchestration`

**Exit criteria**

- [DONE] Strategy construction no longer lives inline in the runtime.
- [DONE] Shared strategy support behavior is reusable across the full strategy catalog.
- [DONE] Runtime, session, and API contracts remain stable while strategy internals deepen.

### [DONE] Phase 3. Direct, Retrieval, Tool, and Router Alignment

**Goal**

Refactor the existing built-in strategies so they fully align with the architecture rules before the missing catalog items are introduced.

**Files to create or update**

- [DONE] `backend/app/orchestration/strategies/direct_agent.py`
- [DONE] `backend/app/orchestration/strategies/retrieval_augmented.py`
- [DONE] `backend/app/orchestration/strategies/tool_assisted.py`
- [DONE] `backend/app/orchestration/strategies/router.py`
- [DONE] `backend/app/orchestration/strategies/echo.py`
- [DONE] `backend/app/orchestration/runtime.py`
- [DONE] `backend/app/orchestration/strategy_registry.py`
- [DONE] `backend/app/orchestration/usecase_router.py`
- [DONE] `backend/tests/unit/orchestration/test_direct_agent_strategy.py`
- [DONE] `backend/tests/unit/orchestration/test_retrieval_strategy.py`
- [DONE] `backend/tests/unit/orchestration/test_tool_assisted_strategy.py`
- [DONE] `backend/tests/unit/orchestration/test_router_strategy.py`
- [DONE] `backend/tests/unit/orchestration/test_limits.py`
- [DONE] `backend/tests/unit/orchestration/test_cancellation.py`
- [DONE] `backend/tests/integration/orchestration/test_direct_runtime_with_fake_llm.py`
- [DONE] `backend/tests/integration/orchestration/test_direct_runtime_streaming.py`
- [DONE] `backend/tests/integration/orchestration/test_retrieval_runtime_with_fake_memory.py`
- [DONE] `backend/tests/integration/orchestration/test_tool_runtime_with_fake_tools.py`
- [DONE] `backend/tests/integration/orchestration/test_router_runtime.py`

**Implementation tasks**

- [DONE] Update `DirectAgentStrategy` so it uses the shared step helpers, emits safe step summaries, and never executes tool calls when tools are disabled for the selected strategy/use case.
- [DONE] Update `RetrievalAugmentedStrategy` so it performs retrieval only through `MemoryGateway`, uses explicit context-budget helpers, and never returns or persists raw memory records.
- [DONE] Update `ToolAssistedStrategy` so it validates logical tool intents before any execution, enforces loop limits, and reduces tool results to safe prompt context and safe public summaries only.
- [DONE] Update `RouterStrategy` so it can choose only configured and policy-allowed candidates, validates any classifier output against the configured candidate set, and exposes only safe routing metadata.
- [DONE] Keep `EchoStrategy` limited to compatibility/test use. It should not become the implicit fallback for the new catalog.
- [DONE] Ensure streaming direct, retrieval, tool, and router paths emit only safe strategy events and do not bypass the same core logic used by non-streaming turns.
- [DONE] Ensure all four built-in strategies can participate in the eventual fallback path without weakening policy rules.

**Validation**

- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m pytest tests/unit/orchestration/test_direct_agent_strategy.py tests/unit/orchestration/test_retrieval_strategy.py tests/unit/orchestration/test_tool_assisted_strategy.py tests/unit/orchestration/test_router_strategy.py tests/unit/orchestration/test_limits.py tests/unit/orchestration/test_cancellation.py tests/integration/orchestration/test_direct_runtime_with_fake_llm.py tests/integration/orchestration/test_direct_runtime_streaming.py tests/integration/orchestration/test_retrieval_runtime_with_fake_memory.py tests/integration/orchestration/test_tool_runtime_with_fake_tools.py tests/integration/orchestration/test_router_runtime.py`
- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m ruff check app/orchestration tests/unit/orchestration tests/integration/orchestration`
- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m mypy app/orchestration`

**Exit criteria**

- [DONE] The existing direct/retrieval/tool/router catalog uses shared helpers instead of ad hoc strategy-local behavior.
- [DONE] Non-streaming and streaming paths stay aligned for the built-in catalog.
- [DONE] The baseline strategies are ready for new fallback, memory-update, and planner behavior.

### [DONE] Phase 4. Fallback Answer Strategy

**Goal**

Implement a real `fallback_answer` strategy and fallback decision path so degradable failures can return safe partial answers without hiding uncertainty or weakening policy.

**Files to create or update**

- [DONE] `backend/app/orchestration/strategies/fallback_answer.py`
- [DONE] `backend/app/orchestration/fallback.py`
- [DONE] `backend/app/orchestration/runtime.py`
- [DONE] `backend/app/orchestration/errors.py`
- [DONE] `backend/app/config/view.py`
- [DONE] `backend/app/config/validation.py`
- [DONE] `backend/config/app.yaml`
- [DONE] `backend/tests/unit/orchestration/test_fallback_answer_strategy.py`
- [DONE] `backend/tests/unit/orchestration/test_fallback_policy_behavior.py`
- [DONE] `backend/tests/integration/orchestration/test_fallback_runtime.py`
- [DONE] `backend/tests/fixtures/config/orchestration_fallback_answer.yaml`

**Implementation tasks**

- [DONE] Add `FallbackAnswerStrategy` under `backend/app/orchestration/strategies/`.
- [DONE] Define a safe fallback decision helper that can classify degradable failures such as optional memory-search failures or optional tool unavailability.
- [DONE] Ensure fallback never runs after policy denial, never pretends a failed side-effect succeeded, and never suppresses material uncertainty.
- [DONE] Support both static fallback messages and agent/LLM-backed fallback answers through provider-neutral boundaries only.
- [DONE] Switch the canonical backend config from `fallback_strategy: direct_agent` to `fallback_strategy: fallback_answer` once the fallback strategy exists and passes validation.
- [DONE] Emit safe fallback metadata into runtime results, stream events, and state deltas without exposing raw exceptions.

**Validation**

- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m pytest tests/unit/orchestration/test_fallback_answer_strategy.py tests/unit/orchestration/test_fallback_policy_behavior.py tests/integration/orchestration/test_fallback_runtime.py`
- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m ruff check app/orchestration tests/unit/orchestration/test_fallback_answer_strategy.py tests/unit/orchestration/test_fallback_policy_behavior.py tests/integration/orchestration/test_fallback_runtime.py`
- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m mypy app/orchestration`
- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -c "from app.config.loader import load_validated_config; load_validated_config('config/app.yaml', env={}); print('ok')"`

**Exit criteria**

- [DONE] The backend has a real `fallback_answer` strategy under `backend/app/orchestration/strategies/`.
- [DONE] Degradable failures can produce safe fallback answers.
- [DONE] Policy denial still blocks execution without fallback-based privilege widening.

### [DONE] Phase 5. Memory Update Strategy

**Goal**

Implement durable memory-write behavior through `MemoryGateway` and policy hooks only.

**Files to create or update**

- [DONE] `backend/app/orchestration/strategies/memory_update.py`
- [DONE] `backend/app/orchestration/memory_intents.py`
- [DONE] `backend/app/orchestration/models.py`
- [DONE] `backend/app/orchestration/result_builder.py`
- [DONE] `backend/app/orchestration/state_delta.py`
- [DONE] `backend/app/orchestration/runtime.py`
- [DONE] `backend/app/config/view.py`
- [DONE] `backend/app/config/validation.py`
- [DONE] `backend/config/app.yaml`
- [DONE] `backend/tests/unit/orchestration/test_memory_update_strategy.py`
- [DONE] `backend/tests/unit/orchestration/test_memory_update_policy.py`
- [DONE] `backend/tests/integration/orchestration/test_memory_update_runtime.py`
- [DONE] `backend/tests/fixtures/config/orchestration_memory_update.yaml`

**Implementation tasks**

- [DONE] Add `MemoryUpdateStrategy` under `backend/app/orchestration/strategies/`.
- [DONE] Define a bounded memory-candidate model and candidate extraction path that can support explicit remember-style use cases and safe post-turn curation where enabled.
- [DONE] Route all writes through `MemoryGateway` only.
- [DONE] Ensure strategy-level memory updates call policy hooks before write attempts and respect write-count limits.
- [DONE] Keep workflow-state deltas limited to safe memory-update summaries. Do not store raw memory records or raw adapter payloads in workflow state.
- [DONE] Decide invocation rules explicitly in config rather than letting direct or retrieval strategies write durable memory opportunistically by default.

**Validation**

- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m pytest tests/unit/orchestration/test_memory_update_strategy.py tests/unit/orchestration/test_memory_update_policy.py tests/integration/orchestration/test_memory_update_runtime.py`
- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m ruff check app/orchestration tests/unit/orchestration/test_memory_update_strategy.py tests/unit/orchestration/test_memory_update_policy.py tests/integration/orchestration/test_memory_update_runtime.py`
- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m mypy app/orchestration`

**Exit criteria**

- [DONE] Durable memory writes happen only through `MemoryGateway` and policy hooks.
- [DONE] Memory-update summaries are safe for runtime/session/API handoff.
- [DONE] No workflow-strategy code imports `memory_store.service.MemoryService` or writes directly to ArcadeDB-backed adapters.

### [DONE] Phase 6. Bounded Planner Strategy

**Goal**

Implement a disabled-by-default planner/executor strategy that remains strictly bounded, schema-validated, and policy-filtered.

**Files to create or update**

- [DONE] `backend/app/orchestration/strategies/bounded_planner.py`
- [DONE] `backend/app/orchestration/strategy_steps.py`
- [DONE] `backend/app/orchestration/models.py`
- [DONE] `backend/app/orchestration/errors.py`
- [DONE] `backend/app/orchestration/runtime.py`
- [DONE] `backend/app/config/view.py`
- [DONE] `backend/app/config/validation.py`
- [DONE] `backend/config/app.yaml`
- [DONE] `backend/tests/unit/orchestration/test_bounded_planner_strategy.py`
- [DONE] `backend/tests/unit/orchestration/test_bounded_planner_validation.py`
- [DONE] `backend/tests/integration/orchestration/test_bounded_planner_runtime.py`
- [DONE] `backend/tests/fixtures/config/orchestration_bounded_planner_disabled.yaml`
- [DONE] `backend/tests/fixtures/config/orchestration_invalid_unbounded_planner.yaml`

**Implementation tasks**

- [DONE] Add `BoundedPlannerStrategy` under `backend/app/orchestration/strategies/`.
- [DONE] Define the plan and plan-step schema within `backend/app/orchestration/` and validate planner output before any execution begins.
- [DONE] Keep the allowed action set explicit and narrow: memory search, tool call, agent invoke, LLM call, and finalize only.
- [DONE] Execute plan steps only through the shared step runner and gateway/agent abstractions.
- [DONE] Enforce planner step limits, tool loop limits, memory-write limits, context budgets, and duration limits before and during execution.
- [DONE] Keep the planner disabled by default in canonical backend config until it passes the full validation gate.

**Validation**

- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m pytest tests/unit/orchestration/test_bounded_planner_strategy.py tests/unit/orchestration/test_bounded_planner_validation.py tests/integration/orchestration/test_bounded_planner_runtime.py`
- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m ruff check app/orchestration tests/unit/orchestration/test_bounded_planner_strategy.py tests/unit/orchestration/test_bounded_planner_validation.py tests/integration/orchestration/test_bounded_planner_runtime.py`
- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m mypy app/orchestration`

**Exit criteria**

- [DONE] The backend has a disabled-by-default bounded planner strategy under `backend/app/orchestration/strategies/`.
- [DONE] Unknown actions, invalid plans, and unbounded configurations fail before execution.
- [DONE] Planner execution remains gateway-only and policy-aware.

### [DONE] Phase 7. Strategy Health, Capabilities, and Composition Root Completion

**Goal**

Complete startup, health, and capability reporting for the full workflow-strategy catalog through the existing backend composition root.

**Files to create or update**

- [DONE] `backend/app/orchestration/health.py`
- [DONE] `backend/app/orchestration/capabilities.py`
- [DONE] `backend/app/orchestration/strategy_factory.py`
- [DONE] `backend/app/orchestration/strategy_registry.py`
- [DONE] `backend/app/orchestration/runtime.py`
- [DONE] `backend/app/config/bootstrap.py`
- [DONE] `backend/app/foundation/capabilities.py`
- [DONE] `backend/app/foundation/health.py`
- [DONE] `backend/tests/unit/orchestration/test_orchestration_health_summary.py`
- [DONE] `backend/tests/unit/orchestration/test_orchestration_capabilities_summary.py`
- [DONE] `backend/tests/integration/test_startup_orchestration.py`

**Implementation tasks**

- [DONE] Surface per-strategy readiness and safe metadata through the existing orchestration health summary.
- [DONE] Expose frontend-safe orchestration capabilities for the full strategy/use-case catalog, including strategy type labels and streaming support.
- [DONE] Ensure health and capabilities are generated from the factory-built registry rather than from hard-coded runtime assumptions.
- [DONE] Emit a redacted strategy startup summary that includes only safe counts, type names, and use-case totals.
- [DONE] Preserve current startup flow under `backend/app/config/bootstrap.py` and keep API/session layers unchanged.

**Validation**

- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m pytest tests/unit/orchestration/test_orchestration_health_summary.py tests/unit/orchestration/test_orchestration_capabilities_summary.py tests/integration/test_startup_orchestration.py tests/unit/test_capabilities.py tests/unit/test_health.py`
- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m ruff check app/orchestration app/config/bootstrap.py app/foundation tests/unit/orchestration tests/integration/test_startup_orchestration.py tests/unit/test_capabilities.py tests/unit/test_health.py`
- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m mypy app/orchestration app/config/bootstrap.py app/foundation`

**Exit criteria**

- [DONE] Health reports safe readiness for the full workflow-strategy catalog.
- [DONE] Capabilities expose only frontend-safe strategy/use-case metadata.
- [DONE] Startup builds and registers the full strategy catalog through the backend composition root under `backend/`.

### [DONE] Phase 8. Quality Gates and Freeze

**Goal**

Freeze the workflow-strategy layer with dependency-boundary tests, fixture coverage, and full backend validation before the next architecture phase.

**Files to create or update**

- [DONE] `backend/tests/unit/orchestration/test_strategy_dependency_boundaries.py`
- [DONE] `backend/tests/unit/orchestration/test_strategy_stream_safety.py`
- [DONE] `backend/tests/unit/orchestration/test_strategy_policy_denial.py`
- [DONE] `backend/tests/unit/orchestration/test_strategy_limit_exceeded.py`
- [DONE] `backend/tests/unit/orchestration/test_strategy_trace_redaction.py`
- [DONE] `backend/tests/fixtures/config/orchestration_invalid_missing_fallback.yaml`
- [DONE] `backend/tests/fixtures/config/orchestration_invalid_raw_mcp_tool.yaml`
- [DONE] `backend/tests/fixtures/config/orchestration_invalid_unbounded_planner.yaml`
- [DONE] `backend/tests/fixtures/config/orchestration_memory_update.yaml`
- [DONE] `backend/tests/fixtures/config/orchestration_fallback_answer.yaml`
- [DONE] `backend/tests/fixtures/config/orchestration_bounded_planner_disabled.yaml`
- [DONE] `backend/README.md`
- [DONE] `docs/backend-workflow-strategies-plan.md`

**Implementation tasks**

- [DONE] Add explicit import-boundary tests so workflow strategies cannot drift into API, session, SQLite, `memory_store`, MCP client, or provider-SDK imports.
- [DONE] Add stream-safety tests to ensure raw prompts, raw provider chunks, raw tool payloads, raw memory records, raw workflow state, credentials, hidden reasoning, and stack traces are never exposed by default.
- [DONE] Add policy-denial, limit-exceeded, fallback-denial, and trace-redaction tests across the full catalog.
- [DONE] Ensure fixture coverage exists for the full supported catalog plus invalid planner/fallback/tool configurations.
- [DONE] Update `backend/README.md` with the frozen workflow-strategy boundary, canonical config locations under `backend/config/`, canonical strategy test surfaces under `backend/tests/`, and handoff to `docs/backend-agents-architecture.md`.
- [DONE] Mark completed phases in this plan as implementation proceeds.

**Validation**

- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m pytest`
- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m ruff check .`
- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m mypy app`

**Exit criteria**

- [DONE] The workflow-strategy layer is covered by focused unit/integration tests and import-boundary checks.
- [DONE] Full backend validation passes from `backend/`.
- [DONE] The workflow-strategy boundary is documented and frozen before deeper agent work begins.

---

## 6. Recommended Delivery Order

Deliver the workflow-strategy work in this order:

1. Expand the config surface and validation first so unsupported catalog entries fail fast.
2. Extract the factory and shared support modules before adding new strategies.
3. Refactor the current direct/retrieval/tool/router catalog onto the shared helpers.
4. Add `fallback_answer` next so degraded paths are available before memory-write and planner work.
5. Add `memory_update` after fallback because it introduces durable side-effect behavior.
6. Add `bounded_planner` last because it compounds the most strategy complexity and should stay disabled by default until the earlier phases are stable.
7. Finish by wiring full health/capabilities and freezing the layer with dependency-boundary tests.

---

## 7. Acceptance Criteria

This implementation plan is complete when:

- All workflow-strategy runtime code remains under `backend/app/orchestration/`.
- The full supported strategy catalog is represented in typed config under `backend/app/config/`.
- `backend/app/orchestration/runtime.py` no longer owns inline strategy construction.
- A dedicated strategy factory exists under `backend/app/orchestration/`.
- Shared step execution, intent validation, context budgeting, fallback decisions, stream mapping, and trace helpers exist under `backend/app/orchestration/`.
- Direct, retrieval, tool-assisted, and router strategies use the shared helpers and fully honor gateway-only boundaries.
- `fallback_answer`, `memory_update`, and `bounded_planner` exist under `backend/app/orchestration/strategies/`.
- Memory writes happen only through `MemoryGateway` and policy hooks.
- Planner execution remains disabled by default until explicitly enabled in validated config.
- Strategies never import API, session, SQLite, `memory_store`, MCP client implementations, or provider SDKs.
- Strategy outputs remain safe for runtime/session/API/SSE handoff.
- Runtime health and capabilities expose the full catalog safely through the backend composition root.
- Canonical tests and fixtures for the workflow-strategy layer live under `backend/tests/`.
- Full backend validation passes from `backend/` with `pytest`, `ruff check .`, and `mypy app`.
- The backend is ready for the next document: `backend-agents-architecture.md`.
