# Backend SQLite Trace Store Implementation Plan

**Document:** `backend-sqlite-trace-store-plan.md`  
**Version:** 1.0  
**Source alignment:** `backend-sqlite-trace-store-architecture.md`, `backend-persistence-plan.md`, `backend-observability-plan.md`, and the current backend persistence/observability baseline  
**Repository rule:** all backend application code lives under `backend/`

---

## 1. Purpose

This plan converts the backend SQLite trace-store architecture into an implementation sequence that can be delivered in small, low-risk phases.

The plan is intentionally strict about repository boundaries:

- Backend application code belongs in `backend/`.
- Backend source modules belong in `backend/app/`.
- Backend tests belong in `backend/tests/`.
- Backend configuration files belong in `backend/config/`.
- Backend local data files belong in `backend/data/`.
- Documentation updates belong in `docs/`.
- No backend runtime, persistence, observability, or SQLite adapter code should be placed in the repository root, `frontend/`, or `mcp/`.

For clarity, this document uses filesystem paths such as `backend/app/persistence/sqlite_trace_store.py`. Python imports may still use the `app.*` package path because `backend/` is the Python project root.

This phase is not greenfield work. The repository already contains a real trace-store slice under `backend/`, but that slice is intentionally narrow. The implementation plan therefore focuses on extending the current backend modules instead of creating parallel contracts, duplicate fakes, or a second trace persistence path.

---

## 2. Review Outcomes

The SQLite trace-store architecture document is implementation-ready and fits the current backend persistence and observability direction. It is strong on append-first persistence, trace correlation, redaction, debug query safety, retention boundaries, and the rule that only backend persistence adapters know SQLite internals.

The review also confirms that the repository already contains a usable but narrower backend trace baseline that must be extended rather than replaced:

- `backend/app/contracts/trace.py` already defines the canonical trace contract surface and the current `TraceEvent` dataclass.
- `backend/app/persistence/trace_store.py` already resolves the configured trace-store implementation.
- `backend/app/persistence/sqlite_trace_store.py` and `backend/app/persistence/sqlite_trace_schema.py` already provide append-only SQLite event persistence under `backend/`.
- `backend/app/persistence/settings.py` already resolves typed trace persistence settings rooted in the backend project.
- `backend/app/config/schemas.py`, `backend/app/config/validation.py`, and `backend/app/config/view.py` already validate and expose the trace-related configuration section.
- `backend/app/persistence/factory.py` already wires the trace store into backend startup and aggregate persistence construction.
- `backend/app/persistence/health.py` already includes trace readiness in aggregate persistence health.
- `backend/app/testing/fakes/fake_trace.py` already provides a deterministic in-memory fake trace store.
- `backend/app/observability/tracing.py` already records redacted trace events through `TraceRecorder` and already depends on the current `TraceStore` contract.
- `backend/tests/integration/test_trace_store_sqlite_smoke.py` already proves schema bootstrap during startup and single-event SQLite persistence.

The main implementation concerns to resolve explicitly during execution are:

1. **The current trace contract is too narrow for the architecture.**  
   `backend/app/contracts/trace.py` currently exposes `record_event` and `health` only, and the current `TraceEvent` shape does not capture the architecture's richer event identity, status, severity, correlation, summary, and query fields.

2. **Trace-specific settings are incomplete.**  
   `backend/app/persistence/settings.py` currently exposes generic SQLite settings plus `payload_max_chars`, while the architecture expects dedicated trace-store settings for payload/error bounds, read/search limits, raw-versus-hashed identifier policy, capture policy, and retention.

3. **The current schema is too small.**  
   `backend/app/persistence/sqlite_trace_schema.py` currently creates one `trace_events` table plus indexes, while the architecture expects a `trace_runs` summary table, ordered event rows with `sequence_no`, and `trace_retention_runs` metadata.

4. **The current store only supports write-one-event behavior.**  
   `backend/app/persistence/sqlite_trace_store.py` currently records one event and returns shallow health output. The architecture requires `record_events`, `read_trace`, `search_traces`, richer health, safe not-found/query behavior, and optional retention cleanup.

5. **Write-path shaping is only partially enforced today.**  
   The current store serializes payload JSON, but the architecture requires identifier validation, event-name validation, bounded string fields, raw ID policy enforcement, session/user hashing, payload byte limits, and trace-run summary maintenance.

