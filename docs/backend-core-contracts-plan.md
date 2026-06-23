# Backend Core Contracts Implementation Plan

**Document:** `backend-core-contracts-plan.md`  
**Version:** 1.0  
**Source alignment:** `backend-core-contracts-architecture.md` and `backend-foundation-plan.md`  
**Repository rule:** all backend application code lives under `backend/`

---

## 1. Purpose

This plan converts the backend core contracts architecture into an implementation sequence that can be delivered in small, low-risk phases.

The plan is intentionally strict about repository boundaries:

- Backend application code belongs in `backend/`.
- Backend source modules belong in `backend/app/`.
- Backend test modules belong in `backend/tests/`.
- Backend contract fakes used by tests belong in `backend/app/testing/`.
- Documentation updates belong in `docs/`.
- No backend contract or runtime code should be placed in the repository root, `frontend/`, or `mcp/`.

---

## 2. Review Outcomes

The architecture document is implementation-ready and internally consistent. It defines a clean contract-first slice that should be built immediately on top of the completed backend foundation.

The review confirms these execution rules:

- Extend the existing backend package tree under `backend/app/`; do not create a second backend source root.
- Add the shared contract layer as `backend/app/contracts/`.
- Add fake gateway, store, agent, and strategy implementations under `backend/app/testing/fakes/`.
- Add contract-focused unit tests under `backend/tests/unit/contracts/`.
- Keep the existing foundation modules in place; this phase adds shared contracts and test doubles, not new provider adapters or new API routes.

The main implementation concerns to address explicitly during execution are:

1. **Dependency direction must remain one-way.**  
   `backend/app/contracts/*` may be imported by later implementation modules, but contract modules must not import concrete modules from future `llm/`, `tools/`, `persistence/`, `agents/`, or orchestration implementations.

2. **Import cycles must be avoided deliberately.**  
   `OrchestrationContext` refers to gateway protocols, and gateway protocols refer back to orchestration context. The implementation should rely on deferred annotations and type-checking-only imports rather than runtime imports across contract modules.

3. **The current backend foundation already covers startup, config loading, and observability.**  
   This contract phase must build on those existing modules in `backend/app/config/`, `backend/app/foundation/`, `backend/app/observability/`, and `backend/app/main.py` rather than revisiting foundation behavior.

4. **Health contracts and health routes are separate concerns.**  
   The contract-level `backend/app/contracts/health.py` should define reusable component health types only. The existing HTTP health behavior remains in `backend/app/foundation/health.py` and `backend/app/api/routes_health.py`.

5. **This phase must stay infrastructure-free.**  
   No real LLM SDKs, MCP clients, SQLite logic, ArcadeDB code, or `memory_store` integration should be added while implementing the contract layer.

---

## 3. Non-Negotiable Boundary Rules

- Treat `backend/` as the Python project root for all core-contract work.
- Create contract source files only under `backend/app/contracts/` and `backend/app/testing/`.
- Create contract tests only under `backend/tests/`.
- Keep documentation-only artifacts under `docs/`.
- Do not place contract code in the repository root, `frontend/`, or `mcp/`.
- Do not add real LLM providers, MCP client adapters, SQLite stores, ArcadeDB adapters, or `memory_store` integrations in this phase.
- Do not add new API endpoints in this phase.
- Do not let contracts import FastAPI request objects, provider SDK types, database client types, or MCP client types.
- Keep contracts limited to standard-library types plus lightweight typing support already available in the backend project.

---

## 4. Phase Overview

| Phase | Name | Primary Outcome |
|---|---|---|
| 0 | [DONE] Contract Package Scaffold | The backend package gains `backend/app/contracts/`, `backend/app/testing/`, and `backend/tests/unit/contracts/` as the canonical locations for contract code and fakes. |
| 1 | [DONE] Shared Context, Result, Error, and Health Models | The backend has stable dataclass-based request, orchestration, result, error, and component-health contracts. |
| 2 | [DONE] Agent, Strategy, and Gateway Protocols | The backend has provider-neutral protocols for agents, orchestration strategies, gateways, stores, policy, and configuration. |
| 3 | [DONE] Fake Implementations and Test Helpers | The backend can construct full fake orchestration contexts without real infrastructure. |
| 4 | [DONE] Contract Tests and Quality Gates | The contract layer is covered by focused unit tests and validated with backend-local quality checks. |
| 5 | [DONE] Contract Freeze and Handoff | The backend core contract slice is documented as complete and ready for later configuration, API, persistence, tooling, and orchestration phases. |

---

## 5. Detailed Implementation Phases

### [DONE] Phase 0. Contract Package Scaffold

