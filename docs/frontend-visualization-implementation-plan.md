# Frontend Visualization Implementation Plan

**Document:** `frontend-visualization-implementation-plan.md`  
**Version:** 1.0  
**Status:** Implementation-ready  
**Tier:** Frontend application  
**Primary source:** `backend-visualization-architecture.md` v1.1  
**Source alignment:** `pluggable_agentic_ai_overall_architecture.md`, `backend-api-architecture.md`, and the existing working frontend implementation  
**Assumption:** The Flask/HTML/CSS/JavaScript frontend, chat page, session handling, REST/SSE integration, admin capabilities/health views, and error display are already implemented and working.

Implementation note (2026-07-11): backend session-history replay now persists bounded first-class `message.artifacts` and mirrors them into `metadata.visualizations`; the current frontend history path remains compatible until a later cleanup switches its primary read path.

---

## 1. Purpose

This document provides the phased implementation plan for adding chart and graph rendering to the existing frontend tier.

The frontend must:

- Receive `ChartArtifact` objects from existing chat responses and SSE events.
- Validate artifact type, renderer, spec version, chart type, and payload bounds.
- Map the renderer-neutral backend contract to the configured browser chart library.
- Render charts in the chat conversation without executing backend-provided code.
- Support inline and, when enabled, reference-mode data.
- Preserve text-only chat compatibility.
- Handle streaming artifacts idempotently.
- Provide responsive, accessible, secure, and diagnosable chart UX.
- Use `/capabilities` to feature-gate supported types and versions.

The frontend must not:

- Select agents or strategies.
- Call MCP.
- Build backend chart summaries.
- Put chart datasets into prompts.
- Infer missing business values.
- Execute arbitrary JavaScript, HTML, or renderer specs returned by the backend.
- Treat chart metadata as trusted HTML.

---

## 2. Ownership Boundary

```text
Backend:
  validates data
  selects canonical chart type
  creates ChartArtifact
  creates ChartContextSummary
  enforces policy
  supplies inline data or data_ref

Frontend:
  validates client-facing artifact contract
  maps neutral artifact to renderer options
  renders and disposes chart instances
  handles loading/error/empty states
  provides responsive and accessible UX

MCP:
  supplies structured external data to backend only
```

The frontend receives `ChartArtifact`. It does not receive or recreate `ChartContextSummary` for model context.

---

## 3. Recommended Cross-Tier Sequence

| Integrated wave | Frontend work | Backend prerequisite | MCP prerequisite |
|---|---|---|---|
| 0 | Review and freeze artifact/SSE fixtures | `ChartArtifact` v1 and event contract frozen | None |
| 1 | Build parser, validator, and renderer adapter with fixtures | No live API required | None |
| 2 | Render all enabled chart types from fixtures | Registry/capabilities draft available | None |
| 3 | Integrate non-streaming chat artifacts | Backend `/chat` artifact response stable | None |
| 4 | Integrate SSE lifecycle and reference mode | Backend SSE and optional artifact route stable | Tool path may still use fixtures |
| 5 | Cross-tier tests with inline and MCP-sourced data | Full backend visualization path | Reporting tool available for tool-data scenario |
| 6 | Accessibility, performance, telemetry, rollout | Production limits finalized | Production tool controls finalized |

Frontend development should begin from shared golden fixtures after the backend contract freeze. It must not wait for the full backend or MCP implementation.

---

## 4. Recommended Frontend Additions

Adapt these logical paths to the existing frontend layout rather than restructuring unrelated code.

```text
frontend/
  app/
    static/
      js/
        visualization/
          artifact-model.js
          artifact-validator.js
          chart-registry.js
          chart-renderer.js
          echarts-adapter.js
          data-loader.js
          stream-controller.js
          chart-instance-store.js
          accessibility.js
          telemetry.js
      css/
        visualization.css

    templates/
      components/
        chart-artifact.html
        chart-loading.html
        chart-error.html
        chart-empty.html

  tests/
    unit/visualization/
    contract/visualization/
    integration/chat/
    e2e/visualization/
    fixtures/visualization/
```

Use the repository's established module/bundling convention. Do not introduce a new build system solely for visualization unless the existing frontend already requires it.

---

## 5. Renderer Decision

Recommended V1 browser renderer:

```text
Apache ECharts
```

Implementation pattern:

```text
ChartArtifact v1
  -> frontend artifact parser
  -> frontend chart registry
  -> ECharts adapter
  -> safe ECharts option object constructed locally
  -> chart instance
```

The frontend must not accept an arbitrary ECharts option object from the backend. It constructs the option object from allowlisted artifact fields.

Pin the renderer version according to the repository dependency policy. Do not depend on an unversioned CDN in production.

---

## 6. Supported V1 Chart Types

The frontend may advertise a type only when an adapter and tests exist.

| Canonical type | V1 frontend mapping |
|---|---|
| `bar` | vertical single-series bar |
| `grouped_bar` | vertical grouped multi-series bar |
| `stacked_bar` | stacked bar |
| `horizontal_bar` | horizontal bar |
| `line` | single-series line |
| `multi_line` | multi-series line |
| `area` | line with area fill |
| `pie` | pie series |
| `donut` | pie series with inner radius |
| `scatter` | x/y scatter |
| `bubble` | scatter with size encoding |
| `histogram` | pre-binned bars or locally binned only when contract explicitly permits |
| `box_plot` | ECharts boxplot input mapping |
| `heatmap` | cartesian heatmap |
| `treemap` | treemap hierarchy |
| `waterfall` | stacked/transparent helper-series mapping |
| `gantt` | approved custom-series mapping with fixed local implementation |
| `radar` | radar indicators and series |
| `table` | accessible HTML table component, not a chart canvas |

Candidate V2 types must remain disabled until both backend registry/validators and frontend adapters exist.

---

## 7. Phase Summary

