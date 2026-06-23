# Backend Foundation Implementation Plan

**Document:** `backend-foundation-plan.md`  
**Version:** 1.0  
**Source alignment:** `backend-foundation-architecture.md`  
**Repository rule:** all backend application code lives under `backend/`

---

## 1. Purpose

This plan converts the backend foundation architecture into an implementation sequence that can be executed in small, low-risk phases.

The plan is intentionally strict about repository boundaries:

- Backend application code belongs in `backend/`.
- Backend source modules belong in `backend/app/`.
- Backend tests belong in `backend/tests/`.
- Documentation updates belong in `docs/`.
- No backend runtime code should be placed in the repository root, `frontend/`, or `mcp/`.

---

## 2. Review Outcomes

The architecture document is implementation-ready and internally consistent. It already provides the right first-slice constraints for the backend foundation:

- application factory first
- composition root before deeper modules
- shallow health and capabilities endpoints only
- structured logging and trace IDs early
- no provider adapters, persistence adapters, agent plugins, or orchestration runtime in this phase

The main implementation concerns to address explicitly during execution are:

1. **Path handling must be deterministic from `backend/`.**
	`.env` loading and `APP_CONFIG_PATH` resolution should not depend on whether commands are run from the repository root or from `backend/`.

2. **`app = create_app()` must remain import-safe.**
	Importing `app.main` cannot require live MCP, LLM, memory, SQLite, or external config services.

3. **Placeholder health checks must remain honest.**
	Future integrations should report `not_checked` or `not_configured`, not fake success.

4. **Repository naming must follow the actual workspace.**
	The architecture document uses `mcp_server/` as an illustrative layout, but this repository currently uses `mcp/`. This plan keeps the real repository boundary and only enforces the important rule: MCP implementation stays outside `backend/`.

---

## 3. Non-Negotiable Boundary Rules

- Treat `backend/` as the Python project root for backend foundation work.
- Create backend source files only under `backend/app/`.
- Create backend test files only under `backend/tests/`.
- Keep packaging and developer entry files at `backend/pyproject.toml`, `backend/README.md`, and `backend/.env.example`.
- Do not place backend implementation code in `docs/`, `frontend/`, `mcp/`, or the repository root.
- Do not add concrete LLM, MCP client, memory, SQLite, or agent implementations during the foundation phase.
- Do not create deep future module trees unless a concrete file is needed now.
- Treat `backend/.venv/` and `backend/dist/` as local or generated artifacts, not as the backend source tree.

---

## 4. Phase Overview

| Phase | Name | Primary Outcome |
|---|---|---|
| 0 | Repository Alignment and Skeleton | `backend/` becomes the canonical Python project root with the minimum file and folder structure. |
| 1 | Settings and Config Stub | Safe settings loading and raw config loading exist without external dependencies. |
| 2 | Composition Root and App Factory | `create_app()` returns a bootable FastAPI app with a foundation container on app state. |
| 3 | Observability and Error Plumbing | Structured logging, trace ID middleware, and safe API error responses are wired in. |
| 4 | Foundation Services and Routes | `/health` and `/capabilities` are implemented with honest placeholder status reporting. |
| 5 | Tests and Quality Gates | Unit tests, linting, and type checks validate the foundation end to end. |
| 6 | Foundation Freeze and Handoff | The backend foundation is documented as complete and ready for core contract work. |

---

## 5. Detailed Implementation Phases

### [DONE] Phase 0. Repository Alignment and Skeleton

**Goal**

Create the minimum backend project shape inside `backend/` and make that folder the only source of truth for backend foundation code.

**Files and folders to create**

- [DONE] `backend/pyproject.toml`
- [DONE] `backend/README.md`
- [DONE] `backend/.env.example`
- [DONE] `backend/app/__init__.py`
- [DONE] `backend/app/api/__init__.py`
- [DONE] `backend/app/config/__init__.py`
- [DONE] `backend/app/observability/__init__.py`
- [DONE] `backend/app/foundation/__init__.py`
- [DONE] `backend/tests/unit/`
- [DONE] `backend/tests/integration/.gitkeep`
- [DONE] `backend/tests/fixtures/.gitkeep`

**Implementation tasks**

- [DONE] Add the Python package metadata and baseline dependencies described in the architecture document.
- [DONE] Keep the initial module tree intentionally small; do not create placeholder folders for future orchestration or provider work.
- [DONE] Add backend README instructions that assume commands are run from `backend/`.
- [DONE] Add `.env.example` entries that reflect backend-local execution.
- [DONE] Make it clear that `backend/dist/` and `backend/.venv/` are not the application source tree.

**Validation**

- [DONE] From `backend/`, install the project with `pip install -e ".[dev]"`.
- [DONE] Confirm the package layout is importable once `app/main.py` exists later in Phase 2.

**Exit criteria**

- [DONE] The backend foundation has a real Python project root under `backend/`.
- [DONE] No backend implementation files have been placed outside `backend/`.

### [DONE] Phase 1. Settings and Config Stub