6. **The store must add defense-in-depth without duplicating observability ownership.**  
   `backend/app/observability/tracing.py` and `backend/app/observability/redaction.py` should remain the main event-shaping boundary, but the SQLite adapter still needs final byte-size enforcement, safe storage normalization, and query-safe readback behavior.

7. **Health and error behavior are still shallow.**  
   The current trace health payload only proves that SQLite opens. The architecture expects schema version visibility, required-versus-optional behavior, safe retention status, known trace query/write/migration error types, and no leakage of SQL, event payloads, or full filesystem paths.

8. **Fake-store and test coverage are not broad enough yet.**  
   The repo has a fake trace store and a smoke test, but it still lacks coverage for schema expansion, batch writes, ordered reads, summary searches, retention, query limits, validation failures, payload truncation, and concurrency.

9. **Avoid unnecessary file churn.**  
   The implementation should keep the canonical trace contract in `backend/app/contracts/trace.py`, the canonical fake in `backend/app/testing/fakes/fake_trace.py`, the current request context helpers in `backend/app/observability/context.py`, and the shared redaction rules in `backend/app/observability/redaction.py`. Add new persistence-local helper files only where they simplify real complexity.

10. **All backend-owned paths must stay under `backend/`.**  
   New trace fixtures belong under `backend/tests/fixtures/config/`, runtime modules under `backend/app/`, and local trace databases under `backend/data/`. No plan step should imply repo-root trace code or repo-root trace data.

---

## 3. Non-Negotiable Boundary Rules

- Treat `backend/` as the Python project root for all trace-store work.
- Create runtime trace-store modules only under `backend/app/persistence/` and `backend/app/observability/`.
- Keep the canonical trace contract under `backend/app/contracts/trace.py`.
- Keep the canonical fake trace store under `backend/app/testing/fakes/fake_trace.py`.
- Keep backend test code under `backend/tests/`.
- Keep backend configuration under `backend/config/` and backend-local SQLite files under `backend/data/`.
- Keep documentation-only artifacts under `docs/`.
- Do not place backend trace-store, query, health, or SQLite code in the repository root, `frontend/`, or `mcp/`.
- Do not let any module outside `backend/app/persistence/` import `sqlite3`, execute trace SQL, or depend on SQLite row shapes, sequence allocation, or schema table names.
- Keep `backend/app/main.py:app = create_app()` import-safe; all I/O, schema bootstrap, and database initialization belong in lifespan startup.
- Do not create duplicate contract files, fake-store files, or observability context modules under new names unless a later cross-repo refactor clearly requires it.
- Logs, traces, health responses, and errors must not expose raw prompts, raw completions, raw request bodies, raw response bodies, raw workflow state, raw tool payloads, raw memory content, API keys, provider credentials, connection strings, authorization headers, cookies, JWTs, or full stack traces.
- Relative trace-store paths must resolve from `backend/`, not from the shell's current working directory.
- Session reset must not delete trace rows.
- Trace retention cleanup, if enabled, must delete trace rows only; it must not touch workflow state, memory-store data, ArcadeDB content, policy config, LLM config, or MCP config.

---

## 4. Phase Overview

| Phase | Name | Primary Outcome |
|---|---|---|
| 0 | [DONE] Current Trace Baseline | The repository already has a trace contract, SQLite trace adapter, startup wiring, fake store, and smoke coverage under `backend/`. |
| 1 | [DONE] Trace Settings and Contract Expansion | Trace-specific runtime settings and contract models become explicit without leaving the existing `backend/` module layout. |
| 2 | [DONE] Schema and Query Surface Expansion | The SQLite trace schema grows from a single event table into the architecture-aligned run/event/retention model while keeping SQL isolated under `backend/app/persistence/`. |
| 3 | [DONE] Write Path Hardening | `record_event` and `record_events` validate, redact, bound, hash, order, and summarize trace events safely. |
| 4 | [DONE] Read, Search, Health, and Retention | Safe debug-read and summary-search APIs, richer health, and optional cleanup behavior become available through the trace-store contract. |
| 5 | [DONE] Startup, Observability, and Error Integration | Startup wiring, recorder behavior, metrics/logging, and backend-specific trace errors line up with the richer store contract without recursive trace writes. |
| 6 | [DONE] Tests, Fixtures, and Quality Gates | Backend-local unit, integration, lint, and type-check coverage proves the architecture acceptance criteria. |
| 7 | [DONE] Freeze and Handoff | The trace-store boundary is documented as stable for later API, session, and orchestration consumers. |

