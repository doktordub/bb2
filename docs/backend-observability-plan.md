# Backend Observability Implementation Plan

**Document:** `backend-observability-plan.md`  
**Version:** 1.0  
**Source alignment:** `backend-observability-architecture.md`, `backend-configuration-plan.md`, and the current backend foundation/configuration implementation  
**Repository rule:** all backend application code lives under `backend/`

---

## 1. Purpose

This plan converts the backend observability architecture into an implementation sequence that can be delivered in small, low-risk phases.

The plan is intentionally strict about repository boundaries:

- Backend application code belongs in `backend/`.
- Backend source modules belong in `backend/app/`.
- Backend tests belong in `backend/tests/`.
- Backend configuration files belong in `backend/config/`.
- Documentation updates belong in `docs/`.
- No backend runtime, persistence, or observability code should be placed in the repository root, `frontend/`, or `mcp/`.

For clarity, this document uses filesystem paths such as `backend/app/observability/logging.py`. Python imports may still use the `app.*` package path because `backend/` is the Python project root.

---

## 2. Review Outcomes

The observability architecture document is implementation-ready and lines up with the completed backend foundation, core-contracts, and configuration phases. It is strong on boundaries, sequencing, and safety requirements.

The review also confirms that this phase is not greenfield work. The repository already contains an observability baseline that must be extended rather than replaced:

- `backend/app/observability/logging.py` already configures a foundation logger.
- `backend/app/observability/middleware.py` already attaches a request trace ID and returns it in the response headers.
- `backend/app/observability/models.py` already defines the API error envelope and trace header constant.
- `backend/app/api/errors.py` already maps request errors into stable JSON responses.
- `backend/app/foundation/health.py` already builds a shallow, secret-safe health response.
- `backend/app/config/redaction.py` and `backend/app/config/view.py` already provide redacted configuration summaries.
- `backend/app/contracts/trace.py` and `backend/app/testing/fakes/fake_trace.py` already provide the core trace contract and an in-memory fake store.

The main implementation concerns to address explicitly during execution are:

1. **Configuration authority is currently split.**  
   Foundation logging still depends on `Settings`, while the observability architecture expects runtime behavior to come from validated YAML through `backend/app/config/view.py`. The implementation should keep `Settings` only as the bootstrap fallback and then switch to configuration-driven observability behavior after config load.

2. **Health status vocabulary must be normalized.**  
   `backend/app/contracts/health.py` and `backend/app/foundation/health.py` currently use different status sets. This must be resolved before adding the broader health aggregator so routes, contracts, and tests all speak one consistent status language.

3. **Event naming already has one partial home.**  
   The minimum event constants already exist in `backend/app/contracts/trace.py`. If this phase adds `backend/app/observability/events.py` as the runtime catalog, the plan should preserve compatibility instead of creating two drifting sources of truth.

4. **Redaction should be shared, not duplicated.**  
   The repository already has configuration redaction logic. Runtime observability redaction should become the common implementation or the common rules source, so logs, traces, health responses, config summaries, and error metadata cannot diverge.

5. **SQLite trace persistence must stay behind a backend-local boundary.**  
   All SQL and schema knowledge must live under `backend/app/persistence/`. No route, agent, gateway, or orchestration module should talk to SQLite directly.

6. **HTTP error mapping should stay at the API boundary.**  
   `backend/app/api/errors.py` should remain the HTTP response mapping layer. If this phase adds observability-side error helpers, they should support that API layer rather than replace it.

7. **Existing foundation routes remain in place.**  
   `GET /health` and `GET /capabilities` already exist. This phase should deepen observability internals without reopening unrelated route design.

---

## 3. Non-Negotiable Boundary Rules