| Phase | Name | Primary output | Depends on |
|---:|---|---|---|
| 0 | [DONE] Baseline and Contract Freeze | Shared fixtures and compatibility rules | Working frontend |
| 1 | [DONE] Renderer Dependency and Artifact Foundation | Parser, validator, registry, safe instance lifecycle | Phase 0 |
| 2 | [DONE] Chart-Type Adapters | Fixture rendering for all enabled V1 types | Phase 1 |
| 3 | [DONE] Chat UI Integration | Non-streaming artifact rendering | Phase 2 and backend REST contract |
| 4 | [DONE] SSE Artifact Lifecycle | Streaming-safe rendering | Phase 3 and backend SSE contract |
| 5 | [DONE] Reference-Mode Data Loading | Protected fetch and cache behavior | Phase 3; backend artifact route |
| 6 | [DONE] Session, History, Reset, and Multi-Artifact UX | Correct lifecycle in real conversations | Phases 3–5 |
| 7 | [DONE] Capabilities, Admin, and Feature Gating | Runtime compatibility controls | Backend health/capabilities |
| 8 | [DONE] Accessibility, Responsive UX, Security, and Performance | Production-quality chart experience | Phases 2–7 |
| 9 | Verification and Cross-Tier Tests | Contract and E2E evidence | Full stack |
| 10 | Rollout and Operations | Reversible production activation | Phase 9 |

---

# 8. Detailed Implementation Phases

## [DONE] Phase 0: Baseline and Contract Freeze

### Goal

Protect the existing chat UX and establish a repo-accurate frontend visualization contract before renderer work.

### Files created or updated

- [DONE] `docs/frontend-visualization-implementation-plan.md`
- [DONE] `docs/decisions/frontend-visualization-phase0.md`
- [DONE] `frontend/app/static/js/services/sse-client.js`
- [DONE] `frontend/tests/js/sse-client.test.mjs`
- [DONE] `frontend/app/settings.py`
- [DONE] `frontend/.env.example`
- [DONE] `frontend/tests/test_settings.py`
- [DONE] `frontend/tests/test_visualization_phase0_contract.py`
- [DONE] `frontend/tests/fixtures/visualization/README.md`
- [DONE] `frontend/tests/fixtures/visualization/unsupported_chart_artifact_v1.json`
- [DONE] `frontend/tests/fixtures/visualization/reference_mode_artifact_provisional_v1.json`
- [DONE] `frontend/tests/fixtures/visualization/expired_reference_error_provisional_v1.json`
- [DONE] `frontend/tests/fixtures/visualization/multi_artifact_chat_response_provisional_v1.json`

### Implementation outcomes

- [DONE] Ran the existing frontend baseline test suite and confirmed the current baseline is green.
- [DONE] Recorded the current frontend owners for message rendering, REST response handling, SSE dispatch, session storage, reset/history UX, capabilities/health loading, error feedback, and CSP in `docs/decisions/frontend-visualization-phase0.md`.
- [DONE] Reused the canonical backend visualization happy-path fixtures directly from `backend/tests/fixtures/visualization/` so the frontend and backend share the same artifact, chat-response, and SSE golden files.
- [DONE] Added frontend-local provisional edge fixtures for unsupported chart type, reference mode, expired reference, and multi-artifact response under `frontend/tests/fixtures/visualization/`.
- [DONE] Extended the frontend SSE client to preserve additive `response.artifact` frames without changing the current text-only chat flow.
- [DONE] Froze the frontend compatibility rules, renderer packaging decision, browser support matrix, and payload-limit defaults in `docs/decisions/frontend-visualization-phase0.md`.
- [DONE] Added frontend visualization payload-limit settings aligned with the backend Phase-0 defaults for artifacts, rows, series, and categories.

### Validation

- [DONE] `frontend/.venv/Scripts/python.exe -m pytest tests/test_frontend_js.py`
- [DONE] `frontend/.venv/Scripts/python.exe -m pytest tests/test_settings.py tests/test_visualization_phase0_contract.py`
- [DONE] `frontend/.venv/Scripts/python.exe -m pytest`

### Baseline issues carried forward

- The current frontend baseline does not yet include a separate browser E2E suite; Phase 0 relies on the existing page, proxy, and JS module coverage under `pytest`.
- Public reference-mode artifact fetch routes remain intentionally unfrozen until later backend/API and frontend phases.
- Unsupported-type, reference-mode, expired-reference, and multi-artifact edge fixtures are frontend-local provisional cases until the backend freezes those public contracts.

### Exit Criteria

- [DONE] Existing tests pass.
- [DONE] Frontend and backend use the same artifact fixtures for the canonical happy path.
- [DONE] Text-only chat behavior is unchanged while additive `response.artifact` events are accepted.
- [DONE] Renderer dependency packaging and CSP impact are decided through the existing self-hosted vendor strategy.
- [DONE] Unknown versions/types have a defined non-executing safe UX in the frontend decision record.

---

## [DONE] Phase 1: Renderer Dependency and Artifact Foundation

### Objective

Build the client-side foundation without connecting live chat.

### Files created or updated

- [DONE] `frontend/app/routes/pages.py`
- [DONE] `frontend/app/templates/visualization_foundation.html`
- [DONE] `frontend/app/static/vendor/echarts/echarts-5.5.1.min.js`
- [DONE] `frontend/app/static/js/visualization/artifact-model.js`
- [DONE] `frontend/app/static/js/visualization/artifact-validator.js`
- [DONE] `frontend/app/static/js/visualization/chart-registry.js`
- [DONE] `frontend/app/static/js/visualization/chart-instance-store.js`
- [DONE] `frontend/app/static/js/visualization/chart-components.js`
- [DONE] `frontend/app/static/js/visualization/echarts-adapter.js`
- [DONE] `frontend/app/static/js/visualization/chart-renderer.js`
- [DONE] `frontend/app/static/js/visualization/index.js`
- [DONE] `frontend/app/static/css/components/visualization.css`
- [DONE] `frontend/app/static/css/components/index.css`
- [DONE] `frontend/tests/js/visualization.test.mjs`
- [DONE] `frontend/tests/test_pages.py`
- [DONE] `frontend/tests/test_static_assets.py`

