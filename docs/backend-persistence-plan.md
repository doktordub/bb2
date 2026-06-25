# Backend Persistence Implementation Plan

**Document:** `backend-persistence-plan.md`  
**Version:** 1.0  
**Source alignment:** `backend-persistence-architecture.md`, `backend-observability-plan.md`, and the current backend implementation baseline  
**Repository rule:** all backend application code lives under `backend/`

---

## 1. Purpose

This plan converts the backend persistence architecture into an implementation sequence that can be delivered in small, low-risk phases.

The plan is intentionally strict about repository boundaries:

- Backend application code belongs in `backend/`.
- Backend source modules belong in `backend/app/`.
- Backend tests belong in `backend/tests/`.
- Backend configuration files belong in `backend/config/`.
- Backend local data files belong in `backend/data/`.
- Documentation updates belong in `docs/`.
- No backend runtime, persistence, or storage adapter code should be placed in the repository root, `frontend/`, or `mcp/`.

For clarity, this document uses filesystem paths such as `backend/app/persistence/settings.py`. Python imports may still use the `app.*` package path because `backend/` is the Python project root.

---

## 2. Review Outcomes

The persistence architecture document is implementation-ready and aligns well with the completed backend foundation, core-contracts, configuration, and observability work. It is strong on separation of concerns, lifecycle rules, safety requirements, and implementation ordering.

The review also confirms that this phase is not greenfield work. The repository already contains a meaningful persistence baseline that should be extended rather than replaced:

- `backend/app/persistence/trace_store.py` already builds the configured trace store.
- `backend/app/persistence/sqlite_trace_store.py` and `backend/app/persistence/sqlite_trace_schema.py` already provide append-only SQLite trace persistence.
- `backend/app/contracts/state.py`, `backend/app/contracts/memory.py`, and `backend/app/contracts/trace.py` already define the core persistence-facing contracts.
- `backend/app/testing/fakes/fake_state.py`, `backend/app/testing/fakes/fake_memory.py`, and `backend/app/testing/fakes/fake_trace.py` already provide test doubles for higher-level modules.
- `backend/app/config/schemas.py` and `backend/app/config/validation.py` already validate the top-level `persistence` configuration section.
- `backend/app/config/bootstrap.py` already wires trace persistence during lifespan startup.
- `backend/app/foundation/container.py` already carries trace persistence through the backend container.
- `backend/tests/integration/test_trace_store_sqlite_smoke.py` already proves the current trace SQLite path works.

The main implementation concerns addressed during execution are:

1. [DONE] **Repository-local path corrections are enforced.**  
  Backend-owned configuration and data remain under `backend/config/` and `backend/data/`, and persistence path resolution stays backend-root-relative.

2. [DONE] **Persistence config is typed at runtime.**  
  Store selection and required/optional behavior now flow through typed persistence settings instead of raw nested config reads in builders.

3. [DONE] **Shared persistence utilities are centralized.**  
  Path resolution, JSON-safe serialization, SQLite pragma/bootstrap helpers, schema-version handling, and persistence error wrapping now live under `backend/app/persistence/`.

4. [DONE] **Workflow state now has a concrete backend adapter.**  
  `backend/app/persistence/sqlite_workflow_state_store.py` and `backend/app/persistence/sqlite_workflow_state_schema.py` now provide the SQLite workflow-state implementation behind the existing contract.

5. [DONE] **Memory access now has a backend-local adapter boundary.**  
  `backend/app/persistence/memory_store_adapter.py` now isolates lazy `memory_store` imports, backend scope normalization, bounded search behavior, safe health output, and safe trace summaries behind the existing memory contract.

6. [DONE] **The composition root is no longer trace-centric.**  
  Startup now builds a full persistence bundle with workflow-state, trace, and memory health semantics before constructing the runtime container.

7. [DONE] **Avoid unnecessary contract-file churn.**  
  The implementation extends the existing `backend/app/contracts/state.py`, `backend/app/contracts/memory.py`, and `backend/app/contracts/trace.py` modules rather than renaming stable contract surfaces.

8. [DONE] **Backend-root-relative behavior remains deterministic.**  
  SQLite paths, startup-created database files, and test fixture execution remain anchored to `backend/`, not the caller's current working directory.

---

## 3. Non-Negotiable Boundary Rules

