# Backend Visualization Implementation Plan

**Document:** `backend-visualization-implementation-plan.md`  
**Version:** 1.0  
**Status:** Implementation-ready  
**Tier:** Backend application  
**Primary source:** `backend-visualization-architecture.md` v1.1  
**Source alignment:** `pluggable_agentic_ai_overall_architecture.md`, `backend-application-architecture.md`, `backend-api-architecture.md`, `backend-session-service-architecture.md`, `backend-llm-gateway-architecture.md`, `backend-tooling-mcp-client-architecture.md`, `backend-orchestration-architecture.md`, `backend-workflow-strategies-architecture.md`, `backend-agents-architecture.md`, `backend-policy-architecture.md`, and `mcp-architecture.md`  
**Assumption:** The backend is already implemented and working. This plan adds visualization without replacing existing API, session, orchestration, agent, gateway, policy, persistence, or observability foundations.

---

## 1. Purpose

This document provides the phased implementation plan for adding visualization capabilities to the existing backend tier.

The implementation must allow the backend to:

- Detect and normalize natural-language chart requests.
- Resolve chart data through approved existing boundaries.
- Validate chart type, data shape, renderer compatibility, and policy.
- Produce a renderer-neutral `ChartArtifact` for the frontend.
- Produce a separate, bounded `ChartContextSummary` for future reasoning.
- Store or reference chart data without copying full datasets into the LLM context.
- Answer follow-up questions using summaries first and deterministic artifact retrieval when exact data is required.
- Return clear user-facing responses when data is missing or the graph type is unsupported.
- Emit safe trace, health, capability, and error information.

The central implementation invariant is:

```text
ChartArtifact
  -> API/SSE
  -> frontend renderer

ChartContextSummary
  -> workflow/session context
  -> future prompt assembly

ChartArtifact.data
  -X-> prompt history by default
```

---

## 2. Scope

### 2.1 In Scope

- Visualization contracts and errors.
- Visualization configuration.
- Chart type registry and alias resolution.
- Renderer capability declarations.
- Universal and chart-specific validation.
- Neutral chart artifact construction.
- Context-safe chart summary construction.
- Session-scoped artifact storage and retrieval.
- Chart agent plugin.
- Optional chart-generation strategy when routing complexity requires it.
- Policy integration.
- LLM, memory, workflow-state, uploaded-file, and MCP-tool data resolution through existing gateways.
- Agent and orchestration result extensions.
- Session-state persistence of compact summaries.
- Existing `/chat` and `/chat/stream` response extensions.
- Conditional artifact retrieval endpoint for reference-mode artifacts.
- Health, capabilities, observability, tests, rollout, and rollback.

### 2.2 Out of Scope

- Browser chart rendering.
- Returning React components, arbitrary JavaScript, or HTML chart implementations.
- Direct database access from chart agents.
- Direct MCP calls from chart agents.
- Direct LLM provider calls.
- Inventing real business values.
- Long-term archival of visualization artifacts.
- Unbounded dataset export.
- Enabling unsupported chart types before backend validation and frontend rendering both exist.
- Replacing the existing workflow-state, trace, memory, tooling, or policy stores.

---

## 3. Existing Boundaries That Must Remain Intact

| Existing component | Visualization use | Must not become |
|---|---|---|
| API layer | Maps artifacts into HTTP/SSE responses | Chart builder or chart router |
| `SessionService` | Loads/saves compact visualization context and clears session artifacts on reset | Visualization engine |
| `OrchestrationRuntime` | Routes chart work, propagates artifacts and context contributions | Renderer |
| Agent registry | Registers `chart_agent` | Infrastructure registry |
| `LLMGateway` | Parses intent and explains computed facts | Numeric source of truth |
| `MemoryGateway` | Retrieves approved data/facts | Chart renderer |
| `ToolGateway` | Retrieves approved external data through MCP | MCP protocol implementation |
| `MCPClientAdapter` | Calls the single MCP endpoint | Chart builder |
| `WorkflowStateStore` | Stores bounded `ChartContextSummary` records | Large dataset store |
| `TraceStore` / observability | Records safe chart lifecycle events | Raw data warehouse |
| `PolicyService` | Allows, denies, or requires approval | Action executor |
| `VisualizationGateway` | Builds, validates, summarizes, stores, and retrieves chart artifacts | Frontend framework or external data client |

---

## 4. Recommended Cross-Tier Sequence

Visualization is backend-led because the backend owns the canonical artifact contract.

| Integrated wave | Backend work | MCP work | Frontend work | Gate |
|---|---|---|---|---|
| 0 | Freeze `ChartArtifact` v1, `ChartContextSummary` v1, SSE additions, and golden fixtures | Review dataset result contract | Review renderer mappings | Contract review approved |
| 1 | Contracts, config, registry, validators | Add visualization-ready reporting/data tools or adapt existing tools | Build fixture parser and adapter skeleton | Schemas validate in all tiers |
| 2 | Artifact builder, summary builder, artifact store, gateway | Complete bounded tool execution and capability discovery | Build renderer with fixtures | Backend unit suite and MCP contract tests pass |
| 3 | Chart agent, routing, policy, state propagation | Backend discovery smoke test | Integrate non-streaming API artifacts | `/chat` returns renderable chart |
| 4 | SSE events and conditional artifact fetch | Reference/pagination behavior if required | Integrate streaming and reference mode | `/chat/stream` renders once and completes |
| 5 | Hardening, observability, limits, compatibility | Tool hardening | Accessibility, responsive behavior, error UX | Full end-to-end suite passes |

Backend Phases 1–5 may proceed while the MCP reporting plugin is being built because inline user data and fixtures are sufficient to develop the core pipeline. Backend tool-based data resolution must not be marked complete until the MCP integration contract passes.

---

## 5. Target Backend Package Additions

Use the existing backend package conventions. The following is the recommended logical layout; adapt the root package name to the current repository without moving unrelated modules.

```text
backend/app/
  visualization/
    __init__.py
    gateway.py
    models.py
    settings.py
    chart_registry.py
    renderer_capabilities.py
    chart_data.py
    validators.py
    chart_spec_builder.py
    chart_summary_builder.py
    artifact_store.py
    computations.py
    context_selector.py
    errors.py
    observability.py
    health.py
    capabilities.py

  agents/
    chart_agent.py

  orchestration/strategies/
    chart_generation_strategy.py        # optional; add only when existing routing is insufficient

  api/
    dto/
      artifacts.py                      # or existing DTO module
    routes/
      artifacts.py                      # only when reference mode needs fetch
```

Recommended tests:

```text
backend/tests/
  unit/visualization/
  unit/agents/test_chart_agent.py
  unit/policy/test_visualization_policy.py
  integration/visualization/
  contract/visualization/
  fixtures/visualization/
```

---

## 6. Contract Baseline

### 6.1 Required Versioned Contracts

The implementation must freeze and version these contracts before production integration:

- `ChartRequest`
- `VisualizationContext`
- `ChartArtifact`
- `ChartContextSummary`
- `ChartArtifactEnvelope`
- `ContextContribution`
- `ChartDataSlice`
- `ChartComputedFacts`
- `RendererCapabilities`
- Visualization errors
- Agent/orchestration artifact extensions
- REST artifact response shape
- SSE artifact event envelope

### 6.2 Compatibility Rules

1. `ChartArtifact.spec_version` starts at `"1.0"`.
2. Additive optional fields are backward-compatible within major version 1.
3. Removing or changing field meaning requires a new spec major version.
4. Unknown `chart_type`, `renderer`, or `spec_version` must fail safely.
5. The backend must never serialize executable renderer code.
6. Metadata must be bounded and redacted.
7. The frontend-facing artifact and context-facing summary remain separate serialized objects.
8. Existing text-only responses remain valid when `artifacts=[]`.
9. Existing SSE text events remain unchanged; artifact events are additive.
10. `context_summary.created` is internal by default and must not expose summary content to the client.

