# Backend Deployment Implementation Plan

**Document:** `backend-deployment-plan.md`  
**Version:** 1.0  
**Source alignment:** `backend-deployment-architecture.md`, `backend-policy-plan.md`, `backend-orchestration-plan.md`, `backend-tooling-mcp-client-plan.md`, `backend-llm-gateway-plan.md`, `backend-memory-store-adapter-plan.md`, `backend-persistence-plan.md`, `backend-api-plan.md`, `backend-session-service-plan.md`, and the current backend implementation baseline  
**Repository rule:** all backend application code lives under `backend/`

---

## 1. Purpose

This plan converts the backend deployment architecture into a phased implementation sequence that can be delivered in small, low-risk slices.

The plan is intentionally strict about repository boundaries:

- Backend application code belongs in `backend/`.
- Backend source modules belong in `backend/app/`.
- Backend tests belong in `backend/tests/`.
- Backend configuration files belong in `backend/config/`.
- Backend local data files belong in `backend/data/`.
- Backend deployment helpers belong in `backend/app/deployment/`, `backend/scripts/`, or `backend/deploy/`.
- Documentation updates belong in `docs/`.
- No backend runtime, deployment, packaging, or operations code should be placed in the repository root, `frontend/`, or `mcp/`.

For clarity, this document uses filesystem paths such as `backend/app/deployment/startup.py`. Python imports may still use the `app.*` package path because `backend/` is the Python project root.

This phase is not greenfield work. The repository already contains a live backend startup path through `backend/app/main.py`, `backend/app/config/bootstrap.py`, `backend/app/config/settings.py`, and `backend/config/app.yaml`. The implementation plan therefore deepens and operationalizes that existing runtime instead of creating a second deployment surface beside it.

All validation commands in this plan assume execution from `backend/` using `.venv\Scripts\python.exe`.

---

## 2. Review Outcomes

The deployment architecture document is implementation-ready in scope. It is strong on the behaviors that matter for this phase:

- boundary-preserving deployment
- configuration-driven runtime selection
- policy-safe defaults
- backend-owned persistence and observability
- deterministic startup and readiness
- smoke-testable deployment entrypoints
- explicit rollback and operational expectations

The review also surfaced a small set of alignment corrections that must shape implementation:

1. **Several architecture path examples are illustrative and must be translated to the real repo layout.**  
   In this repository, backend config lives under `backend/config/`, backend local state lives under `backend/data/`, backend wrapper scripts should live under `backend/scripts/` or `backend/deploy/`, and the separate MCP codebase folder is `mcp/`, not `mcp_server/`.

2. **The actual backend ASGI import path is `app.main:create_app`, not `backend.app.main:create_app`.**  
   `backend/` is the Python project root, not a Python package. Repo-root examples may use `--app-dir backend`, but the import target should still remain `app.main:create_app`.

3. **Current process settings already resolve key paths relative to `backend/`.**  
   `backend/app/config/settings.py` already treats `APP_CONFIG_PATH`, `APP_CONFIG_OVERRIDE_PATH`, and `APP_DATA_DIR` as backend-root-relative values. Deployment work should extend that contract rather than bypass it with a separate path resolver rooted at the repository root.

4. **Startup composition already exists and should remain the owning deployment seam.**  
   `backend/app/config/bootstrap.py` already assembles policy, persistence, memory, LLM, tooling, orchestration, session service, and health/capabilities. Deployment readiness should layer path validation, startup checks, readiness, packaging, and operational helpers onto that seam rather than creating an alternate composition root.

5. **Current health and capabilities routes should be extended additively.**  
   The backend already exposes `GET /health` and `GET /capabilities`. Liveness and readiness semantics should build on those existing routes and services without breaking current API behavior.

6. **The current runtime state defaults already live under `backend/data/`.**  
   The local baseline currently uses `backend/data/workflow_state.db` and `backend/data/trace.db`, not `data/backend/workflow_state.db` and `data/backend/trace.db`. The implementation plan should preserve that backend-owned default unless an operator intentionally externalizes those paths.

