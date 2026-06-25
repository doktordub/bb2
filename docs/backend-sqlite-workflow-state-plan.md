# Backend SQLite Workflow State Implementation Plan

**Document:** `backend-sqlite-workflow-state-plan.md`  
**Version:** 1.0  
**Source alignment:** `backend-sqlite-workflow-state-architecture.md`, `backend-persistence-plan.md`, and the current backend persistence baseline  
**Repository rule:** all backend application code lives under `backend/`

---

## 1. Purpose

This plan converts the backend SQLite workflow-state architecture into an implementation sequence that can be delivered in small, low-risk phases.

The plan is intentionally strict about repository boundaries:

- Backend application code belongs in `backend/`.
- Backend source modules belong in `backend/app/`.
- Backend tests belong in `backend/tests/`.
- Backend configuration files belong in `backend/config/`.
- Backend local data files belong in `backend/data/`.
- Documentation updates belong in `docs/`.
- No backend runtime, persistence, or SQLite adapter code should be placed in the repository root, `frontend/`, or `mcp/`.

For clarity, this document uses filesystem paths such as `backend/app/persistence/sqlite_workflow_state_store.py`. Python imports may still use the `app.*` package path because `backend/` is the Python project root.

This phase is not greenfield work. The repository already contains a real SQLite workflow-state slice under `backend/`, but that slice is narrower than the architecture document. The implementation plan therefore focuses on extending the current backend modules instead of creating parallel contract files, duplicate fakes, or a second persistence path.

---

## 2. Review Outcomes

The workflow-state architecture document is implementation-ready and fits the current backend persistence direction. It is strong on boundaries, reset semantics, data minimization, SQLite isolation, and the handoff to the later API and session-service slices.

The review also confirms that the repository already contains a usable workflow-state baseline that must be extended rather than replaced:

- `backend/app/contracts/state.py` already defines `WorkflowStateStore` and `WorkflowStateRecord`.
- `backend/app/persistence/workflow_state_store.py` already resolves the configured workflow-state store from typed persistence settings.
- `backend/app/persistence/sqlite_workflow_state_store.py` and `backend/app/persistence/sqlite_workflow_state_schema.py` already provide a working SQLite adapter and schema bootstrap.
- `backend/app/persistence/settings.py` already resolves typed persistence settings rooted in `backend/`.
- `backend/app/persistence/factory.py` already builds workflow-state persistence during backend startup.
- `backend/app/persistence/health.py` already includes workflow-state in aggregate persistence health.
- `backend/app/testing/fakes/fake_state.py` already provides a deterministic fake workflow-state store for higher-level tests.
- `backend/tests/integration/test_workflow_state_store_sqlite_smoke.py` already proves the current save/load/reset path works against a temporary SQLite file.
- `backend/tests/integration/test_startup_persistence.py` already proves the database is created during lifespan startup and stays rooted in the backend-local data directory.

The main implementation concerns to resolve explicitly during execution are:

1. **The current schema is narrower than the architecture.**  
   The implementation currently stores everything in one `workflow_states` table plus `schema_version`, while the architecture expects richer session, current-state, and reset metadata boundaries. The plan should upgrade the existing schema in `backend/app/persistence/sqlite_workflow_state_schema.py` instead of creating a second workflow-state adapter.

2. **Workflow-state-specific configuration is incomplete.**  
   The current typed settings resolve shared SQLite options, but the architecture requires additional workflow-state controls such as `max_state_bytes`, `max_history_messages`, `reset_mode`, and optional identity-storage flags. Those settings should be added through the existing validated configuration path rooted in `backend/app/config/` and `backend/app/persistence/settings.py`.

3. **Store behavior is still minimal.**  
   `load` currently returns `{}` for missing state, `save` only persists JSON plus a simple integer version, and `reset` deletes the row outright. The architecture expects deterministic default empty state behavior, derived metadata, size and sensitive-data guardrails, and reset metadata recording.

4. **Health and error behavior are shallow.**  
   The current health payload is intentionally small, but the architecture calls for richer safe state-store readiness details and a more specific workflow-state error taxonomy without leaking SQL, paths, or state content.

5. **Observability hooks are not attached yet.**  
   The current store performs persistence work but does not emit the architecture's safe workflow-state summaries and metrics for load, save, reset, failure, and conflict paths.