- Treat `backend/` as the Python project root for all observability work.
- Create runtime observability modules only under `backend/app/observability/`.
- Create concrete trace persistence modules only under `backend/app/persistence/`.
- Keep shared contracts in `backend/app/contracts/`.
- Keep backend tests under `backend/tests/`.
- Keep documentation-only artifacts under `docs/`.
- Do not place backend observability or persistence code in the repository root, `frontend/`, or `mcp/`.
- Do not let any module outside `backend/app/persistence/` execute trace SQL directly.
- Do not log or persist secrets, raw authorization headers, raw prompts, raw completions, full memory contents, or full tool responses by default.
- Keep `backend/app/main.py:app = create_app()` import-safe; all I/O, schema bootstrap, and runtime wiring should remain inside startup/lifespan code.

---

## 4. Phase Overview

| Phase | Name | Primary Outcome |
|---|---|---|
| 0 | [DONE] Foundation Observability Baseline | The repository already has request trace headers, startup logging baseline, stable API error envelopes, shallow health responses, and trace contracts under `backend/`. |
| 1 | [DONE] Config and Contract Alignment | Observability configuration, health status semantics, and event constant ownership are aligned with the architecture and current backend code. |
| 2 | [DONE] Trace Identity and Context | Trace ID generation, validation, aliases, and async-safe trace context propagation exist as shared helpers. |
| 3 | [DONE] Shared Redaction and Structured Logging | One redaction model and configuration-driven structured logging behavior are in place across logs, health, config summaries, and error metadata. |
| 4 | [DONE] Trace Recorder and SQLite Trace Store | Runtime code can record trace events through the existing trace contract, and append-only SQLite persistence works behind `backend/app/persistence/`. |
| 5 | [DONE] Health Aggregation and Metrics Stub | The backend has a reusable health aggregator and a lightweight metrics interface that later modules can call without choosing a metrics backend. |
| 6 | [DONE] Startup and Request Integration | Startup, middleware, and error paths emit consistent observability signals while preserving import safety and backend-local boundaries. |
| 7 | [DONE] Tests, Freeze, and Handoff | The observability slice is validated with backend-local quality checks and documented as ready for the next backend phases. |

---

## 5. Detailed Implementation Phases

### [DONE] Phase 0. Foundation Observability Baseline

**Goal**

Record the observability work that already exists so the phase plan extends the current backend instead of re-describing a greenfield implementation.

**Files already present**

- [DONE] `backend/app/observability/logging.py`
- [DONE] `backend/app/observability/middleware.py`
- [DONE] `backend/app/observability/models.py`
- [DONE] `backend/app/api/errors.py`
- [DONE] `backend/app/foundation/health.py`
- [DONE] `backend/app/config/redaction.py`
- [DONE] `backend/app/config/view.py`
- [DONE] `backend/app/contracts/trace.py`
- [DONE] `backend/app/testing/fakes/fake_trace.py`
- [DONE] `backend/tests/unit/test_app_factory.py`
- [DONE] `backend/tests/unit/test_health.py`

**Implementation outcomes already in place**

- [DONE] Requests receive a trace ID and return it in the response headers.
- [DONE] Startup remains import-safe and external-service-free until lifespan startup.
- [DONE] Error responses already include the current request trace ID when present.
- [DONE] Health output already exposes a redacted shallow configuration summary.
- [DONE] The backend already has a `TraceStore` contract and a fake trace store for tests.

**Validation already covered**

- [DONE] `backend/tests/unit/test_app_factory.py`
- [DONE] `backend/tests/unit/test_health.py`
- [DONE] `backend/tests/unit/test_capabilities.py`

**Exit criteria**

- [DONE] The observability implementation starts from the existing `backend/` slice instead of replacing it.

### [DONE] Phase 1. Config and Contract Alignment

**Goal**

Align configuration, event ownership, and health status semantics before deeper observability features are added.

**Files to create or update**

- [DONE] `backend/app/config/schemas.py`
- [DONE] `backend/app/config/view.py`
- [DONE] `backend/config/app.yaml`
- [DONE] `backend/tests/fixtures/config/valid_minimal.yaml`
- [DONE] `backend/tests/fixtures/config/valid_full.yaml`
- [DONE] `backend/app/contracts/trace.py`
- [DONE] `backend/app/contracts/health.py`
- [DONE] `backend/app/observability/events.py`
- [DONE] `backend/tests/unit/config/test_config_view.py`
- [DONE] `backend/tests/unit/observability/test_event_catalog.py`