### Tasks

### [DONE] 1.1 Artifact Model and Validation

- [DONE] Implemented a client-side artifact model plus validator that checks `artifact_id`, `type`, canonical `chart_type`, `title`, `renderer`, `spec_version`, `data_mode`, `encoding`, `warnings`, `metadata`, and bounded `options`.
- [DONE] Added defense-in-depth validation for row count, field count, series count, category count, string length, finite numeric values, blocked prototype-pollution keys, script-like values, HTML event-handler field names, and same-origin `data_ref` paths.
- [DONE] Preserved backend authority while ensuring the browser rejects malformed, unsupported, or unsafe payloads before any renderer work begins.

### [DONE] 1.2 Chart Registry

- [DONE] Added a frontend chart registry with exact `chartType`/`renderer`/`specVersion` resolution.
- [DONE] Enforced duplicate rejection and unsupported renderer/spec rejection at registration time.
- [DONE] Registered the initial `grouped_bar` ECharts adapter as the Phase 1 foundation type while leaving the remaining V1 types disabled for Phase 2.

### [DONE] 1.3 Instance Lifecycle

- [DONE] Added a chart instance store keyed by `artifact_id` with `get`, `resize`, `dispose`, `disposeByMessage`, `disposeBySession`, and `disposeAll` support.
- [DONE] Prevented duplicate live renderer instances on the same element and disposed replaced instances deterministically.
- [DONE] Covered the lifecycle behavior with unit tests that verify replacement and session-scoped disposal.

### [DONE] 1.4 Base Renderer

- [DONE] Implemented `ChartRenderer.render(container, artifact)` with validation, adapter lookup, local option construction, ECharts initialization, resize binding, safe telemetry payloads, and disposable handles.
- [DONE] Added loading, empty, error, ready, unsupported, and deferred-reference states without executing backend-provided code.
- [DONE] Added an isolated `/visualization-foundation` page that loads the shared backend fixture and renders it through the Phase 1 frontend path only.

### Deliverables

- [DONE] Pinned self-hosted ECharts dependency (`5.5.1`) served from `frontend/app/static/vendor/echarts/`.
- [DONE] Artifact parser/validator.
- [DONE] Frontend chart registry.
- [DONE] Base renderer.
- [DONE] Chart instance store.
- [DONE] Loading/empty/error components.
- [DONE] Foundation unit tests.

### Validation

- [DONE] `node --test tests/js/visualization.test.mjs`
- [DONE] `frontend/.venv/Scripts/python.exe -m pytest tests/test_pages.py tests/test_static_assets.py tests/test_frontend_js.py`

### Phase 1 constraints carried forward

- Only the `grouped_bar` adapter is enabled in Phase 1. The remaining advertised V1 chart types stay disabled until Phase 2 adds their allowlisted mappings and tests.
- Reference-mode artifacts now validate safely and render a non-fetching deferred state, but protected reference-mode loading remains Phase 5 work.

### Exit Criteria

- [DONE] Valid artifact fixture renders in an isolated test page.
- [DONE] Invalid or malicious fixture is rejected.
- [DONE] No backend-provided code is executed.
- [DONE] Chart instances are disposed without leaks.
- [DONE] Unknown type/version shows a safe unsupported state.

---

## [DONE] Phase 2: Chart-Type Adapters

### Objective

Implement deterministic mappings for every V1 type enabled by backend capabilities.

### Implementation outcomes

- [DONE] Expanded the isolated frontend visualization page into a Phase 2 gallery that renders the shared backend `chart_validation_cases_v1.json` fixtures across every enabled V1 chart type.
- [DONE] Extended the frontend artifact validator to mirror the backend public encoding contract for bar, line, part-to-whole, point/distribution, matrix/hierarchy, specialized, and table artifacts before renderer work begins.
- [DONE] Registered safe adapters for all V1 canonical chart types, including a DOM-rendered semantic table path for `table` while keeping renderer-owned chart construction local to the browser.
- [DONE] Added shared local formatters for currency, decimals, percentages, compact values, temporal labels, and units so adapter output stays consistent without trusting backend HTML or executable payloads.
- [DONE] Added focused frontend JS and page coverage for the full V1 adapter matrix, invalid grouped encoding, null handling, non-temporal line categories, table rendering, and the Phase 2 gallery route.

### Common Adapter Rules

Every adapter must:

- use allowlisted artifact fields;
- escape titles, labels, descriptions, and tooltips;
- use stable defaults;
- honor backend encoding;
- avoid changing numeric meaning;
- support empty/null handling;
- support responsive resizing;
- expose accessible fallback text/table where practical;
- emit no network requests;
- be covered by fixture tests.

### Adapter Deliverables

1. Bar family:
   - [DONE] bar;
   - [DONE] grouped bar;
   - [DONE] stacked bar;
   - [DONE] horizontal bar.
2. Line family:
   - [DONE] line;
   - [DONE] multi-line;
   - [DONE] area.
3. Part-to-whole:
   - [DONE] pie;
   - [DONE] donut.
4. Point/distribution:
   - [DONE] scatter;
   - [DONE] bubble;
   - [DONE] histogram;
   - [DONE] box plot.
5. Matrix/hierarchy:
   - [DONE] heatmap;
   - [DONE] treemap.
6. Specialized:
   - [DONE] waterfall;
   - [DONE] gantt;
   - [DONE] radar.
7. Table:
   - [DONE] semantic HTML table;
   - [DONE] column headers;
   - [DONE] numeric formatting;
   - [DONE] horizontal overflow;
   - [DONE] row-limit notice.

### Formatting

Add local formatters driven by safe artifact options:

- [DONE] currency code;
- [DONE] decimal precision;
- [DONE] percentages;
- [DONE] date/time labels;
- [DONE] compact numbers;
- [DONE] units.