6. **The existing test surface is not broad enough for the architecture.**  
   The repo has smoke coverage, fake-store coverage, startup coverage, and shared settings coverage, but it still lacks corruption, size-limit, reset-metadata, sensitive-data, schema re-open, migration, and concurrency-focused tests.

7. **Avoid unnecessary file churn.**  
   The current canonical workflow-state contract already lives in `backend/app/contracts/state.py`, and the current fake already lives in `backend/app/testing/fakes/fake_state.py`. The implementation plan should keep those names and extend them only when needed.

8. **Shared persistence settings may affect trace persistence too.**  
   If the workflow-state phase adds new generic SQLite settings such as `synchronous`, that change should be done additively so the existing trace-store slice under `backend/app/persistence/sqlite_trace_store.py` remains stable.

---

## 3. Non-Negotiable Boundary Rules

- Treat `backend/` as the Python project root for all workflow-state work.
- Create runtime workflow-state modules only under `backend/app/persistence/`.
- Keep the canonical workflow-state contract under `backend/app/contracts/state.py`.
- Keep the canonical fake workflow-state store under `backend/app/testing/fakes/fake_state.py`.
- Keep backend test code under `backend/tests/`.
- Keep backend configuration under `backend/config/` and backend-local SQLite files under `backend/data/`.
- Keep documentation-only artifacts under `docs/`.
- Do not place backend workflow-state, session, or SQLite code in the repository root, `frontend/`, or `mcp/`.
- Do not let any module outside `backend/app/persistence/` import `sqlite3`, execute workflow-state SQL, or depend on SQLite row shapes.
- Keep `backend/app/main.py:app = create_app()` import-safe; all I/O, schema bootstrap, and database initialization belong in lifespan startup.
- Do not create a duplicate workflow-state contract file or a duplicate fake-store file under new names unless a later cross-repo refactor explicitly requires it.
- Logs, traces, health responses, and errors must not expose raw state payloads, raw prompts, raw completions, raw authorization headers, API keys, provider credentials, connection strings, or full stack traces.
- Relative workflow-state paths must resolve from `backend/`, not from the shell's current working directory.

---

## 4. Phase Overview

| Phase | Name | Primary Outcome |
|---|---|---|
| 0 | [DONE] Current Workflow-State Baseline | The repository already has a working SQLite workflow-state adapter, fake store, typed persistence wiring, and startup coverage under `backend/`. |
| 1 | [DONE] Workflow-State Config and Contract Alignment | Workflow-state-specific settings and stable contract expectations are made explicit without creating new repo-root or duplicate module paths. |
| 2 | [DONE] Schema Expansion and Metadata Model | The SQLite schema grows from the current minimal table into the architecture-aligned session/current-state/reset model while staying fully isolated under `backend/app/persistence/`. |
| 3 | [DONE] Load, Save, and Reset Behavior Hardening | The store now returns the canonical empty state on misses, enforces safe persistence guardrails, records reset metadata, and keeps the fake and SQLite adapters aligned at the behavior level. |
| 4 | [DONE] Startup, Health, and Error Integration | Startup now fails cleanly on required workflow-state availability/schema problems, and health/error surfaces expose richer safe readiness details without leaking state content or filesystem paths. |
| 5 | [DONE] Observability and Concurrency Hardening | The store emits safe operational signals and proves the local SQLite concurrency baseline expected by the architecture. |
| 6 | [DONE] Tests, Fixtures, and Quality Gates | Backend-local tests and config fixtures cover the architecture acceptance criteria without touching real `backend/data/` files. |
| 7 | [DONE] Freeze and Handoff | The workflow-state boundary is documented as stable and ready for the API/session consumer phases. |

---

## 5. Detailed Implementation Phases

### [DONE] Phase 0. Current Workflow-State Baseline

**Goal**

Record the workflow-state work that already exists so the plan extends the current backend instead of re-describing a greenfield implementation.

**Files already present**