**Goal**

Create the missing package and test layout for the contract phase inside the existing `backend/` project.

**Files and folders to create**

- `backend/app/contracts/__init__.py`
- `backend/app/testing/__init__.py`
- `backend/app/testing/fakes/__init__.py`
- `backend/tests/unit/contracts/`

**Files and folders created**

- [DONE] `backend/app/contracts/__init__.py`
- [DONE] `backend/app/testing/__init__.py`
- [DONE] `backend/app/testing/fakes/__init__.py`
- [DONE] `backend/tests/unit/contracts/`

**Implementation tasks**

- [DONE] Extend the current `backend/app/` tree instead of creating a parallel package root.
- [DONE] Keep the contract package centralized under `backend/app/contracts/` to avoid premature module sprawl.
- [DONE] Keep fake implementations in `backend/app/testing/fakes/` so they can be shared across unit tests without polluting production packages.
- [DONE] Create only the directories and `__init__.py` files needed for the contract slice.
- [DONE] Do not create future concrete module trees such as `backend/app/llm/`, `backend/app/tools/`, or `backend/app/persistence/` unless later phases require them.

**Validation**

- [DONE] From `backend/`, confirm the new package roots are importable once the first contract modules are added.

**Exit criteria**

- [DONE] The backend has a single canonical location for contracts, fakes, and contract tests.
- [DONE] No contract files have been placed outside `backend/`.

### [DONE] Phase 1. Shared Context, Result, Error, and Health Models

**Goal**

Define the normalized internal data objects that later agents, strategies, routes, and adapters will share.

**Files to create**


**Files created**

- [DONE] `backend/app/contracts/context.py`
- [DONE] `backend/app/contracts/results.py`
- [DONE] `backend/app/contracts/errors.py`
- [DONE] `backend/app/contracts/health.py`

**Implementation tasks**

- [DONE] Implement `RequestContext` as the normalized request object after API and session resolution.
- [DONE] Implement `OrchestrationContext` as the capability container passed to strategies and agents.
- [DONE] Implement `AgentResult`, `OrchestrationResult`, and `StreamEvent` as serialization-friendly dataclass models.
- [DONE] Implement the backend error hierarchy for configuration, policy, gateway, workflow-state, and trace failures.
- [DONE] Implement `ComponentHealth`, `HealthStatus`, and the `HealthCheck` protocol in the contract package.
- [DONE] Keep these models framework-neutral; do not tie them to FastAPI or Pydantic in this phase.
- [DONE] Use deferred annotations or `TYPE_CHECKING` imports where needed to keep module imports acyclic.

**Validation**

- [DONE] Add and pass model-construction tests for request, orchestration, result, and health objects.
- [DONE] Confirm the contract modules import without importing any concrete backend implementation module outside the contract package.

**Exit criteria**

- [DONE] The backend has stable shared internal DTOs and error categories.
- [DONE] Contract model modules import successfully without infrastructure dependencies.

### [DONE] Phase 2. Agent, Strategy, and Gateway Protocols

**Goal**

Define the provider-neutral interfaces that later runtime and adapter modules will implement.

**Files to create**

- `backend/app/contracts/agents.py`
- `backend/app/contracts/strategies.py`
- `backend/app/contracts/llm.py`
- `backend/app/contracts/memory.py`
- `backend/app/contracts/tools.py`
- `backend/app/contracts/state.py`
- `backend/app/contracts/trace.py`
- `backend/app/contracts/policy.py`
- `backend/app/contracts/config.py`

**Files created**

- [DONE] `backend/app/contracts/agents.py`
- [DONE] `backend/app/contracts/strategies.py`
- [DONE] `backend/app/contracts/llm.py`
- [DONE] `backend/app/contracts/memory.py`
- [DONE] `backend/app/contracts/tools.py`
- [DONE] `backend/app/contracts/state.py`
- [DONE] `backend/app/contracts/trace.py`
- [DONE] `backend/app/contracts/policy.py`
- [DONE] `backend/app/contracts/config.py`

**Implementation tasks**

- [DONE] Define `AgentPlugin` and `AgentMetadata`.
- [DONE] Define `OrchestrationStrategy` and `StrategyMetadata`.
- [DONE] Define the request, response, and protocol types for LLM, memory, tools, workflow state, trace, policy, and configuration.
- [DONE] Keep gateway operations async-first.
- [DONE] Normalize provider-specific details behind logical request and response objects.
- [DONE] Keep component and policy action names explicit so traces and authorization checks remain consistent in later phases.
- [DONE] Ensure the contracts describe capability boundaries only; they must not initialize clients, open connections, or perform I/O.

**Validation**