7. **The current host/port environment contract does not match every example in the architecture doc.**  
   The live settings model currently uses `BACKEND_HOST` and `BACKEND_PORT`. Deployment implementation should either keep those names or add compatibility aliases deliberately; it should not silently assume that `APP_HOST` and `APP_PORT` already exist.

---

## 3. Non-Negotiable Boundary Rules

- Treat `backend/` as the Python project root for all deployment work.
- Keep concrete deployment runtime code under `backend/app/deployment/` and existing backend packages under `backend/app/`.
- Keep canonical backend runtime configuration under `backend/config/`.
- Keep backend-owned local runtime data under `backend/data/` by default.
- Keep deployment wrapper scripts and example host assets under `backend/scripts/` or `backend/deploy/`, not the repository root.
- Keep backend tests under `backend/tests/` and choose unique test basenames so Windows pytest collection does not hit import-file mismatches.
- Do not place backend runtime code in `docs/`, `frontend/`, `mcp/`, or the repository root.
- Do not let deployment modules import frontend modules or MCP server implementation code.
- Keep `backend/app/main.py:app = create_app()` import-safe. Path creation, readiness probes, and dependency initialization belong in lifespan startup, not import time.
- Do not bypass `LLMGateway`, `ToolGateway`, `MemoryGateway`, `PolicyService`, `WorkflowStateStore`, or `TraceStore` from deployment helpers.
- Do not introduce source-controlled secrets under `backend/config/`, `backend/deploy/`, or `backend/scripts/`.
- Do not expose MCP endpoints, provider URLs, bearer tokens, API keys, absolute sensitive filesystem paths, raw prompts, raw tool payloads, raw memory records, or stack traces through health, readiness, smoke output, or deployment diagnostics by default.
- Keep frontend deployment, MCP deployment, and backend deployment as separate concerns even when adding local compose or service examples.

---

## 4. Phase Overview

| Phase | Name | Primary Outcome |
|---|---|---|
| 0 | [DONE] Current Deployment Baseline and Repo Alignment | The plan starts from the real `backend/` runtime tree and corrects the architecture document's illustrative path drift. |
| 1 | Canonical Environment Contract and Backend-Rooted Settings | One explicit deployment env/path contract exists and is validated from `backend/`. |
| 2 | [DONE] Runtime Paths and Startup Validation | Startup owns backend-rooted path validation, fail-fast checks, and safe startup summaries. |
| 3 | Health, Readiness, and Safe Diagnostics | Liveness/readiness semantics extend the current health surface without leaking sensitive details. |
| 4 | Local Run, Validation, and Smoke Entry Points | Developers and CI use one tested `backend/`-rooted run path plus deployment validation and smoke commands. |
| 5 | Packaging and Host Deployment Assets | Backend-only container and host deployment assets package the live backend correctly while keeping `frontend/` and `mcp/` separate. |
| 6 | Backup, Restore, Migration, and Rollback | Backend-owned operational data and release rollback steps are explicit and scriptable. |
| 7 | CI/CD Gates, Freeze, and Handoff | Deployment readiness gains a dedicated test surface, release gates, and final backend-rooted documentation. |

---

## 5. Detailed Implementation Phases

### [DONE] Phase 0. Current Deployment Baseline and Repo Alignment

**Goal**

Record the current deployment baseline so the implementation plan extends the real backend tree instead of describing a second, parallel deployment layout.

**Files already present**

- [DONE] `backend/app/main.py`
- [DONE] `backend/app/config/bootstrap.py`
- [DONE] `backend/app/config/settings.py`
- [DONE] `backend/app/foundation/container.py`
- [DONE] `backend/config/app.yaml`
- [DONE] `backend/.env.example`
- [DONE] `backend/README.md`
- [DONE] `backend/data/workflow_state.db`
- [DONE] `backend/data/trace.db`

**Implementation outcomes already in place**

- [DONE] The backend already has an import-safe app factory with lifespan startup.
- [DONE] The backend already loads validated YAML through the existing `backend/app/config/` pipeline.
- [DONE] The backend already composes persistence, memory, LLM, tooling, orchestration, session, policy, health, and capabilities in one startup path.
- [DONE] The backend already owns its default local SQLite files under `backend/data/`.
- [DONE] The backend already exposes health and capability surfaces that deployment work can extend.