- [DONE] `backend/app/contracts/state.py`
- [DONE] `backend/app/persistence/workflow_state_store.py`
- [DONE] `backend/app/persistence/sqlite_workflow_state_store.py`
- [DONE] `backend/app/persistence/sqlite_workflow_state_schema.py`
- [DONE] `backend/app/persistence/settings.py`
- [DONE] `backend/app/persistence/factory.py`
- [DONE] `backend/app/persistence/health.py`
- [DONE] `backend/app/testing/fakes/fake_state.py`
- [DONE] `backend/tests/unit/persistence/test_fake_workflow_state_store.py`
- [DONE] `backend/tests/unit/persistence/test_persistence_settings.py`
- [DONE] `backend/tests/integration/test_workflow_state_store_sqlite_smoke.py`
- [DONE] `backend/tests/integration/test_startup_persistence.py`
- [DONE] `backend/config/app.yaml`

**Implementation outcomes already in place**

- [DONE] Workflow-state provider selection is already routed through typed persistence settings.
- [DONE] The SQLite workflow-state store is already initialized during backend lifespan startup.
- [DONE] The current store already uses shared backend persistence helpers such as the SQLite connection bootstrap and JSON serialization helpers.
- [DONE] The backend already exposes workflow-state through aggregate persistence health.
- [DONE] The fake workflow-state store already supports higher-level tests without opening SQLite.

**Validation already covered**

- [DONE] `backend/tests/unit/persistence/test_fake_workflow_state_store.py`
- [DONE] `backend/tests/unit/persistence/test_persistence_settings.py`
- [DONE] `backend/tests/integration/test_workflow_state_store_sqlite_smoke.py`
- [DONE] `backend/tests/integration/test_startup_persistence.py`

**Exit criteria**

- [DONE] The plan starts from the real workflow-state baseline under `backend/` instead of creating a duplicate persistence path.

### [DONE] Phase 1. Workflow-State Config and Contract Alignment

**Goal**

Extend the existing backend configuration and contract surfaces so the workflow-state slice can express the architecture-required behavior without introducing unnecessary module churn.

**Files to create or update**

- [DONE] `backend/app/persistence/settings.py`
- [DONE] `backend/app/config/schemas.py`
- [DONE] `backend/app/config/validation.py`
- [DONE] `backend/app/config/view.py`
- [DONE] `backend/app/contracts/state.py`
- [DONE] `backend/config/app.yaml`
- [DONE] `backend/tests/unit/persistence/test_persistence_settings.py`
- [DONE] `backend/tests/unit/config/test_config_view.py`
- [DONE] `backend/tests/fixtures/config/workflow_state_sqlite.yaml`
- [DONE] `backend/tests/fixtures/config/workflow_state_sqlite_small_max_size.yaml`
- [DONE] `backend/tests/fixtures/config/workflow_state_sqlite_delete_reset.yaml`
- [DONE] `backend/tests/fixtures/config/workflow_state_fake.yaml`

**Implementation tasks**

- [DONE] Extend the current `WorkflowStatePersistenceSettings` shape in `backend/app/persistence/settings.py` with workflow-state-specific settings rather than overloading generic store code paths with backend-specific conditionals.
- [DONE] Add or resolve the architecture-required settings under the existing validated config pipeline: `max_state_bytes`, `max_history_messages`, `reset_mode`, `synchronous`, `store_user_id`, and `store_user_id_hash`.
- [DONE] Keep backend-local defaults anchored under `backend/data/`, with `workflow_state.db` remaining a backend-owned file.
- [DONE] Preserve the existing `ValidatedConfigurationView.persistence_settings()` access pattern in `backend/app/config/view.py`; runtime code should continue receiving resolved settings rather than reading raw config sections directly.
- [DONE] Keep `backend/app/contracts/state.py` as the stable contract home. If helper dataclasses or reserved metadata constants are needed, add them there or in workflow-state-local helpers instead of creating a parallel contract module.
- [DONE] Decide and document the canonical missing-state behavior so the fake store, real store, and future session-service consumers all agree on the default empty-state shape.
- [DONE] Keep the legacy config path shape working where practical so current local configs do not break during the transition.
- [DONE] If the new `synchronous` setting is useful to both trace and workflow-state adapters, add it to the shared SQLite settings additively and verify the trace-store defaults remain unchanged.

**Validation**

- [DONE] Add and pass targeted settings tests proving the new workflow-state options parse correctly from `backend/tests/fixtures/config/` fixtures.
- [DONE] Add and pass config-view tests proving backend-root-relative path resolution still behaves deterministically from both the repo root and `backend/`.
- [DONE] Run `backend/.venv\Scripts\python.exe -m pytest backend/tests/unit/persistence/test_persistence_settings.py backend/tests/unit/config/test_config_view.py` from the repository root.

