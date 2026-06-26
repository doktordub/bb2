# Backend Runtime

All backend application work lives under `backend/`. Run backend commands from this directory.

## Boundaries

- Backend application source lives in `backend/app/`.
- Backend runtime YAML lives in `backend/config/`.
- Backend tests and config fixtures live in `backend/tests/`.
- Architecture and handoff documents live in `docs/`.
- `frontend/`, `mcp/`, and the repository root are not backend runtime code locations.
- `.venv/` and `dist/` are local or generated artifacts, not the application source tree.

## Phase Scope

The backend foundation, core contracts, configuration, observability, general persistence, SQLite workflow-state, and SQLite trace-store slices are complete and frozen for later backend phases:

- deterministic backend-root-relative settings and config path resolution
- validated YAML loading, override merging, `${env:...}` interpolation, schema validation, and secret redaction
- import-safe application startup through `app.main`
- config-backed `/health` and `/capabilities` routes
- validated trace ID propagation, async-safe trace context, and request/response correlation headers
- config-driven structured or readable logging plus trace-safe error diagnostics
- shared redaction across config summaries, logs, traces, health payloads, and error metadata
- `TraceRecorder`, SQLite-backed trace persistence behind `app/persistence/`, and reusable health/metrics services
- persistence bundle wiring for workflow-state, trace, and optional memory providers
- SQLite workflow-state schema, safe reset semantics, observability hooks, and concurrency baseline
- SQLite trace-store schema, bounded read/search and retention behavior, plus concurrent write coverage
- stable shared contract DTOs, protocols, and in-memory fakes under `backend/app/contracts/` and `backend/app/testing/fakes/`
- backend-local unit tests plus linting and type checks

## Foundation Freeze

The following foundation surfaces are now the stable handoff boundary for deeper backend work:

- `app.main:create_app()`
- `FoundationContainer`
- `GET /health`
- `GET /capabilities`
- the backend settings loader and bootstrap path

The following concerns remain intentionally deferred:

- real MCP client adapter integration
- real LLM gateway adapters
- `memory_store` integration behind a backend `MemoryGateway`
- SQLite workflow state store
- auth and authorization behavior
- streaming chat routes
- orchestration runtime and `agent_framework` integration

The next architecture document is `../docs/backend-core-contracts-architecture.md` at the repository root.

## Core Contracts Freeze

The following core-contract surfaces are now the stable handoff boundary for later backend phases:

- `app/contracts/context.py`
- `app/contracts/results.py`
- `app/contracts/errors.py`
- `app/contracts/health.py`
- `app/contracts/agents.py`
- `app/contracts/strategies.py`
- `app/contracts/llm.py`
- `app/contracts/memory.py`
- `app/contracts/tools.py`
- `app/contracts/state.py`
- `app/contracts/trace.py`
- `app/contracts/policy.py`
- `app/contracts/config.py`
- `app/testing/fakes/`
- `tests/unit/contracts/`

The following concerns remain intentionally deferred:

- configuration schema validation and runtime loader integration beyond `ConfigurationView` and `ConfigurationLoader`
- API request and response mapping onto `RequestContext` and `OrchestrationResult`
- concrete workflow state implementations and deeper trace query/retention behavior
- concrete LLM, memory, and tool/MCP gateway adapters
- orchestration runtime and non-fake strategies
- production agent plugins and `agent_framework` integration

Later backend phases should build on these backend-local contract paths rather than introducing new shared contract locations.

## Configuration Freeze

The following configuration surfaces are now the stable handoff boundary for later backend phases:

- `backend/app/config/settings.py`
- `backend/app/config/bootstrap.py`
- `backend/app/config/loader.py`
- `backend/app/config/env_resolver.py`
- `backend/app/config/schemas.py`
- `backend/app/config/validation.py`
- `backend/app/config/view.py`
- `backend/app/config/redaction.py`
- `backend/app/contracts/config.py`
- `backend/config/app.yaml`
- `backend/tests/unit/config/`
- `backend/tests/fixtures/config/`

The backend now loads validated configuration through `YamlConfigurationLoader` during FastAPI lifespan startup. Runtime code should consume configuration through `ConfigurationView` or configuration-backed services, not through direct YAML parsing or `os.environ` access.

