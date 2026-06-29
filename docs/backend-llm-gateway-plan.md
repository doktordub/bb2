# Backend LLM Gateway Implementation Plan

**Document:** `backend-llm-gateway-plan.md`  
**Version:** 1.0  
**Source alignment:** `backend-llm-gateway-architecture.md`, `backend-session-service-plan.md`, the current backend implementation baseline, and the repository rule that all backend code lives under `backend/`  
**Repository rule:** all backend application code lives under `backend/`

---

## 1. Purpose

This plan converts the LLM gateway architecture into a phased implementation sequence that can be delivered in small, low-risk slices.

The plan is intentionally strict about repository boundaries:

- Backend application code belongs in `backend/`.
- Backend source modules belong in `backend/app/`.
- Backend tests belong in `backend/tests/`.
- Backend configuration files belong in `backend/config/`.
- Backend local data files belong in `backend/data/`.
- Documentation updates belong in `docs/`.
- No backend runtime, adapter, orchestration, session, or provider code should be placed in the repository root, `frontend/`, or `mcp/`.

For clarity, this document uses filesystem paths such as `backend/app/llm/gateway.py`. Python imports may still use the `app.*` package path because `backend/` is the Python project root.

---

## 2. Review Outcomes

The LLM gateway architecture document is implementation-ready. It is strong on the key boundaries that matter for this phase:

- `API -> SessionService -> OrchestrationRuntime -> LLMGateway -> ProviderAdapter` stays intact.
- Provider access stays behind one backend-owned boundary.
- Logical profile resolution is configuration-driven.
- Streaming, redaction, retries, fallbacks, health, and trace correlation are clearly scoped.
- Memory, tooling/MCP, and workflow-state persistence remain outside the LLM gateway boundary.

The review also confirms that this phase is not greenfield work. The repository already contains meaningful LLM-related groundwork under `backend/` that should be deepened rather than replaced:

- `backend/app/contracts/llm.py` already defines a provider-neutral `LLMGateway` protocol plus minimal `LLMRequest`, `LLMResponse`, and streaming delta models.
- `backend/app/contracts/context.py` already gives `OrchestrationContext` an `llm` capability slot.
- `backend/app/testing/fakes/fake_llm.py` and `backend/app/testing/fakes/fake_agent.py` already exercise the provider-neutral contract surface.
- `backend/app/config/schemas.py`, `backend/app/config/validation.py`, and `backend/config/app.yaml` already define a minimal `llm` configuration section with providers, profiles, and fallback-cycle validation.
- `backend/app/api/errors.py` already reserves an LLM failure boundary through `LLMGatewayError`, even though it is still too coarse for the target architecture.
- `backend/app/foundation/health.py` and `backend/app/foundation/capabilities.py` already expose placeholder LLM readiness based on configuration presence.
- `backend/app/orchestration/core.py` already exists as a narrow runtime boundary, but it is still an echo implementation and does not build an `OrchestrationContext` around a real LLM gateway.
- `backend/app/config/bootstrap.py` already owns backend composition-root wiring during lifespan startup, but it does not yet build an LLM gateway, provider registry, or concrete policy runtime.

The review identifies the following implementation concerns that should shape the plan:

1. **The current public LLM contract is thinner than the target architecture.**  
   `backend/app/contracts/llm.py` currently exposes only `complete` and `stream`, minimal request and response models, and a `LLMStreamDelta` shape. The architecture requires richer request metadata, structured-output support, normalized streaming lifecycle events, health, and profile-listing support.

2. **The current configuration shape is only a starting point.**  
   The backend already has `llm.providers` and `llm.profiles`, but it does not yet expose a typed `LLMSettings` runtime view, provider `enabled` flags, default timeout and retry settings, profile capability flags, profile allowlists, or safe health and capabilities metadata.

3. **There is no concrete `backend/app/llm/` runtime package yet.**  
   The repo has contracts and fakes, but it does not yet have a provider registry, profile resolver, default gateway, provider adapters, retry helpers, streaming normalization, or LLM-specific redaction helpers.

4. **There is no concrete policy runtime yet.**  
   `backend/app/contracts/policy.py` and `backend/app/testing/fakes/fake_policy.py` exist, but there is no real runtime implementation under `backend/app/` that a gateway can call during normal startup. This phase needs the smallest real policy implementation required for LLM profile checks without pre-empting the later policy-hardening document.

5. **The current composition root still wires an echo orchestrator.**  
   `backend/app/config/bootstrap.py` currently builds `EchoOrchestrationRuntime()` and never constructs an LLM registry or gateway. The container also has no dedicated `llm_gateway` or `policy_service` member yet.

6. **Health and capabilities are placeholders only.**  
   The current health payload reports `llm` as configured or not configured, but it does not report safe provider or profile readiness. The current capability payload exposes only a coarse `llm_profiles` boolean.