**Current limitations that later phases must fix**

- There is no dedicated `backend/app/deployment/` package yet.
- The current settings surface does not yet model all deployment-owned path and profile settings.
- There are no explicit live/ready deployment endpoints or additive readiness semantics yet.
- There is no backend-rooted smoke/backup/restore deployment tooling yet.
- The architecture document includes illustrative repo-root examples that would be wrong if copied literally into this workspace.

**Exit criteria**

- [DONE] The plan starts from the actual backend tree under `backend/` and avoids non-existent repo-root deployment surfaces.

### [DONE] Phase 1. Canonical Environment Contract and Backend-Rooted Settings

**Goal**

Define one canonical deployment environment contract that matches the real backend tree and keeps all path resolution anchored under `backend/`.

**Files to create or update**

- [DONE] `backend/app/config/settings.py`
- [DONE] `backend/app/config/schemas.py`
- [DONE] `backend/app/config/validation.py`
- [DONE] `backend/app/config/view.py`
- [DONE] `backend/app/config/loader.py`
- [DONE] `backend/config/app.yaml`
- [DONE] `backend/.env.example`
- [DONE] `backend/tests/unit/test_settings.py` (repo-specific unique basename; this workspace already has a top-level `test_settings.py` and Windows pytest collection would conflict with a second `tests/unit/config/test_settings.py` file)
- [DONE] `backend/tests/unit/config/test_config_view.py`
- [DONE] `backend/tests/unit/config/test_validation.py`
- [DONE] `backend/tests/fixtures/config/deployment_invalid_profile.yaml`
- [DONE] `backend/tests/fixtures/config/deployment_invalid_path_escape.yaml`

**Implementation tasks**

- [DONE] Declare one canonical deployment env contract rooted under `backend/`, keeping backward compatibility with the current `Settings` model where practical.
- [DONE] Keep `APP_CONFIG_PATH`, `APP_CONFIG_OVERRIDE_PATH`, and `APP_DATA_DIR` backend-relative by default.
- [DONE] Decide whether host and port remain `BACKEND_HOST` and `BACKEND_PORT` or gain additive aliases; document and test the chosen contract explicitly.
- [DONE] Add typed deployment settings for log directory, runtime directory, public base URL, graceful shutdown timeout, profile name, and any metrics or readiness bind settings that are truly process-level concerns.
- [DONE] Keep `backend/config/app.yaml` as the canonical tracked base configuration. If environment-specific tracked examples are needed, place them under `backend/config/`, not the repository root.
- [DONE] Ensure tracked YAML stores secret references or env placeholders only, never raw secret values.
- [DONE] Reject unknown deployment profiles and unsafe or ambiguous path values during startup validation.
- [DONE] Expose deployment and path settings through typed helpers under `backend/app/config/` rather than ad hoc `config.get()` calls scattered across startup code.

**Validation**

- [DONE] `.venv\Scripts\python.exe -m pytest tests/unit/config/test_loader_valid_config.py tests/unit/config/test_config_view.py tests/unit/config/test_validation.py tests/unit/test_settings.py`
- [DONE] `.venv\Scripts\python.exe -m ruff check app/config tests/unit/config/test_loader_valid_config.py tests/unit/config/test_config_view.py tests/unit/config/test_validation.py tests/unit/test_settings.py`
- [DONE] `.venv\Scripts\python.exe -m mypy app/config`

**Exit criteria**

- [DONE] One explicit deployment env contract exists for the backend process.
- [DONE] Backend config, data, log, and runtime paths resolve deterministically from `backend/`.
- [DONE] No tracked file under `backend/config/` contains raw secrets.

### [DONE] Phase 2. Runtime Paths and Startup Validation

**Goal**

Introduce deployment-owned path validation and startup checks without bypassing the existing backend composition root.

**Files to create or update**

- [DONE] `backend/app/deployment/__init__.py`
- [DONE] `backend/app/deployment/paths.py`
- [DONE] `backend/app/deployment/startup.py`
- [DONE] `backend/app/deployment/diagnostics.py`
- [DONE] `backend/app/config/bootstrap.py`
- [DONE] `backend/app/foundation/container.py`
- [DONE] `backend/app/main.py`
- [DONE] `backend/tests/unit/deployment/test_deployment_paths.py`
- [DONE] `backend/tests/unit/deployment/test_deployment_startup_validation.py`
- [DONE] `backend/tests/integration/deployment/test_deployment_startup_fail_fast.py`

