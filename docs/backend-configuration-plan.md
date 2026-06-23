# Backend Configuration Implementation Plan

**Document:** `backend-configuration-plan.md`  
**Version:** 1.0  
**Source alignment:** `docs/backend-configuration-architecture.md`, `docs/backend-foundation-plan.md`, and `docs/backend-core-contracts-plan.md`  
**Repository rule:** all backend application code and backend runtime configuration assets live under `backend/`

---

## 1. Purpose

This plan converts the configuration architecture into a repo-accurate implementation sequence that can be delivered in small, low-risk phases.

It builds on the completed backend foundation and core contracts work already present under `backend/`, and it keeps the implementation strict about repository boundaries:

- Backend application code belongs in `backend/`.
- Backend source modules belong in `backend/app/`.
- Backend runtime YAML belongs in `backend/config/`.
- Backend tests and config fixtures belong in `backend/tests/`.
- Documentation updates belong in `docs/` and `backend/README.md`.
- No backend configuration code or runtime assets should be placed in the repository root, `frontend/`, or `mcp/`.

---

## 2. Review Outcomes

The architecture document is implementation-ready and internally consistent. It describes the right next slice after foundation and core contracts: make runtime wiring configuration-driven before real gateways, persistence adapters, orchestration, and agent plugins are added.

The review confirms these execution rules:

- Extend the existing configuration package under `backend/app/config/`; do not create a second configuration root.
- Keep the existing runtime-facing contract boundary in `backend/app/contracts/config.py` and `backend/app/contracts/errors.py`.
- Keep fake config implementations in `backend/app/testing/fakes/`; real loader validation belongs in `backend/tests/unit/config/`.
- Store committed runtime YAML under `backend/config/`, not under a repository-root `config/` directory.
- Store configuration fixtures under `backend/tests/fixtures/config/`, not under a repository-root `tests/` directory.

The main implementation concerns to address explicitly during execution are:

1. **Generic architecture paths must be translated to backend-local paths.**  
   In this repository, `config/app.yaml` means `backend/config/app.yaml`, `app/config/` means `backend/app/config/`, and `tests/fixtures/config/` means `backend/tests/fixtures/config/`.

2. **The foundation phase already shipped config-adjacent code that must be evolved in place.**  
   `backend/app/config/settings.py`, `backend/app/config/loader.py`, `backend/app/config/bootstrap.py`, `backend/app/main.py`, `backend/app/foundation/health.py`, and `backend/app/foundation/capabilities.py` already exist. This phase should extend those files rather than replace the startup path with a parallel implementation.

3. **The contract layer already defines the configuration boundary.**  
   Concrete config code should satisfy `ConfigurationView`, `ConfigurationLoader`, and `ConfigurationError` from `backend/app/contracts/`, and it should retire the foundation-only `ConfigLoadError` once structured validation is in place.

4. **The loader contract is async while the current app factory is sync and import-safe.**  
   The implementation must choose one explicit bridge. The recommended approach is to keep `backend/app/main.py:create_app()` synchronous, use FastAPI lifespan or startup initialization to await configuration loading, and construct the final validated container before the app serves requests.

5. **Current environment-variable names are already part of the backend foundation surface.**  
   Add missing settings in `backend/app/config/settings.py`, but preserve compatibility for current variables such as `APP_ENV`, `APP_CONFIG_PATH`, `BACKEND_HOST`, `BACKEND_PORT`, `LOG_LEVEL`, and `LOG_JSON` unless an explicit migration is approved.

6. **Health and capabilities are still placeholder-driven.**  
   This phase should make them configuration-backed without leaking secrets, raw prompts, raw nested config, or full connection details.

---

## 3. Non-Negotiable Boundary Rules

