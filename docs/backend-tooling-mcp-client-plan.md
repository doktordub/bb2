# Backend Tooling and MCP Client Implementation Plan

**Document:** `backend-tooling-mcp-client-plan.md`  
**Version:** 1.0  
**Source alignment:** `backend-tooling-mcp-client-architecture.md`, `backend-llm-gateway-plan.md`, `backend-memory-store-adapter-plan.md`, the current backend implementation baseline under `backend/`, and the repository rule that all backend application code lives under `backend/`  
**Repository rule:** all backend application code lives under `backend/`

---

## 1. Purpose

This plan converts the tooling and MCP client architecture into a phased implementation sequence that matches the current repository and keeps all backend runtime code inside `backend/`.

The plan is intentionally strict about repository boundaries:

- Backend application code belongs in `backend/`.
- Backend source modules belong in `backend/app/`.
- Backend tests belong in `backend/tests/`.
- Backend configuration files belong in `backend/config/`.
- Backend local data files belong in `backend/data/`.
- Documentation updates belong in `docs/`.
- No backend runtime, adapter, policy, orchestration, or MCP-client code should be placed in the repository root, `frontend/`, or the top-level `mcp/` folder.

For clarity, this document uses filesystem paths such as `backend/app/tools/gateway.py`. Python imports may still use the `app.*` package path because `backend/` is the Python project root.

---

## 2. Review Outcomes

The architecture document is implementation-ready. It is strong on the boundary that matters most for this phase:

- external tools must stay behind one backend-owned `ToolGateway`
- MCP protocol details must stay behind one backend-owned `MCPClientAdapter`
- API and session layers must remain thin
- orchestration, strategies, and agents must stay provider-neutral
- tool execution must be policy-checked, trace-correlated, bounded, and redacted by default
- V1 must stay on one configured MCP endpoint

The review also confirms that this phase is not greenfield work. The repository already contains a shallow tooling baseline under `backend/` that should be deepened rather than replaced:

- `backend/app/contracts/tools.py` already defines a thin provider-neutral tool surface through `ToolSpec`, `ToolCallRequest`, `ToolResult`, and `ToolGateway`.
- `backend/app/contracts/context.py` already gives `OrchestrationContext` a `tools` capability slot.
- `backend/app/testing/fakes/fake_tools.py` already provides a deterministic fake tool gateway for contract and higher-level tests.
- `backend/app/orchestration/core.py` already injects a `ToolGateway` into `DirectAgentOrchestrationRuntime`, but defaults to `_DisabledToolGateway()` and never builds a real tool runtime.
- `backend/app/config/schemas.py` and `backend/app/config/validation.py` already model per-use-case tool toggles plus a minimal top-level `mcp.main` config.
- `backend/app/config/settings.py` already exposes `MCP_MAIN_URL`, but that field is only a shallow bootstrap hook and should not become a second source of truth for tooling runtime behavior.
- `backend/app/policy/service.py` already understands `deny_unknown_tools`, but only at a coarse policy-profile level.
- `backend/app/observability/events.py` already reserves MCP-oriented event names such as `mcp_tools_listed` and `mcp_call_started`.
- `backend/app/foundation/health.py`, `backend/app/foundation/capabilities.py`, and `backend/app/api/errors.py` already reserve MCP/tool placeholders, but they are still configuration-level stubs.
- `backend/config/app.yaml` already contains a single `mcp.main.url` entry, which is the right V1 shape to preserve as the one external MCP endpoint.

The review identifies the following implementation concerns that should shape the plan:

1. **The current public tool contract is much thinner than the target architecture.**  
   `backend/app/contracts/tools.py` currently exposes only list and call operations, with minimal request, result, and tool-description models. The architecture requires richer scope, discovery, streaming, health, capabilities, safe summaries, and normalized error behavior.

2. **There is no concrete runtime package under `backend/app/tools/` yet.**  
   The repo has public contracts and a fake gateway, but it does not yet have a registry, discovery service, schema validator, result normalizer, MCP adapter, transport, auth provider, or concrete `DefaultToolGateway` implementation.

3. **The typed configuration view has no tooling or MCP runtime settings yet.**  
   `backend/app/config/view.py` already exposes typed settings for API, session, LLM, memory, observability, and health, but it has no typed tooling surface that runtime code can consume.

4. **The architecture's package recommendations need to be adapted to the existing repo.**  
   Public provider-neutral tool contracts should remain under `backend/app/contracts/`, and `backend/app/orchestration/core.py` should remain the orchestration entry point. This phase should deepen those existing files instead of renaming modules just to match the architecture's illustrative layout.

5. **Configuration should extend the current repo shape rather than fork it.**  
   The repo already has top-level `mcp:` configuration plus `usecases.*.tools.allowed_tools`, `agents.*.allowed_tools`, and `policy.profiles.*.deny_unknown_tools`. The plan should add a canonical top-level `tooling:` section for defaults, registry, discovery, and per-tool behavior while keeping top-level `mcp:` as the canonical single-endpoint connection section.

6. **There is no real tool registry, discovery, or schema-validation surface yet.**  
   The backend currently has no allowlisted logical registry, no discovered-schema merge behavior, no argument bounds, no secret-like argument detection, and no normalized tool-result shaping.