---

## 5. Detailed Implementation Phases

### [DONE] Phase 0. Current Trace Baseline

**Goal**

Record the trace-store work that already exists so the plan extends the current backend instead of re-describing a greenfield slice.

**Files already present**

- [DONE] `backend/app/contracts/trace.py`
- [DONE] `backend/app/persistence/trace_store.py`
- [DONE] `backend/app/persistence/sqlite_trace_store.py`
- [DONE] `backend/app/persistence/sqlite_trace_schema.py`
- [DONE] `backend/app/persistence/settings.py`
- [DONE] `backend/app/persistence/factory.py`
- [DONE] `backend/app/persistence/health.py`
- [DONE] `backend/app/testing/fakes/fake_trace.py`
- [DONE] `backend/app/observability/tracing.py`
- [DONE] `backend/tests/integration/test_trace_store_sqlite_smoke.py`
- [DONE] `backend/config/app.yaml`

**Implementation outcomes already in place**

- [DONE] Trace provider selection is already routed through typed persistence settings.
- [DONE] The SQLite trace store is already initialized during backend lifespan startup.
- [DONE] Trace SQL already lives under `backend/app/persistence/`, not in API, agent, or orchestration code.
- [DONE] The backend already has a deterministic fake trace store for higher-level tests.
- [DONE] The current `TraceRecorder` already persists redacted payload dictionaries through the shared store contract.

**Validation already covered**

- [DONE] `backend/tests/integration/test_trace_store_sqlite_smoke.py`
- [DONE] The current backend startup path already bootstraps trace persistence from `backend/app/persistence/factory.py`.

**Exit criteria**

- [DONE] The plan starts from the real trace-store baseline under `backend/` instead of inventing a second trace stack.

### [DONE] Phase 1. Trace Settings and Contract Expansion

**Goal**

Extend the existing backend configuration and trace contract surfaces so the store can express the architecture-required behavior without breaking the `backend/`-local module layout.

**Files to create or update**

- [DONE] `backend/app/persistence/settings.py`
- [DONE] `backend/app/config/schemas.py`
- [DONE] `backend/app/config/validation.py`
- [DONE] `backend/app/config/view.py`
- [DONE] `backend/app/contracts/trace.py`
- [DONE] `backend/app/testing/fakes/fake_trace.py`
- [DONE] `backend/config/app.yaml`
- [DONE] `backend/tests/unit/persistence/test_persistence_settings.py`
- [DONE] `backend/tests/unit/config/test_config_view.py`
- [DONE] `backend/tests/unit/persistence/test_fake_trace_store.py`
- [DONE] `backend/tests/fixtures/config/trace_sqlite.yaml`
- [DONE] `backend/tests/fixtures/config/trace_sqlite_no_schema_init.yaml`
- [DONE] `backend/tests/fixtures/config/trace_sqlite_small_payload.yaml`
- [DONE] `backend/tests/fixtures/config/trace_sqlite_retention_enabled.yaml`
- [DONE] `backend/tests/fixtures/config/trace_fake.yaml`

**Implementation tasks**

- [DONE] Add a dedicated `SqliteTraceStoreSettings` runtime type instead of relying only on the generic `SqliteStoreSettings` shape.
- [DONE] Extend the validated config pipeline with the trace-store-specific settings described by the architecture, including:
  - `max_event_payload_bytes`
  - `max_error_detail_bytes`
  - `max_events_per_trace_read`
  - `max_search_results`
  - `store_raw_session_id`
  - `store_session_id_hash`
  - `store_raw_user_id`
  - `store_user_id_hash`
  - `capture_request_body`
  - `capture_response_body`
  - `capture_llm_prompts`
  - `capture_llm_completions`
  - `capture_tool_payloads`
  - `capture_memory_queries`
  - `retention.enabled`
  - `retention.keep_days`
  - `retention.cleanup_batch_size`
- [DONE] Keep backend-local defaults anchored under `backend/data/trace.db` and preserve backend-root-relative path resolution.
- [DONE] Decide how the current `payload_max_chars` setting maps into the richer byte-based payload limit. Prefer one canonical runtime field and keep any compatibility alias temporary and explicit.
- [DONE] Expand the trace contract in `backend/app/contracts/trace.py` to support the full planned surface:
  - richer `TraceEvent`
  - `record_events`
  - `read_trace`
  - `search_traces`
  - `TraceReadModel`
  - `TraceSummary`
  - `TraceSearchFilters`