7. **API error mapping is too coarse for the target architecture.**  
   The current API layer maps `LLMGatewayError` to a generic 503 response. The gateway architecture requires normalized error subclasses and more precise status and code mapping.

8. **Runtime dependency placement needs attention.**  
   `backend/pyproject.toml` currently places `httpx` in the `dev` extra only. If the OpenAI-compatible adapter uses `httpx` at runtime, that dependency must move into `project.dependencies` or another non-dev installation path that production startup can rely on.

9. **One package-layout recommendation should be adapted to the existing repo.**  
   The architecture document recommends LLM-facing models and errors under `backend/app/llm/`. The existing repo already treats provider-neutral request, response, and gateway interfaces as stable public contracts under `backend/app/contracts/`. The plan below keeps the public contract surface there and adds runtime implementation details under `backend/app/llm/` instead of moving established contract modules solely to mirror the architecture example.

---

## 3. Non-Negotiable Boundary Rules

- Treat `backend/` as the Python project root for all LLM gateway work.
- Keep public provider-neutral contracts under `backend/app/contracts/`.
- Create concrete LLM runtime implementation modules only under `backend/app/llm/`.
- Keep backend configuration parsing and typed runtime views under `backend/app/config/` and canonical YAML under `backend/config/`.
- Keep backend tests under `backend/tests/`.
- Keep provider fixtures under `backend/tests/fixtures/config/`.
- Keep documentation-only artifacts under `docs/`.
- Do not place backend LLM runtime code in the repository root, `frontend/`, or `mcp/`.
- Do not let `backend/app/api/` call provider SDKs, raw HTTP clients for model calls, or `LLMGateway` directly.
- Do not let `backend/app/session/` call provider SDKs or `LLMGateway` directly for normal chat behavior.
- Do not let `backend/app/agents/` or `backend/app/orchestration/` import provider SDKs or construct provider-specific HTTP requests.
- Do not let `backend/app/llm/` execute MCP tools, search memory, write memory, or persist workflow state directly.
- Do not let any module outside `backend/app/persistence/` import `sqlite3`, `aiosqlite`, or other concrete database clients.
- Keep `backend/app/main.py:app = create_app()` import-safe. Provider clients, health pings, and network I/O must stay in lifespan startup or per-call runtime code.
- Do not log or trace raw prompts, raw completions, provider credentials, authorization headers, cookies, JWTs, connection strings, or raw provider response bodies by default.
- Keep `SessionService` lifecycle-focused. It should continue to delegate model work only through `OrchestrationRuntime`.
- Reuse the existing `backend/app/orchestration/core.py` module unless a file rename is done atomically. This phase should prefer the lower-churn path of deepening the current orchestration runtime module instead of renaming it just to match the architecture document.

---

## 4. Phase Overview

| Phase | Name | Primary Outcome |
|---|---|---|
| 0 | [DONE] Current LLM Baseline and Architecture Fit | The repo already has contract, config, and fake-gateway groundwork rooted under `backend/`, and the plan now extends that baseline instead of treating the phase as greenfield work. |
| 1 | [DONE] LLM Configuration and Typed Settings Alignment | The `llm` config section becomes a typed, validated runtime surface that supports defaults, provider enablement, profile capabilities, allowlists, and safe runtime accessors. |
| 2 | [DONE] Public Contract Deepening | The public provider-neutral gateway contract under `backend/app/contracts/` grows to cover structured output, richer usage metadata, streaming lifecycle events, health, and profile listing. |
| 3 | [DONE] LLM Runtime Package and Resolver Foundations | A concrete `backend/app/llm/` package exists with internal models, normalized LLM errors, provider protocols, registry logic, redaction helpers, health models, and profile resolution. |
| 4 | [DONE] Default Gateway Core, Policy Hook, and Retry/Fallback | The default gateway can resolve, authorize, trace, redact, retry, fallback, complete, and stream through fake adapters without external services. |
| 5 | [DONE] OpenAI-Compatible Adapter and Optional Provider Scaffolds | The backend can call a local or custom OpenAI-compatible `/v1/chat/completions` endpoint through a provider adapter, while optional provider adapters remain isolated and non-breaking. |
| 6 | [DONE] Orchestration and Composition-Root Wiring | Startup constructs the real LLM gateway and injects it into a real orchestration runtime path without breaking the API or session boundaries. |
| 7 | [DONE] Health, Capabilities, and API Error Mapping | `/health`, `/capabilities`, startup diagnostics, and API error handling expose safe LLM readiness and normalized failure behavior. |
| 8 | [DONE] Fixtures, Quality Gates, Freeze, and Handoff | Focused unit and integration coverage, optional local-runtime smoke tests, README freeze notes, and full backend validation close the phase and hand off to the next architecture document. |

---

## 5. Detailed Implementation Phases