- Treat `backend/` as the Python project root for all persistence work.
- Create runtime persistence modules only under `backend/app/persistence/`.
- Keep backend contracts under `backend/app/contracts/`.
- Keep backend test code under `backend/tests/`.
- Keep backend configuration under `backend/config/` and backend-local data files under `backend/data/`.
- Keep documentation-only artifacts under `docs/`.
- Do not place backend persistence or storage-adapter code in the repository root, `frontend/`, or `mcp/`.
- Do not let any module outside `backend/app/persistence/` import `sqlite3`, `aiosqlite`, ArcadeDB clients, or `memory_store.service.MemoryService`.
- Keep `backend/app/main.py:app = create_app()` import-safe; I/O, schema bootstrap, and runtime wiring belong in lifespan startup, not import time.
- Do not duplicate public memory/request/scope DTOs under `backend/app/persistence/` when `backend/app/contracts/memory.py` already owns them.
- Health responses, logs, errors, and traces must not expose secrets, raw workflow state, raw prompts, raw completions, raw memory contents, full document chunks, raw SQL, or connection strings.
- Relative persistence paths must resolve from `backend/`, not from the shell's current working directory.

---

## 4. Phase Overview

| Phase | Name | Primary Outcome |
|---|---|---|
| 0 | [DONE] Current Persistence Baseline | The repository already has generic persistence config, a real SQLite trace store, persistence-facing contracts, and test fakes under `backend/`. |
| 1 | [DONE] Persistence Settings and Config Alignment | Persistence configuration becomes typed, backend-root-relative, and reusable across stores. |
| 2 | [DONE] Shared Persistence Utilities and SQLite Base | Storage-neutral helpers for paths, serialization, errors, pragmas, and migrations are in place, and the trace store is normalized onto them. |
| 3 | [DONE] Workflow State Store Foundation | A concrete SQLite workflow-state store exists behind the existing contract and fake surfaces. |
| 4 | [DONE] Persistence Bundle, Startup, and Health Wiring | The composition root builds a full persistence bundle and exposes safe required/optional health behavior. |
| 5 | [DONE] Memory Adapter Boundary | The backend now has a backend-local `memory_store` adapter boundary without leaking external memory implementation details. |
| 6 | [DONE] Tests, Fixtures, and Quality Gates | Persistence behavior is now covered by focused unit and integration tests plus backend-local quality gates. |
| 7 | [DONE] Freeze and Handoff | The general persistence boundary phase is closed and ready for the next focused workflow-state and memory-store documents. |

---

## 5. Detailed Implementation Phases

### [DONE] Phase 0. Current Persistence Baseline

**Goal**

Record the persistence work that already exists so the implementation plan extends the current backend instead of re-describing a greenfield slice.

**Files already present**

- [DONE] `backend/app/persistence/trace_store.py`
- [DONE] `backend/app/persistence/sqlite_trace_store.py`
- [DONE] `backend/app/persistence/sqlite_trace_schema.py`
- [DONE] `backend/app/contracts/state.py`
- [DONE] `backend/app/contracts/memory.py`
- [DONE] `backend/app/contracts/trace.py`
- [DONE] `backend/app/testing/fakes/fake_state.py`
- [DONE] `backend/app/testing/fakes/fake_memory.py`
- [DONE] `backend/app/testing/fakes/fake_trace.py`
- [DONE] `backend/app/config/schemas.py`
- [DONE] `backend/app/config/validation.py`
- [DONE] `backend/app/config/bootstrap.py`
- [DONE] `backend/app/foundation/container.py`
- [DONE] `backend/tests/integration/test_trace_store_sqlite_smoke.py`

**Implementation outcomes already in place**

- [DONE] The validated backend config already includes `persistence.workflow_state`, `persistence.trace`, and `persistence.memory` sections.
- [DONE] The backend can already build and initialize a SQLite trace store during lifespan startup.
- [DONE] Trace SQL already lives under `backend/app/persistence/`, not in API, agent, or orchestration code.
- [DONE] The backend already has fake workflow-state, trace, and memory components for higher-level tests.

**Validation already covered**

- [DONE] `backend/tests/integration/test_trace_store_sqlite_smoke.py`
- [DONE] The current backend startup path already bootstraps trace persistence from `backend/app/config/bootstrap.py`.