- [DONE] Add and pass import tests proving all contract modules can be imported together.
- [DONE] Confirm fake implementations can satisfy these protocols in the next phase without changing contract definitions.

**Exit criteria**

- [DONE] The backend has stable protocols for agents, strategies, gateways, stores, policy, and configuration.
- [DONE] No contract module imports provider SDKs, MCP clients, SQLite clients, ArcadeDB clients, or `memory_store` concrete types.

### [DONE] Phase 3. Fake Implementations and Test Helpers

**Goal**

Provide deterministic fake implementations so orchestration and agent behavior can be tested before real infrastructure exists.

**Files to create**

- `backend/app/testing/fakes/fake_llm.py`
- `backend/app/testing/fakes/fake_memory.py`
- `backend/app/testing/fakes/fake_tools.py`
- `backend/app/testing/fakes/fake_state.py`
- `backend/app/testing/fakes/fake_trace.py`
- `backend/app/testing/fakes/fake_policy.py`
- `backend/app/testing/fakes/fake_config.py`
- `backend/app/testing/fakes/fake_agent.py`
- `backend/app/testing/fakes/fake_strategy.py`

**Files created**

- [DONE] `backend/app/testing/fakes/fake_llm.py`
- [DONE] `backend/app/testing/fakes/fake_memory.py`
- [DONE] `backend/app/testing/fakes/fake_tools.py`
- [DONE] `backend/app/testing/fakes/fake_state.py`
- [DONE] `backend/app/testing/fakes/fake_trace.py`
- [DONE] `backend/app/testing/fakes/fake_policy.py`
- [DONE] `backend/app/testing/fakes/fake_config.py`
- [DONE] `backend/app/testing/fakes/fake_agent.py`
- [DONE] `backend/app/testing/fakes/fake_strategy.py`

**Implementation tasks**

- [DONE] Implement deterministic fake gateway and store classes that satisfy the contract protocols.
- [DONE] Implement a fake agent that calls the fake LLM through `OrchestrationContext` rather than touching concrete infrastructure directly.
- [DONE] Implement a fake direct strategy that executes one agent and returns a normalized `OrchestrationResult`.
- [DONE] Keep fake implementations stateful enough for assertions, such as recording requests, tool calls, writes, and trace events.
- [DONE] Keep fakes lightweight and in-memory only.
- [DONE] Avoid embedding production logic in the fakes; they should exist to prove the contracts are usable.

**Validation**

- [DONE] Add and pass tests that build a complete fake `OrchestrationContext` with all fake dependencies.
- [DONE] Add and pass tests showing that the fake strategy can execute the fake agent and return a normalized orchestration result.

**Exit criteria**

- [DONE] The backend can exercise contract-driven agent and strategy flows without real external services.
- [DONE] Each gateway and store contract has at least one matching fake implementation.

### [DONE] Phase 4. Contract Tests and Quality Gates

**Goal**

Make the contract layer safe to extend by enforcing unit coverage and backend-local static checks.

**Files to create**

- `backend/tests/unit/contracts/test_context_models.py`
- `backend/tests/unit/contracts/test_result_models.py`
- `backend/tests/unit/contracts/test_fake_gateways.py`
- `backend/tests/unit/contracts/test_fake_agent_strategy.py`

**Files created**

- [DONE] `backend/tests/unit/contracts/test_context_models.py`
- [DONE] `backend/tests/unit/contracts/test_result_models.py`
- [DONE] `backend/tests/unit/contracts/test_fake_gateways.py`
- [DONE] `backend/tests/unit/contracts/test_fake_agent_strategy.py`

**Implementation tasks**

- [DONE] Cover construction and default behavior for the shared dataclass models.
- [DONE] Cover the fake gateway, store, and policy implementations.
- [DONE] Cover fake agent and fake strategy execution using a complete `OrchestrationContext`.
- [DONE] Add focused assertions that contract tests do not require network calls, external processes, SQLite, ArcadeDB, MCP, or `memory_store`.
- [DONE] Keep tests isolated to the contract slice and do not broaden them into future API, persistence, or provider behavior.
- [DONE] Verify that backend-local commands remain the source of truth for validation.

**Validation**

- [DONE] From `backend/`, run `pytest tests/unit/contracts`.
- [DONE] From `backend/`, run `pytest`.
- [DONE] From `backend/`, run `ruff check .`.
- [DONE] From `backend/`, run `mypy app`.

**Exit criteria**

- [DONE] The contract layer is covered by focused unit tests.
- [DONE] Backend-local test, lint, and type-check commands pass without requiring external services.

### [DONE] Phase 5. Contract Freeze and Handoff

**Goal**