The following concerns remain intentionally deferred beyond this configuration phase:

- real LLM gateway adapters
- MCP client adapter
- SQLite workflow-state implementation beyond the existing trace store
- `memory_store` integration
- policy-engine behavior
- prompt-management details

The next backend phases should build on the observability slice rather than revisiting bootstrap, path resolution, or backend-local boundary decisions.

## Observability Freeze

The following observability surfaces are now the stable handoff boundary for later backend phases:

- `app/observability/context.py`
- `app/observability/ids.py`
- `app/observability/logging.py`
- `app/observability/tracing.py`
- `app/observability/events.py`
- `app/observability/redaction.py`
- `app/observability/health.py`
- `app/observability/metrics.py`
- `app/observability/middleware.py`
- `app/observability/errors.py`
- `app/persistence/trace_store.py`
- `app/persistence/sqlite_trace_store.py`
- `app/persistence/sqlite_trace_schema.py`
- `app/api/errors.py`
- `app/api/routes_health.py`
- `tests/unit/observability/`
- `tests/integration/test_startup_observability.py`
- `tests/integration/test_trace_store_sqlite_smoke.py`
- `tests/integration/test_observability_config_overrides.py`

Later backend phases can rely on these guarantees without reopening the observability foundation:

- each backend request receives a validated trace ID and returns it through `x-trace-id`
- runtime logging is reconfigured from validated observability settings after config load
- logs, traces, health payloads, config summaries, and error metadata share one compatible redaction model
- trace events are recorded through `TraceRecorder` and persisted only behind `app/persistence/`
- `/health` is driven by reusable aggregation logic and a config-backed detail toggle
- metrics remain low-cardinality, backend-local, and optional

The following observability concerns remain intentionally deferred:

- protected trace debug routes and access policy
- retention scheduling, archival, and compression policy
- per-token streaming trace events
- centralized log shipping
- OpenTelemetry or other distributed tracing integration
- provider-specific telemetry enrichments

## Persistence Freeze

The following persistence surfaces are now the stable handoff boundary for later backend phases:

- `app/persistence/settings.py`
- `app/persistence/paths.py`
- `app/persistence/serialization.py`
- `app/persistence/errors.py`
- `app/persistence/factory.py`
- `app/persistence/health.py`
- `app/persistence/sqlite/`
- `app/persistence/sqlite_workflow_state_store.py`
- `app/persistence/sqlite_workflow_state_schema.py`
- `app/persistence/sqlite_trace_store.py`
- `app/persistence/sqlite_trace_schema.py`
- `app/persistence/memory_store_adapter.py`
- `app/contracts/memory.py`
- `tests/unit/persistence/`
- `tests/integration/test_startup_persistence.py`
- `tests/integration/test_sqlite_connection_smoke.py`
- `tests/integration/test_trace_store_sqlite_smoke.py`
- `tests/integration/test_workflow_state_store_sqlite_smoke.py`
- `tests/fixtures/config/persistence_*.yaml`

Later backend phases can rely on these guarantees without reopening the persistence composition root:

- workflow-state and trace SQLite paths resolve from `backend/` and default into `backend/data/`
- memory access is isolated behind `app/persistence/memory_store_adapter.py`
- only persistence adapters import storage engines such as SQLite or `memory_store`
- `/health` reports safe required-versus-optional readiness for workflow-state, trace, and memory
- test fixtures exist for local SQLite startup, optional memory degradation, invalid providers, required-store failure, and fake-provider wiring

The following persistence concerns remain intentionally deferred:

- deeper workflow-state schema tuning and optimistic concurrency
- protected trace debug APIs and trace delete/export policy
- document ingestion and chunk lifecycle management beyond the shallow adapter boundary
- privacy export/delete workflows and retention policies
- deployment-volume, backup, and restore decisions

When the general persistence boundary froze, the next dependent documents were, in order:

- `../docs/backend-sqlite-workflow-state-architecture.md`
- `../docs/backend-sqlite-trace-store-architecture.md`
- `../docs/backend-memory-store-adapter-architecture.md`
- then the API, session, orchestration, tool, and agent architecture documents that consume the persistence boundaries

## Workflow-State Freeze

The following workflow-state surfaces are now the stable handoff boundary for later backend phases:

- `app/contracts/state.py`
- `app/persistence/workflow_state_store.py`
- `app/persistence/sqlite_workflow_state_store.py`
- `app/persistence/sqlite_workflow_state_schema.py`
- `tests/unit/persistence/test_sqlite_workflow_state_schema.py`
- `tests/unit/persistence/test_sqlite_workflow_state_serialization.py`
- `tests/unit/persistence/test_sqlite_workflow_state_reset.py`
- `tests/unit/persistence/test_sqlite_workflow_state_health.py`
- `tests/integration/test_workflow_state_store_sqlite_smoke.py`
- `tests/integration/test_workflow_state_store_concurrency.py`
- `tests/integration/test_startup_persistence.py`
- `tests/fixtures/config/workflow_state_*.yaml`

Later backend phases can rely on these guarantees without reopening workflow-state internals:

- workflow state is consumed only through `WorkflowStateStore` and startup wiring; non-persistence modules do not import SQLite
- relative workflow-state paths resolve from `backend/` and default to `backend/data/workflow_state.db`
- `load()` returns the canonical empty state on misses, `save()` enforces JSON-safe size and sensitive-field guardrails, and `reset()` clears short-term workflow state only
- workflow-state health exposes safe provider, schema, journal, and synchronous readiness details without leaking paths, session IDs, or state payloads
- shared SQLite conventions now match the trace store: config-driven parent-directory creation, schema-version bootstrap, configured pragmas, and safe health output

The following workflow-state concerns remain intentionally deferred:

- cleanup and retention policies for session-state rows and reset history
- compare-and-set or stronger optimistic-concurrency behavior beyond the current version and conflict seam
- stricter conversation-history compaction or summarization policy
- API and session-service decisions about when to load or save state and how much history to persist

The next persistence-specific document is `../docs/backend-sqlite-trace-store-architecture.md`. The next direct consumers of this boundary are `../docs/backend-api-architecture.md` and the later session-service architecture.

Focused workflow-state validation from `backend/`:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\unit\persistence tests\integration\test_workflow_state_store_sqlite_smoke.py tests\integration\test_workflow_state_store_concurrency.py tests\integration\test_startup_persistence.py
.\.venv\Scripts\python.exe -m ruff check app\persistence app\config tests\unit\persistence tests\integration\test_workflow_state_store_sqlite_smoke.py tests\integration\test_workflow_state_store_concurrency.py tests\integration\test_startup_persistence.py
.\.venv\Scripts\python.exe -m mypy app
```

## Trace-Store Freeze

The following trace-store surfaces are now the stable handoff boundary for later backend phases:

- `app/contracts/trace.py`
- `app/persistence/trace_store.py`
- `app/persistence/sqlite_trace_store.py`
- `app/persistence/sqlite_trace_schema.py`
- `app/persistence/sqlite_trace_queries.py`
- `tests/unit/persistence/test_fake_trace_store.py`
- `tests/unit/persistence/test_sqlite_trace_schema.py`
- `tests/unit/persistence/test_sqlite_trace_query_builder.py`
- `tests/unit/persistence/test_sqlite_trace_redaction.py`
- `tests/unit/persistence/test_sqlite_trace_serialization.py`
- `tests/unit/persistence/test_sqlite_trace_health.py`
- `tests/integration/test_trace_store_sqlite_smoke.py`
- `tests/integration/test_sqlite_trace_store_recording.py`
- `tests/integration/test_sqlite_trace_store_batch.py`
- `tests/integration/test_sqlite_trace_store_read_trace.py`
- `tests/integration/test_sqlite_trace_store_search.py`
- `tests/integration/test_sqlite_trace_store_retention.py`
- `tests/integration/test_sqlite_trace_store_concurrency.py`
- `tests/integration/test_startup_persistence.py`
- `tests/fixtures/config/trace_*.yaml`

Later backend phases can rely on these guarantees without reopening trace-store internals:

- trace storage is consumed only through `TraceStore`, `TraceRecorder`, and startup wiring; non-persistence modules do not import SQLite
- relative trace-store paths resolve from `backend/` and default to `backend/data/trace.db`
- validated trace configuration keys under `persistence.trace.sqlite` cover `path`, `create_parent_dirs`, `initialize_schema`, `journal_mode`, `synchronous`, `busy_timeout_ms`, `foreign_keys`, `max_event_payload_bytes`, `max_error_detail_bytes`, `max_events_per_trace_read`, `max_search_results`, raw-versus-hashed session and user ID policy, capture toggles, and retention settings
- `record_event()`, `record_events()`, `read_trace()`, `search_traces()`, `health()`, and retention cleanup are available behind the contract with bounded, redacted behavior
- trace search returns summaries only, trace reads preserve per-trace `sequence_no` ordering, and retention is disabled by default unless `retention.enabled` is set
- shared SQLite conventions match workflow-state: config-driven parent-directory creation, schema-version bootstrap, configured pragmas, safe health output, and concurrent local writes validated under WAL plus busy-timeout settings

The following trace-store concerns remain intentionally deferred:

- protected or role-gated trace debug routes
- session or user trace delete/export policy
- prompt or completion capture outside explicit local-debug policy decisions
- outbox, retry, or stronger write-reliability patterns beyond local SQLite guarantees
- cross-service trace correlation beyond the single backend process

The next direct consumers of this boundary are `../docs/backend-api-architecture.md`, the later session-service architecture, and the later orchestration architecture. Those phases decide when trace reads are exposed and which runtime modules emit which event families.

Focused trace-store validation from `backend/`:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\unit\persistence tests\unit\observability\test_trace_recorder.py tests\integration\test_trace_store_sqlite_smoke.py tests\integration\test_sqlite_trace_store_recording.py tests\integration\test_sqlite_trace_store_batch.py tests\integration\test_sqlite_trace_store_read_trace.py tests\integration\test_sqlite_trace_store_search.py tests\integration\test_sqlite_trace_store_retention.py tests\integration\test_sqlite_trace_store_concurrency.py tests\integration\test_startup_persistence.py
.\.venv\Scripts\python.exe -m ruff check app tests
.\.venv\Scripts\python.exe -m mypy app
```