7. **The current policy runtime is too coarse for the target tool boundary.**  
   `backend/app/policy/service.py` can deny unknown tools in principle, but it does not yet understand tool safety levels, tool-specific approval flags, stream-vs-sync execution, or allowlist checks tied to logical tool definitions.

8. **The current composition root does not build or expose a real tool gateway.**  
   `backend/app/config/bootstrap.py` constructs LLM, memory, persistence, and session services, but it never builds a tooling runtime, injects a real tool gateway into orchestration, or stores that gateway on `FoundationContainer`.

9. **Health, capabilities, and API error mapping are still placeholder-level for tooling.**  
   The current health output treats MCP as a configured/not-configured flag, the capability output exposes only a coarse `mcp_tools` boolean, and the API error layer maps all tool failures to a generic 503.

10. **Transport, authentication, retry, and cancellation behavior are not implemented.**  
    The architecture calls for safe auth modes, timeout handling, retry classification, cancellation, and optional streaming support, but the repo currently has none of those concrete backend-owned runtime pieces.

The plan below makes these repo-specific decisions:

- Keep provider-neutral public tool contracts under `backend/app/contracts/tools.py`.
- Create concrete runtime implementation only under `backend/app/tools/` and `backend/app/tools/mcp/`.
- Keep `backend/app/orchestration/core.py` as the orchestration entry point and deepen it in place.
- Keep `backend/app/config/bootstrap.py` as the composition root and add tooling wiring there.
- Keep top-level `mcp:` in `backend/config/app.yaml` as the canonical single-MCP connection section.
- Add top-level `tooling:` in `backend/config/app.yaml` for defaults, registry, discovery, and per-tool behavior.
- Prefer YAML env interpolation and validated config views over expanding `backend/app/config/settings.py` into a second runtime auth source of truth.

---

## 3. Non-Negotiable Boundary Rules

- Treat `backend/` as the Python project root for all tooling and MCP-client work.
- Keep provider-neutral public tool contracts under `backend/app/contracts/`.
- Create concrete tooling runtime modules only under `backend/app/tools/` and `backend/app/tools/mcp/`.
- Keep backend configuration parsing and typed runtime views under `backend/app/config/`, with canonical YAML under `backend/config/`.
- Keep backend tests under `backend/tests/`.
- Do not place backend tool runtime code in the repository root, `frontend/`, or the top-level `mcp/` folder.
- Do not let `backend/app/api/` call the MCP server, `MCPClientAdapter`, or `ToolGateway` directly for normal chat behavior.
- Do not let `backend/app/session/` call the MCP server, `MCPClientAdapter`, or `ToolGateway` directly for normal chat behavior.
- Do not let `backend/app/agents/`, `backend/app/orchestration/`, or agent plugins import concrete MCP client libraries or raw HTTP MCP transport code.
- Keep `backend/app/orchestration/core.py` as the canonical orchestration runtime module unless a rename is done atomically.
- Keep `backend/app/config/bootstrap.py` as the canonical startup composition path.
- Do not let `backend/app/tools/` call LLM providers directly, search or write memory directly, or persist workflow state directly.
- Do not let any module outside `backend/app/tools/mcp/` speak raw MCP protocol or own MCP auth-header construction.
- Keep V1 to one configured MCP endpoint.
- Keep discovered tools non-callable unless they are explicitly allowlisted by backend config.
- Do not log, trace, persist, or return raw tool arguments, raw tool results, auth headers, bearer tokens, JWTs, OAuth client secrets, or private MCP endpoint details by default.
- Treat tool output as data, not trusted instructions.

---

## 4. Phase Overview

| Phase | Name | Primary Outcome |
|---|---|---|
| 0 | [DONE] Current Tooling Baseline and Architecture Fit | The plan starts from the repo's real tool, MCP, policy, and orchestration baseline under `backend/` instead of treating Phase 12 as greenfield work. |
| 1 | Tooling Configuration and Typed Settings Alignment | Tooling and MCP behavior become a typed, validated config surface rooted under `backend/config/` and consumed through `backend/app/config/view.py`. |
| 2 | Public Tool Contract Deepening and Error Model | The stable provider-neutral tool contract under `backend/app/contracts/` grows to cover scopes, streaming, health, capabilities, and normalized errors. |
| 3 | [DONE] Tool Runtime Package and Fake MCP Adapter Foundations | A concrete runtime package under `backend/app/tools/` exists, including internal MCP DTOs, a deterministic fake adapter, and a tooling factory skeleton. |
| 4 | [DONE] Tool Registry, Discovery, Schema Validation, and Result Normalization | Logical tool registration, allowlist merging, argument validation, redaction, and bounded result shaping become real backend-owned behavior. |
| 5 | [DONE] Default ToolGateway Core, Policy Hooks, and Observability | A real `DefaultToolGateway` can list, resolve, execute, stream, trace, and policy-gate tool calls through a fake adapter without external services. |
| 6 | [DONE] HTTP MCP Transport, Authentication, Retry, and Cancellation | The backend can call one real MCP endpoint safely with auth, timeout, retry, cancellation, and optional local integration coverage. |
| 7 | [DONE] Composition Root and Orchestration Adoption | Startup builds the tooling runtime, injects it into orchestration, and proves that the normal chat path can invoke fake or local MCP tools without API/session coupling. |
| 8 | [DONE] Health, Capabilities, and API Error Mapping | `/health`, `/capabilities`, and API error handling expose safe tooling readiness and stable normalized tool failure behavior. |
| 9 | [DONE] Fixtures, Quality Gates, Freeze, and Handoff | The tooling slice closes with focused fixtures, optional local smoke tests, README freeze notes, a full backend quality gate, and a clean handoff to orchestration and strategy work. |

