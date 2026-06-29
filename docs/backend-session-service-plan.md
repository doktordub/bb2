# Backend Session Service Implementation Plan

**Document:** `backend-session-service-plan.md`  
**Version:** 1.0  
**Source alignment:** `backend-session-service-architecture.md`, `backend-api-plan.md`, `backend-persistence-plan.md`, and the current backend implementation baseline  
**Repository rule:** all backend application code lives under `backend/`

---

## 1. Purpose

This plan converts the session-service architecture into an implementation sequence that can be delivered in small, low-risk phases.

The plan is intentionally strict about repository boundaries:

- Backend application code belongs in `backend/`.
- Backend source modules belong in `backend/app/`.
- Backend tests belong in `backend/tests/`.
- Backend configuration files belong in `backend/config/`.
- Backend local data files belong in `backend/data/`.
- Documentation updates belong in `docs/`.
- No backend runtime, session, orchestration, or adapter code should be placed in the repository root, `frontend/`, or `mcp/`.

For clarity, this document uses filesystem paths such as `backend/app/session/service.py`. Python imports may still use the `app.*` package path because `backend/` is the Python project root.

---

## 2. Review Outcomes

The session-service architecture document is implementation-ready and aligns well with the completed backend foundation, configuration, observability, persistence, workflow-state, trace-store, and API work. It is strong on boundaries, lifecycle rules, trace safety, reset semantics, and sequencing.

The review also confirms that this phase is not greenfield work. The repository already contains a meaningful session walking skeleton under `backend/` that should be deepened rather than replaced:

- `backend/app/session/service.py` already defines the public `SessionService` protocol plus a `WalkingSkeletonSessionService` that exercises the real workflow-state and trace-store paths.
- `backend/app/session/models.py` and `backend/app/session/errors.py` already provide the initial session result/event surface consumed by the API layer.
- `backend/app/api/routes_chat.py` and `backend/app/api/routes_sessions.py` already delegate chat, stream, and reset behavior to `session_service`.
- `backend/app/config/bootstrap.py` already wires a session service into the backend composition root during lifespan startup.
- `backend/app/foundation/container.py` already carries `session_service` through the shared runtime container.
- `backend/app/contracts/context.py` and `backend/app/contracts/results.py` already define the current core request/result models that the deeper session layer should continue to reuse.
- `backend/app/contracts/state.py` and `backend/app/persistence/sqlite_workflow_state_store.py` already provide the session-facing workflow-state contract and concrete SQLite implementation.
- `backend/app/testing/fakes/fake_session_service.py` and `backend/app/testing/fakes/fake_state.py` already provide deterministic test doubles.
- `backend/tests/integration/test_api_chat_fake_session.py`, `backend/tests/integration/test_api_streaming_sse.py`, `backend/tests/integration/test_api_reset_boundary.py`, and `backend/tests/integration/test_workflow_state_store_sqlite_smoke.py` already prove the current API/session/state vertical slice.

The main implementation concerns that must be resolved during execution are:

1. **Dedicated session settings do not exist yet.**  
   The current backend config exposes `api.sessions` transport settings in `backend/config/app.yaml` and `backend/app/config/view.py`, but the architecture requires a top-level `session` runtime section for identifiers, lifecycle, concurrency, history, state-save policy, and trace toggles.

2. **The current session service is still API-coupled.**  
   `backend/app/session/service.py` imports `backend/app/api/request_context.py` and `backend/app/api/schemas.py`. The long-term design requires session-owned DTOs and mapping helpers so the session layer stops depending on API request/response models.

3. **The public workflow-state contract is thinner than the real store behavior.**  
   `backend/app/contracts/state.py` still exposes `load/save/reset` as plain dict-based methods, while `backend/app/persistence/sqlite_workflow_state_store.py` already tracks versions, reset generations, and conflict conditions internally. The session-service phase needs that richer information exposed through the contract for optimistic concurrency, safe history, and streaming finalization.

4. **No dedicated orchestration runtime package exists yet.**  
   There is no `backend/app/orchestration/` package today. This phase should add a narrow runtime protocol there, while continuing to reuse `backend/app/contracts/context.py` and `backend/app/contracts/results.py` instead of duplicating core request/result DTOs.

5. **The session package is still too thin for the architecture boundary.**  
   The current package contains only `backend/app/session/service.py`, `backend/app/session/models.py`, and `backend/app/session/errors.py`. The architecture requires dedicated helpers for identifiers, mapping, lifecycle/state shaping, history, concurrency, and settings.

