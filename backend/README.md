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
- persistence bundle wiring for workflow-state and trace providers, with long-term memory wired separately through `app/memory/`
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

## Chat Continuity

Same-session chat continuity now relies on workflow-state conversation messages under `backend/app/session/` and `backend/app/orchestration/`, not on durable `memory_store` reads.

The current default behavior is:

- short sessions inject bounded prior raw `user` and `assistant` turns directly into the prompt
- longer sessions add a deterministic `session_summary` rollup stored in workflow-state metadata when the raw history window crosses the configured threshold or must be truncated
- continuity remains available even if the durable memory gateway is unavailable
- the built-in `support_agent` remains a direct-answer agent and does not perform durable memory retrieval by default

The canonical continuity settings live under `orchestration.defaults.conversation_context` in `backend/config/app.yaml`, and the public capabilities route exposes whether continuity is enabled plus the active continuity mode without exposing conversation text.

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
- long-term memory access is isolated behind `app/memory/`, with `app/persistence/memory_store_adapter.py` retained only as a compatibility shim
- only persistence adapters import SQLite, and only the dedicated memory adapter imports `memory_store`
- `/health` reports safe required-versus-optional readiness for workflow-state and trace under persistence, with memory reported separately through the dedicated memory gateway
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

## API Walking Skeleton Freeze

The following API and session surfaces are now the stable handoff boundary for later backend phases:

- `app/api/routes_chat.py`
- `app/api/routes_sessions.py`
- `app/api/routes_debug_control.py`
- `app/api/routes_health.py`
- `app/api/routes_capabilities.py`
- `app/api/routes_debug_traces.py`
- `app/api/schemas.py`
- `app/api/sse.py`
- `app/api/dependencies.py`
- `app/api/request_context.py`
- `app/api/errors.py`
- `app/observability/debug_trace_service.py`
- `app/session/service.py`
- `app/session/models.py`
- `app/session/errors.py`
- `tests/unit/api/`
- `tests/integration/test_api_chat_fake_session.py`
- `tests/integration/test_api_streaming_sse.py`
- `tests/integration/test_api_health_with_real_stores.py`
- `tests/integration/test_api_debug_traces_disabled.py`
- `tests/integration/test_api_debug_traces_enabled.py`
- `tests/integration/test_api_sessions_admin.py`
- `tests/integration/test_api_walking_skeleton.py`
- `tests/integration/test_api_reset_boundary.py`
- `tests/integration/test_restart_localhost_guard.py`
- `tests/integration/test_restart_request_flow.py`
- `tests/integration/test_api_trace_correlation.py`
- `tests/integration/test_api_cors.py`
- `tests/fixtures/config/api_*.yaml`

Later backend phases can rely on these guarantees without reopening the API walking skeleton:

- `POST /chat`, `POST /chat/stream`, `POST /sessions/{session_id}/reset`, `GET /sessions/{session_id}/history`, `GET /sessions`, `DELETE /sessions/{session_id}`, `GET /health`, and `GET /capabilities` are the stable V1 backend-local route surface; `POST /restart` is exposed only when both `api.debug_routes.enabled` and `api.debug_routes.restart_enabled` are true
- debug trace routes remain disabled by default and are only exposed when `api.debug_routes.enabled` is true; V1 keeps the localhost guard in place
- session-admin list/delete behavior remains configuration-driven through `session.management.*`, with stable 404 envelopes when those operations are disabled
- API routes stay thin over `SessionService`, health aggregation, capability discovery, and the debug-trace facade; route modules do not import SQLite, `memory_store`, provider SDKs, or MCP client implementations
- the API phase introduced a walking-skeleton `SessionService`; the current startup path now wires `DefaultSessionService` while preserving the same thin-route boundary and SQLite workflow-state/trace guarantees
- streaming persists state only on completion or cancellation boundaries; there are no per-token workflow-state writes
- accepted restart requests write `backend/runtime/restart-request.json` and rely on an external supervisor or wrapper for the follow-on process restart
- fake session behavior remains available for thin-route tests through explicit test-time container overrides rather than production startup wiring
- API fixture coverage now includes `api_basic.yaml`, `api_streaming_enabled.yaml`, `api_debug_traces_disabled.yaml`, `api_debug_traces_enabled.yaml`, `api_small_request_limits.yaml`, `api_cors_localhost.yaml`, and `api_with_real_sqlite_stores.yaml`