**Implementation tasks**

- [DONE] Extend `backend/app/config/schemas.py` so the validated `observability` section includes the architecture-required keys:
   - [DONE] `trace_enabled`
   - [DONE] `trace_store_required`
   - [DONE] `include_stack_traces_in_logs`
   - [DONE] `include_stack_traces_in_traces`
   - [DONE] `max_trace_payload_chars`
   - [DONE] `slow_request_ms`
   - [DONE] `slow_llm_call_ms`
   - [DONE] `slow_tool_call_ms`
   - [DONE] `metrics_enabled`
- [DONE] Extend the validated `health` section with any new architecture-driven flags such as `include_component_details`.
- [DONE] Add small configuration access helpers in `backend/app/config/view.py` so runtime code can read observability settings from validated configuration instead of repeatedly reading raw dictionaries.
- [DONE] Normalize health status semantics across `backend/app/contracts/health.py` and `backend/app/foundation/health.py`.
  Recommended direction: preserve the backend route vocabulary already used by the current health endpoint and adapt component contracts to that same set.
- [DONE] Create `backend/app/observability/events.py` as the canonical runtime event catalog.
- [DONE] Re-export or otherwise preserve the existing minimum event names from `backend/app/contracts/trace.py` so current imports do not break during the transition.
- [DONE] Keep this phase focused on alignment only; do not add SQLite code or new request middleware behavior yet.

**Validation**

- [DONE] Add and pass focused config schema tests for the expanded `observability` and `health` sections.
- [DONE] Add and pass a unit test proving the event catalog has no duplicate values and the contract-level constants remain aligned.
- [DONE] Run `pytest backend/tests/unit/config backend/tests/unit/observability` from `backend/`.

**Exit criteria**

- [DONE] The validated config shape can drive the observability phase without more schema churn.
- [DONE] Health status strings, event constants, and configuration access rules are centralized and unambiguous.

### [DONE] Phase 2. Trace Identity and Context

**Goal**

Replace the current foundation-only trace ID handling with reusable helpers for generation, validation, alias handling, and async-safe trace context propagation.

**Files to create or update**

- [DONE] `backend/app/observability/ids.py`
- [DONE] `backend/app/observability/context.py`
- [DONE] `backend/app/observability/middleware.py`
- [DONE] `backend/app/observability/models.py`
- [DONE] `backend/tests/unit/observability/test_trace_id_generation.py`
- [DONE] `backend/tests/unit/observability/test_trace_context.py`
- [DONE] `backend/tests/unit/test_app_factory.py`

**Implementation tasks**

- [DONE] Add `new_trace_id()` with the architecture-recommended format, such as `trace_<uuid4_hex>`.
- [DONE] Add explicit inbound trace ID validation so invalid or unsafe values are ignored or replaced instead of being accepted as-is.
- [DONE] Accept both `x-trace-id` and the optional alias `x-request-id`, with one documented precedence rule.
- [DONE] Introduce `TraceContext` and contextvar helpers in `backend/app/observability/context.py`.
- [DONE] Move trace-context storage responsibilities out of ad hoc middleware state into shared helpers, while still setting `request.state.trace_id` for API handlers and error mapping.
- [DONE] Ensure the middleware always clears context on success and failure so async request handling cannot leak correlation data across requests.
- [DONE] Keep the response header behavior stable for existing tests and clients.

**Validation**

- [DONE] Add and pass unit tests for trace ID generation, inbound validation, and alias precedence.
- [DONE] Add and pass unit tests that prove trace context is set and reset correctly across async boundaries.
- [DONE] Update the existing app-factory middleware tests so they assert the new trace ID format and invalid-header replacement behavior.

**Exit criteria**

- [DONE] Trace IDs are generated consistently, validated safely, and propagated through shared helpers rather than middleware-only state.

### [DONE] Phase 3. Shared Redaction and Structured Logging

**Goal**

Introduce one redaction model and a configuration-driven logging stack that later backend modules can reuse without leaking sensitive data.

**Files to create or update**