### [DONE] Phase 0. Current LLM Baseline and Architecture Fit

**Goal**

Record the current LLM-related backend baseline so implementation extends the existing repo instead of re-describing a greenfield slice.

**Files already present**

- [DONE] `backend/app/contracts/llm.py`
- [DONE] `backend/app/contracts/context.py`
- [DONE] `backend/app/contracts/errors.py`
- [DONE] `backend/app/contracts/policy.py`
- [DONE] `backend/app/testing/fakes/fake_llm.py`
- [DONE] `backend/app/testing/fakes/fake_agent.py`
- [DONE] `backend/app/testing/fakes/fake_policy.py`
- [DONE] `backend/app/config/schemas.py`
- [DONE] `backend/app/config/validation.py`
- [DONE] `backend/app/config/bootstrap.py`
- [DONE] `backend/app/foundation/container.py`
- [DONE] `backend/app/foundation/health.py`
- [DONE] `backend/app/foundation/capabilities.py`
- [DONE] `backend/app/orchestration/core.py`
- [DONE] `backend/app/api/errors.py`
- [DONE] `backend/config/app.yaml`

**Implementation outcomes already in place**

- [DONE] The backend already has a provider-neutral gateway contract.
- [DONE] The orchestration context already reserves an `llm` slot.
- [DONE] The backend already validates minimal provider/profile references and fallback cycles during config load.
- [DONE] The repo already has deterministic fake LLM and fake policy test doubles.
- [DONE] Health and capabilities already reserve an LLM section, even though both are still placeholders.

**Current limitations that later phases must fix**

- The public LLM request, response, and stream models are too thin for the architecture.
- There is no concrete `backend/app/llm/` runtime package.
- There is no real policy runtime implementation under `backend/app/`.
- The composition root does not construct a gateway or provider registry.
- The orchestration runtime is still an echo implementation.
- Health, capabilities, and API error mapping are still placeholder-level for LLM behavior.

**Exit criteria**

- [DONE] The implementation plan starts from the current `backend/` baseline and extends it rather than replacing it.

### [DONE] Phase 1. LLM Configuration and Typed Settings Alignment

**Goal**

Expand the existing `llm` config section into a typed, validated runtime surface that can drive profile resolution, provider construction, retries, safe health, and capabilities.

**Files to create or update**

- `backend/app/config/schemas.py`
- `backend/app/config/validation.py`
- `backend/app/config/view.py`
- `backend/config/app.yaml`
- `backend/tests/unit/config/test_config_view.py`
- `backend/tests/unit/config/test_validation.py`
- `backend/tests/fixtures/config/llm_fake_basic.yaml`
- `backend/tests/fixtures/config/llm_fake_streaming.yaml`
- `backend/tests/fixtures/config/llm_fake_fallback.yaml`
- `backend/tests/fixtures/config/llm_disabled_provider.yaml`
- `backend/tests/fixtures/config/llm_structured_output.yaml`
- `backend/tests/fixtures/config/llm_trace_capture_disabled.yaml`

**Implementation tasks**

- [DONE] Add a typed `LLMSettings` runtime view in `backend/app/config/view.py` with nested settings such as:
  - `LLMDefaultsSettings`
  - `LLMProviderSettings`
  - `LLMProfileSettings`
  - optional `LLMConcurrencySettings` only if the implementation needs real guards in this phase
- [DONE] Add a `get_llm_settings(config)` accessor so runtime code stops reading raw nested config keys directly.
- [DONE] Deepen provider config to include fields such as:
  - `enabled`
  - `timeout_seconds`
  - `stream_timeout_seconds`
  - `headers` or `default_headers`
  - provider-specific safe `extra` config
- [DONE] Deepen profile config to include fields such as:
  - `temperature`
  - `top_p`
  - `max_output_tokens`
  - `max_input_tokens`
  - `max_total_tokens`
  - `supports_streaming`
  - `supports_json_schema`
  - `supports_tool_calling`
  - `allowed_for.usecases`
  - `allowed_for.agents`
  - `allowed_for.strategies`
  - `fallback_profiles`
- [DONE] Add defaults for:
  - default logical profile
  - per-call timeout
  - per-stream timeout
  - max retries
  - prompt and completion trace-capture flags
- [DONE] Normalize the current config shape so defaults live in a coherent runtime section. The preferred end state is `llm.defaults.profile` plus sibling default settings. A temporary compatibility alias from the current `llm.default_profile` key remains in parsing only while runtime code and canonical fixtures use `llm.defaults.profile`.
- [DONE] Validate at config-load time:
  - default profile exists
  - provider type is known
  - enabled profiles reference known providers
  - fallback cycles are rejected
  - fallback targets exist
  - timeout and retry values are bounded
  - capability flags are internally consistent
  - cloud-provider credentials are present when enabled
  - provider URLs and endpoints are well-formed
  - allowlist references are structurally valid