The following API/session concerns remain intentionally deferred:

- real orchestration runtime behavior
- real memory gateway integration
- real tool and MCP integration
- auth and authorization hardening beyond the localhost debug-route guard

The next direct backend document is `../docs/backend-session-service-architecture.md`.

## Session Service Freeze

The following session-service surfaces are now the stable handoff boundary for later backend phases:

- `app/session/service.py`
- `app/session/lifecycle.py`
- `app/session/streaming.py`
- `app/session/concurrency.py`
- `app/session/history.py`
- `app/session/mapping.py`
- `app/session/identifiers.py`
- `app/session/models.py`
- `app/session/errors.py`
- `app/orchestration/core.py`
- `app/config/bootstrap.py`
- `app/foundation/container.py`
- `app/testing/fakes/fake_session_service.py`
- `app/testing/fakes/fake_orchestration_runtime.py`
- `app/testing/fakes/fake_trace_recorder.py`
- `app/testing/fakes/fake_clock.py`
- `tests/unit/session/`
- `tests/integration/session/`
- `tests/fixtures/config/session_*.yaml`

Later backend phases can rely on these guarantees without reopening the session-service boundary:

- lifespan startup now wires `DefaultSessionService`; import-time app creation remains free of store I/O and external-service startup
- session lifecycle behavior is driven by typed `session.*` settings plus the narrow `app/orchestration/core.py` runtime protocol
- `SessionService` owns create/resume/reset/history behavior, workflow-state load/save/finalization, and safe lifecycle tracing while API routes remain thin
- the current runtime now uses the LLM-backed `DirectAgentOrchestrationRuntime`, so later memory, tooling, and richer strategy work can deepen internals without reopening the API/session contract
- dedicated session unit and integration suites now own primary lifecycle verification, while API suites keep thin-route and wire-level coverage

The following session-service concerns remain intentionally deferred:

- real memory read/write integration
- real tool and MCP client execution
- richer orchestration strategies and agent routing beyond the echo runtime
- policy hardening and authz decisions beyond the current route-level guards
- distributed locking or multi-writer coordination beyond optimistic versioning

The next direct backend document is `../docs/backend-llm-gateway-architecture.md`.

## LLM Gateway Freeze

The following LLM gateway surfaces are now the stable handoff boundary for later backend phases:

- `app/contracts/llm.py`
- `app/llm/`
- `app/policy/service.py`
- `app/orchestration/core.py`
- `app/foundation/health.py`
- `app/foundation/capabilities.py`
- `app/api/errors.py`
- `tests/unit/llm/`
- `tests/integration/llm/`
- `tests/fixtures/config/llm_*.yaml`

Later backend phases can rely on these guarantees without reopening provider access or profile resolution internals:

- `LLMGateway` is the only provider-facing backend boundary for completions, streaming, health, and profile listing
- provider selection, timeouts, retries, fallbacks, and logical profile routing remain configuration-driven under `backend/config/` and `backend/tests/fixtures/config/`
- orchestration and session code continue to consume logical profiles only; they do not import provider SDKs or raw HTTP clients
- `/health`, `/capabilities`, startup diagnostics, and API error responses now expose only safe LLM metadata such as logical profile names, provider types, readiness state, and normalized failure codes
- the OpenAI-compatible HTTP path relies on the runtime `httpx` dependency declared in `backend/pyproject.toml`
- dedicated backend-local validation now lives under `tests/unit/llm/` and `tests/integration/llm/`, with the local OpenAI-compatible smoke test isolated behind an explicit opt-in environment flag

The following LLM concerns remain intentionally deferred:

- tool execution and MCP client behavior behind the later `ToolGateway`
- richer multi-strategy orchestration, routing, and planner behavior beyond the current direct agent runtime
- provider-specific hardening beyond the current OpenAI-compatible runtime path and non-breaking adapter scaffolds
- deeper policy enforcement, authz, and cost controls beyond the current config-driven profile checks