- [DONE] `backend/app/observability/redaction.py`
- [DONE] `backend/app/observability/logging.py`
- [DONE] `backend/app/observability/errors.py`
- [DONE] `backend/app/config/redaction.py`
- [DONE] `backend/app/config/view.py`
- [DONE] `backend/tests/unit/observability/test_observability_redaction.py`
- [DONE] `backend/tests/unit/observability/test_structured_logging.py`
- [DONE] `backend/tests/unit/observability/test_error_observability.py`

**Implementation tasks**

- [DONE] Add a runtime redactor in `backend/app/observability/redaction.py` that supports:
   - [DONE] recursive dictionary/list traversal
   - [DONE] key-based secret redaction
   - [DONE] payload truncation
   - [DONE] safe serialization of unsupported values
   - [DONE] never-raise behavior on error paths
- [DONE] Update `backend/app/config/redaction.py` so configuration summary redaction and runtime telemetry redaction share the same rules or the same implementation.
- [DONE] Rework `backend/app/observability/logging.py` into a two-step model:
   - [DONE] bootstrap logging from `Settings` before validated config loads
   - [DONE] reconfigure logging from `backend/app/config/view.py` after config validation
- [DONE] Enrich log records from `TraceContext` rather than from the current middleware-specific context getter.
- [DONE] Support structured JSON logs and readable local logs from the validated `observability` section.
- [DONE] Add trace-safe error payload helpers in `backend/app/observability/errors.py` for logs and trace events, while keeping HTTP response mapping in `backend/app/api/errors.py`.
- [DONE] Ensure startup summaries, warning logs, and error metadata all remain redacted.

**Validation**

- [DONE] Add and pass redaction tests for nested secrets, long-string truncation, and unsupported object serialization.
- [DONE] Add and pass logging tests proving trace IDs appear in structured logs when context is active.
- [DONE] Add and pass tests proving error observability helpers never expose raw secrets or stack traces when disabled.

**Exit criteria**

- [DONE] Logs, config summaries, health details, and error metadata use one compatible redaction model.
- [DONE] Logging behavior is driven by validated backend configuration rather than foundation-only environment flags.

### [DONE] Phase 4. Trace Recorder and SQLite Trace Store

**Goal**

Provide the first full trace event path: runtime modules emit safe events through a helper, and the concrete SQLite implementation persists them behind the trace-store contract.

**Files to create or update**

- `backend/app/observability/tracing.py`
- `backend/app/persistence/__init__.py`
- `backend/app/persistence/trace_store.py`
- `backend/app/persistence/sqlite_trace_schema.py`
- `backend/app/persistence/sqlite_trace_store.py`
- `backend/app/testing/fakes/fake_trace.py`
- `backend/app/contracts/trace.py`
- `backend/tests/unit/observability/test_trace_recorder.py`
- `backend/tests/integration/test_trace_store_sqlite_smoke.py`

**Implementation tasks**

- [DONE] Add `TraceRecorder` in `backend/app/observability/tracing.py` so later modules do not need to hand-build `TraceEvent` objects repeatedly.
- [DONE] Make `TraceRecorder` honor `trace_enabled`, `trace_payloads_enabled`, `max_trace_payload_chars`, and `trace_store_required`.
- [DONE] Add a concrete trace-store construction boundary in `backend/app/persistence/trace_store.py`.
- [DONE] Implement append-only SQLite event writes in `backend/app/persistence/sqlite_trace_store.py`.
- [DONE] Keep all schema bootstrap logic in `backend/app/persistence/sqlite_trace_schema.py`.
- [DONE] Resolve SQLite file paths from validated backend configuration, keeping path behavior deterministic under `backend/`.
- [DONE] Extend `backend/app/testing/fakes/fake_trace.py` only as needed so recorder behavior and failure paths can be tested without real SQLite.
- [DONE] Keep detailed trace query, retention, compression, and debug UI work explicitly deferred.

**Validation**

- [DONE] Add and pass unit tests for `TraceRecorder` success, disabled payloads, redaction, and store-failure behavior.
- [DONE] Add and pass a smoke integration test that initializes a temporary SQLite trace database and appends at least one event.
- [DONE] Run a focused backend startup test proving schema bootstrap does not require app import-time side effects.