- [DONE] Keep the contract file canonical. Do not create a second public trace DTO module under `backend/app/persistence/` unless a later refactor clearly needs persistence-local internal row types.
- [DONE] Prefer additive contract evolution over churn. For example, if the current `TraceEvent.timestamp` is already a `datetime`, normalize that at the adapter boundary instead of forcing unnecessary call-site rewrites.
- [DONE] Extend `backend/app/testing/fakes/fake_trace.py` to match the richer contract behaviorally, not schema-wise.
- [DONE] Preserve compatibility between `backend/app/contracts/trace.py` and `backend/app/observability/events.py` so event constants do not drift into two competing vocabularies.

**Validation**

- [DONE] Add and pass targeted settings tests proving the new trace options parse correctly from fixture-backed config files under `backend/tests/fixtures/config/`.
- [DONE] Add and pass focused fake-store tests for the expanded contract surface and default limit behavior.
- [DONE] Add and pass configuration-view tests proving backend-root-relative path resolution still behaves deterministically from both the repository root and `backend/`.
- [DONE] Run `.venv\Scripts\python.exe -m pytest tests/unit/persistence/test_persistence_settings.py tests/unit/config/test_config_view.py tests/unit/persistence/test_fake_trace_store.py` from `backend/`.

**Exit criteria**

- [DONE] Trace-store runtime settings are fully typed.
- [DONE] The trace contract can express write, read, search, and health use cases without leaking SQLite internals.
- [DONE] Backend-root-relative defaults remain deterministic.

### [DONE] Phase 2. Schema and Query Surface Expansion

**Goal**

Upgrade the narrow current SQLite schema into the architecture-aligned trace-run and trace-event model while keeping all SQL, DDL, migrations, and query construction isolated under `backend/app/persistence/`.

**Files to create or update**

- `backend/app/persistence/sqlite_trace_schema.py`
- `backend/app/persistence/sqlite_trace_store.py`
- `backend/app/persistence/sqlite_trace_queries.py`
- `backend/app/persistence/serialization.py`
- `backend/app/persistence/errors.py`
- `backend/app/persistence/sqlite/migrations.py`
- `backend/tests/unit/persistence/test_sqlite_trace_schema.py`
- `backend/tests/unit/persistence/test_sqlite_trace_query_builder.py`
- `backend/tests/integration/test_trace_store_sqlite_smoke.py`
- `backend/tests/integration/test_startup_persistence.py`

**Implementation tasks**

- [DONE] Expand the current single-table schema into the architecture-aligned model using backend-local tables for:
   - [DONE] `schema_version`
   - [DONE] `trace_runs`
   - [DONE] `trace_events`
   - [DONE] `trace_retention_runs`
- [DONE] Keep all DDL, schema constants, and schema-version ownership in `backend/app/persistence/sqlite_trace_schema.py`.
- [DONE] Add only the minimal summary and event columns needed for V1 debug access patterns, including:
   - [DONE] `trace_id`
   - [DONE] `sequence_no`
   - [DONE] `event_name`
   - [DONE] `event_type`
   - [DONE] `status`
   - [DONE] `severity`
   - [DONE] timestamps
   - [DONE] duration
   - [DONE] hashed/raw identity fields as permitted by settings
   - [DONE] agent/strategy/llm/tool/error summary fields
   - [DONE] payload size and redaction version
- [DONE] Add only the indexes needed for known access patterns such as trace read order, recent traces, status, use case, error type, and event-name filters.
- [DONE] Introduce `backend/app/persistence/sqlite_trace_queries.py` only to keep read/search SQL and filter normalization out of `sqlite_trace_store.py`. Keep it persistence-local and parameterized.
- [DONE] Reuse the shared SQLite bootstrap helpers under `backend/app/persistence/sqlite/`; do not create a second SQLite initialization path.
- [DONE] Decide and document the migration strategy from the current `trace_events`-only schema. If migration is needed, make it explicit, versioned, and one-way. Do not silently discard existing `backend/data/trace.db` content.
- [DONE] Keep schema initialization idempotent and validate the expected schema version during startup and health.
- [DONE] Prefer hashed identifiers in summary tables by default; raw user/session identifiers should remain opt-in and local-debug only.