- [DONE] Keep secrets environment-resolved and redacted in config views, logs, and health output.

**Validation**

- [DONE] Add and pass focused config-view and validation tests for the expanded LLM section.
- [DONE] Run `.venv\Scripts\python.exe -m pytest tests/unit/config/test_config_view.py tests/unit/config/test_validation.py` from `backend/`.
- [DONE] Run `.venv\Scripts\python.exe -m ruff check app/config tests/unit/config/test_config_view.py tests/unit/config/test_validation.py` from `backend/`.
- [DONE] Run `.venv\Scripts\python.exe -m mypy app/config` from `backend/`.

**Exit criteria**

- [DONE] LLM runtime code can consume a typed `LLMSettings` object instead of raw config sections.
- [DONE] Safe provider and profile readiness can be derived from validated config alone.
- [DONE] Invalid LLM config fails fast during backend startup.

### [DONE] Phase 2. Public Contract Deepening

**Goal**

Deepen the public provider-neutral LLM contract under `backend/app/contracts/` without breaking the repo's established boundary between public contracts and runtime implementation.

**Files to create or update**

- `backend/app/contracts/llm.py`
- `backend/app/contracts/errors.py`
- `backend/app/contracts/__init__.py`
- `backend/app/contracts/trace.py`
- `backend/app/testing/fakes/fake_llm.py`
- `backend/app/testing/fakes/__init__.py`
- `backend/tests/unit/contracts/test_llm_contracts.py`
- `backend/tests/unit/contracts/test_fake_gateways.py`

**Implementation tasks**

- [DONE] Expand `backend/app/contracts/llm.py` so the public gateway protocol covers:
  - `complete(...)`
  - `stream(...)`
  - `health()`
  - `list_profiles()`
- [DONE] Add or deepen provider-neutral public models such as:
  - `LLMContentPart`
  - `LLMResponseFormat`
  - `LLMTokenUsage`
  - `LLMResponse`
  - `LLMStreamEvent`
  - `LLMHealthResult`
  - `LLMProfileSummary`
- [DONE] Replace the current `LLMStreamDelta`-only contract with a lifecycle-aware stream-event model that can represent `started`, `delta`, `metadata`, `completed`, and `error` without leaking provider objects. A compatibility `LLMStreamDelta` shim remains exported for older delta-only test call sites.
- [DONE] Preserve backward compatibility for existing fake and test call sites where practical. The `LLMRequest.component` field remains a safe observability field and the request model normalizes legacy `max_tokens` and dict-style `response_format` inputs.
- [DONE] Keep the public error surface stable by preserving `LLMGatewayError` as the API-facing base class in `backend/app/contracts/errors.py` while leaving room for richer normalized subclasses in the runtime package.
- [DONE] Add new LLM trace-event constants that the runtime layer will use later, such as:
  - `llm_profile_resolved`
  - `llm_policy_checked`
  - `llm_stream_started`
  - `llm_stream_completed`
  - `llm_stream_cancelled`
  - `llm_retry_scheduled`
  - `llm_provider_health_checked`

**Validation**

- [DONE] Add and pass focused contract tests for request and response models, stream events, fake gateway behavior, and list-profile or health surface shape.
- [DONE] Run `.venv\Scripts\python.exe -m pytest tests/unit/contracts/test_llm_contracts.py tests/unit/contracts/test_fake_gateways.py` from `backend/`.
- [DONE] Run `.venv\Scripts\python.exe -m ruff check app/contracts app/testing/fakes/fake_llm.py tests/unit/contracts` from `backend/`.
- [DONE] Run `.venv\Scripts\python.exe -m mypy app/contracts app/testing/fakes/fake_llm.py` from `backend/`.

**Exit criteria**

- [DONE] The public LLM contract exposes the models and methods required by the architecture.
- [DONE] No provider-specific request or response types leak into the public contract.
- [DONE] Existing fake-driven tests still have a stable provider-neutral boundary to exercise.

### [DONE] Phase 3. LLM Runtime Package and Resolver Foundations

**Goal**

Create the concrete `backend/app/llm/` runtime package and the internal types needed to implement provider adapters and gateway behavior cleanly.

**Files to create or update**

- `backend/app/llm/__init__.py`
- `backend/app/llm/models.py`
- `backend/app/llm/errors.py`
- `backend/app/llm/provider_base.py`
- `backend/app/llm/provider_registry.py`
- `backend/app/llm/profile_resolver.py`
- `backend/app/llm/streaming.py`
- `backend/app/llm/redaction.py`
- `backend/app/llm/health.py`
- `backend/app/llm/providers/__init__.py`
- `backend/app/llm/providers/fake.py`
- `backend/tests/unit/llm/test_profile_resolver.py`
- `backend/tests/unit/llm/test_provider_registry.py`
- `backend/tests/unit/llm/test_fake_provider.py`