**Exit criteria**

- [DONE] The persistence plan starts from the real `backend/` implementation baseline rather than from an empty design state.

### [DONE] Phase 1. Persistence Settings and Config Alignment

**Goal**

Convert generic validated persistence config into typed runtime settings and helpers rooted in `backend/`.

**Files to create or update**

- [DONE] `backend/app/persistence/settings.py`
- [DONE] `backend/app/persistence/paths.py`
- [DONE] `backend/app/config/view.py`
- [DONE] `backend/app/config/schemas.py`
- [DONE] `backend/app/config/validation.py`
- [DONE] `backend/config/app.yaml`
- [DONE] `backend/tests/unit/persistence/test_persistence_settings.py`
- [DONE] `backend/tests/unit/persistence/test_path_resolution.py`
- [DONE] `backend/tests/unit/config/test_config_view.py`

**Implementation tasks**

- [DONE] Add typed settings objects for:
  - `SqliteStoreSettings`
  - `WorkflowStatePersistenceSettings`
  - `TracePersistenceSettings`
  - `MemoryPersistenceSettings`
  - `PersistenceSettings`
- [DONE] Expand the validated persistence config only where needed to support architecture-required behavior such as:
  - `base_dir`
  - `required`
  - `create_parent_dirs`
  - `initialize_schema`
  - `journal_mode`
  - `busy_timeout_ms`
  - `foreign_keys`
  - `payload_max_chars`
  - memory search defaults and limits
- [DONE] Add typed access helpers in `backend/app/config/view.py`, such as `persistence_settings()` or equivalent, so runtime modules stop reading raw nested config keys directly.
- [DONE] Resolve backend-owned relative paths against `backend/` and default local SQLite files under `backend/data/`.
- [DONE] Preserve the existing validated config shape where practical instead of doing avoidable schema churn.
- [DONE] Ensure persistence path resolution behaves the same whether commands are launched from the repository root or from `backend/`.

**Validation**

- [DONE] Add and pass focused configuration-view tests for persistence settings parsing.
- [DONE] Add and pass temp-directory path-resolution tests that prove backend-local persistence paths are deterministic.
- [DONE] Run `backend/.venv\Scripts\python.exe -m pytest tests/unit/config/test_config_view.py tests/unit/persistence tests/integration/test_trace_store_sqlite_smoke.py` from `backend/`.

**Exit criteria**

- [DONE] Persistence settings are available as typed runtime objects.
- [DONE] Persistence builders no longer reach into raw nested config paths for routine store setup.
- [DONE] Local persistence defaults are clearly rooted in `backend/data/`.

### [DONE] Phase 2. Shared Persistence Utilities and SQLite Base

**Goal**

Introduce storage-neutral persistence helpers and normalize the current trace-store implementation onto them.

**Files to create or update**

- [DONE] `backend/app/persistence/serialization.py`
- [DONE] `backend/app/persistence/errors.py`
- [DONE] `backend/app/persistence/sqlite/__init__.py`
- [DONE] `backend/app/persistence/sqlite/connection.py`
- [DONE] `backend/app/persistence/sqlite/pragmas.py`
- [DONE] `backend/app/persistence/sqlite/migrations.py`
- [DONE] `backend/app/persistence/sqlite/transactions.py` was not needed in the first pass.
- [DONE] `backend/app/persistence/sqlite_trace_schema.py`
- [DONE] `backend/app/persistence/sqlite_trace_store.py`
- [DONE] `backend/tests/unit/persistence/test_safe_json_serialization.py`
- [DONE] `backend/tests/integration/test_sqlite_connection_smoke.py`

**Implementation tasks**

- [DONE] Add JSON-safe conversion helpers for dataclasses, datetimes, enums, sets, tuples, and unsupported objects.
- [DONE] Add a shared serialization entry point for persistence modules so trace and workflow-state stores do not each invent their own JSON encoding rules.
- [DONE] Introduce persistence-specific error types such as:
  - `PersistenceError`
  - `WorkflowStateError`
  - `TraceStoreError`
  - `MemoryGatewayError`
  - `PersistenceConfigurationError`
  - `PersistenceSerializationError`
  - `PersistenceUnavailableError`