## Setup

Use the existing virtual environment in `.venv/`.

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

## Local Configuration

Copy `.env.example` to `.env` before local development.

The canonical runtime config files are:

- `backend/config/app.yaml` for the checked-in base config
- `backend/config/app.local.yaml` for the optional developer-local override

The default startup path loads `APP_CONFIG_PATH=config/app.yaml` and then applies `APP_CONFIG_OVERRIDE_PATH=config/app.local.yaml` when that override file exists. Relative paths such as `APP_CONFIG_PATH`, `APP_CONFIG_OVERRIDE_PATH`, and `APP_DATA_DIR` are always resolved from `backend/`, not from the caller's current working directory.

The expected process-level settings for this phase are:

- `APP_ENV`
- `APP_CONFIG_PATH`
- `APP_CONFIG_OVERRIDE_PATH`
- `APP_DATA_DIR`
- `MEMORY_STORE_DB_PATH`
- `BACKEND_HOST`
- `BACKEND_PORT`
- `LOG_LEVEL`
- `LOG_JSON`

Local persistence defaults now resolve to:

- `backend/data/workflow_state.db` for workflow state
- `backend/data/trace.db` for operational traces
- `backend/data/memory` for the optional `memory_store` database path when `MEMORY_STORE_DB_PATH` is not overridden

Focused persistence config fixtures live under `backend/tests/fixtures/config/`:

- `persistence_sqlite_local.yaml`
- `persistence_memory_optional.yaml`
- `persistence_required_store_failure.yaml`
- `persistence_invalid_provider.yaml`
- `persistence_fake.yaml`

Provider and integration variables such as `OPENAI_API_KEY`, `GOOGLE_API_KEY`, `MCP_MAIN_URL`, `MEMORY_STORE_CONFIG`, `SQLITE_WORKFLOW_STATE_URL`, and `SQLITE_TRACE_URL` remain configuration inputs. The backend now uses the `memory_store` package only behind `app/persistence/memory_store_adapter.py`.

## Validation

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy app
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Focused persistence validation from `backend/`:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\unit\persistence\test_memory_scope.py tests\unit\persistence\test_memory_store_adapter_health.py tests\unit\test_health.py tests\integration\test_startup_persistence.py
```