6. **Session-specific quality gates are still missing.**  
   The current repository has API and persistence coverage, but it does not yet have the dedicated `backend/tests/unit/session/` and `backend/tests/integration/session/` suites described by the architecture.

7. **Capabilities are ahead of implementation in one place and behind it in another.**  
   `backend/app/foundation/capabilities.py` already exposes reset and client-session-ID support, but `history_enabled` is still hard-coded to `false` instead of being derived from validated session settings and service readiness.

---

## 3. Non-Negotiable Boundary Rules

- Treat `backend/` as the Python project root for all session-service work.
- Create runtime session modules only under `backend/app/session/`.
- Create the orchestration runtime protocol only under `backend/app/orchestration/`.
- Keep backend contracts under `backend/app/contracts/`.
- Keep backend test code under `backend/tests/`.
- Keep backend configuration under `backend/config/` and backend-local data under `backend/data/`.
- Keep documentation-only artifacts under `docs/`.
- Do not place backend session, orchestration, or workflow-state code in the repository root, `frontend/`, or `mcp/`.
- Do not let any module outside `backend/app/persistence/` import `sqlite3`, `aiosqlite`, or other concrete database clients.
- Do not let `backend/app/session/` import FastAPI request/response types, API route modules, LLM provider SDKs, `memory_store.service.MemoryService`, MCP clients, or tool/agent implementations.
- Reuse `backend/app/contracts/context.py` and `backend/app/contracts/results.py` as the core request/result DTO layer unless a contract gap makes a focused additive change necessary.
- Keep `backend/app/main.py:app = create_app()` import-safe; runtime I/O and store initialization must stay in lifespan startup.
- Session reset must remain workflow-state-only. It must not delete memory, document chunks, traces, configuration, or other sessions.
- Logs, traces, health responses, and history responses must not expose raw message text by default, raw workflow state, raw provider payloads, raw tool payloads, secrets, tokens, cookies, or connection strings.

---

## 4. Phase Overview

| Phase | Name | Primary Outcome |
|---|---|---|
| 0 | [DONE] Current API/Session Walking Skeleton Baseline | The repository already has a working API -> session -> workflow-state vertical slice rooted under `backend/`. |
| 1 | [DONE] Session Configuration and Settings Alignment | A dedicated top-level `session` config section and typed session settings exist under `backend/app/config/`. |
| 2 | [DONE] Session DTOs, Identifiers, and Error Boundary | The session layer owns its request/context/history models, identifier helpers, and error taxonomy instead of leaning on API DTOs. |
| 3 | [DONE] Workflow-State Contract Deepening | Version-aware load/save/reset results are exposed through `backend/app/contracts/state.py` and implemented by the existing persistence layer. |
| 4 | [DONE] Non-Streaming Session Service Deepening | `DefaultSessionService.handle_chat` performs create/resume/load/run/save through a runtime protocol instead of the current inline echo logic. |
| 5 | [DONE] Streaming Finalization and Concurrency | `stream_chat` accumulates assistant output safely, finalizes once, and enforces optimistic conflict handling. |
| 6 | [DONE] Reset, History, Health, and Capability Surfacing | Reset remains workflow-state-only while optional history, health, and capabilities become config-driven and safe. |
| 7 | [DONE] Composition Root, Fakes, and Focused Quality Gates | Startup wiring, fakes, fixtures, and dedicated unit/integration suites validate the full session-service slice under `backend/`. |
| 8 | [DONE] Freeze and Handoff | The stable session-service boundary is documented and verified before the later LLM, memory, tooling, and orchestration phases. |

---

## 5. Detailed Implementation Phases

### [DONE] Phase 0. Current API/Session Walking Skeleton Baseline

**Goal**

Record the session-related work that already exists so the implementation plan extends the current backend instead of re-describing a greenfield slice.

**Files already present**