Do not infer or override units when the artifact does not provide them.

### Deliverables

- [DONE] One adapter per enabled canonical type
- [DONE] Shared axis/legend/tooltip/format helpers
- [DONE] Snapshot or structural option tests
- [DONE] Shared backend validation-case gallery fixtures for visual verification
- [DONE] Empty/null/large-label tests
- [DONE] Table component

### Exit Criteria

- [DONE] Every advertised V1 chart type renders from a golden fixture.
- [DONE] Adapter output contains no backend-provided executable payload.
- [DONE] Invalid encoding fails with a chart-level error in the isolated renderer path.
- [DONE] Shared validation fixtures are available for manual visual verification in the Phase 2 gallery.
- [DONE] Frontend capability list exactly matches implemented adapters.

### Validation

- [DONE] `node --test tests/js/visualization.test.mjs`
- [DONE] `frontend/.venv/Scripts/python.exe -m pytest tests/test_pages.py tests/test_frontend_js.py`

---

## [DONE] Phase 3: Non-Streaming Chat UI Integration

### Objective

Render chart artifacts returned from the existing `/chat` response.

### Files created or updated

- [DONE] `frontend/app/static/js/chat/artifacts.js`
- [DONE] `frontend/app/static/js/chat/index.js`
- [DONE] `frontend/app/static/js/chat/conversation.js`
- [DONE] `frontend/app/static/js/chat/requests.js`
- [DONE] `frontend/app/templates/chat.html`
- [DONE] `frontend/app/static/css/pages/chat/conversation.css`
- [DONE] `frontend/tests/js/chat-artifacts.test.mjs`
- [DONE] `frontend/tests/test_pages.py`

### Implementation outcomes

- [DONE] Loaded the pinned self-hosted ECharts runtime on the chat page and exposed the frontend visualization artifact, row, series, and category limits through the existing chat workspace shell.
- [DONE] Added a dedicated chat artifact controller that reuses the Phase 1 and Phase 2 visualization renderer, enforces `max_artifacts_per_response`, and renders artifacts in response order without storing duplicate inline datasets in chat runtime state.
- [DONE] Extended the non-streaming chat success path to preserve the existing assistant text rendering while mounting a per-message artifact region from `payload.data.artifacts`.
- [DONE] Associated rendered charts with assistant message ID, session ID, and artifact ID through DOM datasets plus the shared `ChartInstanceStore` lifecycle hooks.
- [DONE] Added user-visible failure and truncation notices so failed artifacts keep their title/description scaffolding, surface backend warnings, and never hide the text answer.
- [DONE] Disposed rendered chart instances when the conversation thread is cleared so resets, deletes, and history reloads do not leak live renderer instances.
- [DONE] Added focused frontend JS and page coverage for artifact-cap enforcement, fallback notices, cleanup, and chat page runtime asset/config exposure.

### Tasks

1. [DONE] Extend the response handler to read optional `artifacts`.
2. [DONE] Preserve current answer rendering.
3. [DONE] Add an artifact region to the assistant message.
4. [DONE] For each artifact:
   - [DONE] create a stable container;
   - [DONE] show loading state;
   - [DONE] validate;
   - [DONE] render;
   - [DONE] show warnings;
   - [DONE] show chart-level error if rendering fails.
5. [DONE] Support zero, one, or multiple artifacts.
6. [DONE] Enforce `max_artifacts_per_response` defensively.
7. [DONE] Order artifacts as received.
8. [DONE] Associate every chart with:
   - [DONE] message ID;
   - [DONE] session ID;
   - [DONE] artifact ID.
9. [DONE] Store only metadata needed for client lifecycle; do not duplicate large inline data unnecessarily.
10. [DONE] Add user-visible fallback:
    - [DONE] title;
    - [DONE] description;
    - [DONE] backend warning;
    - [DONE] “chart could not be displayed” message.
11. [DONE] Do not display raw JSON by default.
12. [DONE] Keep text answer visible even when all artifacts fail.
13. [DONE] Add safe trace ID display only if the existing UI supports it.

### Recommended Message Structure

```html
<article class="chat-message assistant">
  <div class="message-text"></div>
  <section class="message-artifacts" aria-label="Visualizations">
    <figure class="chart-artifact">
      <figcaption></figcaption>
      <div class="chart-container"></div>
      <div class="chart-status" aria-live="polite"></div>
    </figure>
  </section>
</article>
```

### Deliverables

- [DONE] Chat response integration
- [DONE] Artifact message component
- [DONE] Multi-artifact rendering
- [DONE] Warning/error UX
- [DONE] Non-streaming integration tests

### Validation

- [DONE] `node --test tests/js/chat-artifacts.test.mjs`
- [DONE] `node --test tests/js/chat-artifacts.test.mjs tests/js/visualization.test.mjs`
- [DONE] `frontend/.venv/Scripts/python.exe -m pytest tests/test_pages.py -k chat_page_renders_phase_9_workspace_shell`
- [DONE] `frontend/.venv/Scripts/python.exe -m pytest tests/test_frontend_js.py tests/test_pages.py`

### Exit Criteria

- [DONE] Existing text-only responses render unchanged.
- [DONE] A chart response shows text plus chart.
- [DONE] Multiple artifacts render independently.
- [DONE] One failed chart does not break the message or other charts.
- [DONE] Artifact data is not inserted into the chat input or sent back automatically.

---

## [DONE] Phase 4: SSE Artifact Lifecycle

### Objective

Support charts delivered through the existing streaming chat path.

### Files created or updated

- [DONE] `frontend/app/static/js/chat/artifacts.js`
- [DONE] `frontend/app/static/js/chat/requests.js`
- [DONE] `frontend/app/static/js/services/sse-client.js`
- [DONE] `frontend/tests/js/chat-artifacts.test.mjs`
- [DONE] `frontend/tests/js/sse-client.test.mjs`

### Implementation outcomes

