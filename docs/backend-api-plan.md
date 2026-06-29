# Backend API Implementation Plan

**Document:** `backend-api-plan.md`  
**Version:** 1.0  
**Source alignment:** `backend-api-architecture.md`, `backend-foundation-plan.md`, `backend-core-contracts-plan.md`, `backend-configuration-plan.md`, `backend-observability-plan.md`, `backend-persistence-plan.md`, `backend-sqlite-workflow-state-plan.md`, and `backend-sqlite-trace-store-plan.md`  
**Repository rule:** all backend application code lives under `backend/`

---

## 1. Purpose

This plan converts the backend API architecture into a repo-accurate implementation sequence that can be executed in small, low-risk phases.

The plan is intentionally strict about repository boundaries:

- Backend application code belongs in `backend/`.
- Backend source modules belong in `backend/app/`.
- Backend tests belong in `backend/tests/`.
- Backend configuration files belong in `backend/config/`.
- Backend local data files belong in `backend/data/`.
- Documentation updates belong in `docs/`.
- No backend runtime code should be placed in the repository root, `frontend/`, or `mcp/`.

For clarity, this document uses filesystem paths such as `backend/app/api/routes_chat.py`. Python imports may still use the `app.*` package path because `backend/` is the Python project root.

This phase is not greenfield work. The repository already contains a real backend API baseline under `backend/`, but that slice is intentionally narrow. The implementation plan therefore focuses on extending the current backend modules instead of creating duplicate app factories, duplicate middleware stacks, or a second request-contract surface.

---

## 2. Review Outcomes

The API architecture document is implementation-ready and fits the current backend direction. It is strong on route thinness, request validation, SSE boundaries, trace correlation, safe error mapping, frontend-facing capability discovery, and the rule that API handlers must not reach into SQLite, provider SDKs, MCP clients, or memory internals.

The review also confirms that the repository already contains a usable but narrower backend API baseline that must be extended rather than replaced:

- `backend/app/main.py` already acts as the backend application factory and composition-root entrypoint.
- `backend/app/api/errors.py` already provides stable JSON error envelopes and exception-handler registration.
- `backend/app/api/routes_health.py` and `backend/app/api/routes_capabilities.py` already expose the current foundation endpoints.
- `backend/app/observability/context.py`, `backend/app/observability/ids.py`, and `backend/app/observability/middleware.py` already provide request trace propagation.
- `backend/app/config/bootstrap.py` already builds the backend container during lifespan startup.
- `backend/app/foundation/container.py` already exposes validated config, persistence, tracing, metrics, health, and capabilities to route code.
- `backend/app/contracts/context.py` and `backend/app/contracts/results.py` already define orchestration-facing request and result contracts that later API/session code should reuse rather than duplicate.
- `backend/app/persistence/` already provides the real workflow-state and trace-store foundations that the API walking skeleton should consume through services.
- `backend/tests/unit/test_app_factory.py`, `backend/tests/unit/test_health.py`, and `backend/tests/unit/test_capabilities.py` already cover the current baseline route wiring.

The main implementation concerns to resolve explicitly during execution are:

1. **The architecture's illustrative package layout is not repo-accurate as written.**  
   The document shows backend tests under `tests/`, references `app/api/app_factory.py`, and mentions `trace_context.py`. In this repository, backend code lives under `backend/app/`, backend tests live under `backend/tests/`, the current app factory lives in `backend/app/main.py`, and the existing trace-context helpers live in `backend/app/observability/context.py`.

2. **The current API slice is foundation-oriented, not session-oriented.**  
   The repo currently exposes only `GET /health` and `GET /capabilities`. There is no `backend/app/session/` package, no `SessionService`, no chat routes, no SSE encoder, no reset route, and no debug trace route layer yet.

3. **There is no typed API configuration surface yet.**  
   The current validated config pipeline does not yet expose the architecture's API-specific sections for CORS, request limits, debug routes, session-header behavior, and SSE behavior.

4. **The current health and capabilities responses still reflect the earlier foundation phase.**  
   They already work, but they need to grow into the API-facing shapes described in `backend-api-architecture.md` without losing the current safe-health and safe-capability behavior.

5. **The existing app factory and middleware should be extended, not duplicated.**  
   The plan should keep `backend/app/main.py` as the canonical startup entrypoint unless a later refactor removes real complexity. Likewise, shared trace/timing/request logging should continue to build on `backend/app/observability/middleware.py` instead of creating a competing middleware stack under `backend/app/api/` without a concrete need.

6. **The public contract surface should stay canonical.**  
   The repo already uses `backend/app/contracts/context.py` and `backend/app/contracts/results.py`. The API phase should not create parallel public contract modules such as `backend/app/contracts/request.py` just because the architecture document used illustrative names.