Close the contract slice cleanly so later backend phases can build on stable shared types and protocols instead of revisiting them.

**Implementation tasks**

- [DONE] Confirm the acceptance criteria from `backend-core-contracts-architecture.md` have been met.
- [DONE] Keep the public contract surfaces stable:
  - `backend/app/contracts/context.py`
  - `backend/app/contracts/results.py`
  - `backend/app/contracts/errors.py`
  - `backend/app/contracts/health.py`
  - `backend/app/contracts/agents.py`
  - `backend/app/contracts/strategies.py`
  - `backend/app/contracts/llm.py`
  - `backend/app/contracts/memory.py`
  - `backend/app/contracts/tools.py`
  - `backend/app/contracts/state.py`
  - `backend/app/contracts/trace.py`
  - `backend/app/contracts/policy.py`
  - `backend/app/contracts/config.py`
- [DONE] Record intentional deferrals around real adapters, configuration validation, API DTO mapping, routing strategies, session behavior, and persistence implementations in `backend/README.md`.
- [DONE] Make sure later architecture documents build on these backend-local paths rather than referring to source locations outside `backend/`.

**Validation**

- Re-run the full backend contract check from `backend/`:
   - [DONE] `pytest tests/unit/contracts`
   - [DONE] `pytest`
   - [DONE] `ruff check .`
   - [DONE] `mypy app`

**Exit criteria**

- [DONE] The backend core contract layer is complete and ready for later configuration, persistence, API, tooling, orchestration, and agent implementation phases.

---

## 6. Recommended Delivery Slices

To keep changes reviewable, the phases above should be delivered in small pull-request-sized slices:

1. **Base contracts slice**  
   `backend/app/contracts/__init__.py`, `context.py`, `results.py`, `errors.py`, `health.py`, and the first model-construction tests.

2. **Protocol slice**  
   `backend/app/contracts/agents.py`, `strategies.py`, `llm.py`, `memory.py`, `tools.py`, `state.py`, `trace.py`, `policy.py`, and `config.py`.

3. **Fakes slice**  
   `backend/app/testing/fakes/` implementations plus any shared test helpers needed for context construction.

4. **Contract test slice**  
   `backend/tests/unit/contracts/` coverage for models, fakes, and fake agent/strategy execution.

5. **Freeze slice**  
   final cleanup, static checks, deferred-work notes, and acceptance review.

---

## 7. Validation Matrix

All validation for backend core contract work should be run from `backend/`.

| Check | Command | Purpose |
|---|---|---|
| Focused contract tests | `pytest tests/unit/contracts` | Verifies the contract layer and fake implementations in isolation. |
| Full backend unit tests | `pytest` | Confirms the new contract slice does not regress the existing backend foundation. |
| Lint | `ruff check .` | Enforces code-quality rules across the backend project. |
| Type check | `mypy app` | Validates the backend source tree, including protocol and dataclass typing. |
| Import smoke check | `python -c "from app.contracts.context import RequestContext; from app.testing.fakes.fake_llm import FakeLLMGateway"` | Confirms the new packages import cleanly from the backend project root. |

---

## 8. Done Definition

The implementation plan is complete when the delivered backend core-contract slice satisfies all of the following:

- backend contract source exists only under `backend/`
- shared contract modules live under `backend/app/contracts/`
- fake implementations live under `backend/app/testing/fakes/`
- contract tests live under `backend/tests/unit/contracts/`
- contract modules import without concrete infrastructure dependencies
- `RequestContext` and `OrchestrationContext` can be constructed in tests
- `AgentPlugin` and `OrchestrationStrategy` can be implemented by fakes
- LLM access is represented only by `LLMGateway`
- memory access is represented only by `MemoryGateway`
- tool access is represented only by `ToolGateway`
- workflow state access is represented only by `WorkflowStateStore`
- trace persistence is represented only by `TraceStore`
- policy decisions are represented only by `PolicyService`
- configuration access is represented by `ConfigurationView` and `ConfigurationLoader`
- contract tests pass from `backend/`
- no contract, fake, agent, or strategy module imports provider SDKs, MCP clients, SQLite clients, ArcadeDB clients, or `memory_store` concrete types

---

## 9. Next Step After This Plan

Once this slice is complete, the next backend architecture and implementation targets should build directly on these contracts, starting with:

- backend configuration view and loader integration
- backend API request and response mapping onto `RequestContext` and `OrchestrationResult`
- backend workflow-state and trace-store implementations
- backend LLM, memory, and tool gateway adapters
- backend orchestration runtime and first walking-skeleton chat flow

Those later phases should extend the `backend/` project tree created here, not bypass it.