**Implementation tasks**

- [DONE] Resolve canonical backend-owned paths for config, data, logs, runtime artifacts, and any explicitly externalized memory-store data path.
- [DONE] Create missing `backend/logs/` and `backend/runtime/` directories automatically only in local or test-safe modes when that behavior is explicitly allowed.
- [DONE] Fail fast in staging or production-like profiles when required directories are missing, unwritable, or unsafe.
- [DONE] Validate that workflow-state and trace paths do not accidentally escape intended runtime ownership through ambiguous relative values.
- [DONE] Centralize deployment startup validation before the app is marked ready: profile validity, config load success, path ownership, safe policy preconditions, and required dependency configuration.
- [DONE] Emit one safe startup summary with booleans, counts, and version labels only. Do not include provider URLs, MCP endpoints, raw config, or absolute sensitive paths.
- [DONE] Keep all filesystem mutation and startup probing inside lifespan startup, never during module import.
- [DONE] Extend the existing `backend/app/config/bootstrap.py` path instead of introducing a second application bootstrap flow.

**Validation**

- [DONE] `.venv\Scripts\python.exe -m pytest tests/unit/deployment/test_deployment_paths.py tests/unit/deployment/test_deployment_startup_validation.py tests/integration/deployment/test_deployment_startup_fail_fast.py`
- [DONE] `.venv\Scripts\python.exe -m ruff check app/deployment app/config/bootstrap.py app/foundation/container.py app/main.py tests/unit/deployment tests/integration/deployment/test_deployment_startup_fail_fast.py`
- [DONE] `.venv\Scripts\python.exe -m mypy app/deployment app/config/bootstrap.py app/foundation/container.py app/main.py`

**Exit criteria**

- [DONE] Startup fails early for invalid deployment profiles, unsafe paths, and missing required runtime prerequisites.
- [DONE] Local and test startup can bootstrap backend-owned runtime directories safely.
- [DONE] Deployment validation extends the existing `create_app()` lifecycle instead of creating a second startup path.

### Phase 3. Health, Readiness, and Safe Diagnostics

**Goal**

Separate liveness and readiness semantics while preserving the current backend health surface and response safety guarantees.

**Files to create or update**

- `backend/app/deployment/readiness.py`
- `backend/app/deployment/diagnostics.py`
- `backend/app/api/routes_health.py`
- `backend/app/foundation/health.py`
- `backend/app/observability/health.py`
- `backend/tests/unit/deployment/test_deployment_readiness.py`
- `backend/tests/unit/api/test_health_route.py`
- `backend/tests/integration/deployment/test_deployment_health_readiness.py`

**Implementation tasks**

- Keep `GET /health` backward-compatible and decide whether live/ready semantics are exposed as additive routes such as `GET /health/live` and `GET /health/ready`, or as explicit safe subsections within the current health payload.
- Reuse existing config, policy, persistence, memory, LLM, tooling, and orchestration health methods rather than inventing parallel health logic in deployment code.
- Mark required versus optional readiness dependencies explicitly by profile and configured use-case coverage instead of treating every configured integration as equally mandatory.
- Keep health and readiness payloads limited to safe status labels, booleans, counts, and version markers.
- Do not expose provider URLs, MCP endpoints, raw policy documents, raw trace state, session data, filesystem internals, or stack traces through health or readiness.
- Add a safe deployment diagnostics summary only if it is gated, redacted, and clearly separate from public health routes.

**Validation**

- `.venv\Scripts\python.exe -m pytest tests/unit/deployment/test_deployment_readiness.py tests/unit/api/test_health_route.py tests/integration/deployment/test_deployment_health_readiness.py`
- `.venv\Scripts\python.exe -m ruff check app/deployment app/api/routes_health.py app/foundation/health.py app/observability/health.py tests/unit/deployment tests/integration/deployment/test_deployment_health_readiness.py`
- `.venv\Scripts\python.exe -m mypy app/deployment app/api/routes_health.py app/foundation/health.py app/observability/health.py`