7. **Test layout must stay consistent with the repo.**  
   Unit tests can add `backend/tests/unit/api/`, but integration tests should follow the repository's existing flat `backend/tests/integration/` pattern using names such as `test_api_walking_skeleton.py` unless there is a deliberate repository-wide move.

8. **The API needs two service layers, not one shortcut.**  
   The plan needs a fake session service first for thin-route validation, then a walking-skeleton session service that touches real workflow-state and trace stores while still deferring LLM, memory, tool, and MCP integrations.

9. **Debug trace access must remain optional and tightly bounded.**  
   The trace-store is ready for safe read/search behavior, but API exposure must stay disabled by default, localhost-restricted in V1, and redacted end to end.

10. **All new backend-owned paths must stay under `backend/`.**  
   New route modules belong under `backend/app/api/`, session modules under `backend/app/session/`, config fixtures under `backend/tests/fixtures/config/`, unit tests under `backend/tests/unit/`, and integration tests under `backend/tests/integration/`.

---

## 3. Non-Negotiable Boundary Rules

- Treat `backend/` as the Python project root for all API work.
- Create runtime API modules only under `backend/app/api/` and `backend/app/session/`.
- Extend backend startup through `backend/app/main.py`, `backend/app/config/bootstrap.py`, and `backend/app/foundation/container.py` rather than creating a second composition root.
- Keep orchestration-facing request and result contracts in `backend/app/contracts/context.py` and `backend/app/contracts/results.py`; do not create competing public request/result contract files under new names unless a later refactor clearly requires them.
- Keep backend tests under `backend/tests/` and config fixtures under `backend/tests/fixtures/config/`.
- Keep backend configuration under `backend/config/` and backend-local runtime data under `backend/data/`.
- Keep documentation-only artifacts under `docs/`.
- Do not place backend API, SSE, session, or debug-trace code in the repository root, `frontend/`, or `mcp/`.
- Do not let any route module import `sqlite3`, execute SQL, import `memory_store.service.MemoryService`, import provider SDKs, import MCP client implementations, or import concrete orchestration strategies or agent implementations.
- Route handlers must delegate chat and reset behavior to `SessionService` and debug-trace behavior to a narrow facade; they must not coordinate cross-store transactions.
- Keep `backend/app/main.py:app = create_app()` import-safe. All I/O, config validation, service construction, and store initialization belong in lifespan startup.
- Do not log raw request bodies, raw chat messages, raw provider payloads, raw tool payloads, raw trace payloads, secrets, tokens, cookies, connection strings, or full stack traces in normal API responses.
- Debug trace routes must be disabled by default and must remain redacted, bounded, and localhost-restricted until a later auth/policy phase defines stronger access control.
- Session reset must clear workflow state only. It must not delete memory, traces, config, or other sessions.
- Relative API config and fixture paths must resolve from `backend/`, not from the shell's current working directory.

---

## 4. Phase Overview

| Phase | Name | Primary Outcome |
|---|---|---|
| 0 | [DONE] Current API Baseline | The repository already has an import-safe FastAPI app, trace middleware, stable error handlers, and foundation `/health` and `/capabilities` routes under `backend/`. |
| 1 | [DONE] API Config and Repo Alignment | Typed API settings are added to the validated config pipeline and the plan resolves all architecture-to-repo path differences up front. |
| 2 | [DONE] Session Boundary and DTO Surface | API DTOs, request-context helpers, session-service contracts, and fake session behavior exist without reaching into orchestration or providers. |
| 3 | Middleware and App Wiring | CORS, request limits, API header policy, OpenAPI toggles, dependency wiring, and expanded error mapping are integrated into the existing backend app factory. |
| 4 | Non-Streaming Chat Route | `POST /chat` works against a fake session service and proves the thin-route boundary. |
| 5 | [DONE] Streaming Route and SSE | `POST /chat/stream` emits valid SSE events with safe lifecycle behavior and no per-token state writes. |
| 6 | [DONE] Reset, Health, Capabilities, and Debug Routes | The remaining route surface is completed, existing foundation routes are expanded into API-facing responses, and debug-trace access is added behind strict guards. |
| 7 | [DONE] Walking Skeleton Session Service | The fake session implementation is replaced by a real session slice that loads and saves workflow state and records safe trace summaries. |
| 8 | [DONE] Tests, Quality Gates, and Freeze | Focused tests, fixture configs, and full backend validation prove the API acceptance criteria and hand off cleanly to the deeper session-service phase. |

---

## 5. Detailed Implementation Phases

### [DONE] Phase 0. Current API Baseline

**Goal**

Record the API work that already exists so the plan extends the current backend instead of re-describing a greenfield slice.

**Files already present**