---

## 5. Detailed Implementation Phases

### [DONE] Phase 0. Current Tooling Baseline and Architecture Fit

**Goal**

Record the current backend tooling baseline so implementation extends the existing repo instead of describing a second, parallel tool boundary.

**Files already present**

- [DONE] `backend/app/contracts/tools.py`
- [DONE] `backend/app/contracts/context.py`
- [DONE] `backend/app/contracts/errors.py`
- [DONE] `backend/app/contracts/policy.py`
- [DONE] `backend/app/testing/fakes/fake_tools.py`
- [DONE] `backend/app/orchestration/core.py`
- [DONE] `backend/app/config/schemas.py`
- [DONE] `backend/app/config/settings.py`
- [DONE] `backend/app/config/validation.py`
- [DONE] `backend/app/policy/service.py`
- [DONE] `backend/app/observability/events.py`
- [DONE] `backend/app/foundation/health.py`
- [DONE] `backend/app/foundation/capabilities.py`
- [DONE] `backend/app/api/errors.py`
- [DONE] `backend/app/config/bootstrap.py`
- [DONE] `backend/app/foundation/container.py`
- [DONE] `backend/config/app.yaml`

**Implementation outcomes already in place**

- [DONE] The backend already has a provider-neutral tool capability slot in `OrchestrationContext`.
- [DONE] The direct orchestration runtime already accepts a `ToolGateway`, even though it defaults to a disabled stub.
- [DONE] The repo already has a deterministic fake tool gateway for tests.
- [DONE] The config model already has coarse tool toggles and a single top-level MCP endpoint section.
- [DONE] The policy runtime already reserves `tool.list` and `tool.call` actions plus `deny_unknown_tools`.
- [DONE] Observability, health, capabilities, and API error surfaces already reserve MCP/tool placeholders.

**Current limitations that later phases must fix**

- The public contract is too thin.
- There is no concrete `backend/app/tools/` runtime package.
- There is no typed tooling settings view.
- There is no logical tool registry or discovery merge behavior.
- There is no schema validation or bounded result normalization.
- The policy runtime is too coarse for tool safety and approval semantics.
- Startup does not build or expose a real tool gateway.
- Health, capabilities, and API error mapping are still placeholder-level.
- There is no real MCP transport, auth, retry, or cancellation path.

**Exit criteria**

- [DONE] The implementation plan starts from the current `backend/` baseline and extends it rather than replacing it.

### [DONE] Phase 1. Tooling Configuration and Typed Settings Alignment

**Goal**

Expand the current shallow MCP and tool config surface into a typed, validated runtime view that can drive registry loading, discovery, auth, retries, health, and capabilities.

**Files to create or update**

- [DONE] `backend/app/config/schemas.py`
- [DONE] `backend/app/config/validation.py`
- [DONE] `backend/app/config/view.py`
- [DONE] `backend/app/config/settings.py`
- [DONE] `backend/config/app.yaml`
- [DONE] `backend/tests/unit/config/test_config_view.py`
- [DONE] `backend/tests/unit/config/test_validation.py`
- [DONE] `backend/tests/fixtures/config/tooling_disabled.yaml`
- [DONE] `backend/tests/fixtures/config/tooling_fake_basic.yaml`
- [DONE] `backend/tests/fixtures/config/tooling_fake_streaming.yaml`
- [DONE] `backend/tests/fixtures/config/tooling_invalid_auth.yaml`
- [DONE] `backend/tests/fixtures/config/tooling_invalid_allowlist.yaml`
- [DONE] `backend/tests/fixtures/config/tooling_invalid_transport.yaml`
- [DONE] `backend/tests/fixtures/config/tooling_local_mcp_optional.yaml`

**Implementation tasks**

- [DONE] Add a canonical top-level `tooling:` config section in `backend/config/app.yaml` for backend-owned gateway behavior, including:
  - `tooling.enabled`
  - `tooling.defaults`
  - `tooling.registry`
  - optional `tooling.discovery` fields if they are kept separate from defaults
- [DONE] Keep top-level `mcp:` as the canonical connection section and deepen `mcp.main` to cover:
  - `name`
  - `enabled`
  - `endpoint` or a validated compatibility alias from the current `url`
  - `transport`
  - `timeout_seconds`
  - `stream_timeout_seconds`
  - `auth`
  - `tool_discovery_enabled`
- [DONE] Add typed settings in `backend/app/config/view.py` for:
  - `ToolingDefaultsSettings`
  - `MCPAuthSettings`
  - `MCPServerSettings`
  - `ToolDefinitionSettings`
  - `ToolRegistrySettings`
  - `ToolingSettings`