- [DONE] `backend/app/session/service.py`
- [DONE] `backend/app/session/models.py`
- [DONE] `backend/app/session/errors.py`
- [DONE] `backend/app/testing/fakes/fake_session_service.py`
- [DONE] `backend/app/testing/fakes/fake_state.py`
- [DONE] `backend/app/api/routes_chat.py`
- [DONE] `backend/app/api/routes_sessions.py`
- [DONE] `backend/app/api/dependencies.py`
- [DONE] `backend/app/config/bootstrap.py`
- [DONE] `backend/app/foundation/container.py`
- [DONE] `backend/app/foundation/capabilities.py`
- [DONE] `backend/app/contracts/context.py`
- [DONE] `backend/app/contracts/results.py`
- [DONE] `backend/app/contracts/state.py`
- [DONE] `backend/app/persistence/sqlite_workflow_state_store.py`
- [DONE] `backend/tests/integration/test_api_chat_fake_session.py`
- [DONE] `backend/tests/integration/test_api_streaming_sse.py`
- [DONE] `backend/tests/integration/test_api_reset_boundary.py`
- [DONE] `backend/tests/integration/test_workflow_state_store_sqlite_smoke.py`

**Implementation outcomes already in place**

- [DONE] The API routes already delegate chat, stream, and reset behavior to a session-service boundary.
- [DONE] The current walking skeleton already exercises the real workflow-state store and trace recorder instead of keeping all behavior in a fake route layer.
- [DONE] The current non-streaming path already resolves a session ID, loads workflow state, appends user/assistant messages, saves state, and returns a stable `SessionChatResult`.
- [DONE] The current streaming path already emits ordered stream events and finalizes workflow state only once on completion.
- [DONE] The current reset path already clears workflow state without calling memory or trace deletion paths.
- [DONE] Lifespan startup already wires `session_service` into `FoundationContainer` under `backend/app/config/bootstrap.py`.

**Current limitations that the next phases must fix**

- The session service still imports API DTOs and request-context models directly.
- There is no dedicated `backend/app/orchestration/` runtime package.
- The public session protocol does not yet expose `get_history`.
- The public workflow-state contract does not yet expose version-aware results.
- The backend does not yet have the dedicated `backend/tests/unit/session/` and `backend/tests/integration/session/` suites described by the architecture.

**Exit criteria**

- [DONE] The implementation plan starts from the real `backend/` baseline and extends it rather than replacing it.

### [DONE] Phase 1. Session Configuration and Settings Alignment

**Goal**

Add a dedicated top-level `session` configuration section and typed session settings while keeping HTTP transport settings under `api.sessions`.

**Files to create or update**

- [DONE] `backend/app/config/schemas.py`
- [DONE] `backend/app/config/validation.py`
- [DONE] `backend/app/config/view.py`
- [DONE] `backend/config/app.yaml`
- [DONE] `backend/tests/unit/config/test_config_view.py`
- [DONE] `backend/tests/unit/config/test_validation.py`
- [DONE] `backend/tests/fixtures/config/session_basic.yaml`
- [DONE] `backend/tests/fixtures/config/session_history_enabled.yaml`
- [DONE] `backend/tests/fixtures/config/session_reject_unknown_client_id.yaml`
- [DONE] `backend/tests/fixtures/config/session_streaming.yaml`

**Implementation tasks**

- [DONE] Add a top-level `session:` section in `backend/config/app.yaml` for:
  - identifier settings
  - default user/usecase/history settings
  - lifecycle toggles
  - concurrency policy
  - state save/finalization policy
  - history settings
  - session trace toggles
- [DONE] Keep API transport concerns such as `session_id_header` under `api.sessions`.
- [DONE] Resolve ownership between `api.sessions.accept_client_session_id` and the new `session.identifiers.accept_client_session_id` so only one typed runtime source controls actual lifecycle behavior.
- [DONE] Add typed settings dataclasses and helpers in `backend/app/config/view.py`, such as:
  - `SessionIdentifierSettings`
  - `SessionDefaultsSettings`
  - `SessionLifecycleSettings`
  - `SessionConcurrencySettings`
  - `SessionStateSettings`
  - `SessionHistorySettings`
  - `SessionTracingSettings`
  - `SessionSettings`
- [DONE] Add a typed accessor such as `session_settings()` or `get_session_settings()` so runtime modules stop reading raw nested config keys directly.
- [DONE] Validate identifier patterns, limits, max retries, and mutually inconsistent save flags at config-load time.
- [DONE] Keep all config defaults backend-rooted and documentation/backend references explicit to `backend/config/` and `backend/data/`.

**Validation**

- [DONE] Add and pass focused config-view and validation tests for the new `session` section.
- [DONE] Run `.venv\Scripts\python.exe -m pytest tests/unit/config/test_config_view.py tests/unit/config/test_validation.py` from `backend/`.
- [DONE] Run `.venv\Scripts\python.exe -m ruff check app/config tests/unit/config/test_config_view.py tests/unit/config/test_validation.py` from `backend/`.