**Goal**

Provide safe, deterministic configuration loading that supports local startup and tests without pulling in any external system.

**Files to create**

- [DONE] `backend/app/config/settings.py`
- [DONE] `backend/app/config/loader.py`

**Implementation tasks**

- [DONE] Implement the initial `Settings` model and `load_settings()` helper.
- [DONE] Keep settings limited to application, server, config, logging, docs, and future external placeholders.
- [DONE] Implement the raw YAML loader stub with mapping validation only.
- [DONE] Decide and document one path-resolution rule for relative paths.
  Recommended approach: resolve `.env` and any relative `APP_CONFIG_PATH` against `backend/`, not the current shell working directory.
- [DONE] Ensure missing optional config does not break startup in foundation mode.
- [DONE] If strict config validation is needed later, gate it behind an explicit setting rather than making it the default foundation behavior.

**Validation**

- [DONE] Add and pass `test_settings_defaults`.
- [DONE] Add and pass `test_settings_env_override`.
- [DONE] Add and pass `test_missing_config_allowed_in_foundation_mode`.

**Exit criteria**

- [DONE] Settings load with safe local defaults.
- [DONE] Environment overrides work.
- [DONE] Startup remains possible without live MCP, LLM, memory, or SQLite dependencies.

### [DONE] Phase 2. Composition Root and App Factory

**Goal**

Make backend startup deterministic through a composition root and a testable application factory.

**Files to create**

- [DONE] `backend/app/foundation/container.py`
- [DONE] `backend/app/config/bootstrap.py`
- [DONE] `backend/app/main.py`

**Implementation tasks**

- [DONE] Define the lightweight `FoundationContainer` dataclass.
- [DONE] Implement `build_container(settings)` to assemble only foundation concerns: settings, raw config, health registry, and capabilities service.
- [DONE] Implement `create_app(settings: Settings | None = None) -> FastAPI`.
- [DONE] Attach the container to `app.state.container`.
- [DONE] Register middleware, routes, and exception handlers from the app factory.
- [DONE] Keep the module-level `app = create_app()` safe to import in tests and in `uvicorn app.main:app`.
- [DONE] Avoid all network calls, provider SDK initialization, and database creation during import.

**Validation**

- [DONE] Add and pass `test_create_app`.
- [DONE] Run a direct import check such as `python -c "from app.main import create_app; create_app()"` from `backend/`.

**Exit criteria**

- [DONE] `create_app()` can be imported and executed in isolation.
- [DONE] The backend app boots without external service dependencies.

### [DONE] Phase 3. Observability and Error Plumbing

**Goal**

Introduce the minimum logging, request tracing, and API error behavior needed before deeper modules are added.

**Files to create**

- [DONE] `backend/app/observability/logging.py`
- [DONE] `backend/app/observability/middleware.py`
- [DONE] `backend/app/observability/models.py`
- [DONE] `backend/app/api/errors.py`

**Implementation tasks**

- [DONE] Implement idempotent logging configuration so repeated imports or test app creation do not stack duplicate handlers.
- [DONE] Support human-readable local logs and JSON logs through settings.
- [DONE] Add trace ID middleware that:
  - [DONE] accepts `x-trace-id` when supplied
  - [DONE] generates a new trace ID when absent
  - [DONE] stores the trace ID on request state
  - [DONE] returns `x-trace-id` on the response
- [DONE] Define the minimal API error response shape with stable error codes.
- [DONE] Ensure known errors include trace IDs when available and unknown errors map to `INTERNAL_ERROR`.
- [DONE] Keep logs and error bodies free of secrets, connection strings, raw provider payloads, and stack traces in normal responses.

**Validation**

- [DONE] Add and pass `test_trace_id_header`.
- [DONE] Run a local request through the test client and confirm `x-trace-id` is present.

**Exit criteria**

- [DONE] Every request gets a trace ID.
- [DONE] Logging is initialized early and safely.
- [DONE] Error responses have a stable foundation shape.

### [DONE] Phase 4. Foundation Services and Routes

**Goal**

Implement the foundation-only service layer and the two allowed API routes.

**Files to create**

- [DONE] `backend/app/foundation/health.py`
- [DONE] `backend/app/foundation/capabilities.py`
- [DONE] `backend/app/api/routes_health.py`
- [DONE] `backend/app/api/routes_capabilities.py`

**Implementation tasks**

- [DONE] Implement a shallow `HealthRegistry` with async-compatible checks.
- [DONE] Report foundation checks for settings, config, and logging.
- [DONE] Report future integrations as placeholders only:
  - [DONE] `mcp`
  - [DONE] `llm`
  - [DONE] `memory`
  - [DONE] `workflow_state`
  - [DONE] `trace`
- [DONE] Use the status semantics from the architecture document: `ok`, `degraded`, `failed`, `not_configured`, and `not_checked`.
- [DONE] Implement `CapabilitiesService` returning only foundation-safe feature flags.
- [DONE] Register only `GET /health` and `GET /capabilities` in this phase.
- [DONE] Do not add `POST /chat`, streaming, session reset, or history routes yet.