Focused LLM validation from `backend/`:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\unit\llm tests\integration\llm tests\integration\test_startup_llm.py tests\integration\test_api_walking_skeleton.py
.\.venv\Scripts\python.exe -m ruff check app\llm app\policy app\foundation app\api\errors.py tests\unit\llm tests\integration\llm
.\.venv\Scripts\python.exe -m mypy app
```

The next direct backend document is `../docs/backend-tooling-mcp-client-architecture.md`.

## Memory Gateway Freeze

The following memory gateway surfaces are now the stable handoff boundary for later backend phases:

- `app/contracts/memory.py`
- `app/memory/`
- `app/persistence/memory_store_adapter.py`
- `app/config/bootstrap.py`
- `app/foundation/container.py`
- `app/foundation/health.py`
- `app/foundation/capabilities.py`
- `app/orchestration/core.py`
- `app/api/errors.py`
- `app/testing/fakes/fake_agent.py`
- `tests/unit/memory/`
- `tests/integration/memory/`
- `tests/integration/test_startup_memory.py`
- `tests/unit/test_app_factory.py`
- `tests/unit/test_health.py`
- `tests/unit/test_capabilities.py`
- `tests/unit/api/test_error_mapping.py`
- `tests/fixtures/config/memory_*.yaml`
- `tests/fixtures/config/memory_store_real_local.yaml`
- `tests/fixtures/memory/`

Later backend phases can rely on these guarantees without reopening the memory boundary:

- `MemoryGateway` is the only orchestration-facing backend boundary for long-term memory, chunk retrieval, lifecycle operations, privacy operations, health, and stats
- the concrete `memory_store` wrapper is only called from `app/memory/adapters/memory_store.py`; routes, session code, orchestration, and agents do not import `memory_store` directly
- startup now builds memory through `app/memory/factory.py`, and `PersistenceBundle` now owns workflow-state plus trace only
- `/health` and `/capabilities` expose only safe memory readiness metadata such as provider name, configured/enabled state, and search/ingest availability
- the direct runtime and the fake test agent now exercise memory only through `OrchestrationContext.memory`
- API error responses map normalized memory failures into stable `memory_*` codes instead of surfacing raw adapter failures
- canonical runtime memory configuration lives under the top-level `memory:` section in `backend/config/app.yaml`, while legacy `persistence.memory` values remain compatibility-only inputs
- deterministic memory fixtures and search goldens now live under `tests/fixtures/memory/`, and the local-only real-wrapper smoke path is isolated behind an explicit opt-in environment flag

The following memory concerns remain intentionally deferred:

- tool/MCP-driven retrieval augmentation behind the later `ToolGateway`
- richer multi-agent planning or routing behavior beyond the current direct runtime and fake test agent coverage
- production backup, restore, and operational lifecycle guidance for the underlying memory store
- broader agent-plugin adoption through `agent_framework`, which must continue consuming memory only through `OrchestrationContext.memory`

Focused memory validation from `backend/`:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\unit\memory tests\unit\test_app_factory.py tests\unit\test_health.py tests\unit\test_capabilities.py tests\unit\api\test_error_mapping.py tests\integration\test_startup_memory.py tests\integration\memory
.\.venv\Scripts\python.exe -m ruff check app\memory app\foundation app\orchestration app\api\errors.py tests\unit\memory tests\unit\test_app_factory.py tests\unit\test_health.py tests\unit\test_capabilities.py tests\unit\api\test_error_mapping.py tests\integration\test_startup_memory.py tests\integration\memory
.\.venv\Scripts\python.exe -m mypy app
```

Optional real-wrapper smoke validation stays local-only and should only be run when the developer explicitly opts in:

```powershell
$env:BB2_ENABLE_REAL_MEMORY_STORE_TESTS = "1"
.\.venv\Scripts\python.exe -m pytest tests\integration\memory\test_memory_store_real_local.py
```

The next direct backend document is `../docs/backend-tooling-mcp-client-architecture.md`.