**Exit criteria**

- [DONE] Workflow-state runtime settings are fully typed.
- [DONE] Backend-root-relative defaults remain deterministic.
- [DONE] The workflow-state contract surface is explicit without introducing duplicate file paths.

### [DONE] Phase 2. Schema Expansion and Metadata Model

**Goal**

Upgrade the narrow current SQLite schema into the architecture-aligned workflow-state storage model while keeping all SQL, migrations, and table ownership isolated under `backend/app/persistence/`.

**Files to create or update**

- [DONE] `backend/app/persistence/sqlite_workflow_state_schema.py`
- [DONE] `backend/app/persistence/sqlite_workflow_state_store.py`
- [DONE] `backend/app/persistence/serialization.py`
- [DONE] `backend/app/persistence/errors.py`
- [DONE] `backend/app/persistence/sqlite/migrations.py`
- [DONE] `backend/tests/unit/persistence/test_sqlite_workflow_state_schema.py`
- [DONE] `backend/tests/integration/test_workflow_state_store_sqlite_smoke.py`
- [DONE] `backend/tests/integration/test_sqlite_connection_smoke.py`
- [DONE] `backend/tests/integration/test_startup_persistence.py`

**Implementation tasks**

- [DONE] Expand the current single-table schema into the architecture-aligned model using backend-local table ownership for `workflow_sessions`, `workflow_state_current`, `workflow_state_resets`, and `schema_version`.
- [DONE] Keep the schema version bootstrap idempotent and explicit in `backend/app/persistence/sqlite_workflow_state_schema.py`.
- [DONE] Add the metadata columns the architecture depends on for later API and session work, including state version, hash, byte size, message count, current step, checkpoint name, timestamps, and reset generation.
- [DONE] Add only the minimal indexes needed for session lookup, last activity, reset history, and current-step diagnostics.
- [DONE] Keep state JSON canonical and stable through the existing shared serialization helpers, including sorted-key JSON used for state hashing.
- [DONE] Add backend-local helpers for metadata extraction such as message count, current step, checkpoint name, and state hash.
- [DONE] Validate `session_id` before SQL execution and keep every query parameterized.
- [DONE] If an in-place upgrade from the existing `workflow_states` table is needed, implement it as an explicit, one-way, schema-versioned migration. Do not silently drop or overwrite prior local state.
- [DONE] Avoid introducing a new models file unless row-shaping complexity makes it clearly useful. The current backend can stay simpler if schema rows remain readable inside the store and schema modules.

**Validation**

- [DONE] Add and pass unit tests proving the schema initializer is idempotent and the expected tables and indexes exist.
- [DONE] Add and pass integration coverage for fresh database creation and re-opening an existing database.
- [DONE] Add a migration-focused integration test if the existing `workflow_states` schema needs an upgrade path.
- [DONE] Run `backend/.venv\Scripts\python.exe -m pytest backend/tests/unit/persistence/test_sqlite_workflow_state_schema.py backend/tests/integration/test_sqlite_connection_smoke.py backend/tests/integration/test_workflow_state_store_sqlite_smoke.py backend/tests/integration/test_startup_persistence.py` from the repository root.

**Exit criteria**

- [DONE] The workflow-state schema exposes the metadata required by the architecture.
- [DONE] Schema initialization and version validation remain idempotent and backend-local.
- [DONE] No module outside `backend/app/persistence/` learns table names or row shapes.

### [DONE] Phase 3. Load, Save, and Reset Behavior Hardening

**Goal**

Bring the store behavior up to the architecture contract while preserving the public `WorkflowStateStore` shape already used by the backend.

**Files to create or update**

- [DONE] `backend/app/persistence/sqlite_workflow_state_store.py`
- [DONE] `backend/app/contracts/state.py`
- [DONE] `backend/app/persistence/errors.py`
- [DONE] `backend/app/testing/fakes/fake_state.py`
- [DONE] `backend/tests/unit/persistence/test_sqlite_workflow_state_serialization.py`
- [DONE] `backend/tests/unit/persistence/test_sqlite_workflow_state_reset.py`
- [DONE] `backend/tests/unit/persistence/test_fake_workflow_state_store.py`
- [DONE] `backend/tests/integration/test_workflow_state_store_sqlite_smoke.py`