- [DONE] Expose `get_tooling_settings(config)` so runtime code stops reading raw config keys for tooling behavior.
- [DONE] Preserve the current repo's separation of concerns:
  - `mcp.main` owns connection details for the one external MCP endpoint
  - `tooling.registry.tools` owns logical tool definitions and MCP tool-name mappings
  - `usecases.*.tools.allowed_tools` and `agents.*.allowed_tools` remain contextual allowlist overlays, not the canonical registry
- [DONE] Validate at config-load time that:
  - tooling enabled implies `mcp.main.enabled`
  - V1 still has only one MCP endpoint
  - auth mode and credential combinations are coherent
  - timeouts, retries, argument limits, and result limits are bounded
  - tool names are unique logical names
  - enabled tools map to non-empty MCP tool names
  - schema overrides are valid JSON-schema-shaped objects
  - use-case and agent allowlists reference known logical tool names
  - destructive and external-side-effect tools stay disabled unless explicitly configured
- [DONE] Keep `MCP_MAIN_URL` as a compatibility env input only if needed, but keep canonical runtime auth and endpoint values under `backend/config/app.yaml` with env interpolation.
- [DONE] Keep tooling and MCP secrets redacted in config summaries, startup logs, health payloads, and capability payloads.

**Validation**

- [DONE] Add and pass focused config-view and validation tests for the new tooling and MCP sections.
- [DONE] Run `.venv\Scripts\python.exe -m pytest tests/unit/config/test_config_view.py tests/unit/config/test_validation.py` from `backend/`.
- [DONE] Run `.venv\Scripts\python.exe -m ruff check app/config tests/unit/config/test_config_view.py tests/unit/config/test_validation.py` from `backend/`.
- [DONE] Run `.venv\Scripts\python.exe -m mypy app/config` from `backend/`.

**Exit criteria**

- [DONE] Tooling runtime code consumes one typed `ToolingSettings` object instead of raw nested config keys.
- [DONE] The repo still has one canonical MCP endpoint under `backend/config/app.yaml`.
- [DONE] Invalid tooling or MCP config fails fast during backend startup.

### [DONE] Phase 2. Public Tool Contract Deepening and Error Model

**Goal**

Deepen the stable provider-neutral tool contract under `backend/app/contracts/` so orchestration, policies, and agent plugins have one complete backend-owned tool surface.

**Files to create or update**

- [DONE] `backend/app/contracts/tools.py`
- [DONE] `backend/app/contracts/errors.py`
- [DONE] `backend/app/contracts/policy.py`
- [DONE] `backend/app/contracts/__init__.py`
- [DONE] `backend/app/testing/fakes/fake_tools.py`
- [DONE] `backend/app/testing/fakes/__init__.py`
- [DONE] `backend/tests/unit/contracts/test_tool_contracts.py`
- [DONE] `backend/tests/unit/contracts/test_fake_gateways.py`

**Implementation tasks**

- [DONE] Deepen `backend/app/contracts/tools.py` to cover the target public surface, including models such as:
  - `ToolScopes`
  - `ToolDefinition`
  - `ToolListFilters`
  - `ToolListResult`
  - `ToolExecutionRequest`
  - `ToolResultContent`
  - `ToolResultSummary`
  - `ToolExecutionResult`
  - `ToolStreamEvent`
  - `ToolHealthResult`
  - `ToolCapabilitiesResult`
- [DONE] Extend the public `ToolGateway` protocol to include:
  - `list_tools(...)`
  - `get_tool(...)`
  - `execute(...)`
  - `stream_execute(...)`
  - `health()`
  - `capabilities()`
- [DONE] Keep public contracts provider-neutral. No MCP protocol DTOs or raw transport payloads should appear in `backend/app/contracts/`.
- [DONE] Add normalized tool and MCP-facing backend errors in `backend/app/contracts/errors.py`, such as:
  - `ToolNotFoundError`
  - `ToolDisabledError`
  - `ToolArgumentValidationError`
  - `ToolPolicyDeniedError`
  - `ToolTimeoutError`
  - `ToolCancelledError`
  - `ToolResultTooLargeError`
  - `MCPAuthenticationError`
  - `MCPTransportError`
  - `MCPDiscoveryError`
- [DONE] Deepen `backend/app/contracts/policy.py` to add precise tool actions such as `tool.get`, `tool.execute`, and `tool.stream_execute`, while keeping `tool.call` only as a temporary compatibility alias if a staged migration is needed.
- [DONE] Update `backend/app/testing/fakes/fake_tools.py` to implement the richer public contract while staying deterministic and backend-owned.

**Validation**

- [DONE] Add and pass focused contract and fake-gateway tests for the richer tool surface.
- [DONE] Run `.venv\Scripts\python.exe -m pytest tests/unit/contracts/test_tool_contracts.py tests/unit/contracts/test_fake_gateways.py` from `backend/`.
- [DONE] Run `.venv\Scripts\python.exe -m ruff check app/contracts app/testing/fakes tests/unit/contracts/test_tool_contracts.py tests/unit/contracts/test_fake_gateways.py` from `backend/`.
- [DONE] Run `.venv\Scripts\python.exe -m mypy app/contracts app/testing/fakes` from `backend/`.

**Exit criteria**