**Implementation tasks**

- [DONE] Add gateway-internal models that should not be exposed directly to agents or API code, such as:
  - `ResolvedLLMRequest`
  - `ProviderLLMResponse`
  - `ProviderLLMStreamEvent`
  - `ProviderCapabilities`
  - `ProviderHealthSummary`
  - `ProfileHealthSummary`
- [DONE] Add a normalized runtime error hierarchy in `backend/app/llm/errors.py`, including errors such as:
  - `LLMProfileResolutionError`
  - `LLMPolicyDeniedError`
  - `LLMProviderUnavailableError`
  - `LLMProviderTimeoutError`
  - `LLMRateLimitError`
  - `LLMAuthenticationError`
  - `LLMBadRequestError`
  - `LLMUnsupportedCapabilityError`
  - `LLMContextLengthError`
  - `LLMMalformedResponseError`
  - `LLMStreamingError`
  - `LLMCancelledError`
- [DONE] Add `LLMProviderAdapter` and `ProviderRegistry` with registration rules for unique provider names and disabled-provider handling.
- [DONE] Add a deterministic fake provider adapter under `backend/app/llm/providers/fake.py` so the default gateway can be developed and tested without external services.
- [DONE] Implement `LLMProfileResolver` using the architecture's resolution order:
  1. explicit requested profile
  2. agent-specific configured profile
  3. strategy-specific configured profile
  4. use-case orchestrator or default profile
  5. global default profile
- [DONE] Validate streaming, structured-output, provider-enabled, and allowlist requirements during resolution.
- [DONE] Keep provider-specific request shaping out of the resolver. It should return resolved settings, not wire payloads.

**Validation**

- [DONE] Add and pass focused unit tests for profile resolution, fallback-chain validation, provider registration, and fake provider behavior.
- [DONE] Run `.venv\Scripts\python.exe -m pytest tests/unit/llm/test_profile_resolver.py tests/unit/llm/test_provider_registry.py tests/unit/llm/test_fake_provider.py` from `backend/`.
- [DONE] Run `.venv\Scripts\python.exe -m ruff check app/llm tests/unit/llm` from `backend/`.
- [DONE] Run `.venv\Scripts\python.exe -m mypy app/llm` from `backend/`.

**Exit criteria**

- [DONE] `backend/app/llm/` exists as the owning runtime package for gateway internals.
- [DONE] Profile resolution is deterministic, testable, and configuration-driven.
- [DONE] The gateway can target a fake provider adapter without any external dependency.

### [DONE] Phase 4. Default Gateway Core, Policy Hook, and Retry/Fallback

**Goal**

Implement the default gateway so it can resolve profiles, call policy, trace safely, normalize responses, and handle retries or fallbacks through fake adapters.

**Files to create or update**

- `backend/app/llm/gateway.py`
- `backend/app/llm/retry.py`
- `backend/app/llm/token_budget.py`
- `backend/app/llm/errors.py`
- `backend/app/llm/redaction.py`
- `backend/app/llm/streaming.py`
- `backend/app/policy/__init__.py`
- `backend/app/policy/service.py`
- `backend/app/policy/models.py`
- `backend/app/testing/fakes/fake_policy.py`
- `backend/tests/unit/llm/test_gateway_complete.py`
- `backend/tests/unit/llm/test_gateway_stream.py`
- `backend/tests/unit/llm/test_gateway_policy.py`
- `backend/tests/unit/llm/test_gateway_redaction.py`
- `backend/tests/unit/llm/test_retry_fallback.py`

**Implementation tasks**

- [DONE] Implement a concrete `DefaultLLMGateway` with:
  - `complete(...)`
  - `stream(...)`
  - `health()`
  - `list_profiles()`
- [DONE] Add request-size checks and output-limit enforcement in a way that does not silently rewrite prompts or mutate upstream state.
- [DONE] Normalize gateway behavior around:
  - timeout selection
  - retryable vs non-retryable error classification
  - fallback selection
  - fallback trace events
  - streaming lifecycle milestones
  - safe usage metadata
- [DONE] Emit trace and metric signals through existing observability infrastructure without recording raw prompt or completion text by default.
- [DONE] Introduce the smallest real policy implementation needed for this phase under `backend/app/policy/`. It should:
  - implement the existing `PolicyService` contract
  - evaluate `llm.complete` and `llm.stream`
  - enforce deny-unknown-profile and profile allowlist rules
  - stay intentionally narrow so broader policy hardening can remain in the later policy phase
- [DONE] Re-check policy on fallback profiles before execution.
- [DONE] Keep session-save ownership outside the gateway. The gateway may cancel or fail a stream, but `SessionService` remains responsible for workflow-state finalization decisions.