**Exit criteria**

- [DONE] Session lifecycle behavior is driven by typed `SessionSettings`, not by scattered raw config lookups.
- [DONE] HTTP transport settings remain in `api.*`, while domain lifecycle behavior moves to `session.*`.
- [DONE] Invalid session lifecycle configuration fails fast during backend startup.

### [DONE] Phase 2. Session DTOs, Identifiers, and Error Boundary

**Goal**

Make the session layer own its request/context/history models, identifier rules, and error taxonomy so it stops depending on API DTOs.

**Files to create or update**

- [DONE] `backend/app/session/__init__.py`
- [DONE] `backend/app/session/models.py`
- [DONE] `backend/app/session/errors.py`
- [DONE] `backend/app/session/identifiers.py`
- [DONE] `backend/app/session/mapping.py`
- [DONE] `backend/app/session/settings.py`
- [DONE] `backend/app/api/routes_chat.py`
- [DONE] `backend/app/api/routes_sessions.py`
- [DONE] `backend/app/testing/fakes/fake_session_id_provider.py`
- [DONE] `backend/tests/unit/session/test_session_id_provider.py`
- [DONE] `backend/tests/unit/session/test_session_request_mapping.py`
- [DONE] `backend/tests/unit/session/test_session_error_mapping.py`

**Implementation tasks**

- [DONE] Add session-owned request and context models in `backend/app/session/models.py`:
  - `SessionRequestContext`
  - `SessionChatRequest`
  - `SessionHistoryMessage`
  - `SessionHistoryResult`
- [DONE] Preserve the existing API-facing result shapes in `SessionChatResult` and `SessionResetResult` so response DTO mapping stays stable.
- [DONE] Extend `SessionStreamEvent` with the minimum additional fields needed by the architecture, such as `sequence_no`, without forcing a wire-format change in the API layer.
- [DONE] Add `SessionIdProvider` and validation helpers in `backend/app/session/identifiers.py`.
- [DONE] Add a deterministic fake ID provider for unit tests under `backend/app/testing/fakes/fake_session_id_provider.py`.
- [DONE] Move API-to-session and session-to-core mapping helpers into `backend/app/session/mapping.py`.
- [DONE] Update `backend/app/api/routes_chat.py` and `backend/app/api/routes_sessions.py` so they map API DTOs into session DTOs before calling the service.
- [DONE] Expand `backend/app/session/errors.py` to include the architecture-required taxonomy, including:
  - `InvalidSessionIdError`
  - `SessionIdRequiredError`
  - `SessionNotFoundError`
  - `SessionConflictError`
  - `SessionStateUnavailableError`
  - `SessionResetFailedError`
  - `SessionHistoryDisabledError`
  - `SessionHistoryUnavailableError`
- [DONE] Keep `backend/app/session/` free of FastAPI imports and route-module dependencies after this phase.

**Validation**

- [DONE] Add and pass focused unit tests for session ID generation/validation and request mapping.
- [DONE] Run `.venv\Scripts\python.exe -m pytest tests/unit/session/test_session_id_provider.py tests/unit/session/test_session_request_mapping.py tests/unit/session/test_session_error_mapping.py` from `backend/`.
- [DONE] Run `.venv\Scripts\python.exe -m ruff check app/session app/api/routes_chat.py app/api/routes_sessions.py tests/unit/session` from `backend/`.
- `mypy` remains deferred for this phase; it was not run as part of this change.

**Exit criteria**

- [DONE] The session layer owns its input/context/history DTOs.
- [DONE] API routes adapt into the session layer instead of the session layer importing API request models.
- [DONE] Session identifier and session-error behavior are explicit and testable.

### [DONE] Phase 3. Workflow-State Contract Deepening

**Goal**

Expose the version-aware workflow-state behavior that already exists in SQLite through the public contract so the session layer can implement optimistic concurrency safely.

**Files to create or update**

- [DONE] `backend/app/contracts/state.py`
- [DONE] `backend/app/persistence/sqlite_workflow_state_store.py`
- [DONE] `backend/app/testing/fakes/fake_state.py`
- [DONE] `backend/app/persistence/errors.py`
- [DONE] `backend/tests/unit/persistence/test_fake_workflow_state_store.py`
- [DONE] `backend/tests/unit/persistence/test_sqlite_workflow_state_serialization.py`
- [DONE] `backend/tests/unit/persistence/test_sqlite_workflow_state_reset.py`
- [DONE] `backend/tests/integration/test_workflow_state_store_concurrency.py`
- [DONE] `backend/tests/integration/test_workflow_state_store_sqlite_smoke.py`