- [DONE] Extended the chat visualization controller with a streaming artifact lifecycle that creates placeholder shells on `artifact.started`, renders exactly once on `artifact.completed`, shows chart-level failures on `artifact.failed`, and reuses the existing Phase 1 and Phase 2 renderer path.
- [DONE] Added per-message SSE artifact state with event-id replay protection, artifact-id deduplication, bounded buffering for not-yet-attached message targets, and safe terminal handling so malformed artifact events fail only that artifact lifecycle.
- [DONE] Wired the streaming request loop to preserve the existing text stream, synchronize message session and trace metadata as SSE frames arrive, keep streamed charts mounted through normal stream completion, and clean up partial artifact state on fallback, cancellation, and stream errors.
- [DONE] Extended focused frontend JS coverage for additive `artifact.started`, `artifact.completed`, and `artifact.failed` frames plus replay, preservation, and cancellation behavior.

### Tasks

1. [DONE] Extend the existing SSE dispatcher with additive events:
   - [DONE] `artifact.started`;
   - [DONE] `artifact.completed`;
   - [DONE] `artifact.failed`.
2. [DONE] Preserve existing text events exactly.
3. [DONE] On `artifact.started`:
   - [DONE] create placeholder by `artifact_id`;
   - [DONE] show loading status;
   - [DONE] do not initialize a chart yet.
4. [DONE] On `artifact.completed`:
   - [DONE] validate event;
   - [DONE] obtain complete inline artifact or reference descriptor;
   - [DONE] render exactly once;
   - [DONE] replace loading status.
5. [DONE] On `artifact.failed`:
   - [DONE] show chart-level failure;
   - [DONE] preserve text stream.
6. [DONE] On reconnect/replay:
   - [DONE] use event ID and artifact ID for idempotency;
   - [DONE] do not duplicate chart containers or instances.
7. [DONE] Buffer completed artifact events only when the message container is not ready.
8. [DONE] Dispose partial instances on cancellation, navigation, or session reset.
9. [DONE] Ignore internal `context_summary.created` unless an authorized debug view explicitly uses its metadata.
10. [DONE] Define completion ordering and race handling.
11. [DONE] Add a maximum buffered event count and payload size.
12. [DONE] Ensure a malformed artifact event closes only that artifact lifecycle, not the entire chat stream unless the envelope itself is invalid.

### Deliverables

- [DONE] SSE artifact controller
- [DONE] Placeholder component
- [DONE] Idempotency and replay handling
- [DONE] Cancellation cleanup
- [DONE] Streaming integration tests
- [DONE] Reconnect tests

### Validation

- [DONE] `node --test tests/js/chat-artifacts.test.mjs tests/js/sse-client.test.mjs`

### Exit Criteria

- [DONE] Streamed text and chart render in the correct message.
- [DONE] Each artifact renders once.
- [DONE] Replayed events do not duplicate charts.
- [DONE] Failed artifact does not fail the text response.
- [DONE] Reset/navigation disposes pending instances.
- [DONE] Existing non-artifact streams are unaffected.

---

## [DONE] Phase 5: Reference-Mode Data Loading

### Objective

Render artifacts whose data is retrieved through a protected backend reference.

This phase is conditional. Skip it when the V1 backend is inline-only.

### Files created or updated

- [DONE] `frontend/app/static/js/services/api-client.js`
- [DONE] `frontend/app/static/js/visualization/data-loader.js`
- [DONE] `frontend/app/static/js/visualization/chart-renderer.js`
- [DONE] `frontend/app/static/js/chat/artifacts.js`
- [DONE] `frontend/tests/js/visualization.test.mjs`
- [DONE] `frontend/tests/js/chat-artifacts.test.mjs`
- [DONE] `docs/frontend-visualization-implementation-plan.md`

### Tasks

1. [DONE] Implement `VisualizationDataLoader`.
2. [DONE] Accept only same-origin V1 `data_ref` paths and normalize future configured backend-origin references at the loader boundary.
3. [DONE] Never fetch arbitrary external URLs from artifact metadata.
4. [DONE] Attach existing frontend auth/session headers through the standard API client.
5. [DONE] Handle:
   - [DONE] loading;
   - [DONE] success;
   - [DONE] 401/403;
   - [DONE] 404/expired;
   - [DONE] 409/version mismatch;
   - [DONE] 413/too large;
   - [DONE] 429;
   - [DONE] timeout;
   - [DONE] cancellation.
6. [DONE] Validate fetched data with the same artifact/data schema.
7. [DONE] Use request cancellation when the message is removed/reset.
8. [DONE] Add bounded memory cache by artifact ID and ETag.
9. [DONE] Respect backend cache headers.
10. [DONE] Do not persist sensitive chart data to local storage by default.
11. [DONE] Prevent reference substitution across sessions.
12. [DONE] Add retry only for safe transient failures.
13. [DONE] Show regeneration guidance when expired.

### Implementation outcomes

- [DONE] Extended the shared frontend API client with session-aware detailed JSON fetch support so protected artifact requests keep same-origin credentials, attach `X-Session-Id`, and avoid double-prefixing already rooted `/ui-api/...` references.
- [DONE] Added `VisualizationDataLoader` with protected reference fetch validation, timeout handling, bounded safe retry, cache-control and ETag-aware in-memory caching, and response/session identity checks before any render path consumes fetched rows.
- [DONE] Updated `ChartRenderer` so reference-mode artifacts stay in the existing chart shell, load asynchronously into the same placeholder, and cancel pending fetches on per-artifact, per-message, per-session, and global cleanup flows.
- [DONE] Updated the chat visualization controller so streamed reference artifacts treat `loading_reference` as a terminal artifact lifecycle state, preventing replayed completed events from issuing duplicate protected fetches.
- [DONE] Added focused JS coverage for standard API client header injection, reference artifact caching, reference renderer success, reference fetch cancellation, and streamed reference-mode dedupe.

### Validation

- [DONE] `node --test tests/js/visualization.test.mjs tests/js/chat-artifacts.test.mjs`