**Validation**

- [DONE] Add and pass focused unit tests for complete, stream, retry, fallback, policy denial, prompt-redaction defaults, and structured-output capability failure.
- [DONE] Run `.venv\Scripts\python.exe -m pytest tests/unit/llm/test_gateway_complete.py tests/unit/llm/test_gateway_stream.py tests/unit/llm/test_gateway_policy.py tests/unit/llm/test_gateway_redaction.py tests/unit/llm/test_retry_fallback.py` from `backend/`.
- [DONE] Run `.venv\Scripts\python.exe -m ruff check app/llm app/policy tests/unit/llm` from `backend/`.
- [DONE] Run `.venv\Scripts\python.exe -m mypy app/llm app/policy` from `backend/`.

**Exit criteria**

- [DONE] The default gateway can execute fake non-streaming and streaming calls.
- [DONE] Policy denial blocks provider execution.
- [DONE] Retry and fallback behavior are explicit, bounded, and traceable.
- [DONE] Raw prompts and completions are not logged or traced by default.

### [DONE] Phase 5. OpenAI-Compatible Adapter and Optional Provider Scaffolds

**Goal**

Add the first real provider adapter for local or custom OpenAI-compatible runtimes, and isolate optional adapters so they do not destabilize the main backend path.

**Files to create or update**

- `backend/app/llm/providers/openai_compatible.py`
- `backend/app/llm/providers/openai.py`
- `backend/app/llm/providers/google.py`
- `backend/app/llm/providers/custom_http.py`
- `backend/app/llm/providers/__init__.py`
- `backend/pyproject.toml`
- `backend/tests/unit/llm/test_openai_compatible_adapter.py`
- `backend/tests/unit/llm/test_openai_compatible_streaming.py`
- `backend/tests/unit/llm/test_optional_provider_imports.py`

**Implementation tasks**

- [DONE] Implement the OpenAI-compatible adapter as the primary V1 real provider. It now:
  - [DONE] builds endpoint URLs from configured `base_url`
  - [DONE] maps provider-neutral messages into OpenAI-compatible message bodies
  - [DONE] supports both non-streaming and streaming calls
  - [DONE] normalizes finish reasons, token usage, and provider errors
  - [DONE] keeps auth-header construction inside the adapter
- [DONE] Move `httpx` into `backend/pyproject.toml` runtime dependencies so production startup can rely on the HTTP client path.
- [DONE] Keep optional provider adapters behind isolated modules and optional dependency boundaries. Missing `openai` or Google SDK dependencies do not break fake-provider, config, or local OpenAI-compatible tests.
- [DONE] Keep `custom_http` explicit so it requires configuration rather than guessing provider behavior.
- [DONE] Keep adapter modules from leaking provider JSON or SDK response objects back into the public contract.

**Validation**

- [DONE] Add and pass focused unit tests for request mapping, streaming chunk normalization, timeout mapping, and optional dependency isolation.
- [DONE] Run `.venv\Scripts\python.exe -m pytest tests/unit/llm/test_openai_compatible_adapter.py tests/unit/llm/test_openai_compatible_streaming.py tests/unit/llm/test_optional_provider_imports.py` from `backend/`.
- [DONE] Run `.venv\Scripts\python.exe -m ruff check app/llm/providers tests/unit/llm` from `backend/`.
- [DONE] Run `.venv\Scripts\python.exe -m mypy app/llm/providers` from `backend/`.

**Exit criteria**

- [DONE] The backend can call a configured local or custom OpenAI-compatible provider through the gateway.
- [DONE] Optional provider adapters remain isolated and non-breaking when their dependencies are absent.
- [DONE] Provider raw responses do not leak upward.

### [DONE] Phase 6. Orchestration and Composition-Root Wiring

**Goal**

Wire the real gateway into backend startup and into a real orchestration path without breaking the API or session boundaries.

**Files to create or update**

- `backend/app/llm/factory.py`
- `backend/app/config/bootstrap.py`
- `backend/app/foundation/container.py`
- `backend/app/orchestration/core.py`
- `backend/app/testing/fakes/fake_orchestration_runtime.py`
- `backend/app/testing/fakes/fake_agent.py`
- `backend/tests/fixtures/config/api_with_real_sqlite_stores_fake_llm.yaml`
- `backend/tests/unit/test_app_factory.py`
- `backend/tests/unit/session/test_session_handle_chat.py`
- `backend/tests/unit/session/test_session_stream_chat.py`
- `backend/tests/integration/test_startup_llm.py`
- `backend/tests/integration/test_api_walking_skeleton.py`

**Implementation tasks**

- [DONE] Add an `app/llm/factory.py` helper that builds:
  - [DONE] provider registry
  - [DONE] concrete policy service
  - [DONE] profile resolver
  - [DONE] default gateway