**Validation**

- [DONE] Add and pass `test_health_route`.
- [DONE] Add and pass `test_capabilities_route`.
- [DONE] Verify health responses do not expose secrets or raw environment values.

**Exit criteria**

- [DONE] `GET /health` returns a safe shallow response.
- [DONE] `GET /capabilities` returns explicit foundation feature flags.
- [DONE] No route imports provider SDKs, database clients, `memory_store`, or MCP clients.

### [DONE] Phase 5. Tests and Quality Gates

**Goal**

Make the backend foundation reproducible and safe to extend by enforcing unit tests and baseline static checks.

**Files to create**

- [DONE] `backend/tests/unit/test_settings.py`
- [DONE] `backend/tests/unit/test_app_factory.py`
- [DONE] `backend/tests/unit/test_health.py`
- [DONE] `backend/tests/unit/test_capabilities.py`

**Implementation tasks**

- [DONE] Cover the minimum test set defined by the architecture document.
- [DONE] Keep tests focused on the foundation slice and avoid introducing external dependency fixtures.
- [DONE] Add any additional small test needed to cover trace ID behavior if it is not already asserted in the route tests.
- [DONE] Verify the README local workflow matches the actual backend commands.
- [DONE] Run lint and type checks only against the backend project.

**Validation**

- [DONE] From `backend/`, run `pytest`.
- [DONE] From `backend/`, run `ruff check .`.
- [DONE] From `backend/`, run `mypy app`.

**Exit criteria**

- [DONE] The backend foundation is startable, testable, and statically checked.
- [DONE] The documented commands work from `backend/`.

### [DONE] Phase 6. Foundation Freeze and Handoff

**Goal**

Close the foundation slice cleanly so the next backend phase can build on stable contracts instead of revisiting startup concerns.

**Implementation tasks**

- [DONE] Confirm the acceptance criteria from the architecture document have been met.
- [DONE] Record any intentional deferrals, especially around MCP, LLM, memory, SQLite, auth, streaming, and orchestration.
- [DONE] Keep the public foundation surfaces stable:
  - [DONE] `create_app()`
  - [DONE] `FoundationContainer`
  - [DONE] `/health`
  - [DONE] `/capabilities`
  - [DONE] settings loader
- [DONE] Prepare the next design step for `backend-core-contracts-architecture.md`.

**Validation**

- [DONE] Run the full backend foundation check one final time from `backend/`:
  - [DONE] `pytest`
  - [DONE] `ruff check .`
  - [DONE] `mypy app`
  - [DONE] `uvicorn app.main:app --host 127.0.0.1 --port 8000`

**Exit criteria**

- [DONE] The backend foundation is complete and ready for the core contracts phase.

---

## 6. Recommended Delivery Slices

To keep changes reviewable, the phases above should be delivered in small pull-request-sized slices:

1. **Skeleton slice**
	`pyproject.toml`, README, `.env.example`, package directories, and test directories.

2. **Config slice**
	`settings.py`, `loader.py`, and settings tests.

3. **Bootstrap slice**
	`container.py`, `bootstrap.py`, and `main.py` with app factory tests.

4. **Observability slice**
	logging, middleware, error handling, and trace ID tests.

5. **Foundation route slice**
	health service, capabilities service, routes, and endpoint tests.

6. **Quality slice**
	final cleanup, linting, type checking, README verification, and acceptance review.

---

## 7. Validation Matrix

All validation for backend foundation work should be run from `backend/`.

| Check | Command | Purpose |
|---|---|---|
| Editable install | `pip install -e ".[dev]"` | Confirms the backend package metadata and dependencies are usable. |
| Unit tests | `pytest` | Verifies settings, app factory, health, capabilities, and trace behavior. |
| Lint | `ruff check .` | Enforces foundation code quality. |
| Type check | `mypy app` | Validates the backend source tree only. |
| Local startup | `uvicorn app.main:app --host 127.0.0.1 --port 8000` | Confirms the backend starts without external integrations. |

---

## 8. Done Definition

The implementation plan is complete when the delivered backend foundation satisfies all of the following:

- backend source exists only under `backend/`
- the backend starts through `uvicorn app.main:app`
- `create_app()` is importable and testable
- `GET /health` returns a safe shallow status response
- `GET /capabilities` returns explicit feature flags
- settings load from environment variables and `.env`
- structured logging is initialized
- each request gets an `x-trace-id`
- unit tests pass from `backend/`
- no concrete LLM, MCP, memory, SQLite, or agent implementation is required for startup
- no backend route imports provider SDKs, database clients, `memory_store`, or MCP clients

---

## 9. Next Step After This Plan

Once the foundation slice is complete, the next architecture and implementation target should be the backend core contracts phase, starting with:

- `RequestContext`
- `OrchestrationContext`
- `OrchestrationResult`
- protocol interfaces for gateways and stores
- fake implementations for unit tests

That next phase should build on the `backend/` foundation created here, not bypass it.