### Deliverables

- [DONE] Protected data loader
- [DONE] Same-origin/reference validation
- [DONE] Cancellation and timeout
- [DONE] Bounded in-memory cache
- [DONE] Reference-mode UX
- [DONE] Security and integration tests

### Exit Criteria

- [DONE] Reference artifact renders after authorized fetch.
- [DONE] Cross-session or arbitrary URL fetch is blocked.
- [DONE] Expired artifact shows a clear message.
- [DONE] Sensitive data is not persisted in local storage.
- [DONE] Reset cancels and clears pending reference fetches.

---

## [DONE] Phase 6: Session, History, Reset, and Multi-Artifact UX

### Objective

Make visualization behave correctly throughout the existing conversation lifecycle.

### Tasks

1. [DONE] On session reset:
   - [DONE] dispose chart instances;
   - [DONE] cancel pending data fetches;
   - [DONE] clear client artifact metadata;
   - [DONE] clear placeholders;
   - [DONE] use the existing backend reset path.
2. [DONE] On session switch/history load:
   - [DONE] render artifact metadata/data only when the backend history contract provides it;
   - [DONE] otherwise show an expired/regenerate state rather than inventing data.
3. [DONE] Support recent chart references in normal chat without adding frontend routing logic. The frontend sends the user's text and active session ID; the backend resolves “this chart.”
4. [DONE] Add multi-artifact layout:
   - [DONE] one chart: full width;
   - [DONE] multiple charts: responsive stack or grid;
   - [DONE] no horizontal overflow except table.
5. [DONE] Add chart collapse/expand to manage long conversations.
6. [DONE] Optionally lazy-render charts when they enter the viewport.
7. [DONE] Dispose off-screen charts only if they can be safely recreated from retained artifact data/reference.
   - [DONE] V1 keeps off-screen charts mounted; disposal remains limited to message/session teardown paths backed by retained artifact identity and session-scoped data.
8. [DONE] Preserve message ordering.
9. [DONE] Ensure session ID association is immutable for an artifact.
10. [DONE] Add print behavior or explicitly hide unsupported interactive controls.

### Deliverables

- [DONE] Reset cleanup
- [DONE] History behavior
- [DONE] Session-switch behavior
- [DONE] Multi-artifact layout
- [DONE] Optional lazy rendering
- [DONE] Lifecycle integration tests

### Exit Criteria

- [DONE] Reset removes all current-session chart UI.
- [DONE] Charts never cross session boundaries.
- [DONE] History behavior is predictable.
- [DONE] Long conversations remain usable.
- [DONE] No chart instance leaks remain after repeated session changes.

### Validation

- [DONE] `backend/.venv/Scripts/python.exe -m pytest tests/unit/session/test_session_history.py tests/unit/session/test_session_handle_chat.py tests/unit/api/test_artifact_route.py tests/unit/api/test_sse_formatting.py`
- [DONE] `frontend/.venv/Scripts/python.exe -m pytest tests/test_frontend_js.py tests/test_proxy_routes.py`

---

## [DONE] Phase 7: Capabilities, Admin, and Feature Gating

### Objective

Use backend discovery to prevent renderer mismatch and expose operational status.

### Tasks

1. [DONE] Extend the existing capabilities client to read:
   - [DONE] visualization enabled;
   - [DONE] renderer;
   - [DONE] spec version;
   - [DONE] context summary mode;
   - [DONE] supported chart types;
   - [DONE] reference mode;
   - [DONE] client-relevant limits.
2. [DONE] Intersect backend capabilities with frontend adapter capabilities.
3. [DONE] Render only the intersection.
4. [DONE] If backend returns a type not implemented locally:
   - [DONE] do not attempt rendering;
   - [DONE] show unsupported-client message;
   - [DONE] emit telemetry.
5. [DONE] Add visualization status to the existing admin/capabilities view:
   - [DONE] backend enabled;
   - [DONE] backend supported types;
   - [DONE] frontend implemented types;
   - [DONE] mismatches;
   - [DONE] renderer version;
   - [DONE] reference-mode support.
6. [DONE] Add visualization health to the existing health view.
7. [DONE] Do not expose internal MCP endpoints, credentials, policy rules, or data source secrets.
8. [DONE] Cache capabilities with a bounded lifetime and refresh on deployment/version change.
9. [DONE] Add a startup compatibility check in development/test environments.

### Deliverables

- [DONE] Capabilities parser
- [DONE] Backend/frontend capability intersection
- [DONE] Admin visualization status
- [DONE] Health display
- [DONE] Compatibility warning
- [DONE] Capability contract tests

### Exit Criteria

- [DONE] Frontend never advertises or attempts unsupported types.
- [DONE] Admin view identifies registry mismatches.
- [DONE] Visualization can be disabled server-side without frontend deployment.
- [DONE] No sensitive backend details are displayed.

### Validation

- [DONE] `node --test tests/js/chat-artifacts.test.mjs tests/js/visualization-capabilities.test.mjs`
- [DONE] `frontend/.venv/Scripts/python.exe -m pytest tests/test_pages.py tests/test_openapi_contract.py tests/test_frontend_js.py`
- [DONE] Refreshed `frontend/openAPI.json` from the live backend `http://127.0.0.1:8000/openapi.json`

---

## [DONE] Phase 8: Accessibility, Responsive UX, Security, and Performance

### Objective

[DONE] Make the visualization experience production-ready.

### Files created or updated

- [DONE] `frontend/app/static/js/visualization/chart-components.js`
- [DONE] `frontend/app/static/js/visualization/chart-renderer.js`
- [DONE] `frontend/app/static/js/visualization/echarts-adapter.js`
- [DONE] `frontend/app/static/css/components/visualization.css`
- [DONE] `frontend/tests/js/visualization.test.mjs`

### 8.1 Accessibility