- [DONE] The public provider-neutral tool contract is complete enough for orchestration and agent work.
- [DONE] Tool and MCP failures have stable backend-owned error categories.
- [DONE] No MCP protocol types leak into the public contract layer.

### [DONE] Phase 3. Tool Runtime Package and Fake MCP Adapter Foundations

**Goal**

Create the concrete tooling runtime package under `backend/app/tools/` and establish the internal MCP adapter boundary with deterministic fake behavior first.

**Files to create or update**

- [DONE] `backend/app/tools/__init__.py`
- [DONE] `backend/app/tools/models.py`
- [DONE] `backend/app/tools/errors.py`
- [DONE] `backend/app/tools/factory.py`
- [DONE] `backend/app/tools/mcp/__init__.py`
- [DONE] `backend/app/tools/mcp/protocol_models.py`
- [DONE] `backend/app/tools/mcp/fake.py`
- [DONE] `backend/tests/unit/tools/test_factory.py`
- [DONE] `backend/tests/unit/tools/test_fake_mcp_adapter.py`

**Implementation tasks**

- [DONE] Create `backend/app/tools/` as the runtime-owned package for concrete tool behavior.
- [DONE] Add runtime-private models for resolved definitions, registry entries, discovery snapshots, and adapter-facing request metadata that should not live in public contracts.
- [DONE] Add a small tooling factory or bundle model in `backend/app/tools/factory.py` so startup can later assemble registry, adapter, gateway, health, and capabilities through one backend-owned entry point.
- [DONE] Define an internal `MCPClientAdapter` protocol and internal MCP request/response/stream DTOs under `backend/app/tools/mcp/`.
- [DONE] Implement `backend/app/tools/mcp/fake.py` as a deterministic fake adapter that can:
  - list fake discovered tools
  - execute fake tool calls
  - stream fake incremental events
  - return safe health results
- [DONE] Keep all fake MCP behavior backend-owned and isolated from real transport or auth code.

**Validation**

- [DONE] Add and pass unit tests for fake MCP list, execute, stream, and health behavior.
- [DONE] Run `.venv\Scripts\python.exe -m pytest tests/unit/tools/test_factory.py tests/unit/tools/test_fake_mcp_adapter.py` from `backend/`.
- [DONE] Run `.venv\Scripts\python.exe -m ruff check app/tools tests/unit/tools/test_factory.py tests/unit/tools/test_fake_mcp_adapter.py` from `backend/`.
- [DONE] Run `.venv\Scripts\python.exe -m mypy app/tools` from `backend/`.

**Exit criteria**

- [DONE] A concrete tooling runtime package exists under `backend/app/tools/`.
- [DONE] A fake MCP adapter can satisfy the internal adapter protocol without external services.
- [DONE] Startup has a clear future factory hook for tooling construction.

### [DONE] Phase 4. Tool Registry, Discovery, Schema Validation, and Result Normalization

**Goal**

Implement the backend-owned registry and validation behavior that turns config plus discovered MCP tool metadata into safe logical tool execution.

**Files to create or update**

- [DONE] `backend/app/tools/registry.py`
- [DONE] `backend/app/tools/discovery.py`
- [DONE] `backend/app/tools/schema_validation.py`
- [DONE] `backend/app/tools/result_normalizer.py`
- [DONE] `backend/app/tools/redaction.py`
- [DONE] `backend/tests/unit/tools/test_registry.py`
- [DONE] `backend/tests/unit/tools/test_discovery.py`
- [DONE] `backend/tests/unit/tools/test_schema_validation.py`
- [DONE] `backend/tests/unit/tools/test_result_normalizer.py`

**Implementation tasks**

- [DONE] Implement a logical `ToolRegistry` that maps stable backend logical tool names to configured MCP tool names.
- [DONE] Make configured allowlist entries authoritative. Discovery may enrich schemas and health, but newly discovered tools must remain non-callable unless explicitly allowlisted.
- [DONE] Implement discovery merge behavior that can combine:
  - configured logical tool metadata
  - discovered MCP tool schemas
  - optional schema overrides from config
- [DONE] Add argument validation that covers:
  - JSON-serializable shape
  - required fields
  - type checks
  - enum and array bounds
  - maximum serialized argument bytes
  - obvious secret-like keys
  - tool-specific denylisted fields
- [DONE] Add result normalization that converts raw adapter output into:
  - bounded `ToolExecutionResult`
  - bounded `ToolStreamEvent`
  - explicit truncation markers
  - safe text/json/table/file-ref/image-ref content blocks
  - safe summary metadata
- [DONE] Reuse shared redaction helpers where appropriate, but keep tool-specific secret detection and tool-result shaping in `backend/app/tools/redaction.py`.

**Validation**

- [DONE] Add and pass registry, discovery, schema-validation, and result-normalization unit tests.
- [DONE] Run `.venv\Scripts\python.exe -m pytest tests/unit/tools/test_registry.py tests/unit/tools/test_discovery.py tests/unit/tools/test_schema_validation.py tests/unit/tools/test_result_normalizer.py` from `backend/`.
- [DONE] Run `.venv\Scripts\python.exe -m ruff check app/tools tests/unit/tools/test_registry.py tests/unit/tools/test_discovery.py tests/unit/tools/test_schema_validation.py tests/unit/tools/test_result_normalizer.py` from `backend/`.
- [DONE] Run `.venv\Scripts\python.exe -m mypy app/tools` from `backend/`.