---

## 7. Phase Summary

| Phase | Name | Primary output | Depends on |
|---:|---|---|---|
| 0 | [DONE] Baseline and Contract Freeze | Approved schemas, fixtures, migration decisions | Existing working backend |
| 1 | [DONE] Models, Errors, and Configuration | Typed visualization foundation | Phase 0 |
| 2 | [DONE] Registry, Renderer Capabilities, and Validation | Explicit supported chart catalog | Phase 1 |
| 3 | [DONE] Artifact and Context Summary Builders | Separate frontend and context outputs | Phase 2 |
| 4 | [DONE] Artifact Store and Deterministic Computation | Retrievable session-scoped artifacts | Phase 3 |
| 5 | [DONE] Visualization Gateway | Composed visualization boundary | Phases 2–4 |
| 6 | [DONE] Policy, Observability, Health, and Capabilities | Controlled and diagnosable capability | Phase 5 |
| 7 | [DONE] Chart Agent and Data Resolution | Natural-language chart behavior | Phases 5–6; MCP contract for tool data |
| 8 | [DONE] Orchestration, Session, and Prompt-Context Integration | Correct result routing and summary persistence | Phase 7 |
| 9 | [DONE] API, SSE, and Artifact Retrieval | Stable frontend delivery contract | Phase 8 |
| 10 | [DONE] Verification and Golden Compatibility | Unit, integration, contract, and E2E evidence | Phases 1–9 |
| 11 | Rollout, Monitoring, and Operational Readiness | Safe production activation | Phase 10 |

---

# 8. Detailed Implementation Phases

## [DONE] Phase 0: Baseline and Contract Freeze

### Goal

Establish a repo-accurate baseline and remove contract ambiguity before changing shared models.

### Files created or updated

- [DONE] `docs/backend-visualization-implementation-plan.md`
- [DONE] `docs/decisions/visualization-contract-v1.md`
- [DONE] `backend/tests/fixtures/visualization/chart_artifact_v1.json`
- [DONE] `backend/tests/fixtures/visualization/chart_context_summary_v1.json`
- [DONE] `backend/tests/fixtures/visualization/chat_response_with_chart_v1.json`
- [DONE] `backend/tests/fixtures/visualization/sse_artifact_events_v1.jsonl`
- [DONE] `backend/tests/unit/visualization/test_visualization_phase0_fixtures.py`

### Implementation outcomes

- [DONE] Ran the existing backend unit, integration, lint, and type-check suites and recorded the current baseline in `docs/decisions/visualization-contract-v1.md`.
- [DONE] Recorded the current DTO and serialization owners for agent results, orchestration results, session chat results, chat responses, SSE event envelopes, workflow-state session documents, and health/capabilities.
- [DONE] Identified the current composition-root registration points for settings, policy domains, gateways, agents, strategies, health contributors, and capability contributors.
- [DONE] Froze `ChartArtifact` v1 and `ChartContextSummary` v1 JSON fixtures under `backend/tests/fixtures/visualization/`.
- [DONE] Froze a repo-accurate chat response golden fixture with additive `data.artifacts` rather than a second top-level `artifacts` field.
- [DONE] Froze a repo-accurate SSE golden fixture that preserves the working frontend `response.*` event family and was later upgraded in phase 9 to additive `artifact.started` and `artifact.completed` events.
- [DONE] Chose inline-only public V1 delivery and deferred public reference-mode fetch routes beyond phase 0.
- [DONE] Documented current workflow-state versioning and migration behavior: JSON document version `1`, SQLite schema version `2`, and no phase-0 migration.
- [DONE] Accepted `echarts` as the backend-exposed renderer name for the v1 contract baseline.

### Validation

- [DONE] `backend/.venv/Scripts/python.exe -m pytest tests/unit/visualization/test_visualization_phase0_fixtures.py`
- [DONE] `backend/.venv/Scripts/python.exe -m pytest` executed and the current baseline was captured in the decision record.
- [DONE] `backend/.venv/Scripts/python.exe -m ruff check .` executed and the current baseline was captured in the decision record.
- [DONE] `backend/.venv/Scripts/python.exe -m mypy app` executed and the current baseline was captured in the decision record.

### Baseline issues carried forward

- The current backend baseline is not fully green outside the visualization slice.
- `pytest` currently fails in pre-existing deployment/config/session/health coverage unrelated to the new visualization fixtures.
- `ruff check .` currently reports pre-existing unused imports outside the visualization slice.
- `mypy app` currently reports pre-existing `subprocess.Popen` environment typing issues in deployment process-control helpers.
- These failures were recorded as the phase-0 baseline and were not changed by the visualization contract freeze.

### Exit criteria

- [DONE] The backend now has one repo-accurate visualization contract decision record rooted in `docs/decisions/`.
- [DONE] Artifact and context summary remain separate frozen fixtures.
- [DONE] Existing text-only clients can continue to ignore the future optional `data.artifacts` field.
- [DONE] There is one canonical public SSE artifact event with no `message.*` versus `response.*` ambiguity.

---

## [DONE] Phase 1: Models, Errors, and Configuration

### Objective

Create the typed foundation without changing runtime behavior.

### Tasks

1. [DONE] Add typed models:
   - [DONE] `VisualizationContext`
   - [DONE] `ChartRequest`
   - [DONE] `ChartArtifact`
   - [DONE] `ChartContextSummary`
   - [DONE] `ChartArtifactEnvelope`
   - [DONE] `ContextContribution`
   - [DONE] `ChartDataSlice`
   - [DONE] `ChartComputedFacts`
   - [DONE] `RendererCapabilities`
2. [DONE] Add enums or literals for:
   - [DONE] chart type;
   - [DONE] renderer;
   - [DONE] data mode;
   - [DONE] data source;
   - [DONE] context contribution kind.
3. [DONE] Add error classes:
   - [DONE] `UnsupportedChartTypeError`
   - [DONE] `UnsupportedRendererError`
   - [DONE] `ChartDataMissingError`
   - [DONE] `ChartDataValidationError`
   - [DONE] `ChartEncodingError`
   - [DONE] `ChartPolicyDeniedError`
   - [DONE] `ChartRowLimitExceededError`
   - [DONE] `ChartSeriesLimitExceededError`
   - [DONE] `ChartArtifactBuildError`
   - [DONE] `ChartContextSummaryBuildError`
   - [DONE] `ChartContextSummaryLimitExceededError`
   - [DONE] `ChartArtifactNotFoundError`
   - [DONE] `ChartFollowupAmbiguousError`
4. [DONE] Add typed settings for:
   - [DONE] enablement;
   - [DONE] default and allowed renderers;
   - [DONE] artifact spec version;
   - [DONE] allowed chart types;
   - [DONE] aliases;
   - [DONE] row/series/category/artifact limits;
   - [DONE] sample-data policy;
   - [DONE] context-summary budget;
   - [DONE] artifact-store provider and TTL;
   - [DONE] exact follow-up retrieval;
   - [DONE] safe metadata allowlist.
5. [DONE] Integrate settings into the existing YAML configuration loader.
6. [DONE] Validate cross-field rules:
   - [DONE] default renderer must be in allowed renderers;
   - [DONE] allowed chart types must exist in the registry seed catalog;
   - [DONE] `max_rows_inline <= max_rows_artifact_store`;
   - [DONE] context summary token limits must be positive;
   - [DONE] reference mode requires an enabled artifact store and retrieval path;
   - [DONE] full dataset in context remains false.