Focused session validation from `backend/`:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\unit\session tests\integration\session tests\unit\test_app_factory.py
.\.venv\Scripts\python.exe -m ruff check app\session app\orchestration app\config\bootstrap.py app\foundation\container.py tests\unit\session tests\integration\session
.\.venv\Scripts\python.exe -m mypy app
```

## API Local Development

Use the existing virtual environment in `backend/.venv/`, run the server from `backend/`, and keep relative config paths rooted there:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

The default local API surface is:

- `POST /chat`
- `POST /chat/stream` when `features.streaming_enabled` and the API streaming fixture/override are enabled
- `POST /sessions/{session_id}/reset`
- `GET /sessions/{session_id}/history`
- `GET /artifacts/{artifact_id}` when `visualization.artifact_store.public_retrieval_enabled` is enabled; saved history reference artifacts use this route after reload or restart
- `GET /sessions` and `DELETE /sessions/{session_id}`; these routes return stable admin envelopes and become operational when `session.management.list_enabled` and `session.management.delete_enabled` are enabled
- `GET /health`
- `GET /capabilities`
- `POST /restart` only when both `api.debug_routes.enabled` and `api.debug_routes.restart_enabled` are true; accepted requests write `backend/runtime/restart-request.json` and expect an external supervisor or wrapper to start the process again
- `GET /debug/traces` and `GET /debug/traces/{trace_id}` only when explicitly enabled for local debugging

## Visualization History Replay

Visualization history replay is now a supported backend runtime capability for newly saved assistant turns.

- `GET /sessions/{session_id}/history` returns replayable chart descriptors on `message.artifacts` for sessions saved after the replay refactor.
- Sessions saved before replay persistence landed that only retained `artifact_count` are legacy sessions. They are not backfilled automatically and should remain on the existing regenerate-the-chart warning path in the frontend.
- Inline history storage is bounded by `visualization.history_replay.max_artifacts_per_message`, `visualization.history_replay.max_inline_artifact_bytes`, `visualization.history_replay.max_total_bytes_per_message`, and `persistence.workflow_state.sqlite.max_state_bytes`.
- Durable reference artifacts live in `backend/data/visualization_artifacts.db` by default, or `visualization.artifact_store.sqlite.path` when overridden.
- Durable artifact rows expire according to `visualization.artifact_store.ttl_seconds`; expired rows are purged during artifact-store initialization and later store operations.
- Session reset clears session-scoped durable visualization artifacts when a visualization artifact store is configured.

Focused visualization replay validation from `backend/`:

```powershell
.\.venv\Scripts\python.exe -m pytest --import-mode=importlib tests\integration\visualization\test_session_chart_pipeline.py tests\integration\session\test_session_with_sqlite_workflow_state_store.py
.\.venv\Scripts\python.exe -m ruff check tests\integration\visualization\test_session_chart_pipeline.py tests\integration\session\test_session_with_sqlite_workflow_state_store.py
```

Focused API validation from `backend/`:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\unit\api tests\integration\test_api_chat_fake_session.py tests\integration\test_api_streaming_sse.py tests\integration\test_api_health_with_real_stores.py tests\integration\test_api_debug_traces_disabled.py tests\integration\test_api_debug_traces_enabled.py tests\integration\test_api_sessions_admin.py tests\integration\test_api_walking_skeleton.py tests\integration\test_api_reset_boundary.py tests\integration\test_restart_localhost_guard.py tests\integration\test_restart_request_flow.py tests\integration\test_api_trace_correlation.py tests\integration\test_api_cors.py
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

For machine-local LLM endpoints, prefer `backend/config/app.local.yaml` or `LOCAL_LLM_BASE_URL` instead of changing `backend/config/app.yaml`. For example, a local override can point the OpenAI-compatible provider at `http://192.168.1.80:8081/v1` without changing the committed base config.

The opt-in local OpenAI-compatible smoke test is `tests/integration/llm/test_local_openai_compatible_smoke.py`. Run it with `RUN_LOCAL_LLM_SMOKE=1` and `LOCAL_LLM_BASE_URL=http://192.168.1.80:8081/v1` to verify the configured `/v1/chat/completions` path without editing committed config.

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