**Validation**

- [DONE] Add and pass unit tests proving schema initialization is idempotent and the expected tables and indexes exist.
- [DONE] Add and pass query-builder tests proving read/search SQL stays parameterized and bounded.
- [DONE] Add and pass integration coverage for fresh database creation and re-opening an existing database.
- [DONE] Add and pass a migration-focused integration test if the legacy one-table schema needs an upgrade path.
- [DONE] Run `.venv\Scripts\python.exe -m pytest tests/unit/persistence/test_sqlite_trace_schema.py tests/unit/persistence/test_sqlite_trace_query_builder.py tests/integration/test_trace_store_sqlite_smoke.py tests/integration/test_startup_persistence.py` from `backend/`.

**Exit criteria**

- [DONE] The trace schema supports both ordered event reads and query-friendly trace summaries.
- [DONE] Schema initialization and version validation remain idempotent and backend-local.
- [DONE] No module outside `backend/app/persistence/` learns table names, row shapes, or index names.

### [DONE] Phase 3. Write Path Hardening

**Goal**

Bring the SQLite write behavior up to the architecture contract while preserving the backend's existing observability ownership boundaries.

**Files to create or update**

- `backend/app/persistence/sqlite_trace_store.py`
- `backend/app/contracts/trace.py`
- `backend/app/observability/redaction.py`
- `backend/app/persistence/serialization.py`
- `backend/app/persistence/errors.py`
- `backend/tests/unit/persistence/test_sqlite_trace_redaction.py`
- `backend/tests/unit/persistence/test_sqlite_trace_serialization.py`
- `backend/tests/integration/test_sqlite_trace_store_recording.py`
- `backend/tests/integration/test_sqlite_trace_store_batch.py`

**Implementation tasks**

- [DONE] Validate `trace_id`, `event_id`, `event_name`, `event_type`, `status`, `severity`, and bounded string metadata before persistence.
- [DONE] Normalize timestamps to UTC ISO strings at the adapter boundary.
- [DONE] Generate `event_id` when callers do not provide one.
- [DONE] Apply raw-versus-hashed identity policy consistently for session and user identifiers.
- [DONE] Reuse the existing observability redaction rules as the common source of truth, but keep final payload byte enforcement and storage-safe summarization inside the trace adapter.
- [DONE] Enforce `max_event_payload_bytes` and `max_error_detail_bytes` before commit. If a payload is too large, replace it with a bounded summary instead of persisting the original oversized content.
- [DONE] Use `BEGIN IMMEDIATE` and parameterized SQL to:
   - [DONE] upsert `trace_runs`
   - [DONE] allocate `sequence_no`
   - [DONE] insert `trace_events`
   - [DONE] update summary counters and last-seen fields
- [DONE] Implement `record_events` with bounded batch size, atomic rollback semantics, and per-trace sequence allocation inside one transaction.
- [DONE] Keep trace write failure behavior safe: the store should raise known backend trace-store errors, while the higher-level recorder decides whether request handling continues for optional/degraded paths.
- [DONE] Do not recursively trace trace-store write success. Trace-store write failures should surface through logs and metrics, with trace emission only if explicit recursion protection exists.

**Validation**

- [DONE] Add and pass unit tests for identifier validation, bounded string normalization, redaction behavior, payload truncation, and JSON-safe serialization.
- [DONE] Add and pass integration tests for:
   - [DONE] single-event persistence
   - [DONE] ordered multi-event persistence
   - [DONE] batch commit success
   - [DONE] batch rollback on invalid event
   - [DONE] run-summary counter updates
- [DONE] Run `.venv\Scripts\python.exe -m pytest tests/unit/persistence/test_sqlite_trace_redaction.py tests/unit/persistence/test_sqlite_trace_serialization.py tests/integration/test_sqlite_trace_store_recording.py tests/integration/test_sqlite_trace_store_batch.py` from `backend/`.

**Exit criteria**

- [DONE] Trace events are persisted redacted, bounded, ordered, and correlated by `trace_id`.
- [DONE] Batch writes are atomic for the batch.
- [DONE] The write path updates safe trace-run summaries without exposing raw payloads.

### [DONE] Phase 4. Read, Search, Health, and Retention

**Goal**

Expose the architecture's bounded debug-read and safe search behavior, plus richer health and optional cleanup, through the trace-store contract.

**Files to create or update**