- [DONE] `backend/app/main.py`
- [DONE] `backend/app/api/errors.py`
- [DONE] `backend/app/api/routes_health.py`
- [DONE] `backend/app/api/routes_capabilities.py`
- [DONE] `backend/app/config/bootstrap.py`
- [DONE] `backend/app/foundation/container.py`
- [DONE] `backend/app/observability/context.py`
- [DONE] `backend/app/observability/ids.py`
- [DONE] `backend/app/observability/middleware.py`
- [DONE] `backend/app/observability/tracing.py`
- [DONE] `backend/tests/unit/test_app_factory.py`
- [DONE] `backend/tests/unit/test_health.py`
- [DONE] `backend/tests/unit/test_capabilities.py`
- [DONE] `backend/tests/integration/test_startup_observability.py`
- [DONE] `backend/tests/integration/test_startup_persistence.py`

**Implementation outcomes already in place**

- [DONE] The backend already has an import-safe FastAPI application factory rooted in `backend/app/main.py`.
- [DONE] The current app already registers stable exception handlers through `backend/app/api/errors.py`.
- [DONE] The current app already injects request trace IDs through shared observability middleware.
- [DONE] The backend container already exposes validated config, persistence, trace recording, metrics, health, and capabilities to route code.
- [DONE] The backend startup path already builds real workflow-state and trace-store dependencies during lifespan startup.
- [DONE] The current API slice already exposes foundation `/health` and `/capabilities` routes under `backend/app/api/`.

**Validation already covered**

- [DONE] `backend/tests/unit/test_app_factory.py`
- [DONE] `backend/tests/unit/test_health.py`
- [DONE] `backend/tests/unit/test_capabilities.py`
- [DONE] `backend/tests/integration/test_startup_observability.py`
- [DONE] `backend/tests/integration/test_startup_persistence.py`

**Exit criteria**

- [DONE] The plan starts from the real backend API baseline under `backend/` instead of inventing a second API stack.

### [DONE] Phase 1. API Config and Repo Alignment

**Goal**

Add the architecture's API-specific configuration surface to the existing validated config pipeline and lock in repo-accurate file/layout decisions before route expansion begins.

**Files to create or update**

- [DONE] `backend/app/config/schemas.py`
- [DONE] `backend/app/config/validation.py`
- [DONE] `backend/app/config/view.py`
- [DONE] `backend/app/config/bootstrap.py`
- [DONE] `backend/app/foundation/container.py`
- [DONE] `backend/app/main.py` reviewed and intentionally left unchanged as the canonical startup entrypoint.
- [DONE] `backend/config/app.yaml`
- [DONE] `backend/tests/unit/config/test_config_view.py`
- [DONE] `backend/tests/unit/config/test_validation.py`
- [DONE] `backend/tests/fixtures/config/api_basic.yaml`
- [DONE] `backend/tests/fixtures/config/api_streaming_enabled.yaml`
- [DONE] `backend/tests/fixtures/config/api_debug_traces_disabled.yaml`
- [DONE] `backend/tests/fixtures/config/api_debug_traces_enabled.yaml`
- [DONE] `backend/tests/fixtures/config/api_small_request_limits.yaml`
- [DONE] `backend/tests/fixtures/config/api_cors_localhost.yaml`
- [DONE] `backend/tests/fixtures/config/api_invalid_cors_origin.yaml`
- [DONE] `backend/tests/fixtures/config/api_invalid_request_limit.yaml`
- [DONE] `backend/tests/fixtures/config/api_invalid_timeout.yaml`
- [DONE] `backend/tests/fixtures/config/api_invalid_header_name.yaml`

**Implementation tasks**

- [DONE] Add typed API config models and accessors for:
  - `api.enabled`
  - `api.base_path`
  - `api.docs_enabled`
  - `api.openapi_enabled`
  - `api.cors`
  - `api.request_limits`
  - `api.sessions`
  - `api.tracing`
  - `api.debug_routes`
  - `api.sse`
- [DONE] Validate CORS origins, numeric limits, timeout values, and header names through the existing config-validation pipeline.
- [DONE] Keep backend-root-relative config behavior deterministic from both the repo root and `backend/`.
- [DONE] Decide and document one repo-accurate ownership rule for the app factory: `backend/app/main.py` remains the canonical startup entrypoint unless a later refactor removes real complexity.
- [DONE] Extend the container shape so API wiring can receive typed API settings plus service placeholders without breaking the existing startup path.
- [DONE] Keep `backend/config/app.yaml` and fixture YAML files as the source of truth for API feature toggles; do not read route behavior directly from environment variables inside route modules.
- [DONE] Explicitly correct the architecture document's illustrative layout differences in this phase so later implementation does not drift toward repo-root `tests/` paths or duplicate trace-context modules.

**Validation**