- Treat `backend/` as the Python project root for all configuration work.
- Create or modify backend runtime source only under `backend/app/`.
- Store committed runtime YAML only under `backend/config/`.
- Store config fixtures only under `backend/tests/fixtures/config/`.
- Store config-focused unit tests only under `backend/tests/unit/config/`, while updating existing foundation tests in place under `backend/tests/unit/` where needed.
- Keep documentation-only artifacts under `docs/` and `backend/README.md`.
- Do not place backend configuration code in the repository root, `frontend/`, or `mcp/`.
- Do not add real LLM providers, MCP clients, SQLite stores, ArcadeDB integrations, or `memory_store` adapters in this phase.
- Do not let agents, API routes, or foundation services read `os.environ` or parse YAML directly.
- Do not broaden the configuration contracts unless runtime code truly needs a new contract surface; concrete helpers can stay implementation-local under `backend/app/config/`.

---

## 4. Phase Overview

| Phase | Name | Primary Outcome |
|---|---|---|
| 0 | Configuration Scaffold and Path Alignment | `backend/config/`, `backend/tests/unit/config/`, and `backend/tests/fixtures/config/` become the canonical backend-local locations for runtime config files and config tests. |
| 1 | Settings Expansion and Local Config Baseline | Backend startup settings point at `backend/config/app.yaml` and support deterministic base, override, and data-directory paths. |
| 2 | Loader, Environment Resolution, and Merge Semantics | The backend can read YAML, merge an optional override, resolve `${env:...}` references, and fail cleanly without leaking secrets. |
| 3 | Schema and Cross-Reference Validation | Strict models and config validation reject invalid structure and invalid runtime wiring before the app boots deeper services. |
| 4 | Redaction and Validated Configuration View | Runtime code receives an immutable, read-only configuration view plus reusable secret-safe summaries. |
| 5 | Bootstrap, Container, Health, and Capabilities Integration | The app factory loads validated config through the real backend bootstrap path and exposes safe config-backed health and capability summaries. |
| 6 | Tests, Documentation, and Freeze | The backend configuration slice is fully validated from `backend/`, documented, and ready to hand off to later observability and runtime phases. |

---

## 5. Detailed Implementation Phases

### Phase 0. [DONE] Configuration Scaffold and Path Alignment

**Goal**

Establish the canonical backend-local directories and baseline runtime config assets before deeper loader work begins.

**Files and folders to create**

- [DONE] `backend/config/`
- [DONE] `backend/tests/unit/config/`
- [DONE] `backend/tests/fixtures/config/`
- [DONE] `backend/config/app.yaml`

**Implementation tasks**

- [DONE] Create the backend-local config directory tree instead of relying on the generic paths shown in the architecture examples.
- [DONE] Add a committed minimal `backend/config/app.yaml` that becomes the default runtime config for local backend startup.
- [DONE] Decide up front whether `backend/config/app.local.yaml` remains developer-local and untracked; do not make the backend depend on checked-in machine-specific override files.
- [DONE] Keep all future config references in docs, tests, and code rooted under `backend/`.

**Validation**

- [DONE] Confirm that backend-local config paths resolve the same way whether commands are started from `backend/` or from the repository root.

**Exit criteria**

- [DONE] There is one canonical runtime configuration location under `backend/`.
- [DONE] No backend config assets are planned outside `backend/`.

### Phase 1. [DONE] Settings Expansion and Local Config Baseline

**Goal**

Move from the foundation-phase optional raw-config stub to explicit process-level settings for the configuration phase without breaking backend-local startup.

**Files to modify**

- [DONE] `backend/app/config/settings.py`
- [DONE] `backend/.env.example`
- [DONE] `backend/tests/unit/test_settings.py`

**Implementation tasks**

- [DONE] Change the default base config path so it points at `backend/config/app.yaml` through backend-root-relative resolution.
- [DONE] Add missing process-level settings such as `APP_CONFIG_OVERRIDE_PATH` and `APP_DATA_DIR` in `backend/app/config/settings.py`.
- [DONE] Preserve existing foundation env var compatibility for `APP_ENV`, `APP_CONFIG_PATH`, `BACKEND_HOST`, `BACKEND_PORT`, `LOG_LEVEL`, and `LOG_JSON` unless an explicit migration is approved.
- [DONE] Keep `.env.example` limited to non-secret defaults and local-safe placeholders.
- [DONE] Keep the settings layer limited to process-level behavior such as environment name, config file paths, logging defaults, and local data-directory defaults. Do not move YAML-owned runtime wiring back into settings.