- [DONE] `backend/app/persistence/sqlite_trace_store.py`
- [DONE] `backend/app/persistence/sqlite_trace_queries.py`
- [DONE] `backend/app/persistence/errors.py`
- [DONE] `backend/app/testing/fakes/fake_trace.py`
- [DONE] `backend/tests/unit/persistence/test_sqlite_trace_health.py`
- [DONE] `backend/tests/unit/persistence/test_fake_trace_store.py`
- [DONE] `backend/tests/integration/test_sqlite_trace_store_read_trace.py`
- [DONE] `backend/tests/integration/test_sqlite_trace_store_search.py`
- [DONE] `backend/tests/integration/test_sqlite_trace_store_retention.py`

**Implementation tasks**

- [DONE] Implement `read_trace(trace_id, limit)` with identifier validation, limit clamping, summary lookup, ordered event selection, JSON decode, and known not-found behavior.
- [DONE] Implement `search_traces(filters)` as a bounded summary query. Use `trace_runs` for summary filtering and `EXISTS` clauses only where event-specific filters are needed.
- [DONE] Add `TraceSearchFilters` normalization so search remains bounded by default and does not permit arbitrary SQL behavior.
- [DONE] Ensure search results return summaries only. Do not include full event payloads in search responses.
- [DONE] Extend the fake trace store so higher-level tests can exercise read/search behavior without SQLite.
- [DONE] Enrich `health()` output with safe readiness details such as schema initialization, schema version, provider, required flag, selected pragma mode, and retention-enabled state when those fields can be exposed safely.
- [DONE] Keep full database paths, payloads, raw IDs, SQL text, and stack traces out of health output.
- [DONE] Add optional retention cleanup support, disabled by default, using `trace_retention_runs` plus bounded deletion from `trace_runs` only. Rely on cascade delete for trace events.
- [DONE] Add known backend error wrappers for query, not-found, retention, migration, and availability paths.
- [DONE] Preserve the privacy rule that session reset does not delete traces.

**Validation**

- [DONE] Add and pass unit tests for fake-store limit behavior, safe health output shaping, and query-filter normalization.
- [DONE] Add and pass integration tests for:
   - [DONE] `read_trace` with ordered event return
   - [DONE] missing-trace behavior
   - [DONE] summary search by status, use case, event name, tool, LLM profile, and error type
   - [DONE] safe health output
   - [DONE] retention cleanup deleting trace rows only
- [DONE] Run `.venv\Scripts\python.exe -m pytest tests/unit/persistence/test_sqlite_trace_health.py tests/unit/persistence/test_fake_trace_store.py tests/integration/test_sqlite_trace_store_read_trace.py tests/integration/test_sqlite_trace_store_search.py tests/integration/test_sqlite_trace_store_retention.py` from `backend/`.

**Exit criteria**

- [DONE] `read_trace`, `search_traces`, and `health` behave according to the architecture.
- [DONE] Debug-query behavior is bounded and safe.
- [DONE] Retention cleanup, when enabled, affects trace rows only.

### [DONE] Phase 5. Startup, Observability, and Error Integration

**Goal**

Wire the richer trace store cleanly into backend startup, observability, and aggregate health without creating recursive trace behavior or splitting construction logic.

**Files to create or update**

- [DONE] `backend/app/persistence/trace_store.py`
- [DONE] `backend/app/persistence/factory.py`
- [DONE] `backend/app/persistence/health.py`
- [DONE] `backend/app/persistence/errors.py`
- [DONE] `backend/app/config/bootstrap.py`
- [DONE] `backend/app/foundation/container.py`
- [DONE] `backend/app/observability/tracing.py`
- [DONE] `backend/app/observability/events.py`
- [DONE] `backend/app/observability/metrics.py`
- [DONE] `backend/tests/unit/observability/test_trace_recorder.py`
- [DONE] `backend/tests/integration/test_startup_persistence.py`
- [DONE] `backend/tests/unit/test_health.py`
- [DONE] `backend/tests/fixtures/config/persistence_trace_optional.yaml`

**Implementation tasks**