- [DONE] Add and pass focused config-view tests proving the new API settings parse correctly from fixture-backed YAML under `backend/tests/fixtures/config/`.
- [DONE] Add and pass validation tests proving invalid CORS/timeout/request-limit values fail fast.
- [DONE] Run a focused config gate from `backend/`:
  - `backend/.venv\Scripts\python.exe -m pytest tests/unit/config/test_config_view.py tests/unit/config/test_validation.py`

**Exit criteria**

- [DONE] Typed API settings are available through the validated config pipeline.
- [DONE] The repo-accurate backend path rules are explicit and no phase step implies backend code outside `backend/`.

### [DONE] Phase 2. Session Boundary and DTO Surface

**Goal**

Define the API-facing DTOs and the service boundary that routes will depend on before chat, streaming, and reset routes are added.

**Files to create or update**

- [DONE] `backend/app/api/schemas.py`
- [DONE] `backend/app/api/dependencies.py`
- [DONE] `backend/app/api/request_context.py`
- [DONE] `backend/app/api/versioning.py`
- [DONE] `backend/app/api/security.py`
- [DONE] `backend/app/session/__init__.py`
- [DONE] `backend/app/session/service.py`
- [DONE] `backend/app/session/models.py`
- [DONE] `backend/app/session/errors.py`
- [DONE] `backend/app/testing/fakes/fake_session_service.py`
- [DONE] `backend/tests/unit/api/test_chat_schemas.py`
- [DONE] `backend/tests/unit/api/test_fake_session_service.py`

**Implementation tasks**

- [DONE] Define explicit API DTOs for:
  - `ChatRequest`
  - `ChatResponse`
  - `ResetSessionRequest`
  - `ResetSessionResponse`
  - `HealthResponse`
  - `CapabilitiesResponse`
  - `ApiErrorResponse`
- [DONE] Keep API DTOs under `backend/app/api/` and keep orchestration-facing shapes under `backend/app/contracts/`; do not create duplicate public contract modules just to mirror the architecture's illustrative filenames.
- [DONE] Introduce API request-context helpers for trace ID, request ID, synthetic identity, safe headers, and safe request metadata.
- [DONE] Reuse `backend/app/contracts/context.py:RequestContext` as the downstream orchestration-facing request shape; the new API layer maps into it rather than replacing it.
- [DONE] Introduce `SessionService` as a protocol or narrow abstract service under `backend/app/session/service.py` with methods for:
  - `handle_chat`
  - `stream_chat`
  - `reset_session`
- [DONE] Define `SessionChatResult`, `SessionResetResult`, and `SessionStreamEvent` in `backend/app/session/models.py` so the route layer does not depend on raw orchestration result shapes.
- [DONE] Add a deterministic fake session service under `backend/app/testing/fakes/fake_session_service.py` that can support unit and integration tests without LLM, memory, tool, or MCP dependencies.
- [DONE] Keep the fake session implementation intentionally simple: stable session IDs, echo-like answers, safe metadata, and streaming events that mimic the final route contract without pretending to be a full orchestrator.

**Validation**

- [DONE] Add and pass DTO tests proving required fields, size limits, and serialization behavior.
- [DONE] Add and pass fake-session tests proving stable session IDs, reset behavior, and streaming event ordering.
- [DONE] Run a focused session/DTO gate from `backend/`:
  - `backend/.venv\Scripts\python.exe -m pytest tests/unit/api/test_chat_schemas.py tests/unit/api/test_fake_session_service.py`

**Exit criteria**

- [DONE] The API has explicit request/response DTOs.
- [DONE] Route code can depend on a fake or real `SessionService` without importing persistence or orchestration internals.

### [DONE] Phase 3. Middleware and App Wiring

**Goal**

Wire API-specific limits, headers, OpenAPI toggles, dependency resolution, and expanded error behavior into the existing backend startup path without creating a parallel app factory.

**Files to create or update**

- [DONE] `backend/app/main.py`
- [DONE] `backend/app/api/errors.py`
- [DONE] `backend/app/api/dependencies.py`
- [DONE] `backend/app/api/openapi.py`
- [DONE] `backend/app/observability/middleware.py`
- [DONE] `backend/app/config/bootstrap.py`
- [DONE] `backend/app/foundation/container.py`
- [DONE] `backend/tests/unit/api/test_error_mapping.py`
- [DONE] `backend/tests/unit/api/test_trace_id_middleware.py`
- [DONE] `backend/tests/unit/api/test_request_limits.py`
- [DONE] `backend/tests/integration/test_api_cors.py`

**Implementation tasks**

- [DONE] Extend the current middleware and app wiring to honor typed API settings for:
  - [DONE] CORS
  - [DONE] request-size enforcement
  - [DONE] request timeout metadata
  - [DONE] `X-Trace-Id` acceptance and response behavior
  - [DONE] `X-Session-Id` response behavior where applicable
  - [DONE] safe request timing and request-summary logging