- [DONE] Add SQLite connection/bootstrap helpers that apply configured pragmas and create a schema-version table idempotently.
- [DONE] Refactor `backend/app/persistence/sqlite_trace_store.py` and `backend/app/persistence/sqlite_trace_schema.py` to use the shared SQLite and serialization helpers without changing the external trace contract.
- [DONE] Keep trace payload redaction and payload bounding owned by the observability layer; persistence should store already-safe payloads rather than re-own trace event shaping.

**Validation**

- [DONE] Add and pass unit tests for JSON-safe serialization behavior.
- [DONE] Add and pass a SQLite connection smoke test in a temporary directory.
- [DONE] Re-run `backend/tests/integration/test_trace_store_sqlite_smoke.py` to confirm the refactor preserves current trace-store behavior.

**Exit criteria**

- [DONE] Shared persistence helpers exist for paths, serialization, errors, and SQLite bootstrap.
- [DONE] Trace persistence no longer owns one-off SQLite bootstrap and JSON encoding behavior.

### [DONE] Phase 3. Workflow State Store Foundation

**Goal**

Implement a concrete backend-local SQLite workflow-state store behind the existing workflow-state contract.

**Files to create or update**

- [DONE] `backend/app/persistence/workflow_state_store.py`
- [DONE] `backend/app/persistence/sqlite_workflow_state_store.py`
- [DONE] `backend/app/persistence/sqlite_workflow_state_schema.py`
- [DONE] `backend/app/contracts/state.py` remained the stable workflow-state contract surface for this phase.
- [DONE] `backend/app/testing/fakes/fake_state.py`
- [DONE] `backend/tests/unit/persistence/test_fake_workflow_state_store.py`
- [DONE] `backend/tests/integration/test_workflow_state_store_sqlite_smoke.py`

**Implementation tasks**

- [DONE] Add a workflow-state store builder boundary separate from the concrete SQLite class.
- [DONE] Store one JSON-safe workflow-state document per session with version, timestamps, and metadata.
- [DONE] Keep the early implementation intentionally small:
  - `load()` returns `{}` when no record exists
  - `save()` writes atomically in one transaction
  - `reset()` clears workflow state only
- [DONE] Keep reset semantics strict: workflow-state reset must not touch memory or trace persistence.
- [DONE] Include `updated_at` and version metadata so later documents can deepen optimistic concurrency without changing the public contract.
- [DONE] Provide safe health output that reports provider, configured state, schema initialization, and database existence without exposing raw file paths or contents.
- [DONE] Reuse phase-2 helpers instead of duplicating SQLite bootstrap, path resolution, or JSON serialization logic.

**Validation**

- [DONE] Add and pass fake-store unit tests aligned with the final contract behavior.
- [DONE] Add and pass integration smoke tests for workflow-state save, load, and reset behavior in a temporary database.
- [DONE] Add a focused required-store startup test through the phase-4 startup slice so workflow-state initialization is exercised during lifespan startup.

**Exit criteria**

- [DONE] The backend has a real `WorkflowStateStore` implementation under `backend/app/persistence/`.
- [DONE] Workflow-state lifecycle rules are enforced independently from trace and memory.

### [DONE] Phase 4. Persistence Bundle, Startup, and Health Wiring

**Goal**

Evolve the current trace-only startup path into a full persistence bundle integrated with backend startup and health reporting.

**Files to create or update**

- [DONE] `backend/app/persistence/factory.py`
- [DONE] `backend/app/persistence/health.py`
- [DONE] `backend/app/config/bootstrap.py`
- [DONE] `backend/app/foundation/container.py`
- [DONE] `backend/app/foundation/health.py`
- [DONE] `backend/tests/unit/test_app_factory.py`
- [DONE] `backend/tests/unit/test_health.py`
- [DONE] `backend/tests/integration/test_startup_persistence.py`

**Implementation tasks**

- [DONE] Add a `PersistenceBundle` that groups:
  - `trace_store`
  - `workflow_state`
  - `memory`
- [DONE] Move store/provider selection into `backend/app/persistence/factory.py` so the composition root builds persistence consistently from typed settings.
- [DONE] Extend `backend/app/config/bootstrap.py` to build the full persistence bundle rather than only the trace store.
- [DONE] Extend `backend/app/foundation/container.py` so the backend container exposes the full persistence bundle or equivalent explicit members.
- [DONE] Register persistence health sections for:
  - aggregate persistence state
  - workflow state
  - trace
  - memory