**Exit criteria**

- [DONE] Runtime code can record trace events without knowing SQLite details.
- [DONE] SQLite trace persistence exists behind `backend/app/persistence/` and only there.

### [DONE] Phase 5. Health Aggregation and Metrics Stub

**Goal**

Replace the current foundation-only health registry with a reusable observability aggregator and add a lightweight metrics interface for later backend modules.

**Files to create or update**

- `backend/app/observability/health.py`
- `backend/app/observability/metrics.py`
- `backend/app/foundation/health.py`
- `backend/app/foundation/container.py`
- `backend/app/api/routes_health.py`
- `backend/tests/unit/observability/test_health_aggregator.py`
- `backend/tests/unit/observability/test_metrics_counters.py`
- `backend/tests/unit/test_health.py`

**Implementation tasks**

- [DONE] Move reusable aggregation logic into `backend/app/observability/health.py`.
- [DONE] Keep `backend/app/foundation/health.py` as the shallow composition layer that registers current backend checks and adapts them into the route response shape.
- [DONE] Register health checks for configuration, logging, observability, trace store, and current placeholder future integrations.
- [DONE] Ensure exceptions raised by individual component checks degrade or fail the component safely instead of crashing `/health`.
- [DONE] Add `MetricsRecorder` plus a `NoopMetricsRecorder` in `backend/app/observability/metrics.py`.
- [DONE] Optionally add an in-memory metrics recorder for tests if it keeps later integration tests simpler.
- [DONE] Keep metrics low-cardinality and free of trace IDs, session IDs, prompt text, and other high-cardinality or sensitive values.

**Validation**

- [DONE] Add and pass health-aggregator tests for `ok`, `degraded`, and failure paths.
- [DONE] Update the health-route tests so they assert the new observability and trace-store sections remain safe and redacted.
- [DONE] Add and pass metrics tests proving low-cardinality tags are accepted and sensitive tags are not required.

**Exit criteria**

- [DONE] `/health` is backed by reusable observability logic instead of a foundation-only registry.
- [DONE] A metrics interface exists so later LLM, memory, tool, and workflow modules can emit counters and timings without choosing a backend yet.

### [DONE] Phase 6. Startup and Request Integration

**Goal**

Wire the observability pieces into backend startup, request middleware, and error handling without breaking the current backend app lifecycle.

**Files to create or update**

- [DONE] `backend/app/config/bootstrap.py`
- [DONE] `backend/app/foundation/container.py`
- [DONE] `backend/app/main.py`
- [DONE] `backend/app/observability/middleware.py`
- [DONE] `backend/app/api/errors.py`
- [DONE] `backend/app/api/routes_health.py`
- [DONE] `backend/tests/integration/test_startup_observability.py`
- [DONE] `backend/tests/unit/test_app_factory.py`

**Implementation tasks**

- [DONE] Extend `backend/app/foundation/container.py` so the app state can carry the observability services that later modules will need, such as the redactor, trace recorder, metrics recorder, and health aggregator.
- [DONE] Update `backend/app/config/bootstrap.py` so startup wiring builds observability in the correct order:
   1. [DONE] bootstrap logger
   2. [DONE] validated configuration load
   3. [DONE] redactor
   4. [DONE] structured logging reconfiguration
   5. [DONE] trace store creation and schema bootstrap
   6. [DONE] trace recorder and metrics recorder
   7. [DONE] health aggregator registration
- [DONE] Update `backend/app/main.py` to emit a redacted startup summary and startup failure diagnostics.
- [DONE] Update `backend/app/observability/middleware.py` so the request boundary can emit request start and request completion observability signals using the new trace helpers.
- [DONE] Update `backend/app/api/errors.py` so known and unknown failures can log and record trace-safe error metadata without leaking request bodies or secrets.
- [DONE] Keep `app = create_app()` import-safe by performing all concrete startup work inside lifespan code.
- [DONE] Preserve existing route behavior and response headers while deepening the diagnostics path.