- [DONE] Keep shared request-correlation behavior rooted in `backend/app/observability/middleware.py`; only add `backend/app/api/` helpers when a concern is truly API-specific.
- [DONE] Expand `backend/app/api/errors.py` to map the new session-service errors and validation failures to stable HTTP statuses without exposing stack traces, SQLite details, provider payloads, or sensitive config.
- [DONE] Register OpenAPI docs conditionally from validated config and keep docs/examples free of secrets and internal-only fields.
- [DONE] Extend backend startup so the container can resolve:
  - [DONE] `session_service`
  - [DONE] optional `debug_trace_service`
  - [DONE] any API settings or response-header helpers needed by route dependencies
- [DONE] Preserve import safety: route registration and middleware construction should not initialize network clients or databases outside lifespan startup.

**Validation**

- [DONE] Add and pass middleware tests proving every response carries a trace ID and oversized requests are rejected safely.
- [DONE] Add and pass error-mapping tests proving validation and known service errors produce stable envelopes.
- [DONE] Add and pass an integration CORS check against a configured localhost origin.
- [DONE] Run a focused wiring gate from `backend/`:
  - [DONE] `backend/.venv\Scripts\python.exe -m pytest tests/unit/api/test_error_mapping.py tests/unit/api/test_trace_id_middleware.py tests/unit/api/test_request_limits.py tests/integration/test_api_cors.py`

**Exit criteria**

- [DONE] The existing backend app factory can host API-specific middleware and dependency wiring without forking into a second startup path.
- [DONE] The API has stable header, error, and OpenAPI behavior controlled through validated config.

### [DONE] Phase 4. Non-Streaming Chat Route

**Goal**

Add the first chat route against the fake session service to prove thin-route behavior before real session-state integration begins.

**Files to create or update**

- [DONE] `backend/app/api/routes_chat.py`
- [DONE] `backend/app/api/schemas.py`
- [DONE] `backend/app/api/dependencies.py`
- [DONE] `backend/app/main.py`
- [DONE] `backend/app/testing/fakes/fake_session_service.py`
- [DONE] `backend/tests/unit/api/test_chat_route.py`
- [DONE] `backend/tests/integration/test_api_chat_fake_session.py`

**Implementation tasks**

- [DONE] Implement `POST /chat` under `backend/app/api/routes_chat.py`.
- [DONE] Validate request bodies against the new `ChatRequest` DTO and route-level request limits.
- [DONE] Build an API request context from trace/session/identity helpers and call `SessionService.handle_chat` exactly once per request.
- [DONE] Map the returned session result to the explicit `ChatResponse` DTO.
- [DONE] Return `X-Trace-Id` and `X-Session-Id` headers on success.
- [DONE] Record only safe boundary telemetry such as request size, message length, duration, and route status; do not log or trace raw message bodies.
- [DONE] Keep the route intentionally thin. It must not import persistence stores, call `load()` or `save()` on workflow-state directly, or talk to the trace store SQL/query layer.

**Validation**

- [DONE] Add and pass route tests proving valid requests return a chat response and invalid requests return a stable validation error.
- [DONE] Add and pass an integration test proving `POST /chat` works end to end with the fake session service and the real app factory.
- [DONE] Run a focused chat gate from `backend/`:
  - [DONE] `backend/.venv\Scripts\python.exe -m pytest tests/unit/api/test_chat_route.py tests/integration/test_api_chat_fake_session.py`

**Exit criteria**

- [DONE] `POST /chat` exists and proves the route-to-service boundary without depending on a real orchestrator.
- [DONE] Session IDs and trace IDs are returned consistently on normal chat responses.

### [DONE] Phase 5. Streaming Route and SSE

**Goal**

Add SSE support for `POST /chat/stream` while keeping streaming lifecycle, cancellation, and event shaping inside safe API boundaries.

**Files to create or update**

- [DONE] `backend/app/api/routes_chat.py`
- [DONE] `backend/app/api/sse.py`
- [DONE] `backend/app/api/schemas.py`
- [DONE] `backend/app/session/models.py`
- [DONE] `backend/app/testing/fakes/fake_session_service.py`
- [DONE] `backend/tests/unit/api/test_sse_formatting.py`
- [DONE] `backend/tests/unit/api/test_stream_route.py`
- [DONE] `backend/tests/integration/test_api_streaming_sse.py`

**Implementation tasks**

- [DONE] Add `POST /chat/stream` to `backend/app/api/routes_chat.py`.
- [DONE] Implement an SSE encoder in `backend/app/api/sse.py` for:
  - [DONE] `response.started`
  - [DONE] `response.delta`
  - [DONE] `response.metadata`
  - [DONE] `response.completed`
  - [DONE] `response.error`
  - [DONE] `heartbeat`