7. [DONE] Add safe config summaries that omit sensitive endpoints and credentials.

### Deliverables

- [DONE] Visualization models
- [DONE] Visualization settings models
- [DONE] Visualization error taxonomy
- [DONE] YAML config section
- [DONE] Config validation tests
- [DONE] Serialization tests
- [DONE] Safe startup-summary integration

### Exit Criteria

- [DONE] Models serialize and deserialize deterministically.
- [DONE] Invalid chart settings fail startup with actionable errors.
- [DONE] No visualization code reads raw environment variables.
- [DONE] `ChartContextSummary` has no field intended to hold full row-level data.
- [DONE] Text-only runtime behavior is unchanged.

---

## [DONE] Phase 2: Chart Registry, Renderer Capabilities, and Validation

### Objective

Make chart support explicit and reject invalid requests before artifact creation.

### Tasks

1. [DONE] Implement `ChartTypeRegistry`.
2. [DONE] Register the V1 canonical types:
   - [DONE] `bar`
   - [DONE] `grouped_bar`
   - [DONE] `stacked_bar`
   - [DONE] `horizontal_bar`
   - [DONE] `line`
   - [DONE] `multi_line`
   - [DONE] `area`
   - [DONE] `pie`
   - [DONE] `donut`
   - [DONE] `scatter`
   - [DONE] `bubble`
   - [DONE] `histogram`
   - [DONE] `box_plot`
   - [DONE] `heatmap`
   - [DONE] `treemap`
   - [DONE] `waterfall`
   - [DONE] `gantt`
   - [DONE] `radar`
   - [DONE] `table`
3. [DONE] Add alias normalization from configuration.
4. [DONE] Add explicit renderer capability records by chart type and spec version.
5. [DONE] Implement universal validators:
   - [DONE] registered chart type;
   - [DONE] allowed renderer;
   - [DONE] title present;
   - [DONE] bounded field names and metadata;
   - [DONE] data or `data_ref` present;
   - [DONE] row, series, category, and artifact limits;
   - [DONE] encoding fields exist;
   - [DONE] safe JSON-serializable values.
6. [DONE] Implement chart-specific validators:
   - [DONE] numeric requirements;
   - [DONE] time-series field/order requirements;
   - [DONE] pie/donut part-to-whole rules;
   - [DONE] scatter/bubble x/y/size rules;
   - [DONE] histogram and box-plot input rules;
   - [DONE] heatmap matrix/dimension rules;
   - [DONE] gantt task/date rules;
   - [DONE] waterfall signed contribution rules;
   - [DONE] radar dimension rules.
7. [DONE] Add summary validators:
   - [DONE] required identity fields;
   - [DONE] token estimate;
   - [DONE] no full row list;
   - [DONE] no unbounded sample rows;
   - [DONE] safe metadata;
   - [DONE] `data_ref` when exact retrieval is enabled.
8. [DONE] Add deterministic error-to-user-message mapping helpers.
9. [DONE] Add registry output for health/capability aggregation, but do not expose it publicly until Phase 6.

### Deliverables

- [DONE] Chart registry
- [DONE] Alias mapper
- [DONE] Renderer capability catalog
- [DONE] Universal validators
- [DONE] Chart-specific validators
- [DONE] Context summary validators
- [DONE] Validation fixtures for every V1 type
- [DONE] Unsupported-type response fixture

### Exit Criteria

- [DONE] Supported types are discoverable and stable.
- [DONE] Aliases cannot bypass canonical registry checks.
- [DONE] Unsupported types produce no artifact.
- [DONE] Invalid data fails before artifact construction.
- [DONE] A chart cannot be enabled unless the configured renderer declares support.
- [DONE] Summary validation blocks row-level dataset injection.

### Validation

- [DONE] `backend/.venv/Scripts/python.exe -m pytest tests/unit/visualization/test_chart_registry.py tests/unit/visualization/test_validators.py tests/unit/visualization/test_models.py tests/unit/visualization/test_visualization_phase0_fixtures.py`

---

## [DONE] Phase 3: Chart Artifact and Context Summary Builders

### Objective

Produce deterministic, renderer-neutral artifacts and bounded reasoning summaries.

### Tasks

### 3.1 Data Normalization

1. [DONE] Normalize input records into a stable row model.
2. [DONE] Infer field types conservatively.
3. [DONE] Reject ambiguous mixed-type numeric fields unless safely coercible.
4. [DONE] Normalize dates/times without changing their semantic timezone.
5. [DONE] Preserve source provenance separately from renderer options.
6. [DONE] Compute row, category, and series counts before building.

### 3.2 Artifact Builder

1. [DONE] Implement `ChartSpecBuilder`.
2. [DONE] Generate stable, opaque artifact IDs.
3. [DONE] Build neutral `encoding` and `options`; do not generate executable JavaScript.
4. [DONE] Select `data_mode`:
   - inline when under policy/config limits;
   - reference when enabled and required;
   - error when too large and reference mode is unavailable.
5. [DONE] Include bounded warnings and metadata.
6. [DONE] Make output deterministic for equivalent requests and input ordering where ordering is semantically fixed.
7. [DONE] Add schema validation after construction.

### 3.3 Context Summary Builder

1. [DONE] Implement `ChartSummaryBuilder`.
2. [DONE] Compute chart-specific aggregates and insights deterministically.
3. [DONE] Include:
   - identity;
   - source;
   - fields;
   - counts;
   - time range where relevant;
   - totals, averages, minima, maxima;
   - extrema;
   - trend summary;
   - warnings;
   - artifact/data reference.
4. [DONE] Enforce summary token budgets.
5. [DONE] Compact in this priority order:
   1. identity, title, type, fields, row count, source, reference;
   2. top three insights;
   3. extrema and totals;
   4. optional descriptive details.
6. [DONE] Never use raw rows as a compaction fallback.
7. [DONE] Ensure sensitive values are excluded when policy does not allow them in context.
8. [DONE] Produce `ContextContribution(kind="chart_summary")`.

### 3.4 Chart-Type Summary Coverage

| Chart family | Minimum deterministic facts |
|---|---|
| Bar variants | totals, top/bottom category, per-series extrema |
| Line/area | start/end, direction, peak/trough, largest change, time range |
| Pie/donut | total, largest/smallest shares, concentration |
| Scatter/bubble | ranges, relationship direction, optional computed correlation, outlier hints |
| Histogram | range, bin count, modal bin, shape hints |
| Box plot | median, quartiles, whiskers, outlier count |
| Heatmap | highest/lowest cells and concentration |
| Treemap | total and top contributors |
| Waterfall | start/end and largest positive/negative contributors |
| Gantt | date range, task count, longest/critical tasks when supplied |
| Radar | strongest/weakest dimensions and comparison |
| Table | row/column count and bounded numeric aggregates |

### Deliverables

- [DONE] Data normalization helpers
- [DONE] `ChartSpecBuilder`
- [DONE] `ChartSummaryBuilder`
- [DONE] Token estimator integration
- [DONE] Compaction implementation
- [DONE] Broad chart-family builder coverage using the existing `chart_validation_cases_v1.json` fixture set and focused builder tests
- [DONE] Property tests for “summary does not contain full dataset”

### Exit Criteria

- [DONE] A valid request produces a valid `ChartArtifactEnvelope`.
- [DONE] Artifact and summary are distinct objects.
- [DONE] Large data never silently enters prompt context.
- [DONE] Summary generation is deterministic for fixture inputs.
- [DONE] Summary fits configured budgets.
- [DONE] No renderer-specific executable content is present.

