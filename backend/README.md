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

The backend foundation, core contracts, configuration, and observability slices are complete and frozen for later backend phases:

- deterministic backend-root-relative settings and config path resolution
- validated YAML loading, override merging, `${env:...}` interpolation, schema validation, and secret redaction
- import-safe application startup through `app.main`
- config-backed `/health` and `/capabilities` routes
- validated trace ID propagation, async-safe trace context, and request/response correlation headers
- config-driven structured or readable logging plus trace-safe error diagnostics
- shared redaction across config summaries, logs, traces, health payloads, and error metadata
- `TraceRecorder`, SQLite-backed trace persistence behind `app/persistence/`, and reusable health/metrics services
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

- trace query APIs
- trace retention, archival, and compression
- per-token streaming trace events
- centralized log shipping
- OpenTelemetry or other distributed tracing integration
- provider-specific telemetry enrichments

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
- `BACKEND_HOST`
- `BACKEND_PORT`
- `LOG_LEVEL`
- `LOG_JSON`

Provider and integration variables such as `OPENAI_API_KEY`, `GOOGLE_API_KEY`, `MCP_MAIN_URL`, `MEMORY_STORE_CONFIG`, `SQLITE_WORKFLOW_STATE_URL`, and `SQLITE_TRACE_URL` remain configuration inputs only. They are not exercised by real gateway implementations in this phase.

## Validation

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy app
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```