- [DONE] Map `SessionStreamEvent` values to the public SSE contract and keep the event set stable and frontend-safe.
- [DONE] Return correct SSE headers, including trace/session headers and no-cache behavior.
- [DONE] Support heartbeat behavior from validated config.
- [DONE] Handle disconnects and cancellation without continuing to emit events.
- [DONE] Keep streaming state behavior bounded: the route must not save workflow state per token and must not expose raw provider events or raw tool payloads.

**Validation**

- [DONE] Add and pass unit tests proving SSE encoding and event order are correct.
- [DONE] Add and pass route tests proving stream errors are emitted as `response.error` events.
- [DONE] Add and pass an integration test proving the real app returns `text/event-stream` with well-formed events.
- [DONE] Run a focused streaming gate from `backend/`:
  - [DONE] `backend/.venv\Scripts\python.exe -m pytest tests/unit/api/test_sse_formatting.py tests/unit/api/test_stream_route.py tests/integration/test_api_streaming_sse.py`

**Exit criteria**

- [DONE] `POST /chat/stream` emits valid SSE events.
- [DONE] The API streaming boundary is in place without per-token persistence writes or raw provider leakage.

### [DONE] Phase 6. Reset, Health, Capabilities, and Debug Routes

**Goal**

Complete the V1 route surface, evolve the current foundation routes into API-facing responses, and add optional debug-trace access behind explicit guards.

**Files to create or update**

- [DONE] `backend/app/api/routes_sessions.py`
- [DONE] `backend/app/api/routes_health.py`
- [DONE] `backend/app/api/routes_capabilities.py`
- [DONE] `backend/app/api/routes_debug_traces.py`
- [DONE] `backend/app/observability/debug_trace_service.py`
- [DONE] `backend/app/foundation/health.py`
- [DONE] `backend/app/foundation/capabilities.py`
- [DONE] `backend/app/api/dependencies.py`
- [DONE] `backend/app/main.py`
- [DONE] `backend/tests/unit/api/test_session_reset_route.py`
- [DONE] `backend/tests/unit/api/test_health_route.py`
- [DONE] `backend/tests/unit/api/test_capabilities_route.py`
- [DONE] `backend/tests/unit/api/test_debug_trace_routes.py`
- [DONE] `backend/tests/integration/test_api_health_with_real_stores.py`
- [DONE] `backend/tests/integration/test_api_debug_traces_disabled.py`
- [DONE] `backend/tests/integration/test_api_debug_traces_enabled.py`

**Implementation tasks**

- [DONE] Implement `POST /sessions/{session_id}/reset` with path validation, optional reset reason parsing, and strict delegation to `SessionService.reset_session`.
- [DONE] Ensure reset clears workflow state only and does not delete traces, memory, or configuration.
- [DONE] Expand `GET /health` from the current foundation response into the API-facing shape described by the architecture while preserving safe health output and required-versus-optional semantics.
- [DONE] Expand `GET /capabilities` so it exposes frontend-safe feature flags such as:
  - [DONE] chat availability
  - [DONE] streaming availability
  - [DONE] reset availability
  - [DONE] max message size
  - [DONE] safe use-case display names
  - [DONE] debug trace enablement state
- [DONE] Add a narrow `DebugTraceService` under `backend/app/observability/` that wraps redacted trace-store read/search behavior without exposing route code to SQL or SQLite row details.
- [DONE] Add `GET /debug/traces/{trace_id}` and `GET /debug/traces` only behind config guards and localhost restrictions.
- [DONE] Keep health/capability/debug outputs free of raw payloads, secrets, provider credentials, and full filesystem paths.

**Validation**

- [DONE] Add and pass route tests proving reset validates session IDs and calls the service boundary correctly.
- [DONE] Add and pass health and capabilities tests proving safe output shaping.
- [DONE] Add and pass debug-route tests proving the routes are disabled by default and bounded when enabled.
- [DONE] Add and pass integration tests with the real stores for health and debug-trace wiring.
- [DONE] Run a focused route-completion gate from `backend/`:
  - [DONE] `backend/.venv\Scripts\python.exe -m pytest tests/unit/api/test_session_reset_route.py tests/unit/api/test_health_route.py tests/unit/api/test_capabilities_route.py tests/unit/api/test_debug_trace_routes.py tests/integration/test_api_health_with_real_stores.py tests/integration/test_api_debug_traces_disabled.py tests/integration/test_api_debug_traces_enabled.py`

**Exit criteria**

- [DONE] The API exposes `/sessions/{session_id}/reset`, `/health`, and `/capabilities` in their intended V1 shapes.
- [DONE] Optional debug trace routes stay disabled by default and safe when enabled.