**Implementation tasks**

- [DONE] Change missing-session `load` behavior from a bare empty dictionary to a deterministic default empty state that includes the expected backend workflow-state structure.
- [DONE] Keep the empty-state helper backend-local so future session-service code can rely on one stable shape.
- [DONE] Validate that `save` receives a dictionary, normalize `session_id`, and serialize through the shared JSON-safe backend serializer.
- [DONE] Enforce `max_state_bytes` before committing the transaction, raising a workflow-state-specific safe error when the payload is too large.
- [DONE] Derive and persist safe metadata such as message count, current step, checkpoint name, hash, and reset generation without exposing `state_json` in traces or errors.
- [DONE] Add a last-line safety check for obvious secret-bearing keys and reject unsafe persistence attempts by default.
- [DONE] Implement reset behavior through the configured `reset_mode`, with `replace_with_empty_state` as the preferred default and `delete_state_row` as an explicit alternative.
- [DONE] Record reset metadata without storing the cleared state payload.
- [DONE] Keep optimistic concurrency deferred in this phase while retaining the schema support and dedicated workflow-state conflict error type for a later compare-and-set implementation.
- [DONE] Update `backend/app/testing/fakes/fake_state.py` so higher-level tests see the same missing-state and reset behavior contract as the real adapter, without inheriting SQLite-specific details.

**Validation**

- [DONE] Add and pass unit tests for default empty-state shape, repeated-save version increments, reset behavior, invalid session IDs, corrupt stored JSON, oversized state, and sensitive-key rejection.
- [DONE] Extend the SQLite smoke test so it asserts derived metadata and reset behavior instead of only state JSON replacement.
- [DONE] Run `backend/.venv\Scripts\python.exe -m pytest backend/tests/unit/persistence/test_sqlite_workflow_state_serialization.py backend/tests/unit/persistence/test_sqlite_workflow_state_reset.py backend/tests/unit/persistence/test_fake_workflow_state_store.py backend/tests/integration/test_workflow_state_store_sqlite_smoke.py` from the repository root.

**Exit criteria**

- [DONE] `load`, `save`, and `reset` behave the same way the architecture describes.
- [DONE] The fake store and real store align at the behavior level.
- [DONE] The workflow-state adapter persists only safe, bounded state.

### [DONE] Phase 4. Startup, Health, and Error Integration

**Goal**

Preserve import-safe backend startup while surfacing richer workflow-state readiness and a workflow-state-specific safe error model.

**Files to create or update**

- [DONE] `backend/app/persistence/workflow_state_store.py`
- [DONE] `backend/app/persistence/factory.py`
- [DONE] `backend/app/persistence/health.py`
- [DONE] `backend/app/persistence/errors.py`
- [DONE] `backend/app/config/bootstrap.py`
- [DONE] `backend/app/foundation/container.py`
- [DONE] `backend/tests/integration/test_startup_persistence.py`
- [DONE] `backend/tests/unit/test_health.py`

**Implementation tasks**

- [DONE] Keep workflow-state initialization in backend startup wiring only; do not move any SQLite setup into import-time module code.
- [DONE] Enrich workflow-state `health()` output with safe readiness details such as schema initialization, schema version, provider, required flag, and selected pragma mode when those fields can be exposed without revealing sensitive paths.
- [DONE] Keep full database paths out of health output; at most expose a basename-only path in local-safe contexts if the backend health policy allows it.
- [DONE] Add workflow-state-specific error wrappers under `backend/app/persistence/errors.py` for migration, availability, serialization, size, and conflict failures.
- [DONE] Preserve the existing required-versus-optional semantics in aggregate persistence health, with workflow state remaining a required backend capability.
- [DONE] Fail startup when required workflow-state initialization or schema validation fails.
- [DONE] Keep `app.state.container` and the current persistence bundle stable so later API and session-service phases still consume one backend-owned workflow-state surface.

**Validation**

- [DONE] Add and pass startup tests for required-store failure and schema mismatch failure; optional workflow-state degradation remains intentionally unsupported because workflow state stays required.
- [DONE] Add and pass health tests proving workflow-state readiness output does not leak state content, user IDs, session IDs, or full filesystem paths.
- [DONE] Run `backend/.venv\Scripts\python.exe -m pytest backend/tests/integration/test_startup_persistence.py backend/tests/unit/test_health.py` from the repository root.