- [DONE] Decide whether `backend/app/persistence/trace_store.py` remains the explicit trace-store build boundary or whether `backend/app/persistence/factory.py` becomes the only construction seam. Keep one clear backend-owned path.
- [DONE] Build the richer SQLite trace store from typed settings resolved under `backend/`; the adapter must not read environment variables directly.
- [DONE] Keep all SQLite setup in lifespan startup. Do not move database initialization into import-time code.
- [DONE] Update `TraceRecorder` so it can emit the richer trace-event shape, including event name, status, severity, and summary fields such as agent/strategy/llm/tool metadata where available.
- [DONE] Preserve the existing backend rule that trace-store failures should not recursively generate more trace-store writes.
- [DONE] Add low-cardinality metrics and structured-log coverage for trace record/read/search/retention success/failure paths.
- [DONE] Preserve required-versus-optional trace behavior in aggregate persistence health and startup failure handling.
- [DONE] Wrap SQLite and query failures in backend-specific trace errors without exposing SQL text, payload content, or sensitive filesystem details.
- [DONE] Keep future API debug routes as later consumers of the contract only; do not add route-level SQLite access in this phase.

**Validation**

- [DONE] Add and pass unit tests proving `TraceRecorder` maps runtime inputs into the richer trace-event surface without recursive failure behavior.
- [DONE] Add and pass startup tests for required trace-store failure, optional trace-store degradation, and aggregate health semantics.
- [DONE] Run `.venv\Scripts\python.exe -m pytest tests/unit/observability/test_trace_recorder.py tests/integration/test_startup_persistence.py tests/unit/test_health.py` from `backend/`.

**Exit criteria**

- [DONE] Startup and observability layers consume the trace store only through backend-owned contracts and typed settings.
- [DONE] Trace-store failures are diagnosable without recursive trace writes or sensitive leakage.
- [DONE] Aggregate health remains consistent with the backend's required/optional persistence model.

### [DONE] Phase 6. Tests, Fixtures, and Quality Gates

**Goal**

Close the gap between the current smoke coverage and the architecture acceptance criteria using backend-local fixtures, targeted adapter tests, and full backend quality gates.

**Files to create or update**

- [DONE] `backend/tests/fixtures/config/trace_sqlite.yaml`
- [DONE] `backend/tests/fixtures/config/trace_sqlite_no_schema_init.yaml`
- [DONE] `backend/tests/fixtures/config/trace_sqlite_small_payload.yaml`
- [DONE] `backend/tests/fixtures/config/trace_sqlite_retention_enabled.yaml`
- [DONE] `backend/tests/fixtures/config/trace_fake.yaml`
- [DONE] `backend/tests/unit/persistence/test_fake_trace_store.py`
- [DONE] `backend/tests/unit/persistence/test_sqlite_trace_schema.py`
- [DONE] `backend/tests/unit/persistence/test_sqlite_trace_query_builder.py`
- [DONE] `backend/tests/unit/persistence/test_sqlite_trace_redaction.py`
- [DONE] `backend/tests/unit/persistence/test_sqlite_trace_serialization.py`
- [DONE] `backend/tests/unit/persistence/test_sqlite_trace_health.py`
- [DONE] `backend/tests/integration/test_trace_store_sqlite_smoke.py`
- [DONE] `backend/tests/integration/test_sqlite_trace_store_recording.py`
- [DONE] `backend/tests/integration/test_sqlite_trace_store_batch.py`
- [DONE] `backend/tests/integration/test_sqlite_trace_store_read_trace.py`
- [DONE] `backend/tests/integration/test_sqlite_trace_store_search.py`
- [DONE] `backend/tests/integration/test_sqlite_trace_store_retention.py`
- [DONE] `backend/tests/integration/test_sqlite_trace_store_concurrency.py`
- [DONE] `backend/tests/integration/test_startup_persistence.py`

**Implementation tasks**

- [DONE] Add focused unit coverage for settings parsing, schema idempotence, query parameterization, identifier validation, redaction, payload size limits, fake-store behavior, and health output safety.
- [DONE] Add integration coverage for:
   - [DONE] fresh database bootstrap
   - [DONE] re-opening an initialized database
   - [DONE] single-event write
   - [DONE] ordered multi-event write
   - [DONE] batch rollback
   - [DONE] `read_trace`
   - [DONE] `search_traces`
   - [DONE] retention cleanup
   - [DONE] safe startup behavior
   - [DONE] concurrent writes against a temporary SQLite database
- [DONE] Keep all adapter tests rooted in `tmp_path` or equivalent temporary directories. No test should depend on real `backend/data/trace.db`.
- [DONE] Keep the fake trace store as the default choice for higher-level API, session, orchestration, and gateway unit tests. Reserve SQLite integration tests for the adapter and startup wiring.
- [DONE] Re-run startup and health tests after any schema, settings, or error-model change so the backend lifespan path stays stable.