- [DONE] Extend the composition root so `backend/app/config/bootstrap.py` constructs the LLM stack during lifespan startup.
- [DONE] Add `llm_gateway` and `policy_service` to `backend/app/foundation/container.py` to improve testability and future orchestration composition.
- [DONE] Deepen `backend/app/orchestration/core.py` from echo-only behavior into a still-small runtime that can:
  - [DONE] build an `OrchestrationContext`
  - [DONE] inject the real `LLMGateway`
  - [DONE] call a direct or fake agent through the provider-neutral boundary
  - [DONE] keep tool and memory execution outside the LLM gateway itself
- [DONE] Preserve the boundary that `SessionService` still talks only to `OrchestrationRuntime`, not to `LLMGateway`.
- [DONE] Keep this phase intentionally smaller than the future orchestration document. The gateway path is now proven without implementing the full multi-strategy runtime.

**Validation**

- [DONE] Add and pass focused startup, orchestration, and session-flow tests that prove API and session layers can exercise the real gateway path through fakes.
- [DONE] Run `.venv\Scripts\python.exe -m pytest tests/unit/test_app_factory.py tests/unit/session/test_session_handle_chat.py tests/unit/session/test_session_stream_chat.py tests/integration/test_startup_llm.py tests/integration/test_api_walking_skeleton.py` from `backend/`.
- [DONE] Run `.venv\Scripts\python.exe -m ruff check app/config/bootstrap.py app/foundation/container.py app/orchestration app/llm app/testing/fakes tests/unit/session tests/integration/test_startup_llm.py` from `backend/`.
- [DONE] Run `.venv\Scripts\python.exe -m mypy app/config/bootstrap.py app/foundation/container.py app/orchestration app/llm` from `backend/`.

**Exit criteria**

- [DONE] Startup constructs a real LLM gateway under `backend/`.
- [DONE] A real orchestration path can invoke the gateway without any direct API or session dependency on provider code.
- [DONE] API and session boundaries remain unchanged from the caller's perspective.

### [DONE] Phase 7. Health, Capabilities, and API Error Mapping

**Goal**

Replace LLM placeholders in health and capabilities with safe readiness output, and map normalized LLM errors into stable API responses.

**Files to create or update**

- [DONE] `backend/app/foundation/health.py`
- [DONE] `backend/app/foundation/capabilities.py`
- [DONE] `backend/app/api/errors.py`
- [DONE] `backend/app/api/routes_capabilities.py`
- [DONE] `backend/tests/unit/test_health.py`
- [DONE] `backend/tests/unit/test_capabilities.py`
- [DONE] `backend/tests/unit/api/test_error_mapping.py`
- [DONE] `backend/tests/unit/api/test_capabilities_route.py`
- [DONE] `backend/tests/unit/api/test_health_route.py`
- [DONE] `backend/tests/integration/test_api_health_with_real_stores.py`

**Implementation tasks**

- [DONE] Replace the current placeholder `llm` health check with safe provider and profile readiness summaries built from the real gateway or LLM health service.
- [DONE] Expose only frontend-safe capability fields such as:
  - `enabled`
  - `default_profile`
  - `streaming_supported`
  - `structured_output_supported`
  - safe logical profile names only if the product actually wants them exposed
- [DONE] Update API error mapping so normalized LLM runtime errors produce stable response codes and statuses such as:
  - unknown profile or unsupported capability -> 400
  - policy denied -> 403
  - provider unavailable or rate limited -> 503
  - provider timeout -> 504
- [DONE] Keep credentials, headers, tokens, and sensitive base URLs out of health, capabilities, and API error responses.
- [DONE] Emit a redacted startup summary for configured providers, profiles, and default profile only.

**Validation**

- [DONE] Add and pass focused tests for health payload shape, capability safety, and normalized API error mapping.
- [DONE] Run `.venv\Scripts\python.exe -m pytest tests/unit/test_health.py tests/unit/test_capabilities.py tests/unit/api/test_error_mapping.py tests/unit/api/test_capabilities_route.py tests/unit/api/test_health_route.py tests/integration/test_api_health_with_real_stores.py` from `backend/`.
- [DONE] Run `.venv\Scripts\python.exe -m ruff check app/foundation app/api/errors.py app/api/routes_capabilities.py tests/unit/test_health.py tests/unit/test_capabilities.py tests/unit/api` from `backend/`.
- [DONE] Run `.venv\Scripts\python.exe -m mypy app/foundation app/api/errors.py app/api/routes_capabilities.py` from `backend/`.

**Exit criteria**

- [DONE] `/health` reports safe LLM readiness instead of a placeholder boolean.
- [DONE] `/capabilities` exposes only safe logical-profile and feature metadata.
- [DONE] API error handling distinguishes policy, timeout, configuration, and provider failures cleanly.