### [DONE] Phase 7. Walking Skeleton Session Service

**Goal**

Replace the fake session service with a real walking-skeleton session path that uses workflow-state and trace persistence while still deferring full orchestration, LLM, memory, tool, and MCP integrations.

**Files to create or update**

- [DONE] `backend/app/session/service.py`
- [DONE] `backend/app/session/models.py`
- [DONE] `backend/app/session/errors.py`
- [DONE] `backend/app/config/bootstrap.py`
- [DONE] `backend/app/foundation/container.py`
- [DONE] `backend/app/contracts/context.py`
- [DONE] `backend/app/testing/fakes/fake_session_service.py`
- [DONE] `backend/tests/unit/api/test_session_service_mapping.py`
- [DONE] `backend/tests/integration/test_api_walking_skeleton.py`
- [DONE] `backend/tests/integration/test_api_reset_boundary.py`
- [DONE] `backend/tests/integration/test_api_trace_correlation.py`

**Implementation tasks**

- [DONE] Implement a real `SessionService` that:
  - [DONE] loads workflow state once near request start
  - [DONE] maps API request data into `backend/app/contracts/context.py:RequestContext`
  - [DONE] runs a stub orchestrator or echo-style internal execution path
  - [DONE] saves final workflow state once per non-streaming request
  - [DONE] saves final or cancellation-safe state once per streaming request
  - [DONE] records safe trace summaries through the existing trace recorder/store boundary
- [DONE] Keep the session implementation intentionally narrow: it should exercise real workflow-state and trace dependencies without pretending the later LLM, memory, tool, or MCP phases already exist.
- [DONE] Map known persistence/session failures to explicit session-service errors so the existing API error layer can translate them cleanly.
- [DONE] Extend startup wiring so the real session service is built from the same container/persistence/config path as the rest of the backend.
- [DONE] Preserve the architecture rule that the API does not call `WorkflowStateStore` directly for chat behavior; only the session service may do so.
- [DONE] Preserve streaming lifecycle rules: no per-token state saves, safe cancellation, and final completion or cancellation summaries only.

**Validation**

- [DONE] Add and pass focused unit tests proving API request context maps correctly into orchestration-facing request context.
- [DONE] Add and pass integration tests proving `POST /chat` persists workflow-state changes through the walking skeleton and that reset clears workflow state only.
- [DONE] Add and pass integration tests proving trace IDs show up both in responses and in the trace-store-backed observability path.
- [DONE] Run a focused walking-skeleton gate from `backend/`:
  - [DONE] `backend/.venv\Scripts\python.exe -m pytest tests/unit/api/test_session_service_mapping.py tests/integration/test_api_walking_skeleton.py tests/integration/test_api_reset_boundary.py tests/integration/test_api_trace_correlation.py`

**Exit criteria**

- [DONE] The API walking skeleton exercises real workflow-state and trace-store dependencies through `SessionService`.
- [DONE] Chat, stream, and reset routes remain thin while the backend stays ready for the deeper session-service architecture phase.

### [DONE] Phase 8. Tests, Quality Gates, and Freeze

**Goal**

Prove the API acceptance criteria end to end, keep the test/fixture layout repo-accurate, and hand off cleanly to the next document.

**Files to create or update**

- [DONE] `backend/tests/unit/api/test_chat_schemas.py`
- [DONE] `backend/tests/unit/api/test_chat_route.py`
- [DONE] `backend/tests/unit/api/test_stream_route.py`
- [DONE] `backend/tests/unit/api/test_session_reset_route.py`
- [DONE] `backend/tests/unit/api/test_health_route.py`
- [DONE] `backend/tests/unit/api/test_capabilities_route.py`
- [DONE] `backend/tests/unit/api/test_error_mapping.py`
- [DONE] `backend/tests/unit/api/test_trace_id_middleware.py`
- [DONE] `backend/tests/unit/api/test_request_limits.py`
- [DONE] `backend/tests/unit/api/test_sse_formatting.py`
- [DONE] `backend/tests/unit/api/test_debug_trace_routes.py`
- [DONE] `backend/tests/integration/test_api_chat_fake_session.py`
- [DONE] `backend/tests/integration/test_api_streaming_sse.py`
- [DONE] `backend/tests/integration/test_api_health_with_real_stores.py`
- [DONE] `backend/tests/integration/test_api_debug_traces_disabled.py`
- [DONE] `backend/tests/integration/test_api_debug_traces_enabled.py`
- [DONE] `backend/tests/integration/test_api_walking_skeleton.py`
- [DONE] `backend/tests/integration/test_api_reset_boundary.py`
- [DONE] `backend/tests/integration/test_api_trace_correlation.py`
- [DONE] `backend/tests/integration/test_api_cors.py`
- [DONE] `backend/tests/fixtures/config/api_basic.yaml`
- [DONE] `backend/tests/fixtures/config/api_streaming_enabled.yaml`
- [DONE] `backend/tests/fixtures/config/api_debug_traces_disabled.yaml`
- [DONE] `backend/tests/fixtures/config/api_debug_traces_enabled.yaml`
- [DONE] `backend/tests/fixtures/config/api_small_request_limits.yaml`
- [DONE] `backend/tests/fixtures/config/api_cors_localhost.yaml`
- [DONE] `backend/tests/fixtures/config/api_with_real_sqlite_stores.yaml`
- [DONE] `backend/README.md`