**Validation**

- [DONE] Run `.venv\Scripts\python.exe -m pytest tests/unit/persistence tests/unit/observability/test_trace_recorder.py tests/integration/test_trace_store_sqlite_smoke.py tests/integration/test_sqlite_trace_store_recording.py tests/integration/test_sqlite_trace_store_batch.py tests/integration/test_sqlite_trace_store_read_trace.py tests/integration/test_sqlite_trace_store_search.py tests/integration/test_sqlite_trace_store_retention.py tests/integration/test_sqlite_trace_store_concurrency.py tests/integration/test_startup_persistence.py` from `backend/`.
- [DONE] Run `.venv\Scripts\python.exe -m ruff check app tests` from `backend/`.
- [DONE] Run `.venv\Scripts\python.exe -m mypy app` from `backend/`.

**Exit criteria**

- [DONE] Trace-store behavior is covered by backend-local unit, integration, lint, and type-check gates.
- [DONE] The architecture acceptance criteria have executable coverage or an explicit deferred note.

### [DONE] Phase 7. Freeze and Handoff

**Goal**

Document the trace-store boundary as stable and make the next backend consumers explicit.

**Files to create or update**

- [DONE] `backend/README.md`
- [DONE] `docs/backend-persistence-plan.md`
- [DONE] `docs/backend-sqlite-trace-store-plan.md`

**Implementation tasks**

- [DONE] Update `backend/README.md` with the stable trace-store boundary, backend-local configuration keys, default database file location under `backend/data/trace.db`, read/search availability, retention defaults, and validation commands.
- [DONE] Record shared SQLite conventions that now apply to both workflow-state and trace adapters.
- [DONE] Note intentionally deferred items such as protected trace debug routes, session/user trace-delete policy, prompt/completion capture in local debug mode, or future outbox/reliability patterns.
- [DONE] Hand off to the next backend consumers under `docs/backend-api-architecture.md`, the future session-service document, and the future orchestration document. Those later phases decide when trace reads are exposed and which runtime modules emit which event families.
- [DONE] Keep the handoff consistent with the existing backend observability and persistence baselines rather than reopening finished foundation work.

**Validation**

- [DONE] Re-run the full backend quality gate from `backend/` with `.venv\Scripts\python.exe -m pytest`, `.venv\Scripts\python.exe -m ruff check .`, and `.venv\Scripts\python.exe -m mypy app`.

**Exit criteria**

- [DONE] The trace-store slice is documented as a stable backend boundary.
- [DONE] The next backend phases can consume trace storage through contracts and startup wiring without knowing SQLite internals.

---

## 6. Acceptance Focus

This plan is complete when the backend trace-store implementation satisfies the architecture's core acceptance goals using the existing `backend/` layout:

- `backend/app/persistence/sqlite_trace_store.py` implements the trace contract from `backend/app/contracts/trace.py`.
- SQLite details remain isolated to `backend/app/persistence/` and the shared SQLite helper modules.
- Trace settings, fixtures, startup behavior, and database paths remain rooted under `backend/`.
- `record_event`, `record_events`, `read_trace`, `search_traces`, and `health` all behave according to the trace-store architecture.
- Trace events are correlated by `trace_id` and ordered by per-trace `sequence_no`.
- Trace payloads are JSON-safe, redacted before persistence, and bounded by configured limits.
- Raw prompts, completions, workflow-state JSON, request bodies, response bodies, and full tool payloads are not persisted by default.
- Session reset does not delete traces.
- Trace retention cleanup, if enabled, deletes trace rows only.
- Health responses, errors, logs, and metrics stay safe and redacted.
- Unit and integration coverage prove the backend is ready for the later API, session-service, and orchestration slices.

---

## 7. Summary

The repository already had a backend-local SQLite trace baseline, and this plan extended that baseline to the architecture-defined bar for bounded queries, redaction, retention behavior, concurrency coverage, and startup-safe health integration.

This work did not create a second trace stack. It extended the existing modules under `backend/app/persistence/`, kept contracts under `backend/app/contracts/`, kept tests under `backend/tests/`, and froze the trace-store slice as a stable backend boundary for the upcoming API, session-service, and orchestration consumers.