**Exit criteria**

- [DONE] Logical tools resolve deterministically through a backend-owned registry.
- [DONE] Invalid arguments fail before any adapter call.
- [DONE] Oversized or unsafe results are bounded or rejected through normalized backend behavior.

### [DONE] Phase 5. Default ToolGateway Core, Policy Hooks, and Observability

**Goal**

Implement the real backend-owned `DefaultToolGateway` and connect it to policy and observability using the fake adapter first.

**Files to create or update**

- [DONE] `backend/app/tools/gateway.py`
- [DONE] `backend/app/tools/retry.py`
- [DONE] `backend/app/policy/service.py`
- [DONE] `backend/app/policy/models.py`
- [DONE] `backend/app/observability/events.py`
- [DONE] `backend/app/observability/tracing.py`
- [DONE] `backend/tests/unit/tools/test_gateway.py`
- [DONE] `backend/tests/unit/tools/test_gateway_streaming.py`
- [DONE] `backend/tests/unit/tools/test_gateway_policy.py`
- [DONE] `backend/tests/unit/tools/test_gateway_trace_events.py`
- [DONE] `backend/tests/unit/observability/test_event_catalog.py`

**Implementation tasks**

- [DONE] Implement `DefaultToolGateway` in `backend/app/tools/gateway.py` with support for:
  - listing policy-filtered logical tools
  - resolving one logical tool definition
  - non-streaming execute
  - streaming execute
  - health
  - capabilities
- [DONE] Call policy before both list and execute paths.
- [DONE] Deepen `backend/app/policy/service.py` so tool policy can enforce:
  - deny unknown tools
  - deny disabled tools
  - allowlist matching by use case, agent, and strategy
  - tool safety levels
  - destructive/external-side-effect default deny
  - approval-required signals without yet implementing the human approval workflow itself
- [DONE] Emit safe tool-layer trace events from the gateway. The current `mcp_*` event names should remain adapter-layer events, while gateway-layer events should clearly represent logical tool execution rather than raw MCP protocol calls.
- [DONE] Add retry helpers for normalized retryable and non-retryable tool errors, even while the adapter is still fake-backed.
- [DONE] Ensure policy denial stops adapter execution and normalizes into backend-owned tool policy errors.

**Validation**

- [DONE] Add and pass unit tests for list, get, execute, stream, denial, retry classification, and safe trace emission.
- [DONE] Run `.venv\Scripts\python.exe -m pytest tests/unit/tools/test_gateway.py tests/unit/tools/test_gateway_streaming.py tests/unit/tools/test_gateway_policy.py tests/unit/tools/test_gateway_trace_events.py tests/unit/observability/test_event_catalog.py` from `backend/`.
- [DONE] Run `.venv\Scripts\python.exe -m ruff check app/tools app/policy app/observability tests/unit/tools tests/unit/observability/test_event_catalog.py` from `backend/`.
- [DONE] Run `.venv\Scripts\python.exe -m mypy app/tools app/policy app/observability` from `backend/`.

**Exit criteria**

- [DONE] A real `DefaultToolGateway` exists and works against a fake adapter.
- [DONE] Policy denial blocks tool execution before any adapter call.
- [DONE] Safe tool execution events are recorded without raw arguments or raw results by default.

### [DONE] Phase 6. HTTP MCP Transport, Authentication, Retry, and Cancellation

**Goal**

Add the real HTTP-first MCP client path, plus auth, timeout, retry, and cancellation behavior, while keeping optional local integration coverage isolated from normal CI.

**Files to create or update**

- [DONE] `backend/app/tools/mcp/client_adapter.py`
- [DONE] `backend/app/tools/mcp/transport.py`
- [DONE] `backend/app/tools/mcp/auth.py`
- [DONE] `backend/app/tools/mcp/event_stream.py`
- [DONE] `backend/app/tools/mcp/errors.py`
- [DONE] `backend/app/tools/retry.py`
- [DONE] `backend/tests/unit/tools/test_http_transport.py`
- [DONE] `backend/tests/unit/tools/test_auth_provider.py`
- [DONE] `backend/tests/unit/tools/test_retry.py`
- [DONE] `backend/tests/unit/tools/test_cancellation.py`
- [DONE] `backend/tests/integration/tools/test_mcp_local_optional.py`

**Implementation tasks**

- [DONE] Implement a real backend-owned `MCPClientAdapter` that speaks to the single configured MCP endpoint through `backend/app/tools/mcp/transport.py`.
- [DONE] Start with HTTP-first transport and keep SSE or WebSocket support behind the abstraction only if the selected MCP stack requires it.
- [DONE] Implement auth providers for the V1 modes defined by the architecture:
  - [DONE] `none`
  - [DONE] `bearer`
  - [DONE] `jwt`
  - [DONE] `oauth_client_credentials`