Provider and integration variables such as `OPENAI_API_KEY`, `GOOGLE_API_KEY`, `MCP_MAIN_URL`, `MEMORY_STORE_CONFIG`, `SQLITE_WORKFLOW_STATE_URL`, and `SQLITE_TRACE_URL` remain configuration inputs. The backend now uses the `memory_store` package only behind `app/memory/adapters/memory_store.py`, with `app/persistence/memory_store_adapter.py` preserved as a compatibility shim.

Memory-specific config and fixtures now live at:

- `backend/config/app.yaml` for the canonical `memory:` runtime configuration
- `backend/tests/fixtures/config/memory_disabled.yaml`
- `backend/tests/fixtures/config/memory_fake_basic.yaml`
- `backend/tests/fixtures/config/memory_store_basic.yaml`
- `backend/tests/fixtures/config/memory_store_markdown_chunking.yaml`
- `backend/tests/fixtures/config/memory_trace_capture_disabled.yaml`
- `backend/tests/fixtures/config/memory_trace_capture_enabled_local_only.yaml`
- `backend/tests/fixtures/config/memory_store_real_local.yaml`
- `backend/tests/fixtures/memory/golden_memories.jsonl`
- `backend/tests/fixtures/memory/golden_search_cases.yaml`

## Tooling and MCP Freeze

The following tooling surfaces are now the stable handoff boundary for later backend phases:

- `app/contracts/tools.py`
- `app/tools/`
- `app/tools/mcp/`
- `app/foundation/health.py`
- `app/foundation/capabilities.py`
- `app/api/errors.py`
- `backend/config/app.yaml`
- `tests/unit/tools/`
- `tests/integration/tools/test_mcp_local_optional.py`
- `tests/fixtures/config/tooling_*.yaml`

Later backend phases can rely on these guarantees without reopening the tooling boundary:

- orchestration reaches external tools only through `ToolGateway`; API and session layers remain thin and do not speak MCP
- MCP protocol, transport, auth, retries, and discovery stay isolated under `app/tools/mcp/`
- canonical runtime config keys live under top-level `tooling.*` for gateway behavior and `mcp.main.*` for the single configured MCP endpoint
- `/health` and `/capabilities` expose only safe tooling summaries such as configured versus enabled state, discovery status, transport type, and bounded tool counts
- API error envelopes map normalized tool and MCP failures to backend-owned status codes and messages without leaking raw downstream payloads or credentials

Focused tooling fixtures and tests now include:

- `backend/tests/fixtures/config/tooling_disabled.yaml`
- `backend/tests/fixtures/config/tooling_fake_basic.yaml`
- `backend/tests/fixtures/config/tooling_fake_streaming.yaml`
- `backend/tests/fixtures/config/tooling_invalid_auth.yaml`
- `backend/tests/fixtures/config/tooling_invalid_allowlist.yaml`
- `backend/tests/fixtures/config/tooling_invalid_secret_like_arguments.yaml`
- `backend/tests/fixtures/config/tooling_approval_required.yaml`
- `backend/tests/fixtures/config/tooling_local_mcp_optional.yaml`
- `backend/tests/unit/tools/`
- `backend/tests/integration/tools/test_mcp_local_optional.py`

The following tooling concerns remain intentionally deferred:

- multi-MCP routing and per-tool endpoint selection
- a full human approval workflow beyond the default approval-required denial path
- richer side-effect policy, tenant-aware tool exposure, and user-specific capability filtering
- long-running external tool jobs and distributed tool orchestration

The next direct backend document is `../docs/backend-orchestration-architecture.md`, followed by `../docs/backend-workflow-strategies-architecture.md` and the later agent documents.

## Orchestration Freeze

The following orchestration surfaces are now the stable handoff boundary for later backend phases:

- `app/orchestration/`
- `app/config/bootstrap.py`
- `app/foundation/health.py`
- `app/foundation/capabilities.py`
- `app/testing/fakes/fake_orchestration_runtime.py`
- `app/testing/fakes/fake_strategy.py`
- `backend/config/app.yaml`
- `tests/unit/orchestration/`
- `tests/integration/orchestration/`
- `tests/fixtures/config/orchestration_*.yaml`