**Exit criteria**

- Liveness and readiness semantics are explicit and safe.
- The public health surface remains backward-compatible for existing backend consumers.
- Deployment diagnostics stay redacted and policy-safe.

### Phase 4. Local Run, Validation, and Smoke Entry Points

**Goal**

Provide one reproducible backend-rooted run path plus deployment validation and smoke tooling that exercise the real application entrypoint.

**Files to create or update**

- `backend/app/deployment/smoke.py`
- `backend/app/deployment/validate_config.py`
- `backend/scripts/run_backend.ps1`
- `backend/scripts/smoke_backend.ps1`
- `backend/README.md`
- `backend/.env.example`
- `backend/tests/unit/deployment/test_deployment_smoke.py`
- `backend/tests/integration/deployment/test_deployment_smoke_cli.py`

**Implementation tasks**

- Document and test the canonical ASGI startup command from `backend/`: `.venv\Scripts\python.exe -m uvicorn app.main:create_app --factory --host ... --port ...`.
- If wrapper scripts are added, keep them under `backend/scripts/` and have them delegate to the same backend-rooted Python and Uvicorn commands rather than reimplementing startup logic.
- Provide a deployment validation CLI that reuses the existing typed config loader and validator instead of adding a second parser.
- Provide a smoke CLI that checks `GET /health`, `GET /capabilities`, non-streaming chat, and streaming chat when enabled.
- Keep smoke inputs synthetic and side-effect-free so CI can run them against fake or local test providers.
- Document repo-root invocation only as a thin convenience wrapper that uses `--app-dir backend app.main:create_app`, not `backend.app.main:create_app`.

**Validation**

- `.venv\Scripts\python.exe -m pytest tests/unit/deployment/test_deployment_smoke.py tests/integration/deployment/test_deployment_smoke_cli.py`
- `.venv\Scripts\python.exe -m ruff check app/deployment tests/unit/deployment/test_deployment_smoke.py tests/integration/deployment/test_deployment_smoke_cli.py`
- `.venv\Scripts\python.exe -m mypy app/deployment`

**Exit criteria**

- Developers and CI have one tested backend-rooted run command.
- Deployment validation and smoke tooling execute the same code path used by the live backend.
- Documentation no longer references repo-root `scripts/` or `backend.app` import paths for backend startup.

### Phase 5. Packaging and Host Deployment Assets

**Goal**

Package the backend as a standalone deployable unit without absorbing `frontend/` or `mcp/` responsibilities.

**Files to create or update**

- `backend/Dockerfile`
- `backend/.dockerignore`
- `backend/deploy/docker-compose.local.yaml`
- `backend/deploy/systemd/backend.service.example`
- `backend/README.md`

**Implementation tasks**

- Package backend runtime assets from `backend/` only, using `app.main:create_app` as the ASGI target.
- Mount or externalize `backend/config/`, `backend/data/`, `backend/logs/`, and `backend/runtime/` explicitly when packaging for containers or single-host deployment.
- Keep frontend and MCP deployment as separate services, and use the real repo folder name `mcp/` in local examples rather than `mcp_server/`.
- Avoid baking secrets or environment-specific private config into the image.
- Preserve the current single-worker default and document the conditions required before multi-worker scaling is allowed.
- Keep packaging assets backend-owned and colocated with the backend project instead of adding repo-root deployment artifacts.

**Validation**

- Build the container image when Docker is available.
- Verify documented host examples still target `app.main:create_app` and backend-rooted paths only.
- Run the deployment smoke flow against the packaged backend when practical.

**Exit criteria**

- There is one backend-only packaging story for local container and single-host deployment.
- All examples use `backend/`-rooted paths and the live backend import target.
- `frontend/` and `mcp/` remain separate deployment concerns.

### Phase 6. Backup, Restore, Migration, and Rollback

**Goal**

Turn backend-owned state, config, and schema changes into explicit operational workflows.

**Files to create or update**