**Exit criteria**

- [DONE] Workflow-state readiness is explicit and safe.
- [DONE] Startup failure behavior matches configuration policy.
- [DONE] Errors are backend-specific and safe for later API mapping.

### [DONE] Phase 5. Observability and Concurrency Hardening

**Goal**

Add the architecture's safe diagnostics and concurrency baseline without violating the existing backend separation between persistence and higher-level runtime code.

**Files to create or update**

- [DONE] `backend/app/persistence/sqlite_workflow_state_store.py`
- [DONE] `backend/app/observability/events.py`
- [DONE] `backend/app/observability/tracing.py`
- [DONE] `backend/app/observability/metrics.py`
- [DONE] `backend/app/persistence/factory.py`
- [DONE] `backend/tests/unit/observability/test_workflow_state_events.py`
- [DONE] `backend/tests/integration/test_workflow_state_store_concurrency.py`

**Implementation tasks**

- [DONE] Emit safe workflow-state summaries for load, save, reset, failure, and conflict paths using the backend's existing observability abstractions instead of adding direct route or session-service dependencies.
- [DONE] Prefer injecting a small observer or recorder dependency from backend startup wiring over importing logging or trace globals directly inside the store.
- [DONE] Keep event payloads bounded and metadata-only. Never log or trace `state_json`.
- [DONE] Reuse the existing backend metrics surface for low-cardinality counters and timings for workflow-state operations.
- [DONE] Confirm the configured SQLite pragmas, especially WAL, busy timeout, foreign keys, and synchronous mode, are applied consistently for the workflow-state store's short-lived connection model.
- [DONE] Add concurrency coverage that exercises repeated saves against a temporary SQLite database to prove the baseline local behavior does not corrupt the current row.
- [DONE] Keep the event vocabulary ready for the future optimistic-concurrency error path, including a dedicated conflict event and counter seam.

**Validation**

- [DONE] Add and pass unit tests for workflow-state observability event payload shaping if the implementation exposes a direct test seam.
- [DONE] Add and pass an integration test that performs concurrent saves against a temporary workflow-state database.
- [DONE] Run `backend/.venv\Scripts\python.exe -m pytest backend/tests/unit/observability/test_workflow_state_events.py backend/tests/integration/test_workflow_state_store_concurrency.py` from the repository root.

**Exit criteria**

- [DONE] Workflow-state operations are diagnosable without leaking state content.
- [DONE] The local SQLite concurrency baseline is explicitly covered.
- [DONE] The persistence slice remains decoupled from API and orchestration code.

### [DONE] Phase 6. Tests, Fixtures, and Quality Gates

**Goal**

Close the gap between the current smoke coverage and the architecture acceptance criteria using backend-local fixtures and validation commands.

**Files to create or update**

- [DONE] `backend/tests/fixtures/config/workflow_state_sqlite.yaml`
- [DONE] `backend/tests/fixtures/config/workflow_state_sqlite_small_max_size.yaml`
- [DONE] `backend/tests/fixtures/config/workflow_state_sqlite_delete_reset.yaml`
- [DONE] `backend/tests/fixtures/config/workflow_state_fake.yaml`
- [DONE] `backend/tests/unit/persistence/test_sqlite_workflow_state_schema.py`
- [DONE] `backend/tests/unit/persistence/test_sqlite_workflow_state_serialization.py`
- [DONE] `backend/tests/unit/persistence/test_sqlite_workflow_state_reset.py`
- [DONE] `backend/tests/unit/persistence/test_sqlite_workflow_state_health.py`
- [DONE] `backend/tests/unit/persistence/test_fake_workflow_state_store.py`
- [DONE] `backend/tests/integration/test_workflow_state_store_sqlite_smoke.py`
- [DONE] `backend/tests/integration/test_workflow_state_store_concurrency.py`
- [DONE] `backend/tests/integration/test_startup_persistence.py`

**Implementation tasks**