**Implementation tasks**

- [DONE] Add the unit and integration coverage called for by `backend-api-architecture.md`, using the repo's real backend-local test paths.
- [DONE] Keep integration tests flat under `backend/tests/integration/` to match the current repository pattern.
- [DONE] Add fixture-backed config coverage for basic API startup, streaming enabled, debug routes enabled/disabled, small request limits, localhost CORS, and real SQLite-backed session-service behavior.
- [DONE] Update `backend/README.md` with backend-local API route expectations, dev startup instructions, test commands, and any safe debug-route notes.
- [DONE] Run the full backend quality gate from `backend/`:
  - [DONE] `backend/.venv\Scripts\python.exe -m pytest`
  - [DONE] `backend/.venv\Scripts\python.exe -m ruff check .`
  - [DONE] `backend/.venv\Scripts\python.exe -m mypy app`
- [DONE] Confirm that the API acceptance criteria from `backend-api-architecture.md` are satisfied at repo-accurate paths under `backend/`.
- [DONE] Record the intentional deferrals for the next phase, especially:
  - [DONE] deep session lifecycle rules
  - [DONE] history shaping and optional history route policy
  - [DONE] real orchestration runtime behavior
  - [DONE] LLM gateway integration
  - [DONE] memory gateway integration
  - [DONE] tool and MCP integration
  - [DONE] auth/policy hardening beyond localhost debug-route guards

**Exit criteria**

- [DONE] API behavior is covered by focused tests at both the unit and integration level.
- [DONE] The backend API walking skeleton is stable, repo-accurate, and ready for `docs/backend-session-service-architecture.md`.

The walking-skeleton label in this document is now historical. The current backend keeps the same API ownership rules, but startup is wired to the deeper `DefaultSessionService` delivered by the later session-service phase.

---

## 6. Implementation Priorities

The highest-value execution order inside this plan is:

1. Type the API config surface and settle repo-accurate file ownership first.
2. Add DTOs, request-context helpers, and the `SessionService` boundary before adding routes.
3. Extend the existing app factory and middleware rather than creating parallel startup or middleware paths.
4. Prove the thin-route boundary first with a fake session service and `POST /chat`.
5. Add SSE and reset behavior before deepening the health/capabilities/debug surfaces.
6. Replace the fake session path with the real walking skeleton only after the route contracts and middleware boundaries are stable.
7. Finish with full backend validation and documentation updates rooted in `backend/`.

This order preserves the intended architecture layering:

```text
config -> app factory -> middleware/dependencies -> routes -> session service
session service -> workflow state / trace store
later -> orchestration runtime, llm gateway, memory gateway, tool gateway, mcp client
```

---

## 7. Completion Standard

This plan should be considered complete when the backend can do all of the following from inside `backend/` without leaking persistence or provider details into route code:

- Build typed API settings from validated config under `backend/config/`.
- Register `/chat`, `/chat/stream`, `/sessions/{session_id}/reset`, `/health`, and `/capabilities` from the backend app rooted in `backend/app/main.py`.
- Keep route handlers thin and delegate chat/reset behavior to `SessionService`.
- Emit stable, explicit request/response DTOs and SSE events.
- Return `X-Trace-Id` and `X-Session-Id` where applicable.
- Enforce request limits, CORS, and safe error behavior through validated config and shared middleware.
- Keep request-boundary telemetry safe and redacted.
- Expose optional debug trace routes only when explicitly enabled and only through bounded redacted read/search behavior.
- Exercise real workflow-state and trace-store dependencies through the stable `SessionService` boundary, which the API phase introduced as a walking skeleton and the later session-service phase deepened into `DefaultSessionService`, without introducing direct route-level store calls.
- Run focused API tests plus the full backend validation gate from `backend/`.
- Hand off cleanly to `docs/backend-session-service-architecture.md` for deeper session lifecycle and orchestration behavior.

The key constraint remains unchanged throughout implementation:

> **All backend API code lives under `backend/`, and the API remains a boundary layer that validates requests, builds safe request context, delegates to services, and returns safe REST/SSE responses without becoming the orchestration or persistence layer itself.**