### Validation

- [DONE] `backend/.venv/Scripts/python.exe -m pytest tests/unit/visualization/test_chart_data.py tests/unit/visualization/test_chart_builders.py`

---

## [DONE] Phase 4: Visualization Artifact Store and Deterministic Computation

### Objective

Support follow-up questions and reference-mode delivery without using the LLM context as a dataset store.

### Tasks

1. [DONE] Implement `VisualizationArtifactStore` protocol:
   - [DONE] save artifact and summary;
   - [DONE] get artifact;
   - [DONE] get summary;
   - [DONE] delete session artifacts;
   - [DONE] get bounded data slice;
   - [DONE] compute facts.
2. [DONE] Implement the selected V1 provider:
   - [DONE] session-scoped in-memory cache.
3. [DONE] Do not put large full datasets in workflow-state JSON.
4. [DONE] Add TTL and expiration handling.
5. [DONE] Scope every artifact by session and, when available, user/tenant/project.
6. [DONE] Enforce ownership checks before retrieval.
7. [DONE] Add deterministic computation helpers:
   - [DONE] exact value lookup;
   - [DONE] extrema;
   - [DONE] totals/averages;
   - [DONE] period filtering;
   - [DONE] series comparison;
   - [DONE] bounded row projection;
   - [DONE] chart reuse with a new validated request.
8. [DONE] Add field allowlists and `max_rows` to retrieval.
9. [DONE] Add reset integration hook to remove:
   - [DONE] summaries;
   - [DONE] artifacts;
   - [DONE] data references;
   - [DONE] cache entries.
10. [DONE] Ensure reset does not remove long-term memory, source business records, or traces.
11. [DONE] Add expiration-safe user messages.

### Deliverables

- [DONE] Artifact store protocol
- [DONE] V1 artifact store implementation
- [DONE] TTL cleanup
- [DONE] Session ownership enforcement
- [DONE] Deterministic computation service
- [DONE] Reset cleanup hook
- [DONE] Artifact-not-found and expired behavior tests

### Exit Criteria

- [DONE] Artifacts are retrievable by ID only within the authorized scope.
- [DONE] Session reset clears session-scoped visualization state.
- [DONE] Exact follow-ups can be answered without loading all rows into an LLM prompt.
- [DONE] Expired artifacts fail safely.
- [DONE] Large datasets are not embedded in workflow state.

### Validation

- [DONE] `backend/.venv/Scripts/python.exe -m pytest tests/unit/visualization/test_artifact_store.py tests/unit/session/test_session_reset.py`

---

## [DONE] Phase 5: Visualization Gateway

### Objective

Create the single backend boundary that composes registry, validation, builders, policy hooks, storage, and retrieval.

### Tasks

1. [DONE] Implement the `VisualizationGateway` protocol.
2. [DONE] Implement `DefaultVisualizationGateway`.
3. [DONE] `build_visualization(...)` flow:
   1. [DONE] normalize chart type alias;
   2. [DONE] resolve renderer;
   3. [DONE] check capability and policy preconditions through composable authorizer hooks;
   4. [DONE] normalize data;
   5. [DONE] validate request and data;
   6. [DONE] construct artifact;
   7. [DONE] construct context summary;
   8. [DONE] validate both outputs;
   9. [DONE] persist/cache when configured;
   10. [DONE] return envelope.
4. [DONE] `retrieve_chart_artifact(...)` flow:
   1. [DONE] validate identity and scope;
   2. [DONE] check exact-retrieval policy;
   3. [DONE] retrieve artifact;
   4. [DONE] filter fields and rows;
   5. [DONE] compute requested facts where possible;
   6. [DONE] return `ChartArtifact`, `ChartDataSlice`, or `ChartComputedFacts`.
5. [DONE] Implement `supported_chart_types()` and `renderer_capabilities()`.
6. [DONE] Add cancellation propagation.
7. [DONE] Add normalized error mapping.
8. [DONE] Add fake gateway for agent, orchestration, and API tests.
9. [DONE] Add dependency-boundary tests that prevent the visualization module from importing:
   - [DONE] frontend code;
   - [DONE] MCP clients;
   - [DONE] database clients;
   - [DONE] concrete LLM providers;
   - [DONE] external API clients.

### Deliverables

- [DONE] Gateway interface and default implementation
- [DONE] Fake visualization gateway
- [DONE] Composition-root factory
- [DONE] Build and retrieval flows
- [DONE] Boundary tests
- [DONE] Error normalization

### Exit Criteria

- [DONE] Gateway tests pass with no external services.
- [DONE] Invalid requests never create or store artifacts.
- [DONE] Gateway owns artifact/summary creation, not the agent.
- [DONE] Gateway cannot access MCP or concrete persistence clients directly.
- [DONE] Cancellation and timeout behavior are predictable.

### Files created or updated

- [DONE] `backend/app/visualization/gateway.py`
- [DONE] `backend/app/visualization/__init__.py`
- [DONE] `backend/app/testing/fakes/fake_visualization.py`
- [DONE] `backend/app/testing/fakes/__init__.py`
- [DONE] `backend/tests/unit/visualization/test_gateway.py`
- [DONE] `backend/tests/unit/visualization/test_import_boundaries.py`

### Implementation outcomes

- [DONE] Added the public `VisualizationGateway` protocol and the `DefaultVisualizationGateway` composition layer.
- [DONE] Composed alias normalization, renderer resolution, builder validation, summary validation, and artifact-store persistence into one backend-owned gateway flow.
- [DONE] Added bounded retrieval modes for full artifacts, data slices, and computed facts.
- [DONE] Added additive cancellation-token support using the existing orchestration cancellation helper.
- [DONE] Added normalized visualization error mapping for non-visualization exceptions.
- [DONE] Added a visualization runtime bundle/factory that wires settings, registry, capabilities, builders, and the V1 in-memory artifact store.
- [DONE] Added a fake visualization gateway suitable for agent, orchestration, and API tests.
- [DONE] Added import-boundary coverage for frontend, MCP, database, provider SDK, and external API client dependencies.

### Validation

- [DONE] `backend/.venv/Scripts/python.exe -m pytest tests/unit/visualization/test_gateway.py tests/unit/visualization/test_import_boundaries.py`

---

## [DONE] Phase 6: Policy, Observability, Health, and Capabilities

### Objective

Make visualization controlled, bounded, visible, and safe before user-facing routing is enabled.

### Tasks

### 6.1 Policy

1. [DONE] Add a visualization policy domain and request model.
2. [DONE] Gate:
   - [DONE] use-case enablement;
   - [DONE] agent permission;
   - [DONE] chart types;
   - [DONE] renderers;
   - [DONE] data sources;
   - [DONE] uploaded-file use;
   - [DONE] memory use;
   - [DONE] tool use;
   - [DONE] inline/reference mode;
   - [DONE] exact follow-up retrieval;
   - [DONE] data export;
   - [DONE] sensitive fields;
   - [DONE] row/series/category/artifact/token limits.
3. [DONE] Deny unknown chart types and renderers.
4. [DONE] Deny full dataset prompt insertion.
5. [DONE] Add final enforcement in `VisualizationGateway`.
6. [DONE] Keep policy evaluative; it must not build artifacts or fetch data.

### 6.2 Observability

 [DONE] Add a safe visualization trace-event catalog and gateway emission for build, summary, storage, delivery, retrieval, computation, denial, and failure paths.

Safe event catalog:

```text
chart_request_detected
chart_intent_parse_started
chart_intent_parse_completed
chart_data_resolution_started
chart_data_resolution_completed
chart_validation_started
chart_validation_failed
chart_artifact_build_started
chart_artifact_created
chart_context_summary_created
chart_artifact_stored
chart_artifact_delivered
chart_followup_detected
chart_followup_answered_from_summary
chart_followup_artifact_retrieved
chart_followup_computation_completed
chart_request_failed
```

[DONE] Add safe visualization metrics for request counts, validation failures, policy denials, row counts, summary token estimates, and build/retrieval timings.

Recommended metrics:

- request count by canonical chart type;
- success/error/unsupported/missing-data count;
- validation failure count;
- inline vs reference count;
- rows processed;
- summary token estimate;
- artifact build duration;
- summary build duration;
- artifact retrieval duration;
- cache hit/miss/expired count;
- policy denial count.

[DONE] Do not log or trace full chart rows by default.

### 6.3 Health and Capabilities

[DONE] Add safe health:

```json
{
  "visualization": {
    "configured": true,
    "enabled": true,
    "default_renderer": "echarts",
    "supported_chart_types_count": 19,
    "context_summary_enabled": true,
    "artifact_store_enabled": true
  }
}
```

[DONE] Add capabilities:

- enabled status;
- renderer;
- spec version;
- context summary mode;
- supported canonical chart types;
- reference mode support;
- maximum safe client-visible limits where appropriate.

### Deliverables

- [DONE] Visualization policy models and rules
- [DONE] Gateway final policy enforcement
- [DONE] Trace events and metrics
- [DONE] Health contributor
- [DONE] Capabilities contributor
- [DONE] Redaction tests
- [DONE] Policy fixture matrix

### Exit Criteria

- [DONE] Visualization is deny-by-default unless configured.
- [DONE] Policy denial prevents artifact creation.
- [DONE] Traces contain no raw rows, credentials, prompts, or raw MCP payloads.
- [DONE] `/health` and `/capabilities` expose safe visualization status.
- [DONE] Limits are enforced consistently by policy and validators.

### Files created or updated

- [DONE] `backend/app/contracts/policy.py`
- [DONE] `backend/app/contracts/trace.py`
- [DONE] `backend/app/config/schemas.py`
- [DONE] `backend/app/config/view.py`
- [DONE] `backend/app/policy/settings.py`
- [DONE] `backend/app/policy/rule_loader.py`
- [DONE] `backend/app/policy/visualization_policy.py`
- [DONE] `backend/app/visualization/gateway.py`
- [DONE] `backend/app/visualization/policy.py`
- [DONE] `backend/app/visualization/observability.py`
- [DONE] `backend/app/visualization/health.py`
- [DONE] `backend/app/visualization/capabilities.py`
- [DONE] `backend/app/visualization/__init__.py`
- [DONE] `backend/app/observability/events.py`
- [DONE] `backend/app/observability/metrics.py`
- [DONE] `backend/app/foundation/health.py`
- [DONE] `backend/app/foundation/capabilities.py`
- [DONE] `backend/app/api/schemas.py`
- [DONE] `backend/tests/unit/config/test_config_view.py`
- [DONE] `backend/tests/unit/config/test_validation.py`
- [DONE] `backend/tests/unit/policy/test_visualization_policy.py`
- [DONE] `backend/tests/unit/visualization/test_gateway.py`
- [DONE] `backend/tests/unit/api/test_health_route.py`
- [DONE] `backend/tests/unit/api/test_capabilities_route.py`
- [DONE] `backend/tests/unit/test_health.py`
- [DONE] `backend/tests/unit/test_capabilities.py`
- [DONE] `backend/tests/integration/policy/test_startup_policy.py`

### Implementation outcomes

- [DONE] Added typed `policy.visualization` config parsing, validation, and profile-level defaults.
- [DONE] Added `visualization.build` and `visualization.retrieve` policy actions plus the internal visualization policy evaluator.
- [DONE] Extended use-case and agent policy gating to cover visualization requests.
- [DONE] Added visualization gateway policy authorizers and preserved policy denials as `ChartPolicyDeniedError`.
- [DONE] Added visualization-safe trace event names, low-cardinality metrics tags, and a gateway observer that emits bounded lifecycle metadata only.
- [DONE] Added safe visualization health and capability payload builders and exposed them through `/health` and `/capabilities`.
- [DONE] Switched the visualization package root to lazy exports to remove import-time circular dependencies.
- [DONE] Added focused unit and integration coverage for visualization policy config, gateway policy enforcement, observability, and health/capability exposure.

### Validation

- [DONE] `backend/.venv/Scripts/python.exe -m pytest tests/unit/config/test_config_view.py tests/unit/config/test_validation.py tests/unit/policy/test_visualization_policy.py tests/unit/visualization/test_gateway.py`
- [DONE] `backend/.venv/Scripts/python.exe -m pytest tests/unit/api/test_health_route.py tests/unit/api/test_capabilities_route.py tests/unit/test_health.py tests/unit/test_capabilities.py tests/unit/test_app_factory.py tests/integration/policy/test_startup_policy.py`
- [DONE] `backend/.venv/Scripts/python.exe -m pytest --import-mode=importlib tests/unit/visualization tests/unit/policy tests/unit/api/test_health_route.py tests/unit/api/test_capabilities_route.py tests/unit/test_health.py tests/unit/test_capabilities.py tests/unit/test_app_factory.py tests/integration/policy/test_startup_policy.py`

---

## [DONE] Phase 7: Chart Agent and Controlled Data Resolution

### Objective

Add task-specific chart behavior while preserving gateway boundaries.

### Tasks

1. [DONE] Register `chart_agent` through the existing agent plugin pattern.
2. [DONE] Add capabilities:
   - [DONE] chart request parsing;
   - [DONE] chart data resolution;
   - [DONE] chart artifact generation;
   - [DONE] context summary generation;
   - [DONE] chart follow-up answering.
3. [DONE] Add structured LLM outputs for:
   - [DONE] `generate_chart`;
   - [DONE] `chart_followup`;
   - [DONE] `not_chart`;
   - [DONE] `missing_data`.
4. [DONE] Validate all LLM-produced fields before use.
5. [DONE] Implement data-source selection in this priority order unless the use case config overrides it:
   1. [DONE] explicit user-provided structured values;
   2. [DONE] relevant existing workflow-state data;
   3. [DONE] approved uploaded-file ingestion result;
   4. [DONE] approved memory retrieval;
   5. [DONE] approved logical tool call through `ToolGateway`.
6. [DONE] Never treat the LLM as the numeric source of truth unless sample/demo mode is explicitly requested and allowed.
7. [DONE] For tool data:
   - [DONE] call only logical, allowlisted backend tool names;
   - [DONE] expect a bounded structured dataset;
   - [DONE] validate source/provenance, fields, types, row count, and truncation;
   - [DONE] ask for filters/aggregation when the tool result is too large or truncated in a way that prevents the chart.
8. [DONE] Handle missing data with a concrete request for required fields.
9. [DONE] Handle unsupported chart type by listing allowed alternatives and returning no fake artifact.
10. [DONE] Implement follow-up routing:
    - [DONE] answer from summary when sufficient;
    - [DONE] call gateway deterministic computation for exact questions;
    - [DONE] retrieve bounded rows only when required and policy allows;
    - [DONE] pass compact computed facts, not full data, to the LLM for explanation.
11. [DONE] Return:
    - [DONE] natural-language answer;
    - [DONE] artifact list;
    - [DONE] chart summary context contribution;
    - [DONE] safe metadata.
12. [DONE] Keep `chart_generation_strategy` deferred because the existing router/direct-agent strategy does not need to change in phase 7.

### Deliverables