**Implementation tasks**

- [DONE] Extend `backend/app/contracts/state.py` with structured public dataclasses such as:
  - `WorkflowStateRecord`
  - `WorkflowStateSaveResult`
  - `WorkflowStateResetResult`
- [DONE] Deepen `WorkflowStateStore` so it can support:
  - `load(session_id) -> WorkflowStateRecord`
  - `save(session_id, state, expected_version, metadata) -> WorkflowStateSaveResult`
  - `reset(session_id, reason, metadata) -> WorkflowStateResetResult`
- [DONE] Preserve `default_workflow_state()` and `normalize_workflow_state_session_id()` as the canonical shared helpers so session code does not fork identifier or empty-state logic.
- [DONE] Surface the existing SQLite store’s internal version, reset-generation, and conflict behavior through the public contract instead of hiding it behind `None`-returning methods.
- [DONE] Update `backend/app/testing/fakes/fake_state.py` so tests can simulate:
  - deterministic version increments
  - conflict failures
  - empty-state loads
  - reset generations
- [DONE] Keep all SQLite-specific logic inside `backend/app/persistence/` and avoid leaking SQL details into `backend/app/session/`.

**Validation**

- [DONE] Add and pass unit tests for version-aware fake-store behavior and contract serialization rules.
- [DONE] Re-run the existing SQLite workflow-state smoke and concurrency tests.
- [DONE] Run `.venv\Scripts\python.exe -m pytest tests/unit/persistence/test_fake_workflow_state_store.py tests/unit/persistence/test_sqlite_workflow_state_serialization.py tests/unit/persistence/test_sqlite_workflow_state_reset.py tests/integration/test_workflow_state_store_sqlite_smoke.py tests/integration/test_workflow_state_store_concurrency.py` from `backend/`.

**Exit criteria**

- [DONE] The workflow-state contract exposes enough metadata for optimistic session concurrency.
- [DONE] Session-service code no longer has to infer version semantics from raw state dicts.
- [DONE] Fake and SQLite workflow-state stores behave consistently at the contract boundary.

### [DONE] Phase 4. Non-Streaming Session Service Deepening

**Goal**

Replace the inline walking-skeleton chat behavior with a real session-service implementation that delegates reasoning to a runtime protocol and owns only session continuity.

**Files to create or update**

- [DONE] `backend/app/orchestration/__init__.py`
- [DONE] `backend/app/orchestration/core.py`
- [DONE] `backend/app/session/service.py`
- [DONE] `backend/app/session/lifecycle.py`
- [DONE] `backend/app/session/mapping.py`
- [DONE] `backend/app/testing/fakes/fake_orchestration_runtime.py`
- [DONE] `backend/app/testing/fakes/fake_clock.py`
- [DONE] `backend/tests/unit/session/test_session_handle_chat.py`
- [DONE] `backend/tests/unit/session/test_session_trace_events.py`
- [DONE] `backend/tests/integration/session/test_session_with_sqlite_workflow_state_store.py`

**Implementation tasks**

- [DONE] Add `backend/app/orchestration/core.py` with the narrow `OrchestrationRuntime` protocol.
- [DONE] Reuse `backend/app/contracts/context.py:RequestContext` and `backend/app/contracts/results.py:OrchestrationResult` instead of creating duplicate request/result models.
- [DONE] Add a real `DefaultSessionService` implementation alongside the current walking skeleton, or replace the walking skeleton in place once tests cover the new behavior.
- [DONE] Move create/resume/load/save and state-shaping logic into dedicated helpers under `backend/app/session/lifecycle.py`.
- [DONE] Implement `handle_chat` so it:
  - resolves or creates the session ID
  - resolves the effective use case from validated config
  - loads workflow state once
  - builds the core `RequestContext`
  - appends the user message to a draft state
  - calls `OrchestrationRuntime.run(...)`
  - applies the result to state
  - saves exactly once with `expected_version`
  - records safe session lifecycle trace events
  - returns a stable `SessionChatResult`
- [DONE] Keep raw message bodies out of traces and logs; only safe counts, flags, and bounded metadata should be recorded.
- [DONE] Keep the runtime implementation fake/echo-based for now if needed, but move that behavior behind the runtime protocol instead of keeping it inside the session service.