**Validation**

- [DONE] Extend `backend/tests/unit/test_settings.py` with default-path, env-override, and backend-root-relative path-resolution checks.

**Exit criteria**

- [DONE] Settings can identify the base config path, optional override path, environment, and data directory before any YAML is parsed.
- [DONE] Local startup behavior remains deterministic from `backend/`.

### Phase 2. [DONE] Loader, Environment Resolution, and Merge Semantics

**Goal**

Turn the foundation raw loader into a deterministic YAML reader that supports environment references and override merging.

**Files to create**

- [DONE] `backend/app/config/env_resolver.py`
- [DONE] `backend/tests/unit/config/test_env_resolver.py`
- [DONE] `backend/tests/unit/config/test_loader_valid_config.py`
- [DONE] `backend/tests/unit/config/test_loader_invalid_config.py`

**Files to modify**

- [DONE] `backend/app/config/loader.py`

**Implementation tasks**

- [DONE] Replace the foundation-only payload wrapper in `backend/app/config/loader.py` with reusable helpers for reading YAML mappings, merging override mappings, and preparing the structure for schema validation.
- [DONE] Support `${env:VAR_NAME}`, `${env:VAR_NAME:default}`, and `${env:VAR_NAME:}` interpolation inside strings, not only whole-value substitutions.
- [DONE] Keep relative path resolution anchored to `backend/` regardless of the caller working directory.
- [DONE] Standardize loader failures on `ConfigurationError` from `backend/app/contracts/errors.py`.
- [DONE] Keep deep-merge rules deterministic: dictionaries merge recursively, scalars replace scalars, lists replace lists, and schema validation remains responsible for rejecting unknown fields.
- [DONE] Ensure missing required environment variables fail fast and secret-looking values are never echoed back in exception messages.

**Validation**

- [DONE] Load a minimal valid YAML file through `backend/app/config/loader.py`.
- [DONE] Prove required env refs fail cleanly.
- [DONE] Prove optional env defaults resolve correctly.
- [DONE] Prove base-plus-override merging behaves as documented.

**Exit criteria**

- [DONE] Loader inputs are deterministic and secret-safe before schema parsing begins.
- [DONE] Backend-local path handling is consistent across settings, loader helpers, and tests.

### Phase 3. [DONE] Schema and Cross-Reference Validation

**Goal**

Reject invalid configuration structure and invalid runtime wiring before the backend constructs deeper services.

**Files to create**

- [DONE] `backend/app/config/schemas.py`
- [DONE] `backend/app/config/validation.py`
- [DONE] `backend/tests/fixtures/config/valid_minimal.yaml`
- [DONE] `backend/tests/fixtures/config/valid_full.yaml`
- [DONE] `backend/tests/fixtures/config/invalid_missing_active_usecase.yaml`
- [DONE] `backend/tests/fixtures/config/invalid_unknown_strategy.yaml`
- [DONE] `backend/tests/fixtures/config/invalid_unknown_agent.yaml`
- [DONE] `backend/tests/fixtures/config/invalid_unknown_llm_provider.yaml`
- [DONE] `backend/tests/fixtures/config/invalid_unknown_llm_profile.yaml`
- [DONE] `backend/tests/fixtures/config/invalid_fallback_cycle.yaml`
- [DONE] `backend/tests/fixtures/config/invalid_missing_env.yaml`
- [DONE] `backend/tests/fixtures/config/invalid_secret_literal.yaml`
- [DONE] `backend/tests/unit/config/test_cross_reference_validation.py`

**Implementation tasks**