### [DONE] Phase 8. Fixtures, Quality Gates, Freeze, and Handoff

**Goal**

Complete the test matrix, isolate optional local-runtime tests from CI, freeze the LLM boundary, and hand off cleanly to the next backend architecture slice.

**Files to create or update**

- [DONE] `backend/tests/fixtures/config/llm_openai_compatible_local.yaml`
- [DONE] `backend/tests/fixtures/config/llm_policy_denied.yaml`
- [DONE] `backend/tests/fixtures/config/llm_unknown_profile.yaml`
- [DONE] `backend/tests/fixtures/config/llm_trace_capture_enabled_local_only.yaml`
- [DONE] `backend/tests/integration/llm/test_gateway_fake_complete.py`
- [DONE] `backend/tests/integration/llm/test_gateway_fake_stream.py`
- [DONE] `backend/tests/integration/llm/test_gateway_fallback.py`
- [DONE] `backend/tests/integration/llm/test_gateway_trace_events.py`
- [DONE] `backend/tests/integration/llm/test_gateway_policy_denied.py`
- [DONE] `backend/tests/integration/llm/test_orchestration_uses_llm_profiles.py`
- [DONE] `backend/tests/integration/llm/test_local_openai_compatible_smoke.py`
- [DONE] `backend/README.md`
- [DONE] `docs/backend-llm-gateway-plan.md`

**Implementation tasks**

- [DONE] Add the fixture matrix described by the architecture so config, gateway, and startup tests can cover fake, fallback, disabled-provider, structured-output, and trace-capture scenarios.
- [DONE] Add end-to-end integration tests that prove:
  - gateway startup with fake providers
  - non-streaming calls through fake providers
  - streaming calls through fake providers
  - fallback behavior on fake failures
  - trace-event emission
  - orchestration profile routing
  - API and session boundaries remain unchanged
- [DONE] Add an optional local-runtime smoke test against a configured OpenAI-compatible endpoint. Mark it so CI does not depend on a private local server.
- [DONE] Update `backend/README.md` with:
  - the frozen LLM gateway boundary
  - runtime dependency notes
  - config ownership under `backend/config/`
  - test entry points under `backend/tests/`
  - deferred work for memory, tooling/MCP, richer orchestration, and later policy hardening
- [DONE] When phases 1 through 8 are complete, update this plan document to mark completed phases `[DONE]` and record the validated command set.

**Validation**

- [DONE] Run the focused new integration suite from `backend/`.
- [DONE] Run `.venv\Scripts\python.exe -m pytest` from `backend/`.
- [DONE] Run `.venv\Scripts\python.exe -m ruff check .` from `backend/`.
- [DONE] Run `.venv\Scripts\python.exe -m mypy app` from `backend/`.

**Exit criteria**

- [DONE] Fake-provider tests run without external services.
- [DONE] Optional local-runtime smoke tests are isolated from CI.
- [DONE] The backend has a stable, documented LLM gateway boundary rooted entirely under `backend/`.
- [DONE] The phase is ready to hand off to `docs/backend-memory-store-adapter-architecture.md`.

---

## 6. Cross-Phase Execution Notes

- Prefer additive changes over large renames. The repo already uses `backend/app/contracts/llm.py` and `backend/app/orchestration/core.py`; keep those stable unless a rename can be completed atomically in the same phase.
- Keep the LLM phase focused on the gateway boundary. Do not use this phase to implement full memory retrieval, MCP tooling, or the later multi-strategy orchestration design.
- If prompt or completion capture is ever enabled for local debugging, guard it behind explicit config and fixture coverage, and keep it disabled by default.
- Keep local-provider and fake-provider paths first-class. They are the cheapest validation surfaces for this backend.
- Treat safe redaction and safe health output as non-negotiable deliverables, not follow-up polish.

---

## 7. Final Acceptance Criteria

This implementation plan should be considered complete when all phases above have shipped and the backend satisfies the architecture's acceptance bar:

- `LLMGateway` provides provider-neutral `complete`, `stream`, `health`, and `list_profiles` methods.
- Agents and orchestration code use logical profiles only.
- API routes and `SessionService` do not call providers or `LLMGateway` directly.
- Provider and model selection are configuration-driven.
- Local OpenAI-compatible runtimes are supported through configuration.
- Provider SDK or HTTP response objects do not leak into contracts, session results, API responses, workflow state, or traces.
- LLM calls are trace-correlated and safe by default.
- Raw prompts, raw completions, and credentials are not logged or traced by default.
- Health, capabilities, and API error responses expose only safe LLM metadata.
- Unknown profiles, disabled providers, policy denial, timeouts, and malformed responses map to stable backend errors.
- Retry and fallback behavior are bounded, policy-checked, and traceable.
- All code for the phase lives under `backend/`, and the backend is ready for the next document: `backend-memory-store-adapter-architecture.md`.