- [DONE] `chart_agent`
- [DONE] Agent descriptor and YAML configuration
- [DONE] Structured intent models
- [DONE] Data-resolution coordinator
- [DONE] MCP structured dataset adapter/validator
- [DONE] Missing-data and unsupported-type responses
- [DONE] Follow-up handler
- [DONE] Agent unit tests with fake gateways

### Exit Criteria

- [DONE] Inline user data produces a valid chart.
- [DONE] Approved tool data produces a valid chart.
- [DONE] Unsupported types produce no artifact.
- [DONE] Missing data is requested rather than invented.
- [DONE] Summary-only follow-ups avoid artifact retrieval.
- [DONE] Exact follow-ups use bounded deterministic retrieval.
- [DONE] The chart agent imports no MCP client, database client, renderer, or provider SDK.

---

## [DONE] Phase 8: Orchestration, Session, and Prompt-Context Integration

### Objective

Route artifacts to clients and summaries to context without cross-contamination.

### Tasks

### [DONE] 8.1 Core Result Extensions

1. [DONE] Extend `AgentResult` additively with:
   - `artifacts`;
   - `context_contributions`.
2. [DONE] Extend `OrchestrationResult` additively with the same fields.
3. [DONE] Preserve defaults so existing agents require no changes.
4. [DONE] Add artifact and contribution count limits.

### [DONE] 8.2 Orchestration

1. [DONE] Route chart requests and follow-ups to the chart agent/strategy.
2. [DONE] Propagate `ChartArtifact` to result artifacts.
3. [DONE] Propagate only `ChartContextSummary` as a context contribution.
4. [DONE] Add a guard that rejects any context contribution containing artifact inline data.
5. [DONE] Keep artifact data out of normal conversation history and prompt assembly.
6. [DONE] Include relevant recent summaries using:
   - explicit artifact/title reference;
   - recency;
   - active use case;
   - token budget.
7. [DONE] Apply context compaction and eviction.
8. [DONE] Emit internal summary-created events.

### [DONE] 8.3 Session Service

1. [DONE] Persist compact summaries at stable turn completion boundaries.
2. [DONE] Do not write state on every streaming delta.
3. [DONE] Extend safe history projection only if the frontend needs artifact metadata for reload; do not include full chart data in message text.
4. [DONE] Integrate visualization artifact cleanup with reset.
5. [DONE] Preserve concurrency rules for simultaneous stream/reset.
6. [DONE] Migrate existing workflow-state documents additively:
   - missing `visualization_context` means empty;
   - old sessions remain readable.

### [DONE] 8.4 Prompt Assembly

Include:

- [DONE] selected relevant summaries;
- [DONE] artifact IDs and titles;
- [DONE] fields and counts;
- [DONE] computed insights;
- [DONE] retrieval references.

Exclude:

- [DONE] `ChartArtifact.data`;
- [DONE] full row/point/bin lists;
- [DONE] raw uploaded-file content;
- [DONE] raw tool results;
- [DONE] inline renderer options containing full data.

### Deliverables

- [DONE] Additive result models
- [DONE] Orchestration routing
- [DONE] Context-contribution guard
- [DONE] Visualization context selector
- [DONE] Workflow-state serialization/migration
- [DONE] Session reset integration
- [DONE] Prompt assembly tests
- [DONE] Backward-compatibility tests

### Exit Criteria

- [DONE] Existing non-chart agents still work unchanged.
- [DONE] Chart artifacts appear in orchestration results.
- [DONE] Only chart summaries enter prompt context.
- [DONE] Old sessions load without migration failure.
- [DONE] Reset removes session visualization state.
- [DONE] Streaming finalization persists summaries once.

### Validation

- [DONE] `backend/.venv/Scripts/python.exe -m pytest tests/unit/agents/test_chart_agent.py tests/unit/orchestration/test_runtime.py tests/unit/orchestration/test_usecase_router.py tests/unit/session/test_session_stream_chat.py`

---

## [DONE] Phase 9: API, SSE, and Conditional Artifact Retrieval

### Objective

Expose stable visualization delivery through the existing frontend boundary.

### Tasks

### 9.1 REST

1. [DONE] Add optional `artifacts` to the existing chat response DTO.
2. [DONE] Map `OrchestrationResult.artifacts` to the response.
3. [DONE] Do not expose raw `context_contributions`.
4. [DONE] Preserve text-only response compatibility.
5. [DONE] Add safe metadata:
   - [DONE] trace ID remains available on the response envelope;
   - [DONE] context summary added flag;
   - [DONE] artifact count;
   - [DONE] optional context summary ID, not content.

### 9.2 SSE

1. [DONE] Preserve current text event names.
2. [DONE] Add:
   - [DONE] `artifact.started`;
   - [DONE] `artifact.completed`;
   - [DONE] `artifact.failed` support in the public encoder.
3. [DONE] Keep `context_summary.created` internal unless an admin/debug mode explicitly needs it.
4. [DONE] Include the complete inline artifact in one bounded completed event, or provide a reference-mode artifact descriptor.
5. [DONE] Do not split raw chart rows into token-like deltas.
6. [DONE] Ensure event ordering:

```text
message start
optional text deltas
artifact.started
artifact.completed | artifact.failed
message completed
```

7. [DONE] Add event idempotency using `artifact_id`.
8. [DONE] Handle client disconnect/cancellation without storing a partially validated artifact as completed.

### 9.3 Reference Mode

[DONE] When reference mode is enabled, add a protected route such as:

```text
GET /artifacts/{artifact_id}
```

Requirements:

- [DONE] session/user ownership validation;
- [DONE] TTL checks;
- [DONE] policy check;
- [DONE] bounded data fields;
- [DONE] ETag or cache-control where appropriate;
- [DONE] no source credentials or internal storage URI exposure;
- [DONE] normalized not-found/expired errors.

[DONE] Do not add the route when V1 is configured inline-only.

### 9.4 OpenAPI and Capabilities

1. [DONE] Update OpenAPI schemas.
2. [DONE] Add visualization capabilities.
3. [DONE] Add example response and SSE fixtures.
4. [DONE] Document compatibility behavior.

### Deliverables

- [DONE] Updated response DTOs
- [DONE] REST mapping
- [DONE] SSE artifact events
- [DONE] Optional artifact retrieval route
- [DONE] OpenAPI changes
- [DONE] API contract tests
- [DONE] Compatibility tests for text-only clients

### Exit Criteria

- [DONE] `/chat` returns answer plus zero or more valid artifacts.
- [DONE] `/chat/stream` emits one completed event per artifact.
- [DONE] Existing clients that ignore artifacts continue to work.
- [DONE] Reference-mode artifacts are fetchable only by authorized scope.
- [DONE] API never copies artifact data into prompt history.

### Files created or updated

- [DONE] `backend/app/api/schemas.py`
- [DONE] `backend/app/api/sse.py`
- [DONE] `backend/app/api/routes_artifacts.py`
- [DONE] `backend/app/config/bootstrap.py`
- [DONE] `backend/app/foundation/container.py`
- [DONE] `backend/app/main.py`
- [DONE] `backend/app/orchestration/runtime.py`
- [DONE] `backend/app/policy/stream_policy.py`
- [DONE] `backend/app/session/mapping.py`
- [DONE] `backend/app/session/models.py`
- [DONE] `backend/app/session/service.py`
- [DONE] `backend/app/session/streaming.py`
- [DONE] `backend/tests/fixtures/config/visualization_public_artifacts_enabled.yaml`
- [DONE] `backend/tests/fixtures/visualization/sse_artifact_events_v1.jsonl`
- [DONE] `backend/tests/unit/api/test_artifact_route.py`
- [DONE] `backend/tests/unit/api/test_chat_route.py`
- [DONE] `backend/tests/unit/api/test_chat_schemas.py`
- [DONE] `backend/tests/unit/api/test_sse_formatting.py`
- [DONE] `backend/tests/unit/api/test_stream_route.py`
- [DONE] `backend/tests/unit/policy/test_stream_policy.py`
- [DONE] `backend/tests/unit/session/test_session_stream_chat.py`
- [DONE] `backend/tests/unit/visualization/test_visualization_phase0_fixtures.py`