Later backend phases can rely on these guarantees without reopening the orchestration boundary:

- `SessionService` now builds `OrchestrationRequest` and `OrchestrationRuntimeContext`, calls `run_turn(...)` / `stream_turn(...)`, and persists the returned `WorkflowStateDelta` itself
- the stable runtime surface is `DefaultOrchestrationRuntime` plus the compatibility exports in `app/orchestration/core.py`; later phases should deepen internals behind that boundary instead of reintroducing session-to-gateway shortcuts
- built-in V1 strategies now live under `app/orchestration/strategies/` for `echo`, `direct_agent`, `retrieval_augmented`, `tool_assisted`, and `router`
- orchestration reaches LLM, memory, and tools only through `LLMGateway`, `MemoryGateway`, and `ToolGateway`, while health and capabilities flow outward only through the orchestration-owned summaries consumed by foundation
- safe assistant-message metadata, step summaries, and stream events may be persisted or surfaced, but raw provider payloads, raw tool payloads, raw memory records, stack traces, and hidden reasoning remain excluded by default
- deterministic fakes and fixture-backed tests now cover strategy resolution, runtime behavior, state-delta application, memory/tool integration, limits, cancellation, health/capabilities, and the session-runtime handoff
- opt-in local backend checks remain isolated behind explicit fixtures and enablement in `tests/fixtures/config/llm_openai_compatible_local.yaml`, `tests/fixtures/config/memory_store_real_local.yaml`, and `tests/fixtures/config/tooling_local_mcp_optional.yaml`

Focused orchestration fixtures and tests now include:

- `backend/tests/fixtures/config/orchestration_basic_direct.yaml`
- `backend/tests/fixtures/config/orchestration_streaming_direct.yaml`
- `backend/tests/fixtures/config/orchestration_retrieval_augmented.yaml`
- `backend/tests/fixtures/config/orchestration_tool_assisted.yaml`
- `backend/tests/fixtures/config/orchestration_router.yaml`
- `backend/tests/fixtures/config/orchestration_unknown_usecase.yaml`
- `backend/tests/fixtures/config/orchestration_disabled_strategy.yaml`
- `backend/tests/fixtures/config/orchestration_policy_denied.yaml`
- `backend/tests/fixtures/config/orchestration_limits.yaml`
- `backend/tests/fixtures/config/orchestration_debug_unsafe_invalid.yaml`
- `backend/tests/unit/orchestration/test_orchestration_fixture_examples.py`
- `backend/tests/unit/orchestration/`
- `backend/tests/integration/orchestration/`

The following orchestration concerns remain intentionally deferred:

- workflow-specific strategy deepening beyond the current V1 built-ins
- agent-plugin catalogs and broader `agent_framework` adoption behind the later agent architecture phase
- approval workflows, planner/resume semantics, and long-running background orchestration
- deeper policy hardening beyond the current config-driven orchestration, tool, and LLM guards