- [DONE] Implement strict Pydantic models in `backend/app/config/schemas.py` for `app`, `features`, `usecases`, `strategies`, `agents`, `llm`, `mcp`, `persistence`, `policy`, `observability`, and `health`.
- [DONE] Use `extra="forbid"` so unknown YAML keys fail rather than being silently ignored.
- [DONE] Validate that the active use case exists and is enabled.
- [DONE] Validate strategy, agent, LLM provider, LLM profile, fallback profile, and policy-profile references before app startup completes.
- [DONE] Validate subset rules such as agent tool allowlists versus use-case tool allowlists where both are configured.
- [DONE] Validate provider-specific structural requirements such as SQLite path presence and required memory adapter config.
- [DONE] Detect LLM fallback cycles explicitly instead of deferring failure to runtime.
- [DONE] Decide and document the minimal acceptable local dummy-secret rule for committed fixtures so real secrets are still rejected without making tests brittle.

**Validation**

- [DONE] Parse `backend/tests/fixtures/config/valid_minimal.yaml` successfully.
- [DONE] Parse `backend/tests/fixtures/config/valid_full.yaml` successfully.
- [DONE] Reject each invalid fixture with a clean `ConfigurationError` or equivalent validation failure surface that can be converted into `ConfigurationError` by the loader.

**Exit criteria**

- [DONE] Invalid wiring fails before service construction.
- [DONE] Unknown config keys and invalid types cannot slip past the configuration boundary.

### Phase 4. [DONE] Redaction and Validated Configuration View

**Goal**

Expose one immutable read-only configuration surface to runtime code and provide a reusable redaction utility for logs, health, and errors.

**Files to create**

- [DONE] `backend/app/config/redaction.py`
- [DONE] `backend/app/config/view.py`
- [DONE] `backend/tests/unit/config/test_redaction.py`
- [DONE] `backend/tests/unit/config/test_config_view.py`

**Files to modify**

- `backend/app/testing/fakes/fake_config.py` only if helper parity improves tests without expanding the contract surface.

**Implementation tasks**

- [DONE] Implement shared sensitive-key matching for terms such as `api_key`, `token`, `secret`, `password`, `credential`, and `authorization`.
- [DONE] Implement recursive redaction for dictionaries, lists, tuples, and nested config sections.
- [DONE] Implement `ValidatedConfigurationView` in `backend/app/config/view.py` so it satisfies the existing `ConfigurationView` protocol.
- [DONE] Freeze loaded config values for read-only runtime access rather than passing mutable nested dictionaries through the application.
- [DONE] Add a concrete `as_redacted_dict()` helper only on the concrete view type if needed for health and logging; do not expand the shared contract unless runtime code truly requires that method.
- [DONE] Ensure `require()` and `section()` raise `ConfigurationError` with path-safe messages.

**Validation**

- [DONE] Prove `get`, `require`, `section`, and immutability behavior in `backend/tests/unit/config/test_config_view.py`.
- [DONE] Prove nested secret redaction in `backend/tests/unit/config/test_redaction.py`.

**Exit criteria**

- [DONE] Runtime modules have one stable read-only config surface.
- [DONE] Safe config summaries can be generated without duplicating redaction logic.

### Phase 5. [DONE] Bootstrap, Container, Health, and Capabilities Integration

**Goal**

Replace the foundation raw-config stub with validated configuration in the real backend bootstrap path.

**Files to modify**

- [DONE] `backend/app/config/bootstrap.py`
- [DONE] `backend/app/config/loader.py`
- [DONE] `backend/app/foundation/container.py`
- [DONE] `backend/app/foundation/health.py`
- [DONE] `backend/app/foundation/capabilities.py`
- [DONE] `backend/app/api/routes_health.py`
- [DONE] `backend/app/api/routes_capabilities.py`
- [DONE] `backend/app/main.py`
- [DONE] `backend/tests/unit/test_app_factory.py`
- [DONE] `backend/tests/unit/test_health.py`
- [DONE] `backend/tests/unit/test_capabilities.py`

**Implementation tasks**