- [DONE] Use `<figure>` and `<figcaption>`.
- [DONE] Provide chart title and description.
- [DONE] Provide an accessible textual summary from safe frontend-visible fields when available.
- [DONE] For data tables, use semantic `<table>`, `<thead>`, `<tbody>`, and scoped headers.
- [DONE] Avoid color-only meaning by keeping visible legends, ECharts decal support, and differentiated line symbols/styles where practical.
- [DONE] Support keyboard focus for interactive controls and scrollable table regions.
- [DONE] Ensure status and error messages use appropriate live regions.
- [DONE] Respect reduced-motion preferences through the existing global reduced-motion policy and disabled chart animation.
- [DONE] Add automated coverage for screen-reader-facing shell metadata and keyboard-focusable visualization regions.
- [DONE] Do not expose the backend `ChartContextSummary` unless it is explicitly included in the client contract.

### 8.2 Responsive Behavior

- [DONE] Use `ResizeObserver` with debouncing.
- [DONE] Provide minimum and maximum chart heights.
- [DONE] Handle narrow labels with rotation/truncation plus tooltip.
- [DONE] Stack legends on narrow screens.
- [DONE] Keep tables horizontally scrollable.
- [DONE] Re-render or resize after a hidden panel becomes visible.
- [DONE] Add responsive renderer and stylesheet coverage aligned with the existing three-panel chat layout.

### 8.3 Security

- [DONE] Never use `eval`, `new Function`, or dynamic script insertion.
- [DONE] Never set untrusted chart text with `innerHTML`.
- [DONE] Sanitize/escape all labels and metadata.
- [DONE] Block dangerous object keys.
- [DONE] Validate URL schemes and origins.
- [DONE] Enforce CSP compatibility with the pinned self-hosted renderer asset.
- [DONE] Keep the pinned dependency model and automated JS validation coverage in place for the vendored renderer path.
- [DONE] Avoid storing visualization data in local/session storage by default.
- [DONE] Bound tooltip text and metadata.
- [DONE] Do not create download/export actions unless backend policy and frontend requirements explicitly enable them.

### 8.4 Performance

- [DONE] Keep the pinned renderer self-hosted and lazy-instantiated only when chart artifacts are rendered.
- [DONE] Preserve the existing no-bundler vendor strategy rather than introducing a new build path.
- [DONE] Avoid progressive rendering or sampling unless explicitly configured by future policy work.
- [DONE] Enforce client row/point limits.
- [DONE] Use reference mode for large payloads.
- [DONE] Debounce resize.
- [DONE] Dispose instances.
- [DONE] Avoid repeated deep-copy work inside the live render path.
- [DONE] Use performance telemetry without chart values.
- [DONE] Record render/update/resize timing signals that support bundle/render/resize/memory budget follow-up in later verification.

### Deliverables

- [DONE] Accessible chart shell
- [DONE] Responsive CSS
- [DONE] Reduced-motion behavior
- [DONE] Security tests
- [DONE] Dependency pinning remains enforced through the self-hosted vendor asset path
- [DONE] Performance baseline instrumentation
- [DONE] Browser/device-oriented responsive coverage in the frontend JS suite

### Validation

- [DONE] `frontend/.venv/Scripts/python.exe -m pytest tests/test_frontend_js.py`

### Exit Criteria

- [DONE] Keyboard and screen-reader-facing core flows expose accessible chart metadata, focusable controls, and correct live-region semantics.
- [DONE] Charts resize correctly in the chat layout.
- [DONE] Security tests detect no code execution or unsafe HTML path.
- [DONE] Performance telemetry and debounced resize behavior are in place for agreed-budget validation.
- [DONE] Repeated chart creation/reset continues to dispose chart instances through the tracked lifecycle.

---

## Phase 9: Verification and Cross-Tier Testing

### Objective

Prove compatibility with backend artifacts and complete end-to-end behavior.

### 9.1 Unit Tests

- artifact parser;
- validator;
- malicious fields;
- chart registry;
- each adapter;
- formatting;
- instance lifecycle;
- data loader;
- SSE controller;
- capability intersection;
- error states.

### 9.2 Contract Tests

Use the exact backend golden fixtures for:

- grouped bar;
- line/multi-line;
- pie/donut;
- scatter/bubble;
- histogram/box plot;
- heatmap;
- treemap;
- waterfall;
- gantt;
- radar;
- table;
- unsupported type;
- unknown version;
- reference mode;
- multiple artifacts.

### 9.3 Integration Tests

- `/chat` text only;
- `/chat` text plus inline chart;
- multiple charts;
- one invalid artifact;
- `/chat/stream` lifecycle;
- SSE reconnect/replay;
- reference fetch;
- expired reference;
- reset while loading;
- session switch;
- capabilities mismatch.

### 9.4 End-to-End Tests

1. User supplies inline values and asks for a chart.
2. Backend returns an artifact.
3. Frontend renders it.
4. User asks a follow-up.
5. Frontend sends only the user text and session ID.
6. Backend answers from summary or bounded retrieval.
7. Frontend displays answer without resending chart data.

Tool-data scenario:

1. User requests approved reporting data chart.
2. Backend chart agent calls ToolGateway/MCP.
3. MCP returns structured data.
4. Backend returns `ChartArtifact`.
5. Frontend renders the same contract as inline data.

### 9.5 Visual Regression

Maintain reference screenshots at representative viewport sizes for every chart family and light/dark theme if both are supported.

### Deliverables

- Unit suite
- Contract suite
- Integration suite
- E2E suite
- Visual regression suite
- Browser compatibility report
- Accessibility report
- Performance report

### Exit Criteria

- All enabled chart types pass contract and visual tests.
- Inline and MCP-sourced charts render identically for equivalent artifacts.
- Follow-up requests do not resend full chart datasets.
- Reset and stream reconnect tests pass.
- Accessibility and performance gates pass.

---

## Phase 10: Rollout and Operations

### Objective

Enable the feature gradually and preserve fast rollback.

### Tasks