- [DONE] Enforce required versus optional behavior at startup:
  - workflow state should be required in the backend walking skeleton
  - trace should follow configuration-driven required behavior
  - memory may remain optional until the memory-gateway phase or use-case-specific enablement
- [DONE] Log only redacted persistence summaries; avoid exposing raw SQLite paths, connection strings, SQL, or backend-local secrets in health or startup diagnostics.

**Validation**

- [DONE] Add and pass a startup test that proves lifespan startup creates workflow-state and trace databases in a temporary backend-local data directory.
- [DONE] Add and pass health tests that cover `ok`, `degraded`, and failure behavior for required versus optional persistence stores.
- [DONE] Run focused startup and health tests from `backend/`.

**Exit criteria**

- [DONE] Backend startup builds persistence consistently through one composition-root path.
- [DONE] `/health` can report persistence readiness safely for workflow-state, trace, and memory.

### [DONE] Phase 5. Memory Adapter Boundary

**Goal**

Add a backend-local memory adapter boundary without leaking `memory_store` internals beyond `backend/app/persistence/`.

**Files to create or update**

- [DONE] `backend/app/persistence/memory_store_adapter.py`
- [DONE] `backend/app/persistence/factory.py`
- [DONE] `backend/app/contracts/memory.py`
- [DONE] `backend/app/testing/fakes/fake_memory.py`
- [DONE] `backend/tests/unit/persistence/test_memory_scope.py`
- [DONE] `backend/tests/unit/persistence/test_memory_store_adapter_health.py`
- [DONE] `backend/tests/fixtures/config/persistence_memory_optional.yaml`

**Implementation tasks**

- [DONE] Keep public memory DTOs and `MemoryScope` in `backend/app/contracts/memory.py`; do not create a competing public model tree under persistence unless an internal private mapper becomes necessary.
- [DONE] Implement `MemoryStoreAdapter` as the only backend module allowed to import `memory_store.service.MemoryService`.
- [DONE] Use lazy import or lazy initialization so `backend/app/main.py:app = create_app()` remains import-safe and optional memory providers can degrade cleanly.
- [DONE] Normalize backend-level scope checks and search limits before calling the underlying memory library.
- [DONE] Wrap external memory-library failures in backend persistence errors instead of leaking third-party exception shapes.
- [DONE] Emit only safe trace summaries for memory operations; do not log or persist full memory texts or full document chunks by default.
- [DONE] Keep this phase intentionally shallow. Defer document ingestion, chunk lifecycle, ranking behavior, and policy-heavy promotion flows to the later memory-specific architecture document.

**Validation**

- [DONE] Add and pass unit tests for scope validation and search-limit normalization.
- [DONE] Add and pass optional-store health tests for missing or misconfigured memory-store dependencies.
- [DONE] `memory_store` is available locally, and a shallow adapter smoke test now exercises the installed package through the adapter health boundary.

**Exit criteria**

- [DONE] The backend has a clear memory adapter boundary under `backend/app/persistence/`.
- [DONE] No agent, API, or orchestration-facing module imports `memory_store` directly.

### [DONE] Phase 6. Tests, Fixtures, and Quality Gates

**Goal**

Make the persistence slice reproducible, backend-local, and safe to extend.

**Files to create or update**

- [DONE] `backend/tests/unit/persistence/test_persistence_settings.py`
- [DONE] `backend/tests/unit/persistence/test_path_resolution.py`
- [DONE] `backend/tests/unit/persistence/test_safe_json_serialization.py`
- [DONE] `backend/tests/unit/persistence/test_fake_workflow_state_store.py`
- [DONE] `backend/tests/unit/persistence/test_memory_scope.py`
- [DONE] `backend/tests/unit/persistence/test_memory_store_adapter_health.py`
- [DONE] `backend/tests/integration/test_sqlite_connection_smoke.py`
- [DONE] `backend/tests/integration/test_trace_store_sqlite_smoke.py`
- [DONE] `backend/tests/integration/test_workflow_state_store_sqlite_smoke.py`
- [DONE] `backend/tests/integration/test_startup_persistence.py`
- [DONE] `backend/tests/fixtures/config/persistence_sqlite_local.yaml`
- [DONE] `backend/tests/fixtures/config/persistence_fake.yaml`
- [DONE] `backend/tests/fixtures/config/persistence_memory_optional.yaml`
- [DONE] `backend/tests/fixtures/config/persistence_required_store_failure.yaml`
- [DONE] `backend/tests/fixtures/config/persistence_invalid_provider.yaml`
- [DONE] `backend/README.md`