### Implementation outcomes

- [DONE] Extended the public chat response DTO with additive `data.artifacts` support backed by session/orchestration result propagation.
- [DONE] Added frontend-safe visualization response metadata including artifact counts, delivery mode, and summary IDs without exposing raw context contributions.
- [DONE] Added SSE artifact lifecycle events with `artifact_id`-based event IDs while preserving the existing `response.*` text event family.
- [DONE] Preserved visualization artifacts and context contributions through streaming finalization so chart turns keep the same delivery contract as non-streaming turns.
- [DONE] Added a shared visualization runtime/store at the composition root and passed the shared gateway into orchestration/session paths.
- [DONE] Added a conditional `GET /artifacts/{artifact_id}` route that reuses the shared visualization gateway for policy-checked, session-scoped retrieval.
- [DONE] Added focused route, SSE, policy, and golden-fixture coverage for the public visualization delivery surface.

### Validation

- [DONE] `backend/.venv/Scripts/python.exe -m pytest tests/unit/api/test_chat_schemas.py tests/unit/api/test_chat_route.py`
- [DONE] `backend/.venv/Scripts/python.exe -m pytest tests/unit/api/test_sse_formatting.py tests/unit/api/test_stream_route.py tests/unit/policy/test_stream_policy.py tests/unit/session/test_session_stream_chat.py tests/unit/visualization/test_visualization_phase0_fixtures.py`
- [DONE] `backend/.venv/Scripts/python.exe -m pytest tests/unit/api/test_artifact_route.py tests/unit/api/test_chat_route.py`

---

## [DONE] Phase 10: Verification, Golden Fixtures, and Cross-Tier Compatibility

### Objective

Prove the feature across isolated modules and the full three-tier path.

### Files created or updated

- [DONE] `backend/tests/integration/visualization/test_session_chart_pipeline.py`
- [DONE] `backend/tests/contract/visualization/test_golden_fixture_catalog.py`
- [DONE] `backend/tests/fixtures/visualization/golden_fixture_catalog_v1.json`
- [DONE] `backend/tests/fixtures/visualization/missing_data_response_v1.json`
- [DONE] `backend/tests/fixtures/visualization/reference_mode_large_series_v1.json`
- [DONE] `backend/tests/fixtures/visualization/expired_artifact_error_v1.json`
- [DONE] `frontend/tests/test_visualization_phase0_contract.py`
- [DONE] `docs/decisions/visualization-phase10-compatibility-report.md`

### Implementation outcomes

- [DONE] Added a real backend visualization integration test that exercises `SessionService -> OrchestrationRuntime -> ChartAgent -> VisualizationGateway` using the shared MCP structured dataset fixture.
- [DONE] Verified follow-up behavior answers from persisted chart summaries plus deterministic retrieval and keeps raw tool rows out of the follow-up prompt.
- [DONE] Published a shared phase-10 golden fixture catalog covering the minimum required chart, error, and reference-mode cases.
- [DONE] Added backend contract tests that resolve the catalog against current chart fixtures and public response envelopes.
- [DONE] Updated the frontend shared-fixture test to the current additive SSE artifact lifecycle contract (`artifact.started` and `artifact.completed`).
- [DONE] Published a phase-10 compatibility report under `docs/decisions/`.

### Test Layers

### 10.1 Unit Tests

- [DONE] alias normalization;
- [DONE] registry lookup;
- [DONE] renderer support;
- [DONE] every validator;
- [DONE] artifact builder;
- [DONE] summary builder;
- [DONE] token compaction;
- [DONE] store TTL and ownership;
- [DONE] deterministic computations;
- [DONE] policy decisions;
- [DONE] error mapping;
- [DONE] result/context separation.

### 10.2 Agent Tests

- [DONE] inline bar chart;
- [DONE] time-series chart;
- [DONE] missing data;
- [DONE] unsupported type;
- [DONE] invalid pie data;
- [DONE] tool-based structured dataset;
- [DONE] truncated tool result;
- [DONE] summary-only follow-up;
- [DONE] exact-data follow-up;
- [DONE] ambiguous chart reference;
- [DONE] full-dataset request denied by policy;
- [DONE] sample data disabled/enabled.

### 10.3 Integration Tests

```text
POST /chat
  -> SessionService
  -> OrchestrationRuntime
  -> ChartAgent
  -> VisualizationGateway
  -> ChartArtifactEnvelope
  -> ChatResponse.artifacts
  -> WorkflowStateStore receives ChartContextSummary only
```

Follow-up:

```text
POST /chat
  -> load recent ChartContextSummary
  -> route to ChartAgent
  -> answer from summary OR retrieve bounded facts
  -> no full dataset added to prompt
```

### 10.4 Contract Tests

Validate shared golden fixtures against:

- [DONE] backend JSON schema;
- [DONE] MCP structured dataset adapter;
- [DONE] frontend artifact and SSE parser compatibility;
- [DONE] shared cross-tier golden fixture catalog compatibility.

### 10.5 Security and Boundary Tests

- [DONE] secret-like metadata rejected/redacted;
- [DONE] cross-session artifact access denied;
- [DONE] unknown tool not callable;
- [DONE] unknown renderer/type denied;
- [DONE] artifact rows absent from traces;
- [DONE] artifact rows absent from prompt captures;
- [DONE] chart agent dependency imports enforced.

### 10.6 Performance Tests

Measure:

- [DONE] artifact serialization size;
- [DONE] reference-mode threshold;
- [DONE] bounded artifact retrieval shape;
- [DONE] context summary selection under budget.

### Golden Fixtures

At minimum:

```text
bar_income_expense
line_monthly_revenue
pie_revenue_mix
scatter_ad_spend_revenue
histogram_latency
heatmap_incident_hour
gantt_project_plan
table_operational_summary
unsupported_chart_type
missing_data
reference_mode_large_series
expired_artifact
```

- [DONE] bar_income_expense
- [DONE] line_monthly_revenue
- [DONE] pie_revenue_mix
- [DONE] scatter_ad_spend_revenue
- [DONE] histogram_latency
- [DONE] heatmap_incident_hour
- [DONE] gantt_project_plan
- [DONE] table_operational_summary
- [DONE] unsupported_chart_type
- [DONE] missing_data
- [DONE] reference_mode_large_series
- [DONE] expired_artifact

### Deliverables

- [DONE] Focused unit/integration/contract and frontend consumer suites
- [DONE] Golden fixture catalog
- [DONE] Prompt-leak regression test
- [DONE] Cross-tier compatibility report
- [DONE] Performance baseline
- [DONE] Security test report

### Exit Criteria

- [DONE] All test layers pass.
- [DONE] Frontend shared consumers accept the same artifact and SSE fixtures as the backend.
- [DONE] Tool data contract is accepted without ad hoc transformations.
- [DONE] No test detects full chart rows in context or traces.
- [DONE] Performance and payload limits are documented and enforced.

---

## Phase 11: Rollout and Operational Readiness

### Objective

Enable visualization safely without destabilizing the working system.

### Tasks

1. Add feature flags:
   - global visualization;
   - per use case;
   - per agent;
   - reference mode;
   - tool data;
   - uploaded-file data;
   - exact follow-up retrieval;
   - selected chart types.