**Validation**

- [DONE] Add and pass unit tests for `handle_chat` load/run/save sequencing and trace safety.
- [DONE] Add and pass an integration test that runs the service against the real SQLite workflow-state store.
- [DONE] Run `.venv\Scripts\python.exe -m pytest tests/unit/session/test_session_handle_chat.py tests/unit/session/test_session_trace_events.py tests/integration/session/test_session_with_sqlite_workflow_state_store.py` from `backend/`.
- [DONE] Run `.venv\Scripts\python.exe -m ruff check app/session app/orchestration tests/unit/session tests/integration/session` from `backend/`.
- [DONE] Run `.venv\Scripts\python.exe -m mypy app/session app/orchestration` from `backend/`.

**Exit criteria**

- [DONE] Non-streaming chat flows through a runtime protocol rather than inline echo logic.
- [DONE] The session service owns session continuity and state boundaries, not orchestration decisions.
- [DONE] Successful non-streaming chat loads once and saves once.

### [DONE] Phase 5. Streaming Finalization and Concurrency

**Goal**

Deepen the streaming path so it accumulates assistant output safely, finalizes state once, and behaves predictably under optimistic conflicts.

**Files to create or update**

- [DONE] `backend/app/session/service.py`
- [DONE] `backend/app/session/streaming.py`
- [DONE] `backend/app/session/concurrency.py`
- [DONE] `backend/app/testing/fakes/fake_orchestration_runtime.py`
- [DONE] `backend/tests/unit/session/test_session_stream_chat.py`
- [DONE] `backend/tests/unit/session/test_session_concurrency.py`
- [DONE] `backend/tests/integration/session/test_session_streaming_finalization.py`
- [DONE] `backend/tests/integration/session/test_session_with_api_chat_route.py`

**Implementation tasks**

- [DONE] Add dedicated streaming helpers in `backend/app/session/streaming.py` for:
  - event mapping
  - assistant-delta accumulation
  - completion finalization
  - cancellation/failure checkpoint shaping
- [DONE] Add a small concurrency helper in `backend/app/session/concurrency.py` that centralizes conflict-policy decisions for chat, stream, and reset operations.
- [DONE] Implement `stream_chat` so it:
  - resolves session ID and use case once
  - loads workflow state once at stream start
  - builds one draft state before runtime streaming begins
  - yields safe `SessionStreamEvent` values only
  - never saves workflow state on every token/delta
  - saves exactly once on completion
  - optionally saves one cancellation/failure checkpoint when configured
  - maps optimistic version conflicts to `SessionConflictError`
- [DONE] Validate the reset-during-stream case through expected-version mismatch rather than in-process lock tricks.
- [DONE] Keep the API SSE surface unchanged unless the architecture requires additive metadata such as `sequence_no`.

**Validation**

- [DONE] Add and pass unit tests proving that streaming does not save per delta and does save once on completion.
- [DONE] Add and pass integration tests for streaming finalization and stream/API integration.
- [DONE] Run `.venv\Scripts\python.exe -m pytest tests/unit/session/test_session_stream_chat.py tests/unit/session/test_session_concurrency.py tests/integration/session/test_session_streaming_finalization.py tests/integration/session/test_session_with_api_chat_route.py` from `backend/`.

**Exit criteria**

- [DONE] Streaming state is loaded once and saved once.
- [DONE] Cancellation, failure, and conflict paths are explicit and test-covered.
- [DONE] The session layer does not rely on ad hoc global in-process locks for correctness.

### [DONE] Phase 6. Reset, History, Health, and Capability Surfacing

**Goal**

Finish the remaining service-level lifecycle behaviors while keeping reset safe and optional history bounded and disabled by default.

**Files to create or update**

- [DONE] `backend/app/session/service.py`
- [DONE] `backend/app/session/history.py`
- [DONE] `backend/app/session/errors.py`
- [DONE] `backend/app/api/errors.py`
- [DONE] `backend/app/api/schemas.py`
- [DONE] `backend/app/api/routes_sessions.py`
- [DONE] `backend/app/foundation/capabilities.py`
- `backend/app/foundation/health.py`
- [DONE] `backend/tests/unit/session/test_session_reset.py`
- [DONE] `backend/tests/unit/session/test_session_history.py`
- [DONE] `backend/tests/unit/api/test_error_mapping.py`
- [DONE] `backend/tests/unit/test_capabilities.py`
- [DONE] `backend/tests/integration/session/test_session_reset_clears_workflow_state_only.py`