- `backend/app/deployment/operations.py`
- `backend/scripts/backup_backend.ps1`
- `backend/scripts/restore_backend.ps1`
- `backend/scripts/migrate_backend.ps1`
- `backend/README.md`
- `backend/tests/unit/deployment/test_deployment_operations.py`

**Implementation tasks**

- Define backend-owned backup targets clearly: tracked config examples under `backend/config/`, active runtime config paths, `backend/data/workflow_state.db*`, `backend/data/trace.db*`, and configured memory-store data when it is backend-managed.
- Implement or document migration entrypoints that call backend-owned persistence migration code rather than triggering schema work from normal request paths.
- Codify restore and rollback order around the current composition root: stop backend, restore config, restore memory if needed, restore workflow state, restore trace, restart, run readiness, run smoke.
- Keep operational output redacted. Do not print secrets, raw provider data, or overly detailed absolute path internals in normal script output.
- Document how incompatible schema changes are promoted and rolled back before enabling traffic.

**Validation**

- `.venv\Scripts\python.exe -m pytest tests/unit/deployment/test_deployment_operations.py`
- `.venv\Scripts\python.exe -m ruff check app/deployment tests/unit/deployment/test_deployment_operations.py`
- `.venv\Scripts\python.exe -m mypy app/deployment`

**Exit criteria**

- Release and rollback steps are explicit for backend-owned state.
- Backup, restore, and migration assets live under `backend/` only.
- Operational workflows call backend-owned adapters and migration seams rather than raw implementation details.

### Phase 7. CI/CD Gates, Freeze, and Handoff

**Goal**

Close deployment readiness with dedicated tests, release gates, and stable backend-rooted operations documentation.

**Files to create or update**

- `backend/tests/unit/deployment/`
- `backend/tests/integration/deployment/`
- `backend/README.md`
- `docs/backend-deployment-plan.md`

**Implementation tasks**

- Add dedicated deployment unit tests for env parsing, path resolution, readiness safety, startup summaries, and smoke configuration.
- Add dedicated deployment integration tests for startup success and failure, readiness behavior, smoke flow, and graceful shutdown.
- Gate deployment promotion on the full backend quality bar plus focused deployment validation and smoke commands from `backend/`.
- Record a final release checklist covering config validation, policy safety, startup validation, health/readiness checks, smoke pass, and rollback asset availability.
- Update `backend/README.md` with the frozen deployment entrypoints and operational expectations.
- Treat future infrastructure, secrets-manager, proxy, and cloud-IaC work as follow-on operations phases that build on this deployment seam rather than moving runtime code out of `backend/`.

**Validation**

- `.venv\Scripts\python.exe -m pytest`
- `.venv\Scripts\python.exe -m ruff check .`
- `.venv\Scripts\python.exe -m mypy app`
- `.venv\Scripts\python.exe -m app.deployment.validate_config --config config/app.yaml`
- `.venv\Scripts\python.exe -m app.deployment.smoke --base-url http://127.0.0.1:8000`

**Exit criteria**

- Deployment readiness is testable and documented from `backend/`.
- The backend deployment surface is frozen around backend-owned paths, commands, and operational seams.
- Future infrastructure-specific work can build on this phase without reopening the backend module boundaries.

---

## 6. Final Acceptance Criteria

The deployment phase is complete when all of the following are true:

- Every backend deployment example, command, script path, and runtime directory reference is rooted under `backend/`.
- The canonical backend runtime entrypoint remains `app.main:create_app`.
- Deployment validation, readiness, and smoke tooling execute against the same composition root used by the live backend.
- Health, readiness, and diagnostics remain redacted and policy-safe.
- Backend packaging assets do not absorb frontend or MCP implementation responsibilities.
- Backup, restore, migration, and rollback expectations are documented and backend-owned.
- The full backend quality gate and focused deployment checks pass from `backend/`.

---

## 7. Handoff Notes

This plan closes the final backend roadmap phase by operationalizing the runtime that already exists under `backend/`.

If follow-on work is needed after this phase, it should target one of these areas without reopening core backend boundaries:

- infrastructure-as-code and environment provisioning
- reverse proxy and TLS hardening
- secrets manager integration
- centralized logging and metrics export
- production traffic management and scaling
- formal operations runbooks and release automation