- [DONE] Keep credential loading config-driven and env-resolved through `backend/config/app.yaml` rather than spreading auth behavior across unrelated bootstrap settings.
- [DONE] Ensure that auth headers, bearer tokens, JWTs, OAuth client secrets, and raw token responses never leak into logs, traces, health, capabilities, or error responses.
- [DONE] Add timeout handling, cancellation propagation, retry classification, and optional idempotency-key propagation for safe tool categories.
- [DONE] Add a cheap, safe health probe for the MCP adapter.
- [DONE] Keep optional local MCP integration tests clearly separated from the default CI path.

**Validation**

- [DONE] Add and pass unit tests for auth-header construction, timeout handling, retry classification, and cancellation behavior.
- [DONE] Run `.venv\Scripts\python.exe -m pytest tests/unit/tools/test_http_transport.py tests/unit/tools/test_auth_provider.py tests/unit/tools/test_retry.py tests/unit/tools/test_cancellation.py` from `backend/`.
- [DONE] Run `.venv\Scripts\python.exe -m ruff check app/tools tests/unit/tools/test_http_transport.py tests/unit/tools/test_auth_provider.py tests/unit/tools/test_retry.py tests/unit/tools/test_cancellation.py` from `backend/`.
- [DONE] Run `.venv\Scripts\python.exe -m mypy app/tools` from `backend/`.
- Run the optional local MCP smoke test only when the local MCP endpoint and credentials are explicitly configured.

**Exit criteria**

- [DONE] The backend can call one real MCP endpoint through a backend-owned adapter.
- [DONE] Credentials remain redacted and contained.
- [DONE] Retry, timeout, and cancellation behavior are explicit and bounded.

### [DONE] Phase 7. Composition Root and Orchestration Adoption

**Goal**

Wire the new tooling runtime into normal backend startup and prove that the standard chat path can reach tools only through orchestration.

**Files to create or update**

- [DONE] `backend/app/tools/factory.py`
- [DONE] `backend/app/config/bootstrap.py`
- [DONE] `backend/app/foundation/container.py`
- [DONE] `backend/app/orchestration/core.py`
- [DONE] `backend/app/testing/fakes/fake_agent.py`
- [DONE] `backend/tests/unit/test_app_factory.py`
- [DONE] `backend/tests/unit/orchestration/test_tooling_integration.py`
- [DONE] `backend/tests/integration/test_startup_tooling.py`
- [DONE] `backend/tests/integration/test_api_tooling_fake_path.py`
- [DONE] `backend/tests/fixtures/config/api_with_fake_mcp_tooling.yaml`

**Implementation tasks**

- [DONE] Add a real tooling-runtime build path in `backend/app/tools/factory.py` that can assemble:
  - typed tooling settings
  - registry
  - discovery behavior
  - MCP adapter
  - gateway
  - tooling health and capabilities helpers
- [DONE] Update `backend/app/config/bootstrap.py` to build tooling during lifespan startup and inject it into `DirectAgentOrchestrationRuntime.from_config(..., tools=...)`.
- [DONE] Keep the existing policy-service sharing model coherent. The tooling runtime should use the same policy-service instance already built for the real LLM path rather than creating a conflicting second policy runtime.
- [DONE] Add a `tool_gateway` field to `backend/app/foundation/container.py` so health, capabilities, and future debug surfaces can access the real runtime-owned gateway.
- [DONE] Keep `backend/app/session/service.py` unchanged in responsibility. It should continue to delegate normal chat behavior only through orchestration.
- [DONE] Add at least one deterministic fake tool-calling path through orchestration so the normal `POST /chat` flow can prove the boundary:
  - API -> SessionService -> OrchestrationRuntime -> ToolGateway -> FakeMCPAdapter
- [DONE] Keep import-time app creation safe. Tool discovery, MCP health, or network I/O must occur during lifespan startup or on demand, not at module import time.

**Validation**

- [DONE] Add and pass focused startup and orchestration integration coverage for fake-tool execution.
- [DONE] Run `.venv\Scripts\python.exe -m pytest tests/unit/test_app_factory.py tests/unit/orchestration/test_tooling_integration.py tests/integration/test_startup_tooling.py tests/integration/test_api_tooling_fake_path.py` from `backend/`.
- [DONE] Run `.venv\Scripts\python.exe -m ruff check app/config/bootstrap.py app/foundation/container.py app/orchestration app/tools tests/unit/orchestration tests/integration/test_startup_tooling.py tests/integration/test_api_tooling_fake_path.py` from `backend/`.
- [DONE] Run `.venv\Scripts\python.exe -m mypy app/config/bootstrap.py app/foundation/container.py app/orchestration app/tools` from `backend/`.

**Exit criteria**

- [DONE] Startup builds and exposes a real tool gateway under `backend/`.
- [DONE] Orchestration receives the gateway through the existing runtime path.
- [DONE] The normal chat path can invoke tools without API or session layer coupling to MCP.

### [DONE] Phase 8. Health, Capabilities, and API Error Mapping

**Goal**

Replace the current placeholder tool/MCP reporting with safe, normalized health, capability, and API error behavior.

**Files to create or update**