2. Deploy with visualization disabled by default.
3. Enable in a development environment using fixtures.
4. Enable inline mode for internal users.
5. Enable tool-based data after MCP integration smoke tests.
6. Enable reference mode only after authorization and TTL tests.
7. Monitor:
   - unsupported/missing-data rate;
   - validation failures;
   - artifact size;
   - build latency;
   - context token use;
   - retrieval misses;
   - policy denials;
   - frontend render errors reported through client telemetry.
8. Establish rollback:
   - disable visualization flag;
   - leave additive DTO fields in place;
   - stop routing to `chart_agent`;
   - retain old text-only behavior;
   - clear session-scoped chart caches as needed.
9. Publish runbooks for:
   - renderer mismatch;
   - unsupported spec version;
   - artifact expiration;
   - oversized data;
   - MCP reporting-tool failure;
   - summary build failure;
   - cross-session access alert.

### Deliverables

- Feature flags
- Deployment configuration
- Dashboards and alerts
- Runbooks
- Rollback procedure
- Production readiness review
- Support documentation

### Exit Criteria

- Visualization can be disabled without rolling back the entire backend.
- Text-only chat remains operational during visualization failure.
- Alerts and runbooks cover primary failure modes.
- Production enablement is scoped and reversible.
- Operational owners accept the feature.

---

## 9. Configuration Example

```yaml
visualization:
  enabled: false
  default_renderer: echarts
  artifact_spec_version: "1.0"

  allowed_renderers:
    - echarts

  allowed_chart_types:
    - bar
    - grouped_bar
    - stacked_bar
    - horizontal_bar
    - line
    - multi_line
    - area
    - pie
    - donut
    - scatter
    - bubble
    - histogram
    - box_plot
    - heatmap
    - treemap
    - waterfall
    - gantt
    - radar
    - table

  limits:
    max_artifacts_per_response: 3
    max_rows_inline: 5000
    max_rows_artifact_store: 50000
    max_series: 12
    max_categories: 100
    max_metadata_bytes: 8192

  context_summary:
    enabled: true
    mode: summary_only
    max_tokens_per_chart_summary: 600
    max_chart_summaries_per_session_context: 5
    max_total_visualization_context_tokens: 1800
    include_data_ref: true
    include_aggregate_stats: true
    include_extrema: true
    include_trend_summary: true
    include_sample_rows: false
    max_sample_rows: 0
    eviction_policy: most_recent_relevant

  artifact_store:
    enabled: true
    provider: session_cache
    ttl_seconds: 7200
    allow_reference_mode: true

  data_sources:
    user_provided: true
    workflow_state: true
    uploaded_file: true
    memory: true
    tool: true
    sample_data: false

agents:
  chart_agent:
    enabled: false
    llm_profile: planning_reasoning
    allowed_tools:
      - reporting.query_metric_series
      - finance.get_monthly_summary

policy:
  visualization:
    enabled: false
    deny_unknown_chart_types: true
    deny_unknown_renderers: true
    require_data_source: true
    allow_exact_followup_retrieval: true
    allow_full_dataset_in_context: false
    allow_export: false
```

---

## 10. API Contract Example

```json
{
  "answer": "Here is a grouped bar chart comparing income and expense.",
  "session_id": "session_123",
  "agent_name": "chart_agent",
  "strategy_name": "direct_agent",
  "trace_id": "trace_123",
  "artifacts": [
    {
      "artifact_id": "chart_01",
      "type": "chart",
      "chart_type": "grouped_bar",
      "title": "Income vs Expense - Last 6 Months",
      "description": "Monthly income and expense comparison.",
      "renderer": "echarts",
      "spec_version": "1.0",
      "data_mode": "inline",
      "data": [
        {"month": "Jan", "income": 5200, "expense": 4100}
      ],
      "data_ref": null,
      "encoding": {
        "x": "month",
        "y": ["income", "expense"]
      },
      "options": {
        "currency": "USD",
        "stacked": false
      },
      "warnings": [],
      "metadata": {
        "source": "user_provided"
      }
    }
  ],
  "metadata": {
    "context_summary_added": true,
    "artifact_count": 1
  }
}
```

The corresponding stored context must be a compact summary, not a copy of `artifacts[0].data`.

---

## 11. Risk Register

| Risk | Impact | Mitigation |
|---|---|---|
| Artifact data enters prompt history | Context exhaustion and data exposure | Explicit `ContextContribution`, guards, prompt-leak tests |
| Frontend/backend chart support diverges | Render failure | Versioned registry, capabilities, shared fixtures |
| LLM invents values | Misleading chart | Data-source requirement and deterministic validation |
| Tool result too large | Latency and payload failure | Aggregation-first queries, bounds, reference mode |
| Cross-session artifact access | Data leak | Session/user scope checks in store and route |
| Summary too large | Context growth | Token budget and compaction |
| Unsupported chart returns fake artifact | User confusion | Registry validation before build |
| Existing clients break | Regression | Additive fields and unchanged text event names |
| Workflow-state grows excessively | Storage instability | Store summaries only; cache full data separately |
| Renderer spec becomes executable | XSS/security risk | Neutral allowlisted contract and frontend safe adapter |
| Artifact expires before follow-up | Poor UX | TTL metadata and regenerate guidance |
| Policy and validator limits differ | Inconsistent behavior | Shared typed settings and boundary tests |

---

## 12. Definition of Done

The backend visualization implementation is complete when:

- Natural-language chart requests route to the chart capability.
- All enabled chart types are explicit in the registry and frontend-compatible.
- Unsupported types return a clear response and no artifact.
- Missing real data is requested and never fabricated.
- `VisualizationGateway` produces a separate artifact and context summary.
- The frontend receives `ChartArtifact`.
- Prompt assembly receives only `ChartContextSummary`.
- Full row-level data is absent from context and traces by default.
- Follow-up questions use summaries first and bounded deterministic retrieval second.
- Session reset clears visualization summaries and session-scoped artifacts.
- Policy controls chart types, renderers, data sources, limits, and retrieval.
- REST and SSE contracts are additive and backward-compatible.
- Health and capabilities expose safe visualization status.
- Golden fixtures pass backend, MCP adapter, and frontend contract tests.
- The feature is configuration-driven, observable, reversible, and production-ready.

---

## 13. Implementation Checklist

### Contracts
- [DONE] Freeze artifact and summary v1 schemas.
- [DONE] Freeze additive REST and SSE contracts.
- [DONE] Publish shared golden fixtures.

### Core
- [DONE] Add models, errors, and settings.
- [DONE] Add chart registry and aliases.
- [DONE] Add renderer capabilities.
- [DONE] Add validators.
- [DONE] Add artifact builder.
- [DONE] Add summary builder.
- [DONE] Add artifact store and computations.
- [DONE] Add visualization gateway.

### Runtime
- [DONE] Add visualization policy.
- [ ] Add chart agent.
- [ ] Add data-resolution adapters.
- [ ] Extend agent and orchestration results.
- [ ] Persist context summaries.
- [ ] Exclude artifacts from prompt history.
- [DONE] Integrate reset.

### API
- [ ] Add artifacts to chat response.
- [ ] Add artifact SSE events.
- [ ] Add optional reference retrieval route.
- [ ] Update OpenAPI, health, and capabilities.

### Quality
- [ ] Unit tests.
- [ ] Agent tests.
- [ ] Integration tests.
- [ ] Contract tests.
- [ ] Security and prompt-leak tests.
- [ ] Performance tests.
- [ ] End-to-end tests.
- [ ] Rollout and rollback runbooks.