- [DONE] Add focused unit coverage for settings parsing, session ID validation, default empty-state stability, schema idempotence, serialization, size limits, sensitive-data handling, and fake-store behavior.
- [DONE] Add integration coverage for fresh database bootstrap, re-opening an initialized database, missing-session load, repeated-save version increments, reset metadata, safe health output, and concurrency.
- [DONE] Keep all adapter tests rooted in `tmp_path` or equivalent temporary directories; no test should depend on real `backend/data/workflow_state.db`.
- [DONE] Keep the fake store as the default choice for higher-level session, orchestration, and API unit tests. Reserve SQLite integration tests for the adapter and startup wiring only.
- [DONE] Re-run the relevant startup test after any settings or migration change so backend lifespan wiring remains stable.

**Validation**

- [DONE] Run `backend/.venv\Scripts\python.exe -m pytest backend/tests/unit/persistence backend/tests/integration/test_workflow_state_store_sqlite_smoke.py backend/tests/integration/test_workflow_state_store_concurrency.py backend/tests/integration/test_startup_persistence.py` from the repository root.
- [DONE] Run `backend/.venv\Scripts\python.exe -m ruff check backend/app/persistence backend/app/config backend/tests/unit/persistence backend/tests/integration/test_workflow_state_store_sqlite_smoke.py backend/tests/integration/test_workflow_state_store_concurrency.py backend/tests/integration/test_startup_persistence.py` from the repository root.
- [DONE] Run `backend/.venv\Scripts\python.exe -m mypy backend/app` from the repository root.

**Exit criteria**

- [DONE] Workflow-state behavior is covered by backend-local unit, integration, lint, and type-check gates.
- [DONE] The architecture acceptance criteria have executable coverage or an explicit deferred note.

### [DONE] Phase 7. Freeze and Handoff

**Goal**

Document the workflow-state boundary as stable and make the next backend consumers explicit.

**Files to create or update**

- [DONE] `backend/README.md`
- [DONE] `docs/backend-persistence-plan.md`
- [DONE] `docs/backend-sqlite-workflow-state-plan.md`

**Implementation tasks**

- [DONE] Update `backend/README.md` with the stable workflow-state boundary, backend-local configuration keys, default database file location under `backend/data/`, reset semantics, and validation commands.
- [DONE] Record any final shared-SQLite conventions that now apply to both the workflow-state and trace-store adapters.
- [DONE] Note any intentionally deferred items such as cleanup policies, compare-and-set conflict handling, or stricter history compaction, so later phases do not treat them as accidental omissions.
- [DONE] Hand off to the next workflow-state consumers under `docs/backend-api-architecture.md` and the future session-service document, which will decide when to load state, when to save state, and how much conversation history to persist.
- [DONE] Keep the handoff consistent with the existing trace-store slice rather than re-opening finished persistence-foundation work.

**Validation**

- [DONE] Re-run the full backend quality gate from the repository root with `backend/.venv\Scripts\python.exe -m pytest backend/tests`, `backend/.venv\Scripts\python.exe -m ruff check backend`, and `backend/.venv\Scripts\python.exe -m mypy backend/app`.

**Exit criteria**

- [DONE] The workflow-state slice is documented as a stable backend boundary.
- [DONE] The next backend phases can consume workflow-state through contracts and startup wiring without knowing SQLite internals.

---

## 6. Acceptance Focus

This plan is complete when the backend workflow-state implementation satisfies the architecture's core acceptance goals using the existing `backend/` layout:

- `backend/app/persistence/sqlite_workflow_state_store.py` implements the existing workflow-state contract from `backend/app/contracts/state.py`.
- SQLite details remain isolated to `backend/app/persistence/` and shared SQLite helpers.
- Workflow-state paths, config, tests, and startup behavior remain rooted under `backend/`.
- `load`, `save`, `reset`, and `health` all behave according to the workflow-state architecture.
- Reset affects only short-term workflow state and does not modify trace persistence, long-term memory, LLM settings, MCP settings, or policy configuration.
- Health responses, errors, logs, and traces stay safe and redacted.
- Unit and integration coverage prove the backend is ready for the later API and session-service slices.

---

## 7. Summary

The repository already had a backend-local SQLite workflow-state implementation, and this plan extended that foundation to the architecture-defined bar for schema richness, reset semantics, safe health behavior, observability hooks, and validation.

This work did not create a second workflow-state stack. It extended the existing modules under `backend/app/persistence/`, kept contracts under `backend/app/contracts/`, kept tests under `backend/tests/`, and froze the workflow-state slice as a stable backend boundary for the upcoming API and session-service consumers.