Focused orchestration validation from `backend/`:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\unit\orchestration tests\integration\orchestration tests\unit\session\test_session_handle_chat.py tests\unit\session\test_session_stream_chat.py tests\integration\session\test_session_with_sqlite_workflow_state_store.py tests\integration\session\test_session_streaming_finalization.py tests\integration\test_api_walking_skeleton.py
.\.venv\Scripts\python.exe -m ruff check app\orchestration app\session app\testing\fakes tests\unit\orchestration tests\integration\orchestration tests\unit\session tests\integration\session tests\integration\test_api_walking_skeleton.py
.\.venv\Scripts\python.exe -m mypy app
```

The next direct backend documents are `../docs/backend-workflow-strategies-architecture.md`, followed by `../docs/backend-agents-architecture.md`.

## Workflow-Strategies Freeze

The following workflow-strategy surfaces are now the stable handoff boundary for later backend phases:

- `app/orchestration/strategies/`
- `app/orchestration/strategy_factory.py`
- `app/orchestration/strategy_registry.py`
- `app/orchestration/strategy_steps.py`
- `app/orchestration/context_budget.py`
- `app/orchestration/prompt_inputs.py`
- `app/orchestration/tool_intents.py`
- `app/orchestration/memory_intents.py`
- `app/orchestration/fallback.py`
- `app/orchestration/stream_mapping.py`
- `app/orchestration/trace_helpers.py`
- `app/orchestration/health.py`
- `app/orchestration/capabilities.py`
- `backend/config/app.yaml`
- `tests/fixtures/config/orchestration_*.yaml`
- `tests/unit/orchestration/`
- `tests/integration/orchestration/`

Later backend phases can rely on these guarantees without reopening the workflow-strategy layer:

- the built-in catalog now includes `direct_agent`, `retrieval_augmented`, `tool_assisted`, `router`, `fallback_answer`, `memory_update`, and the disabled-by-default `bounded_planner`
- startup, `/health`, and `/capabilities` expose only safe strategy readiness, type labels, streaming support, and use-case feature flags derived from the registry-backed orchestration summaries
- strategies remain gateway-only and import-boundary checked against API, session, SQLite, `memory_store`, MCP-client, and provider-SDK dependencies
- stream, health, capability, and trace metadata continue to exclude raw prompts, raw provider chunks, raw tool payloads, raw memory records, raw workflow-state data, credentials, hidden reasoning, and stack traces by default
- canonical workflow-strategy config stays rooted under `backend/config/`, while fixture-backed strategy validation stays under `backend/tests/fixtures/config/` and `backend/tests/unit/orchestration/`

The following workflow-strategy concerns remain intentionally deferred:

- concrete agent-plugin internals and broader `agent_framework` composition
- stronger policy hardening beyond the current strategy/tool/memory denial and approval seams
- planner resume semantics, durable execution checkpoints, and long-running background workflows
- richer evaluation datasets and optimization loops for future agent phases

Focused workflow-strategy validation from `backend/`:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\unit\orchestration tests\integration\orchestration tests\integration\test_startup_orchestration.py tests\unit\test_capabilities.py tests\unit\test_health.py
.\.venv\Scripts\python.exe -m ruff check app\orchestration app\foundation app\config\bootstrap.py tests\unit\orchestration tests\integration\orchestration tests\integration\test_startup_orchestration.py tests\unit\test_capabilities.py tests\unit\test_health.py
.\.venv\Scripts\python.exe -m mypy app
```

The next direct backend document is `../docs/backend-agents-architecture.md`.

## Agents Freeze

The following agent-layer surfaces are now the stable handoff boundary for later backend phases:

- `app/agents/`
- `app/contracts/agents.py`
- `app/config/bootstrap.py`
- `app/foundation/health.py`
- `app/foundation/capabilities.py`
- `app/orchestration/health.py`
- `app/orchestration/capabilities.py`
- `app/api/schemas.py`
- `tests/unit/agents/`
- `tests/integration/agents/`
- `tests/fixtures/config/agents_*.yaml`

Later backend phases can rely on these guarantees without reopening the agent boundary:

- configured agents are built and registered through the dedicated `app/agents/` package, while `app/contracts/agents.py` and `app/orchestration/registry.py` remain the compatibility seams for upstream callers
- startup, `/health`, and `/capabilities` now expose only safe agent metadata: names, type labels, prompt-profile names, configured LLM profiles, memory/tool requirements, streaming support, and frontend-safe capability labels
- import-time package surfaces for `app/agents/`, `app/agents/plugins/`, and `app/orchestration/` are lazy, which prevents circular imports while keeping the public package APIs stable
- dedicated boundary tests now cover forbidden imports, trace redaction, policy denial, and cancellation alongside the existing agent unit and integration suites
- deterministic fakes remain sufficient for agent-layer run/stream/health/policy coverage without reaching real provider SDKs, SQLite clients, MCP clients, or `memory_store`

The following agent-layer concerns remain intentionally deferred:

- deeper policy hardening beyond the current safe-denial, capability, and gateway checks
- approval workflows and richer human-in-the-loop review semantics
- broader `agent_framework` integration beyond the current bounded plugin/runtime seam
- prompt-injection hardening, evaluation datasets, and optimization loops beyond the current safe redaction and bounded prompt model