- [DONE] Implement `YamlConfigurationLoader` in `backend/app/config/loader.py` so it satisfies the existing `ConfigurationLoader` contract.
- [DONE] Make `backend/app/config/bootstrap.py` the single backend bootstrap entry point for base YAML loading, optional override loading, env resolution, schema parsing, cross-reference validation, redaction, and view construction.
- [DONE] Reconcile the async loader contract with the current sync `create_app()` shape by using FastAPI lifespan or startup initialization rather than `asyncio.run()` inside import-time code.
- [DONE] Extend `backend/app/foundation/container.py` so the container exposes the validated `ConfigurationView` and a safe config summary instead of the foundation-only raw config payload.
- [DONE] Update `backend/app/foundation/health.py` so configuration health can report safe summary fields such as environment, active use case, profile counts, configured provider names, and persistence-provider names without exposing secrets or raw endpoints.
- [DONE] Update `backend/app/foundation/capabilities.py` so capabilities derive from `features`, enabled use cases, and configured profile availability rather than returning all-false placeholders.
- [DONE] Keep startup failure behavior strict: configuration errors should stop backend startup and remain redacted in logs and error summaries.
- [DONE] Keep `backend/app/main.py` import-safe: no live provider, database, or MCP client initialization should occur at import time.

**Validation**

- [DONE] Update `backend/tests/unit/test_app_factory.py` to cover the final bootstrap flow and any lifespan-driven initialization.
- [DONE] Update `backend/tests/unit/test_health.py` to verify safe config-backed health output without secrets.
- [DONE] Update `backend/tests/unit/test_capabilities.py` to verify config-backed feature exposure.
- [DONE] Confirm importing `backend/app/main.py` remains free of network calls, provider SDK initialization, and database creation.

**Exit criteria**

- [DONE] Backend startup is configuration-backed and fail-fast.
- [DONE] Health and capabilities reflect validated configuration instead of a raw stub.

### Phase 6. [DONE] Tests, Documentation, and Freeze

**Goal**

Close the configuration phase with backend-local validation, updated docs, and a stable handoff boundary for later backend modules.

**Files to modify**

- [DONE] `backend/README.md`

**Implementation tasks**

- [DONE] Update `backend/README.md` with the canonical config file locations under `backend/config/`, override behavior, environment-variable expectations, and backend-local validation commands.
- [DONE] Ensure all documentation and code examples refer to backend runtime paths with the `backend/` prefix.
- [DONE] Record the stable configuration surfaces under `backend/app/config/` and the config test surfaces under `backend/tests/`.
- [DONE] Record the intentionally deferred concerns that remain outside this phase: real LLM gateway adapters, MCP client adapter, SQLite workflow-state and trace stores, `memory_store` integration, policy-engine behavior, and prompt-management details.

**Validation**

- [DONE] From `backend/`, run `./.venv/Scripts/python.exe -m pytest`.
- [DONE] From `backend/`, run `./.venv/Scripts/python.exe -m ruff check .`.
- [DONE] From `backend/`, run `./.venv/Scripts/python.exe -m mypy app`.
- [DONE] From `backend/`, run `./.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000`.

**Exit criteria**

- [DONE] The backend configuration slice is documented as complete.
- [DONE] The backend is ready to hand off to `docs/backend-observability-architecture.md` and later runtime phases without reopening configuration boundaries.

---

## 6. Completion Gate

This plan should be considered complete only when all of the following are true:

- The real backend app loads configuration through `backend/app/config/` and not through a foundation-only raw-config stub.
- The validated runtime config is exposed through the existing configuration contracts in `backend/app/contracts/`.
- Runtime YAML, config fixtures, and config-focused tests all live under `backend/`.
- Health, capabilities, logs, and loader failures remain redacted and do not expose secrets or raw endpoints.
- Backend validation commands pass when run from `backend/`.
- Later backend modules can depend on `ConfigurationView` and small config resolvers rather than raw nested dictionaries or environment-variable lookups.