1. Add frontend feature flag.
2. Ship renderer code with flag disabled.
3. Enable fixture/demo mode in development.
4. Enable for internal backend use case.
5. Enable inline artifacts first.
6. Enable streaming artifacts.
7. Enable reference mode last.
8. Add safe client telemetry:
   - artifact received;
   - validation failed;
   - unsupported type/version;
   - render started/completed/failed;
   - reference fetch failed;
   - resize/dispose errors;
   - no chart data values.
9. Add dashboards for render success and compatibility mismatches.
10. Add runbooks:
    - blank chart;
    - unsupported type;
    - renderer load failure;
    - CSP failure;
    - reference expired;
    - SSE duplicate;
    - memory leak;
    - backend capability mismatch.
11. Rollback:
    - disable frontend visualization flag;
    - continue showing text answers;
    - ignore artifact fields safely;
    - do not require backend rollback.

### Deliverables

- Feature flag
- Client telemetry
- Dashboard
- Runbooks
- Rollback procedure
- Production readiness review

### Exit Criteria

- Visualization can be disabled without disabling chat.
- Text answers remain available during renderer failure.
- Render success and failure are observable.
- Production activation is scoped and reversible.

---

## 9. Frontend Artifact Validation Rules

Before rendering, verify:

```text
artifact is an object
artifact.type == "chart"
artifact.artifact_id is a bounded safe string
artifact.chart_type is in frontend registry
artifact.renderer == "echarts"
artifact.spec_version is supported
artifact.data_mode is inline or reference
inline mode has bounded data
reference mode has an approved same-origin data_ref
encoding fields exist in data
options contain only allowlisted keys
warnings are bounded strings
metadata contains no executable values
all numbers are finite
dangerous object keys are absent
```

A failed validation produces a chart-level error component and telemetry. It must not prevent the assistant answer from rendering.

---

## 10. Suggested Local ECharts Option Boundary

Adapters may produce only locally constructed fields such as:

```text
title
aria
tooltip
legend
grid
xAxis
yAxis
dataset
series
visualMap
radar
dataZoom when explicitly allowed
```

Do not pass through arbitrary backend option objects. Map allowlisted semantic options individually, for example:

```text
artifact.options.currency -> local value formatter
artifact.options.stacked -> local series stack configuration
artifact.options.show_legend -> local legend visibility
```

Reject or ignore unknown options according to the compatibility policy, and record a safe warning.

---

## 11. UX States

| State | User experience |
|---|---|
| Loading | Chart placeholder and accessible status |
| Complete | Title, chart/table, description, warnings |
| Empty data | Clear “no data available” state |
| Unsupported type | Text answer plus unsupported-chart message |
| Unsupported version | Update/compatibility message |
| Invalid payload | Safe render-error message |
| Reference loading | Loading with cancellation |
| Reference expired | Regenerate/request data again guidance |
| Policy denied | Backend-provided natural-language response; no fake chart |
| Partial warning | Render valid chart and display bounded warning |
| Offline/transport failure | Preserve text and offer normal retry through existing chat UX |

---

## 12. Risk Register

| Risk | Impact | Mitigation |
|---|---|---|
| Executable renderer payload | XSS/code execution | Local adapters, no arbitrary option pass-through |
| Backend/frontend support mismatch | Blank charts | Capability intersection and contract tests |
| SSE replay duplicates charts | Broken UX/leaks | Artifact ID idempotency |
| Chart instance leak | Browser slowdown | Instance store and disposal tests |
| Large inline payload | UI freeze | Client limits and reference mode |
| Reference fetch crosses scope | Data exposure | Same-origin, session auth, backend ownership checks |
| Chart failure hides answer | Loss of usability | Independent text and artifact regions |
| Accessibility gap | Excludes users | Figure/table semantics and testing |
| Responsive failure in three-panel layout | Unusable chart | ResizeObserver and breakpoint tests |
| Client stores sensitive data | Exposure | In-memory only by default |
| Frontend begins routing chart requests | Architecture drift | Send normal chat only; backend owns routing |
| Export bypasses policy | Data leakage | No export action by default |

---

## 13. Definition of Done

The frontend visualization implementation is complete when:

- Existing text-only chat remains unchanged.
- `ChartArtifact` v1 is parsed and validated.
- Every enabled backend chart type has a tested frontend adapter.
- The frontend constructs renderer options locally.
- No backend-provided code is executed.
- `/chat` artifacts render inside the correct assistant message.
- `/chat/stream` artifact events render exactly once.
- Reference-mode data is fetched only through the protected backend route.
- Reset, history, session switch, cancellation, and disposal work correctly.
- Backend and frontend capabilities are intersected.
- Chart errors do not hide the assistant answer.
- Accessibility, responsiveness, security, and performance gates pass.
- Shared backend fixtures pass frontend contract tests.
- Inline and MCP-sourced data use the same artifact-rendering path.
- The feature is observable, configuration-driven, and reversible.

---

## 14. Implementation Checklist

### Foundation
- [ ] Freeze artifact/SSE fixtures.
- [ ] Pin ECharts.
- [ ] Add parser and validator.
- [ ] Add frontend chart registry.
- [ ] Add instance store and base renderer.

### Adapters
- [ ] Bar family.
- [ ] Line/area family.
- [ ] Pie/donut.
- [ ] Scatter/bubble.
- [ ] Histogram/box plot.
- [ ] Heatmap/treemap.
- [ ] Waterfall/gantt/radar.
- [ ] Accessible table.

### Integration
- [ ] Non-streaming chat.
- [ ] SSE lifecycle.
- [ ] Reference mode, if enabled.
- [ ] Reset/history/session lifecycle.
- [DONE] Capabilities and health.
- [DONE] Admin compatibility status.

### Quality
- [ ] Accessibility.
- [ ] Responsive behavior.
- [ ] Security/CSP.
- [ ] Performance.
- [ ] Unit tests.
- [ ] Contract tests.
- [ ] Integration tests.
- [ ] E2E and visual regression.
- [ ] Telemetry, runbooks, and rollback.