**Implementation tasks**

- [DONE] Deepen `reset_session` so it passes reason and safe request metadata through the version-aware workflow-state contract.
- [DONE] Add `get_history(...)` to the public session-service boundary, backed by `backend/app/session/history.py`.
- [DONE] Keep history disabled by default unless validated config enables it.
- [DONE] Ensure history projection returns only bounded user/assistant-safe content and never returns raw workflow state, scratchpads, provider payloads, or tool payloads.
- [DONE] Expand API error mapping for the richer session error taxonomy.
- [DONE] Stop hard-coding `history_enabled` to `false` in `backend/app/foundation/capabilities.py`; derive it from validated session settings and actual service availability.
- Optionally expose a small session-health surface in `backend/app/foundation/health.py` if that improves readiness reporting without leaking session data.
- [DONE] Verify reset does not delete traces or call memory deletion paths.

**Validation**

- [DONE] Add and pass focused unit tests for reset behavior, history projection, and API error mapping.
- [DONE] Add and pass an integration test proving reset clears workflow state only.
- [DONE] Run `.venv\Scripts\python.exe -m pytest tests/unit/session/test_session_reset.py tests/unit/session/test_session_history.py tests/unit/api/test_error_mapping.py tests/unit/test_capabilities.py tests/integration/session/test_session_reset_clears_workflow_state_only.py` from `backend/`.

**Exit criteria**

- [DONE] Reset remains workflow-state-only.
- [DONE] Optional history is bounded, redacted, and config-driven.
- [DONE] Capability and health outputs reflect real session settings rather than hard-coded defaults.

### [DONE] Phase 7. Composition Root, Fakes, and Focused Quality Gates

**Goal**

Wire the deeper session service into the backend composition root and add the dedicated fakes, fixtures, and tests required to keep the slice stable.

**Files to create or update**

- [DONE] `backend/app/config/bootstrap.py`
- [DONE] `backend/app/foundation/container.py`
- [DONE] `backend/app/testing/fakes/fake_session_service.py`
- [DONE] `backend/app/testing/fakes/fake_orchestration_runtime.py`
- [DONE] `backend/app/testing/fakes/fake_trace_recorder.py`
- [DONE] `backend/app/testing/fakes/fake_clock.py`
- [DONE] `backend/tests/fixtures/config/session_basic.yaml`
- [DONE] `backend/tests/fixtures/config/session_history_disabled.yaml`
- [DONE] `backend/tests/fixtures/config/session_history_enabled.yaml`
- [DONE] `backend/tests/fixtures/config/session_conflict_reject.yaml`
- [DONE] `backend/tests/fixtures/config/session_streaming.yaml`
- [DONE] `backend/tests/fixtures/config/session_with_real_sqlite_store.yaml`
- [DONE] `backend/tests/unit/test_app_factory.py`
- [DONE] `backend/tests/unit/session/`
- [DONE] `backend/tests/integration/session/`

**Implementation tasks**

- [DONE] Update `backend/app/config/bootstrap.py` so lifespan startup constructs the real `DefaultSessionService` and its runtime dependency.
- [DONE] Keep import-time app creation free of store I/O and external-service startup.
- [DONE] Decide whether the old `WalkingSkeletonSessionService` remains as a test-only shim or is removed after the runtime-backed service is stable.
- [DONE] Expand fake dependencies so session tests can run without real SQLite or future LLM/memory/tooling integrations.
- [DONE] Create dedicated fixture configs for session lifecycle modes, history toggles, conflict policy, and real-store integration.
- [DONE] Move primary session behavior verification into `backend/tests/unit/session/` and `backend/tests/integration/session/`, leaving route-thinness tests in API suites.

**Validation**

- [DONE] Run `.venv\Scripts\python.exe -m pytest tests/unit/session tests/integration/session tests/unit/test_app_factory.py tests/integration/test_api_streaming_sse.py tests/integration/test_api_reset_boundary.py` from `backend/`.
- [DONE] Run `.venv\Scripts\python.exe -m ruff check app/session app/orchestration app/config/bootstrap.py app/foundation/container.py tests/unit/session tests/integration/session` from `backend/`.
- [DONE] Run `.venv\Scripts\python.exe -m mypy app/session app/orchestration app/config/bootstrap.py app/foundation/container.py` from `backend/`.

**Exit criteria**