- [DONE] `backend/app/tools/health.py`
- [DONE] `backend/app/tools/capabilities.py`
- [DONE] `backend/app/foundation/health.py`
- [DONE] `backend/app/foundation/capabilities.py`
- [DONE] `backend/app/api/errors.py`
- [DONE] `backend/app/api/schemas.py`
- [DONE] `backend/tests/unit/test_health.py`
- [DONE] `backend/tests/unit/test_capabilities.py`
- [DONE] `backend/tests/unit/api/test_error_mapping.py`
- [DONE] `backend/tests/unit/api/test_health_route.py`
- [DONE] `backend/tests/unit/api/test_capabilities_route.py`

**Implementation tasks**

- [DONE] Replace the current placeholder `mcp` health component with real tooling-aware MCP health that can report safe details such as:
  - configured vs enabled
  - adapter reachability
  - discovery state
  - logical tool counts
  - safe provider or transport type
- [DONE] Keep private endpoint details and credentials out of health output.
- [DONE] Replace the current coarse `mcp_tools` capability boolean with real tooling capability summaries derived from the gateway, such as:
  - tooling enabled
  - streaming support present or absent
  - counts by safe tool category or safety level if that is useful and safe
  - optional list of safe logical tool names only when policy allows exposing them
- [DONE] Deepen `backend/app/api/errors.py` so normalized tool errors map to stable API responses such as:
  - 400 or 422 for argument-shape problems
  - 403 for policy denial or approval-required refusal
  - 404 for unknown logical tool name
  - 503 for unavailable adapter or downstream MCP failures
  - 504 for timeouts
- [DONE] Keep error payloads safe and backend-owned. Raw MCP error envelopes must not leak to the frontend.

**Validation**

- [DONE] Add and pass health, capabilities, and API error-mapping tests for the tooling slice.
- [DONE] Run `.venv\Scripts\python.exe -m pytest tests/unit/test_health.py tests/unit/test_capabilities.py tests/unit/api/test_error_mapping.py tests/unit/api/test_health_route.py tests/unit/api/test_capabilities_route.py` from `backend/`.
- [DONE] Run `.venv\Scripts\python.exe -m ruff check app/tools app/foundation app/api/errors.py app/api/schemas.py tests/unit/test_health.py tests/unit/test_capabilities.py tests/unit/api/test_error_mapping.py tests/unit/api/test_health_route.py tests/unit/api/test_capabilities_route.py` from `backend/`.
- [DONE] Run `.venv\Scripts\python.exe -m mypy app/tools app/foundation app/api/errors.py app/api/schemas.py` from `backend/`.

**Exit criteria**

- [DONE] `/health` includes safe tooling and MCP readiness.
- [DONE] `/capabilities` exposes safe tooling summaries without leaking secrets or private endpoint details.
- [DONE] Tool failures surface as stable backend-owned API errors.

### [DONE] Phase 9. Fixtures, Quality Gates, Freeze, and Handoff

**Goal**

Close the tooling slice with focused fixtures, optional local smoke tests, backend-quality validation, README freeze notes, and a clean handoff to the next architecture documents.

**Files to create or update**

- [DONE] `backend/tests/fixtures/config/tooling_*.yaml`
- [DONE] `backend/tests/unit/tools/`
- [DONE] `backend/tests/integration/tools/`
- [DONE] `backend/README.md`
- [DONE] `docs/backend-tooling-mcp-client-plan.md`

**Implementation tasks**

- [DONE] Finalize the fixture matrix under `backend/tests/fixtures/config/`, including:
  - tooling disabled
  - fake basic tool path
  - fake streaming path
  - invalid auth
  - invalid allowlist
  - invalid secret-like arguments
  - optional local MCP smoke path
  - optional approval-required example
- [DONE] Keep local MCP tests opt-in and isolated from normal CI.
- [DONE] Update `backend/README.md` to record:
  - the stable backend tool boundary
  - the canonical tooling and MCP config keys under `backend/config/`
  - the runtime package location under `backend/app/tools/`
  - the test surface under `backend/tests/`
  - explicit deferrals such as multi-MCP routing, full approval workflow, and broader side-effect policy
- [DONE] Run the focused tooling suites first, then the full backend quality gate from `backend/`:
  - `.venv\Scripts\python.exe -m pytest`
  - `.venv\Scripts\python.exe -m ruff check .`
  - `.venv\Scripts\python.exe -m mypy app`
- [DONE] After the slice freezes, update this plan document with `[DONE]` status markers and record the handoff target as `docs/backend-orchestration-architecture.md`, followed by the workflow-strategy and agent documents that depend on the tooling boundary.

**Exit criteria**

- [DONE] Focused tooling validation passes.
- [DONE] The full backend quality gate passes from `backend/`.
- [DONE] The stable tooling boundary is documented in `backend/README.md`.
- [DONE] The backend is ready for `docs/backend-orchestration-architecture.md` to assume a provider-neutral tool gateway and a real MCP client adapter.

---

## 6. Implementation Order Cross-Check

This plan intentionally preserves the architecture document's implementation order while adapting it to the current repo:

- config first
- public contracts second
- runtime package and fake adapter before real transport
- registry, validation, and result normalization before orchestration adoption
- real transport and auth before local MCP smoke tests
- startup wiring before health and API freeze
- full quality gate only after the slice is end-to-end complete under `backend/`

That sequence keeps the early slices testable without external services and avoids coupling the API or session layers directly to MCP while the tooling runtime is still forming.