**Validation**

- [DONE] Add and pass a startup integration test proving observability wiring happens during lifespan startup and not during module import.
- [DONE] Update request middleware tests so they cover request start/completion behavior, trace header propagation, and safe handling of invalid inbound trace IDs.
- [DONE] Add and pass a focused error-path test proving unhandled exceptions still return stable JSON error envelopes while observability output remains trace-safe.

**Exit criteria**

- [DONE] Startup and request handling both emit consistent, redacted, configuration-driven observability signals.
- [DONE] The backend remains import-safe and rooted entirely in `backend/`.

### [DONE] Phase 7. Tests, Freeze, and Handoff

**Goal**

Finish the observability slice with backend-local tests, developer documentation, and explicit deferrals for the next backend phases.

**Files to create or update**

- [DONE] `backend/tests/unit/observability/`
- [DONE] `backend/tests/integration/`
- [DONE] `backend/tests/fixtures/config/observability_enabled.yaml`
- [DONE] `backend/tests/fixtures/config/observability_trace_payloads_disabled.yaml`
- [DONE] `backend/tests/fixtures/config/observability_unstructured_logging.yaml`
- [DONE] `backend/tests/fixtures/config/health_minimal.yaml`
- [DONE] `backend/tests/fixtures/config/health_detailed.yaml`
- [DONE] `backend/README.md`

**Implementation tasks**

- [DONE] Add the missing fixture configurations needed to exercise observability toggles and health detail behavior.
- [DONE] Make sure all observability-specific tests live under `backend/tests/unit/observability/` or `backend/tests/integration/`.
- [DONE] Update `backend/README.md` with the canonical backend-local validation commands and the new observability boundaries.
- [DONE] Record explicit deferrals for:
   - [DONE] trace query APIs
   - [DONE] trace retention and archival
   - [DONE] per-token streaming trace events
   - [DONE] centralized log shipping
   - [DONE] OpenTelemetry or other distributed tracing integration
   - [DONE] provider-specific telemetry enrichments
- [DONE] Confirm the next backend phases can depend on trace IDs, trace recording, redaction, health aggregation, and metrics stubs without revisiting the foundation setup.

**Validation**

- [DONE] From `backend/`, run `.venv\Scripts\python.exe -m pytest`.
- [DONE] From `backend/`, run `.venv\Scripts\python.exe -m ruff check .`.
- [DONE] From `backend/`, run `.venv\Scripts\python.exe -m mypy app`.

**Exit criteria**

- [DONE] The observability implementation is startable, testable, and documented from `backend/`.
- [DONE] Deferred work is explicit, and later backend phases can build on the observability slice without reopening path or boundary decisions.

---

## 6. Acceptance Gate for This Plan

This plan should be considered complete when the implementation can satisfy all of the following without placing backend code outside `backend/`:

- One validated trace ID is created or accepted for each request.
- Trace context can enrich logs and trace events safely across async request handling.
- Structured logging behavior comes from validated backend configuration after config load.
- A shared redaction model is used by logs, traces, health responses, config summaries, and error metadata.
- Trace events are emitted through `backend/app/contracts/trace.py` and persisted only through implementations under `backend/app/persistence/`.
- `/health` remains safe, redacted, and backed by reusable observability aggregation.
- A lightweight metrics interface exists for later backend modules.
- Startup logging and startup failures are diagnosable without leaking secrets.
- All backend-local tests, lint checks, and type checks pass from `backend/`.

---

## 7. Summary

The observability phase should be implemented as an extension of the current backend foundation, not as a rewrite.

The highest-value sequence is:

1. align config and contracts
2. centralize trace IDs and context
3. centralize redaction and logging
4. add trace recording and SQLite persistence behind `backend/app/persistence/`
5. upgrade health aggregation and metrics
6. integrate everything into backend startup and request handling
7. freeze the slice with backend-local tests and documentation

That sequence keeps the backend diagnosable early, preserves the existing `backend/` repository structure, and gives later LLM, memory, tooling, state, orchestration, and agent phases a stable observability backbone.