- [DONE] Lifespan startup wires the deeper session service instead of the old walking skeleton.
- [DONE] Focused session behavior has dedicated unit and integration coverage under `backend/tests/`.
- [DONE] Future LLM/memory/tooling phases can replace runtime internals without changing the API/session contract.

### [DONE] Phase 8. Freeze and Handoff

**Goal**

Close the session-service phase with documentation, validation, and explicit handoff boundaries for later architecture documents.

**Files to create or update**

- [DONE] `backend/README.md`
- [DONE] `docs/backend-session-service-plan.md`
- [DONE] `docs/backend-api-plan.md`
- [DONE] `docs/backend-llm-gateway-architecture.md` reference targets only; no implementation work belongs there yet

**Implementation tasks**

- [DONE] Update `backend/README.md` with the stable session-service boundary, config surface, test locations, and explicit deferrals.
- [DONE] Mark completed phases in this plan as work finishes.
- [DONE] Update `docs/backend-api-plan.md` so it no longer describes the session service as only a walking skeleton once this phase is complete.
- [DONE] Record the stable handoff points for the next documents:
  - [DONE] LLM gateway
  - [DONE] memory-store adapter
  - [DONE] tooling/MCP client adapter
  - [DONE] orchestration runtime/strategies
  - [DONE] policy
- [DONE] Run the full backend quality gate from `backend/`:
  - [DONE] `.venv\Scripts\python.exe -m pytest`
  - [DONE] `.venv\Scripts\python.exe -m ruff check .`
  - [DONE] `.venv\Scripts\python.exe -m mypy app`

**Exit criteria**

- [DONE] The session-service boundary is documented as stable.
- [DONE] Full backend validation passes from `backend/`.
- [DONE] The next implementation document can deepen the LLM/runtime internals without changing session-service ownership rules.

---

## 6. Acceptance Checklist

This plan should be considered complete when the implementation satisfies all of the following:

- `SessionService` exposes `handle_chat`, `stream_chat`, `reset_session`, and optional `get_history` methods.
- The session layer owns session DTOs instead of depending on API request DTOs.
- `backend/app/session/` no longer imports FastAPI request/response types or API route modules.
- The backend has a typed top-level `session` config section under `backend/config/app.yaml`.
- The session layer uses a narrow runtime protocol under `backend/app/orchestration/`.
- The plan reuses `backend/app/contracts/context.py` and `backend/app/contracts/results.py` instead of duplicating core request/result models.
- The workflow-state contract exposes the version-aware data needed for optimistic concurrency.
- Non-streaming chat loads workflow state once and saves it once on success.
- Streaming chat does not save workflow state on every delta and finalizes state once on completion.
- Reset clears short-term workflow state only.
- Optional history is bounded, redacted, and disabled by default unless config enables it.
- Session errors map cleanly to stable API responses.
- Session lifecycle traces do not include raw message bodies by default.
- Capabilities and optional health output derive from session settings and readiness rather than hard-coded placeholders.
- Dedicated session unit and integration tests live under `backend/tests/`.
- All backend code and tests added for this phase remain rooted under `backend/`.

---

## 7. Anti-Patterns to Avoid

Avoid these during implementation:

- Keeping long-term session logic in `backend/app/api/` instead of `backend/app/session/`.
- Creating new backend runtime modules outside `backend/`.
- Duplicating `RequestContext` or `OrchestrationResult` under a new package when `backend/app/contracts/` already owns them.
- Leaving `backend/app/session/service.py` coupled to `backend/app/api/schemas.py` and `backend/app/api/request_context.py` after the DTO phase.
- Reaching into raw nested config keys throughout runtime session code after typed `SessionSettings` exists.
- Importing `sqlite3` or store-specific types into `backend/app/session/`.
- Calling LLM providers, memory gateways, tool gateways, or MCP clients directly from `backend/app/session/`.
- Saving workflow state on every streamed token.
- Treating session reset as trace deletion or memory deletion.
- Returning raw workflow state through history, health, or capability endpoints.
- Logging or tracing raw chat message bodies by default.
- Implementing session correctness with ad hoc global in-memory locks instead of optimistic versioning.

---

## 8. Handoff Target

Once this plan is implemented and frozen, the next document to deepen should remain:

```text
docs/backend-llm-gateway-architecture.md
```

The session-service layer should be stable enough by then that later LLM, memory, tooling, orchestration, and policy work can change runtime internals without reopening API/session lifecycle ownership.