Focused agent validation from `backend/`:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\unit\agents tests\integration\agents tests\unit\test_health.py tests\unit\test_capabilities.py tests\unit\test_app_factory.py
.\.venv\Scripts\python.exe -m ruff check app\agents app\orchestration app\foundation app\api\schemas.py app\config\bootstrap.py tests\unit\agents tests\integration\agents tests\unit\test_health.py tests\unit\test_capabilities.py tests\unit\test_app_factory.py
.\.venv\Scripts\python.exe -m mypy app
```

## Policy Freeze

The following policy-layer surfaces are now the stable handoff boundary for later backend phases:

- `app/policy/`
- `app/contracts/policy.py`
- `app/config/bootstrap.py`
- `app/foundation/health.py`
- `app/foundation/capabilities.py`
- `tests/unit/policy/`
- `tests/integration/policy/`
- `tests/fixtures/config/policy_*.yaml`

Later backend phases can rely on these guarantees without reopening the policy boundary:

- deny-by-default policy decisions remain centralized behind `DefaultPolicyService` and the typed evaluator registry under `app/policy/`
- live policy evaluation now records only safe audit summaries, uses a bounded per-turn decision cache, and emits low-cardinality policy metrics
- `/health` exposes a frontend-safe policy status summary with mode, profile count, rule count, and bounded cache/audit counters only
- `/capabilities` continues to hide internal policy details unless an explicit policy profile allows them
- dedicated boundary tests now cover forbidden imports, cache safety, audit safety, startup wiring, and the existing exposure-policy regressions

The following policy-layer concerns remain intentionally deferred:

- human approval workflow execution beyond `approval_required` decisions
- external policy engines, RBAC/ABAC providers, or organization-specific policy backends
- richer tenant/user-aware policy administration and authoring workflows
- deployment-time hardening and operations readiness beyond the backend-owned runtime policy surface

Focused policy validation from `backend/`:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\unit\policy tests\integration\policy tests\unit\test_health.py tests\unit\test_capabilities.py tests\unit\test_app_factory.py
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy app
```

The next direct backend document is `../docs/backend-deployment-architecture.md`.

## Task Execution Chat Rollout

The task-first `task_execution_chat` flow is now validated for staged activation, but the current rollout decision is to keep multiple parallel use cases instead of replacing `default_chat` or `support_web_chat` immediately.

Activation flags:

- disabled baseline: keep `orchestration.usecases.task_execution_chat.enabled: false`
- staged activation: set `orchestration.usecases.task_execution_chat.enabled: true` and keep `app.active_usecase` plus `session.defaults.default_usecase` on the current default; callers opt in by sending `usecase: task_execution_chat`
- default activation: set `orchestration.usecases.task_execution_chat.enabled: true`, `app.active_usecase: task_execution_chat`, and `session.defaults.default_usecase: task_execution_chat`
- rollout fixtures for these three states live under `tests/fixtures/config/task_execution_chat_disabled.yaml`, `tests/fixtures/config/task_execution_chat_staged.yaml`, and `tests/fixtures/config/task_execution_chat_enabled.yaml`

Health expectations:

- `/health` should remain green on the existing backend dependencies; `task_execution_chat` does not add a new required external service boundary
- config-backed health summaries should only show `task_execution_chat` as the active default when `app.active_usecase` has been switched
- successful task-first responses should expose additive metadata such as `response_mode`, `needs_user_input`, `pending_task_count`, and `generated_artifact_count` without requiring API or frontend contract changes

Failure modes:

- missing required inputs should stop with a clarification response instead of a fallback answer
- enabling `bounded_planner` while canonical `memory.enabled` or `tooling.enabled` are still off will fail config validation
- custom configs that add the use case without matching LLM, agent, strategy, tool, or policy allowlists can still fail at startup or at request time
- fallback answers should now be rare for multi-step chart requests; treat frequent fallback on `task_execution_chat` as a rollout regression

Focused task-execution rollout validation from `backend/`:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\unit\config\test_loader_valid_config.py tests\integration\orchestration\test_bounded_planner_runtime.py tests\integration\visualization\test_session_chart_pipeline.py
```

The rollout decision record is `../docs/decisions/task-execution-chat-rollout-decision.md`.

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