**Implementation tasks**

- [DONE] Add fixture-backed configuration coverage for valid local SQLite persistence, fake providers, optional memory-store degradation, invalid provider rejection, and required-store startup failure.
- [DONE] Keep unit persistence tests under `backend/tests/unit/persistence/`.
- [DONE] Keep integration tests under the existing `backend/tests/integration/` naming pattern unless there is a deliberate repository-wide move to nested integration subfolders.
- [DONE] Update `backend/README.md` with backend-local persistence paths, configuration expectations, and test commands.
- [DONE] Run the full backend quality gate from `backend/`:
  - [DONE] `backend/.venv\Scripts\python.exe -m pytest`
  - [DONE] `backend/.venv\Scripts\python.exe -m ruff check .`
  - [DONE] `backend/.venv\Scripts\python.exe -m mypy app`

**Exit criteria**

- [DONE] Persistence behavior is covered by focused tests at both the unit and integration level.
- [DONE] Developer documentation matches the actual backend-local config and data layout.

### [DONE] Phase 7. Freeze and Handoff

**Goal**

Close the general persistence-boundary phase cleanly so the next focused backend documents can deepen workflow-state and memory behavior without reopening repository-boundary or composition-root questions.

**Implementation tasks**

- [DONE] Confirm that the acceptance criteria from `backend-persistence-architecture.md` are satisfied at repo-accurate paths under `backend/`.
- [DONE] Record intentional deferrals, especially:
  - deep workflow-state schema tuning
  - trace query and debug APIs
  - optimistic concurrency refinements
  - document ingestion and chunk lifecycle
  - privacy export/delete tooling
  - retention, backup, and deployment-volume decisions
- [DONE] Confirm the next dependent documents and implementation order remain:
  - `docs/backend-sqlite-workflow-state-architecture.md`
  - `docs/backend-sqlite-trace-store-architecture.md`
  - `docs/backend-memory-store-adapter-architecture.md`
  - then the API, session, orchestration, tool, and agent documents that consume the persistence boundaries
- [DONE] Record the follow-on status: `docs/backend-sqlite-workflow-state-plan.md` now freezes the workflow-state slice, so the next persistence-specific deepening document is `docs/backend-sqlite-trace-store-architecture.md`.

**Validation**

- [DONE] Re-run the full backend quality gate if freeze follows active implementation.
- [DONE] Verify that documentation and README instructions remain accurate when executed from `backend/`.

**Exit criteria**

- [DONE] The backend persistence boundary is stable, backend-local, and ready for the next focused implementation document.

---

## 6. Implementation Priorities

The highest-value execution order inside this plan is:

1. Type the persistence settings and path rules first.
2. Centralize shared SQLite and serialization behavior before adding a second concrete store.
3. Add workflow-state persistence next, because later API and session work depends on it directly.
4. Upgrade startup and health wiring only after trace and workflow-state stores share one factory path.
5. Add the memory adapter boundary last in this phase, keeping deep memory semantics deferred.

This order keeps the next backend walking skeleton small:

```text
startup -> config -> observability -> persistence bundle
request -> trace/session ids -> workflow state load/save -> trace events
later -> memory adapter, orchestration runtime, agents, and tools
```

---

## 7. Completion Standard

This plan should be considered complete when the backend can do all of the following from inside `backend/` without leaking storage details outside persistence adapters:

- Build typed persistence settings from validated config.
- Resolve persistence paths under `backend/data/` deterministically.
- Initialize trace and workflow-state SQLite stores through shared helpers.
- Expose safe health status for workflow-state, trace, and memory providers.
- Keep `memory_store` isolated behind a backend-local adapter boundary.
- Run focused unit and integration tests without depending on real production data files.
- Hand off cleanly to the next workflow-state and memory-specific architecture documents.

The key constraint remains unchanged throughout implementation:

> **All backend persistence code lives under `backend/`, and all runtime modules outside `backend/app/persistence/` depend on contracts and composition-root wiring rather than concrete storage engines.**