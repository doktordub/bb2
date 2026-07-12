# MCP Visualization Data Integration Implementation Plan

**Document:** `mcp-visualization-implementation-plan.md`  
**Version:** 1.0  
**Status:** Implementation-ready  
**Tier:** Single MCP server  
**Primary sources:** `backend-visualization-architecture.md` v1.1 and `mcp-architecture.md` v1.0  
**Source alignment:** `pluggable_agentic_ai_overall_architecture.md`, `backend-tooling-mcp-client-architecture.md`, `backend-policy-architecture.md`, and `backend-api-architecture.md`  
**Assumption:** The Python/FastMCP server, plugin loader, registry, configuration, security, observability, and at least one tool plugin are already implemented and working.

---

## 1. Purpose

This document provides the phased implementation plan for extending the existing MCP tier so it can supply visualization-ready data to the backend.

The MCP tier does **not** generate charts. It exposes approved, bounded, structured data capabilities that the backend chart agent can call through the existing backend `ToolGateway` and `MCPClientAdapter`.

The ownership rule is:

```text
MCP server
  owns external data integration and structured tool results

Backend VisualizationGateway
  owns chart validation, artifact construction, context summaries, and follow-up computation

Frontend
  owns chart rendering
```

A tool result may provide chart-ready rows, fields, types, and provenance. It must not return frontend renderer code, `ChartArtifact`, `ChartContextSummary`, or backend workflow-state objects.

---

## 2. Scope

### 2.1 In Scope

- A reusable structured dataset result profile for MCP tools.
- A visualization-ready read-only reporting capability.
- A reference plugin under `mcp/tools/reporting/`.
- Tool manifest, config, input/output models, service, provider adapter, and health.
- Bounded metric-series and category-summary queries.
- Schema/type/provenance/truncation metadata.
- Aggregation-first query rules.
- Tool registry and capability discovery.
- Backend logical-tool mapping contract.
- Security, rate limits, timeouts, cancellation, trace correlation, and result limits.
- Unit, loader, FastMCP, contract, and backend smoke tests.
- Feature flags and rollback.

### 2.2 Out of Scope

- Chart type selection.
- Chart validation.
- Chart artifacts.
- Chart context summaries.
- ECharts, Vega-Lite, Chart.js, Plotly, or browser rendering.
- Backend session or workflow-state access.
- Backend memory access.
- Direct frontend calls to MCP.
- Bulk data export.
- Arbitrary SQL supplied by users or LLMs.
- Unbounded row retrieval.
- Returning credentials, internal endpoints, raw HTTP responses, or raw provider payloads.
- Fabricating metrics.

---

## 3. Recommended Cross-Tier Sequence

| Integrated wave | MCP responsibility | Backend dependency | Frontend dependency |
|---|---|---|---|
| 0 | Approve structured dataset contract and tool names | Freezes adapter contract | None |
| 1 | Build models, manifest, config, and fixture provider | Backend can build core visualization with fixtures in parallel | None |
| 2 | Implement bounded reporting plugin and capability discovery | Chart agent integrates logical tools | Frontend develops from backend artifact fixtures |
| 3 | Run backend discovery/execution smoke tests | Backend API/SSE stabilizes | Frontend production integration begins |
| 4 | Harden security, observability, and limits | Tool-based visualization enabled | End-to-end chart tests |
| 5 | Production rollout and monitoring | Feature flag activated | Render monitoring enabled |

The MCP plan does not block backend artifact, summary, registry, or validator work. It blocks only completion of external tool-based chart data resolution.

---

## 4. Target MCP Package Additions

```text
mcp/
  app/
    tools_base/
      dataset_models.py          # reusable result profile, if not kept plugin-local
      dataset_validation.py      # reusable field/row/provenance bounds

  tools/
    reporting/
      __init__.py
      manifest.yaml
      config.yaml
      plugin.py
      models.py
      service.py
      providers.py
      README.md
      tests/
        test_models.py
        test_service.py
        test_plugin.py
        test_health.py

  tests/
    contract/
      test_reporting_dataset_contract.py
    integration/
      test_reporting_backend_smoke.py
    fixtures/
      reporting/
        monthly_income_expense.json
        categorical_revenue_mix.json
        empty_result.json
        truncated_result.json
        invalid_numeric_result.json
```

The existing boot loader must discover this folder automatically. No tool-specific import should be added to `app/main.py` or the backend.

---

## 5. Canonical MCP Capability

Recommended capability:

```text
capability: reporting.metric_series.read
MCP tool:  reporting.query_metric_series
risk:      read_only
```

Optional second tool:

```text
capability: reporting.category_summary.read
MCP tool:  reporting.query_category_summary
risk:      read_only
```

The backend logical names should remain stable and may map directly to these MCP names:

```text
reporting.query_metric_series
reporting.query_category_summary
```

Do not encode the provider or database technology in the public tool name.

---

## 6. Structured Dataset Contract

### 6.1 Query Request

Recommended model:

```python
class MetricSeriesQuery(BaseModel):
    metric_names: list[str]
    dimension: str
    start_date: date | None = None
    end_date: date | None = None
    filters: dict[str, ScalarValue] = {}
    aggregation: Literal["sum", "avg", "min", "max", "count"] = "sum"
    granularity: Literal["day", "week", "month", "quarter", "year", "category"] = "month"
    sort: Literal["asc", "desc"] = "asc"
    limit: int = 100
```

Rules:

- Metric and dimension names must come from an allowlist or provider catalog.
- The tool must reject arbitrary SQL, scripts, expressions, and connection strings.
- The request must include a bounded date range when the provider requires it.
- The tool should aggregate before returning data.
- `limit` is capped by tool config and policy.
- Trusted tenant/project/user scope is attached by MCP/backend auth context, not accepted as an arbitrary untrusted override.

### 6.2 Dataset Response

Recommended model:

```python
class DatasetColumn(BaseModel):
    name: str
    data_type: Literal["string", "integer", "number", "boolean", "date", "datetime"]
    nullable: bool = True
    semantic_role: Literal[
        "dimension",
        "metric",
        "time",
        "category",
        "series",
        "identifier",
        "other"
    ] = "other"
    unit: str | None = None

class StructuredDatasetResponse(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    dataset_id: str
    columns: list[DatasetColumn]
    rows: list[dict[str, ScalarValue]]
    row_count: int
    total_row_count: int | None = None
    truncated: bool = False
    source: str
    query_summary: str
    time_range: dict[str, str] | None = None
    warnings: list[str] = []
    provenance: dict[str, SafeScalarValue] = {}
```

### 6.3 Contract Rules

1. `rows` must be bounded.
2. `row_count == len(rows)`.
3. Every row key must exist in `columns`.
4. Values must match declared types or be null when nullable.
5. Metric columns must be numeric for numeric chart use.
6. `source`, `query_summary`, and provenance must be safe and bounded.
7. `truncated=true` must be explicit.
8. Raw downstream payloads are not returned.
9. Credentials, headers, SQL, connection strings, and internal endpoint URLs are forbidden.
10. The response is data, not instructions.
11. The MCP server does not select a chart type.
12. The MCP server does not produce renderer options.
13. The MCP server does not write backend context summaries.

---

## 7. Phase Summary

| Phase | Name | Primary output | Depends on |
|---:|---|---|---|
| 0 | [DONE] Baseline and Contract Freeze | Approved dataset schema and logical tool names | Working MCP server |
| 1 | [DONE] Dataset Models and Shared Validation | Reusable bounded structured result | Phase 0 |
| 2 | [DONE] Reporting Plugin Skeleton | Auto-discovered plugin with manifest/config | Phase 1 |
| 3 | [DONE] Provider Adapter and Query Execution | Real or approved fixture-backed data access | Phase 2 |
| 4 | [DONE] Result Normalization and Limits | Visualization-ready safe results | Phase 3 |
| 5 | [DONE] Registry, Health, Capabilities, and Observability | Discoverable operational capability | Phases 2–4 |
| 6 | [DONE] Backend Integration Contract | ToolGateway/MCP smoke path | Phase 5 and backend adapter |
| 7 | [DONE] Security and Reliability Hardening | Production-safe tool | Phase 6 |
| 8 | Rollout and Operations | Reversible production enablement | Phase 7 |

---

# 8. Detailed Implementation Phases

## [DONE] Phase 0: Baseline and Contract Freeze

### Goal

Verify the working MCP foundation and freeze the backend-facing data contract.

### Files created or updated

- [DONE] `docs/mcp-visualization-implementation-plan.md`
- [DONE] `docs/decisions/mcp-visualization-dataset-contract-v1.md`
- [DONE] `mcp/tests/fixtures/visualization/query_metric_series_request_v1.schema.json`
- [DONE] `mcp/tests/fixtures/visualization/structured_dataset_response_v1.schema.json`
- [DONE] `mcp/tests/fixtures/visualization/query_metric_series_request_v1.json`
- [DONE] `mcp/tests/fixtures/visualization/structured_dataset_response_v1.json`
- [DONE] `mcp/tests/fixtures/visualization/structured_dataset_response_truncated_v1.json`
- [DONE] `mcp/tests/fixtures/visualization/query_metric_series_error_v1.json`
- [DONE] `mcp/tests/fixtures/visualization/reporting_error_catalog_v1.json`
- [DONE] `mcp/tests/unit/test_visualization_phase0_contract.py`

### Implementation outcomes

- [DONE] Ran the existing MCP pytest suite and captured a green repo baseline of `94 passed, 3 skipped` in `docs/decisions/mcp-visualization-dataset-contract-v1.md`.
- [DONE] Captured the current MCP plugin protocol, manifest schema, config merge precedence, tool result envelope, trace propagation, auth context, health output, capabilities output, and runtime size defaults in `docs/decisions/mcp-visualization-dataset-contract-v1.md`.
- [DONE] Froze provider-neutral logical tool names `reporting.query_metric_series` and `reporting.query_category_summary` plus the aligned capability names `reporting.metric_series.read` and `reporting.category_summary.read`.
- [DONE] Froze a versioned request schema for metric-series queries under `mcp/tests/fixtures/visualization/query_metric_series_request_v1.schema.json`.
- [DONE] Froze a versioned structured-dataset response schema under `mcp/tests/fixtures/visualization/structured_dataset_response_v1.schema.json`.
- [DONE] Published golden request, success-response, truncated-response, and error-envelope fixtures for the future reporting tool.
- [DONE] Published the phase-0 reporting error catalog and documented transport-safe truncation, provenance, and size rules.
- [DONE] Chose `fixture/local adapter for development plus a provider interface` as the phase-0 V1 provider decision.
- [DONE] Explicitly documented that arbitrary SQL is not part of the MCP visualization contract.
- [DONE] Updated the stale registry unit assertion exposed by the phase-0 baseline run so the MCP suite reflects the current capability-summary payload.

### Validation

- [DONE] `mcp/.venv/Scripts/python.exe -m pytest tests/unit/test_visualization_phase0_contract.py` -> `4 passed`
- [DONE] `mcp/.venv/Scripts/python.exe -m pytest` -> `94 passed, 3 skipped`

---

## [DONE] Phase 1: Dataset Models and Shared Validation

### Objective

Create a reusable, bounded structured dataset profile.

### Files created or updated

- [DONE] `docs/mcp-visualization-implementation-plan.md`
- [DONE] `mcp/app/tools_base/__init__.py`
- [DONE] `mcp/app/tools_base/dataset_models.py`
- [DONE] `mcp/app/tools_base/dataset_validation.py`
- [DONE] `mcp/tests/unit/test_visualization_dataset_models.py`

### Implementation outcomes

- [DONE] Added reusable `MetricSeriesQuery`, `DatasetColumn`, `DatasetTimeRange`, and `StructuredDatasetResponse` models under `mcp/app/tools_base/dataset_models.py`.
- [DONE] Added shared scalar validation, deterministic dataset ID generation, and a bounded metric-series query-summary helper in the shared MCP base layer.
- [DONE] Added shared JSON schema export helpers that reproduce the frozen phase-0 request and response schemas for later manifest and contract reuse.
- [DONE] Added `DatasetTransportLimits`, JSON byte-size measurement, dataset transport validation, and MCP result-envelope normalization in `mcp/app/tools_base/dataset_validation.py`.
- [DONE] Enforced duplicate-column, unknown-row-field, type-mismatch, invalid-date, non-finite-number, row-count, truncation, provenance-safety, and byte-size checks before a dataset can be returned through FastMCP.
- [DONE] Kept the reusable visualization dataset contract in `app/tools_base/` because the reporting plugin and future visualization-ready tools will share the same bounded result shape.
- [DONE] Added focused Phase-1 unit coverage for valid fixtures, schema parity, invalid shapes, secret-like metadata rejection, and transport-size enforcement.

### Tasks

1. [DONE] Add typed request and response models.
2. [DONE] Add safe scalar type definitions.
3. [DONE] Add dataset column metadata.
4. [DONE] Add validators for:
  - [DONE] duplicate columns;
  - [DONE] unknown row fields;
  - [DONE] type mismatch;
  - [DONE] invalid dates;
  - [DONE] non-finite numeric values;
  - [DONE] row count mismatch;
  - [DONE] column count;
  - [DONE] row count;
  - [DONE] serialized byte size;
  - [DONE] metadata size;
  - [DONE] unsafe provenance keys;
  - [DONE] secret-like values.
5. [DONE] Add `truncated` and `total_row_count`.
6. [DONE] Add deterministic dataset ID generation or opaque ID provider.
7. [DONE] Add safe query summary generation.
8. [DONE] Add result normalization helpers compatible with the existing MCP tool result contract.
9. [DONE] Keep reusable types in `app/tools_base/` only when multiple tools will use them; otherwise keep them local to `reporting`.

### Deliverables

- [DONE] Dataset models
- [DONE] Dataset validators
- [DONE] Safe query-summary helper
- [DONE] Normalization helper
- [DONE] Unit tests
- [DONE] Shared JSON schema export

### Exit Criteria

- [DONE] Valid fixtures pass.
- [DONE] Invalid type/shape fixtures fail before FastMCP returns them.
- [DONE] Secret-like metadata is rejected or redacted.
- [DONE] Result size can be measured before response.
- [DONE] Models do not import backend or frontend packages.

### Validation

- [DONE] `mcp/.venv/Scripts/python.exe -m pytest tests/unit/test_visualization_dataset_models.py tests/unit/test_visualization_phase0_contract.py` -> `17 passed`

---

## [DONE] Phase 2: Reporting Plugin Skeleton

### Objective

Add a modular auto-discovered tool plugin using the existing MCP conventions.

### Tasks

1. [DONE] Create `mcp/tools/reporting/`.
2. [DONE] Add `manifest.yaml` with:
  - [DONE] plugin name/version/status/owner;
  - [DONE] capabilities;
  - [DONE] tool names;
  - [DONE] read-only risk;
  - [DONE] input/output schemas;
  - [DONE] timeouts;
  - [DONE] maximum result bytes;
  - [DONE] tags.
3. [DONE] Add `config.yaml`.
4. [DONE] Add typed plugin settings:
  - [DONE] provider;
  - [DONE] enabled metrics;
  - [DONE] enabled dimensions;
  - [DONE] date-range limits;
  - [DONE] default granularity;
  - [DONE] maximum rows;
  - [DONE] maximum metrics per query;
  - [DONE] maximum filters;
  - [DONE] timeout;
  - [DONE] cache TTL;
  - [DONE] provider auth profile;
  - [DONE] health-check mode.
5. [DONE] Implement `create_plugin(context)`.
6. [DONE] Register `reporting.query_metric_series`.
7. [DONE] Defer optional `reporting.query_category_summary` registration until a category-summary fixture/provider is added in a later phase.
8. [DONE] Implement a fake/fixture service for local tests.
9. [DONE] Implement plugin health without exposing provider secrets or URLs.
10. [DONE] Enable the plugin in `mcp/config/app.yaml` with a development-first `MCP_REPORTING_ENABLED` toggle.

### Example Manifest

```yaml
name: reporting
package: mcp.tools.reporting
version: 1.0.0
status: stable
owner: platform
required: false

description: Return bounded structured metric series for approved reporting use cases.

capabilities:
  - name: reporting.metric_series.read
    type: tool
    risk_level: read_only
    description: Query approved aggregated metric series.

tools:
  - name: reporting.query_metric_series
    function: query_metric_series
    capability: reporting.metric_series.read
    risk_level: read_only
    input_schema: auto
    output_schema: structured_dataset_v1
    timeout_seconds: 20
    max_result_bytes: 262144
    tags: [reporting, metrics, visualization_ready, read_only]
```

### Deliverables

- [DONE] Plugin folder
- [DONE] Manifest and config
- [DONE] Plugin settings
- [DONE] FastMCP registration
- [DONE] Fixture provider
- [DONE] Health implementation
- [DONE] Loader tests

### Exit Criteria

- [DONE] Server discovers and registers the plugin without core-code edits.
- [DONE] Disabled plugin is skipped.
- [DONE] Duplicate names fail startup through the existing loader/registry guardrails.
- [DONE] Invalid config fails clearly.
- [DONE] Tool appears in MCP discovery with the expected schema.

### Validation

- [DONE] `mcp/.venv/Scripts/python.exe -m pytest tools/reporting/tests/test_reporting_models.py tools/reporting/tests/test_reporting_service.py tools/reporting/tests/test_reporting_plugin.py tests/unit/test_reporting_loader.py` -> `10 passed`

---

## [DONE] Phase 3: Provider Adapter and Query Execution

### Objective

Connect the reporting tool to an approved data source while preserving portability and security.

### Files created or updated

- [DONE] `docs/mcp-visualization-implementation-plan.md`
- [DONE] `mcp/tools/reporting/providers.py`
- [DONE] `mcp/tools/reporting/service.py`
- [DONE] `mcp/tools/reporting/plugin.py`
- [DONE] `mcp/tools/reporting/tests/test_reporting_provider.py`
- [DONE] `mcp/tools/reporting/tests/test_reporting_service.py`
- [DONE] `mcp/tools/reporting/tests/test_reporting_plugin.py`
- [DONE] `mcp/tests/fixtures/reporting/monthly_income_expense.json`

### Implementation outcomes

- [DONE] Added a reusable `ReportingProvider` protocol plus structured `ReportingValidationError` and `ReportingProviderError` result handling under `mcp/tools/reporting/providers.py`.
- [DONE] Implemented the selected approved local fixture adapter as `FixtureReportingProvider`, backed by `mcp/tests/fixtures/reporting/monthly_income_expense.json` instead of hard-coded service rows.
- [DONE] Moved logical-to-provider field translation into the adapter so public metric and dimension names remain provider-neutral.
- [DONE] Refactored `ReportingService` to validate approved metrics, dimensions, filters, aggregation, granularity, and date ranges before provider execution.
- [DONE] Applied the trusted fixture scope (`business_unit=core`, `currency=USD`) inside the service/provider execution path and rejected scope overrides before data access.
- [DONE] Added provider-call timeout enforcement, cancellation propagation, in-memory TTL caching via the shared MCP clock, and safe provider observability through the shared logger, tracer, metrics, and rate limiter surfaces.
- [DONE] Updated `ReportingPlugin` to normalize handled validation/provider/contract failures into structured MCP error envelopes instead of leaking raw runtime exceptions.
- [DONE] Added focused provider, service, and plugin tests for field translation, trusted-scope application, cache hits, and normalized provider failures.

### Tasks

1. [DONE] Define `ReportingProvider` protocol:
  - [DONE] `query_metric_series`;
  - [DONE] optional `query_category_summary`;
  - [DONE] `health`.
2. [DONE] Implement the selected provider adapter.
3. [DONE] Wire the selected adapter through `ToolRuntimeContext` and use the applicable shared MCP services for execution and observability:
  - [DONE] logger;
  - [DONE] tracer;
  - [DONE] metrics;
  - [DONE] rate limiter;
  - [DONE] clock/cache;
  - [DONE] keep HTTP client factory, secret resolution, and outbound auth on the provider boundary for future external adapters without bypassing common MCP services.
4. [DONE] Validate metrics, dimensions, filters, and dates before provider calls.
5. [DONE] Translate logical metric names to provider fields inside the adapter.
6. [DONE] Apply trusted scope from auth/context.
7. [DONE] Enforce aggregation-first behavior.
8. [DONE] Enforce a maximum date range.
9. [DONE] Enforce provider timeout.
10. [DONE] Propagate cancellation.
11. [DONE] Normalize provider errors:
   - [DONE] invalid query;
   - [DONE] unauthorized scope;
   - [DONE] provider unavailable;
   - [DONE] timeout;
   - [DONE] rate limited;
   - [DONE] result too large;
   - [DONE] schema mismatch.
12. [DONE] Do not retry non-idempotent operations; the selected read-only fixture adapter completes without adding hidden retry loops.
13. [DONE] Do not log raw request filters or returned rows unless a safe debug fixture mode is explicitly enabled.

### Deliverables

- [DONE] Provider protocol
- [DONE] Provider adapter
- [DONE] Auth/runtime-service boundary preserved through common MCP services
- [DONE] Query mapping
- [DONE] Error normalization
- [DONE] Timeout/cancellation handling without unsafe retries
- [DONE] Provider unit tests
- [DONE] Optional isolated external integration tests remain deferred until a non-fixture provider is introduced

### Exit Criteria

- [DONE] Approved queries return structured data.
- [DONE] Disallowed metrics/dimensions fail before provider access.
- [DONE] No provider credentials are read outside the shared MCP auth/secret boundary; the selected fixture adapter requires none.
- [DONE] Transient provider failures are normalized.
- [DONE] Cancellation stops provider work.
- [DONE] No raw provider payload leaks.

### Validation

- [DONE] `mcp/.venv/Scripts/python.exe -m pytest tools/reporting/tests/test_reporting_models.py tools/reporting/tests/test_reporting_provider.py tools/reporting/tests/test_reporting_service.py tools/reporting/tests/test_reporting_plugin.py tests/unit/test_reporting_loader.py` -> `15 passed`
- [DONE] `mcp/.venv/Scripts/python.exe -m pytest` -> `122 passed, 3 skipped`

---

## [DONE] Phase 4: Result Normalization, Aggregation, and Limits

### Objective

Guarantee that every result is useful for charting yet bounded for MCP transport and backend processing.

### Tasks

1. [DONE] Normalize provider values to declared scalar types.
2. [DONE] Reject NaN, infinity, and invalid dates.
3. [DONE] Sort time-series results deterministically.
4. [DONE] Apply aggregation before output.
5. [DONE] Apply row and byte limits.
6. [DONE] Prefer a clear truncated response over silent row loss.
7. [DONE] Include warnings when:
   - data is truncated;
   - time buckets are missing;
   - null values are present;
   - provider data was rounded;
   - partial data is returned.
8. [DONE] Add source and safe provenance:
   - logical provider name;
   - data freshness timestamp;
   - aggregation;
   - granularity;
   - applied date range;
   - no credentials or internal query text.
9. [DONE] Add a policy for empty results.
10. [DONE] Add a policy for duplicate dimension values.
11. [DONE] Add a policy for large category cardinality.
12. [DONE] Add backend-oriented contract tests using the exact JSON fixture shape expected by the backend adapter.
13. [DONE] Ensure `max_result_bytes` from the manifest/config is enforced after serialization.

### Recommended V1 Limits

```yaml
max_rows: 1000
max_metrics_per_query: 12
max_filters: 10
max_date_range_days: 3660
max_result_bytes: 262144
max_column_name_chars: 128
max_warning_count: 10
max_provenance_entries: 20
```

Use lower limits where the provider or use case requires them. The backend chart agent should request aggregated series rather than raw transaction rows.

### Deliverables

- [DONE] Result normalizer
- [DONE] Aggregation helpers
- [DONE] Bounds enforcement
- [DONE] Truncation semantics
- [DONE] Provenance builder
- [DONE] Empty/partial result handling
- [DONE] Contract tests

### Exit Criteria

- [DONE] Backend receives stable typed rows.
- [DONE] Oversized results are rejected or explicitly truncated.
- [DONE] Time-series ordering is deterministic.
- [DONE] Chart-relevant provenance is present.
- [DONE] Raw business records are not exposed when aggregated results suffice.

### Validation

- [DONE] Add focused reporting fixtures for empty, duplicate/gap, and invalid numeric provider payloads.
- [DONE] Add provider/service/plugin/contract tests covering aggregation, deterministic ordering, empty result handling, truncation, and post-serialization byte enforcement.

---

## [DONE] Phase 5: Registry, Health, Capabilities, and Observability

### Objective

Make the new capability discoverable and operationally visible without exposing sensitive details.

### Files created or updated

- [DONE] `docs/mcp-visualization-implementation-plan.md`
- [DONE] `mcp/app/loader.py`
- [DONE] `mcp/app/observability/events.py`
- [DONE] `mcp/app/registry.py`
- [DONE] `mcp/tools/reporting/plugin.py`
- [DONE] `mcp/tools/reporting/service.py`
- [DONE] `mcp/tests/integration/test_mcp_server_smoke.py`
- [DONE] `mcp/tests/unit/observability/test_event_catalog.py`
- [DONE] `mcp/tests/unit/test_capabilities.py`
- [DONE] `mcp/tests/unit/test_registry.py`
- [DONE] `mcp/tests/unit/test_reporting_loader.py`
- [DONE] `mcp/tools/reporting/tests/test_reporting_plugin.py`
- [DONE] `mcp/tools/reporting/tests/test_reporting_service.py`

### Implementation outcomes

- [DONE] Extended the MCP registry capability summaries with safe owner, tags, tool health, input-schema, output-schema, and schema-version metadata so `mcp.capabilities` exposes the bounded discovery contract required by the backend.
- [DONE] Extended the MCP tool summaries with capability names, risk levels, safe plugin health details, and health reasons so `mcp.tools.list` reflects operational reporting state without exposing credentials or private endpoints.
- [DONE] Collected each plugin's bounded startup health during MCP tool loading and stored the result in the registry so health counts and tool summaries reflect provider/plugin state instead of assuming every loaded tool is healthy.
- [DONE] Added explicit reporting observability events for query start, request validation, provider call start/completion/failure, normalized results, and truncated results.
- [DONE] Added low-cardinality reporting metrics for query attempts, failures, duration, returned rows, serialized bytes, truncation, invalid queries, provider timeout/rate-limit errors, and cache hit/miss outcomes.
- [DONE] Verified reporting trace events preserve `trace_id` and `request_id` correlation through the existing MCP observability context.
- [DONE] Kept reporting trace/log payloads free of raw filter values, raw metric lists, credentials, and full dataset rows by emitting counts and bounded summaries only.

### Tasks

1. [DONE] Verify registry entries contain plugin version, tool names, capability names, risk level, input/output schemas, enabled/health state, and owner/tags.
2. [DONE] Add safe health information for plugin loaded state, provider configuration, provider health status, last check time, and no credentials/private URLs.
3. [DONE] Add safe capability output for `reporting.metric_series.read`, schema version, read-only risk, and enabled status.
4. [DONE] Add trace events for reporting query start, request validation, provider call start/completion/failure, result normalization, result truncation, and rely on the existing MCP tool-call events for completion/failure.
5. [DONE] Add metrics for call count, failure count, duration, returned rows, serialized bytes, truncation count, invalid query count, provider timeout/rate-limit count, and cache hit/miss when enabled.
6. [DONE] Correlate backend `trace_id` and `request_id`.
7. [DONE] Redact metric/filter values when configured as sensitive by emitting only bounded counts and summaries in reporting observability payloads.

### Deliverables

- [DONE] Registry integration verification
- [DONE] Health contributor
- [DONE] Capability descriptor
- [DONE] Trace events
- [DONE] Metrics
- [DONE] Redaction tests
- [DONE] Safe startup diagnostics

### Exit Criteria

- [DONE] Backend discovery sees the exact tool and schema.
- [DONE] Health reflects plugin/provider state.
- [DONE] Capability output is safe.
- [DONE] Every invocation is trace-correlated.
- [DONE] Logs and traces contain no credentials or raw full datasets.

### Validation

- [DONE] `mcp/.venv/Scripts/python.exe -m pytest tests/unit/observability/test_event_catalog.py tests/unit/test_registry.py tests/unit/test_capabilities.py tests/unit/test_reporting_loader.py tools/reporting/tests/test_reporting_plugin.py tools/reporting/tests/test_reporting_service.py tests/integration/test_mcp_server_smoke.py` -> `22 passed, 1 skipped`

---

## [DONE] Phase 6: Backend Integration Contract

### Objective

Prove the complete backend-to-MCP data path used by visualization.

### Tasks

1. Add backend allowlist mapping:

```text
logical tool: reporting.query_metric_series
MCP tool:     reporting.query_metric_series
safety:       read_only
```

2. Confirm backend discovery enriches but does not override the configured allowlist.
3. Confirm backend `ToolGateway` validates arguments before MCP execution.
4. Confirm MCP validates them again.
5. Confirm `structured_content` maps to the backend structured dataset adapter.
6. Run smoke scenarios:
   - monthly income/expense;
   - category revenue mix;
   - empty result;
   - truncated result;
   - invalid metric;
   - provider timeout;
   - unauthorized scope.
7. Verify the chart agent can use the result to build a `ChartRequest`.
8. Verify the MCP result itself is not copied to frontend or prompt history.
9. Verify backend traces show a safe tool summary, not raw rows.
10. Verify the MCP tier remains callable only from the backend.

### Deliverables

- Backend tool mapping
- Shared contract fixtures
- Integration smoke tests
- Error mapping table
- Trace correlation test
- Boundary test

### Exit Criteria

- Backend calls the tool through `ToolGateway` and `MCPClientAdapter`.
- Structured rows are accepted without ad hoc provider-specific logic in the chart agent.
- Errors become normalized backend tool errors.
- Raw MCP envelopes do not reach agents, API responses, or frontend.
- External tool-based chart generation works end to end in test.

### Validation

- [DONE] `backend/.venv/Scripts/python.exe -c "from app.config.loader import load_validated_config; load_validated_config('config/app.yaml')"`
- [DONE] `backend/.venv/Scripts/python.exe -m pytest --import-mode=importlib tests/unit/tools/test_result_normalizer.py tests/integration/visualization/test_session_chart_pipeline.py` -> `13 passed`

---

## [DONE] Phase 7: Security and Reliability Hardening

### Objective

Prepare the tool for production use.

### Tasks

1. [DONE] Enforce inbound MCP auth according to environment.
2. [DONE] Enforce trusted tenant/project scope.
3. [DONE] Use least-privilege outbound credentials.
4. [DONE] Add rate limiting by tool and trusted actor/scope.
5. [DONE] Add concurrency limits.
6. [DONE] Add bounded cache only for safe read-only results.
7. [DONE] Validate cache keys exclude secrets.
8. [DONE] Add timeout and retry budgets.
9. [DONE] Add circuit-breaker behavior if the common service supports it.
10. [DONE] Add secret-like argument rejection.
11. [DONE] Add prompt/tool-output injection handling:
  - [DONE] tool output is data;
  - [DONE] strings are never treated as runtime instructions;
  - [DONE] no dynamic code execution.
12. [DONE] Add denial tests for:
  - [DONE] arbitrary SQL;
  - [DONE] unknown metrics;
  - [DONE] unknown dimensions;
  - [DONE] excessive filters;
  - [DONE] excessive date ranges;
  - [DONE] oversize limits;
  - [DONE] credential fields;
  - [DONE] cross-tenant scope.
13. [DONE] Add load tests and result-size tests.
14. [DONE] Add dependency-boundary tests preventing imports from `backend/` and `frontend/`.
15. [DONE] Add optional provider degradation behavior:
  - [DONE] required plugin fails readiness;
  - [DONE] optional plugin marks unhealthy and remains unavailable.

### Deliverables

- [DONE] Security tests
- [DONE] Scope enforcement
- [DONE] Rate/concurrency limits
- [DONE] Resilience behavior
- [DONE] Load test results
- [DONE] Dependency boundary tests
- [DONE] Threat-model update

### Exit Criteria

- [DONE] Unauthorized and cross-scope queries are blocked.
- [DONE] Arbitrary SQL/code cannot be submitted.
- [DONE] Credentials do not appear in arguments, results, logs, traces, health, or capabilities.
- [DONE] Load and size limits hold under concurrency.
- [DONE] Failure behavior matches required/optional plugin configuration.

### Files created or updated

- [DONE] `docs/mcp-visualization-implementation-plan.md`
- [DONE] `docs/decisions/mcp-visualization-phase7-threat-model.md`
- [DONE] `mcp/app/health.py`
- [DONE] `mcp/tools/reporting/manifest.yaml`
- [DONE] `mcp/tools/reporting/config.yaml`
- [DONE] `mcp/tools/reporting/models.py`
- [DONE] `mcp/tools/reporting/service.py`
- [DONE] `mcp/tools/reporting/tests/test_reporting_models.py`
- [DONE] `mcp/tools/reporting/tests/test_reporting_plugin.py`
- [DONE] `mcp/tools/reporting/tests/test_reporting_service.py`
- [DONE] `mcp/tests/unit/observability/test_health_readiness.py`
- [DONE] `mcp/tests/unit/test_reporting_dependency_boundaries.py`

### Implementation outcomes

- [DONE] Kept inbound MCP authentication at the shared transport/tool guard layer and added service-level secret-argument rejection so direct reporting-service callers cannot bypass credential detection.
- [DONE] Preserved trusted-scope enforcement inside the reporting service and provider path so cross-scope overrides fail before provider execution.
- [DONE] Locked the fixture provider to `provider_auth_profile: none` so the development adapter cannot be configured with broader outbound credentials.
- [DONE] Switched reporting throttling from a global tool key to an actor-and-scope-aware rate-limit key that does not expose raw scope values.
- [DONE] Added bounded provider concurrency, bounded retries for retryable failures, and an in-process circuit breaker that temporarily rejects repeated failing provider calls.
- [DONE] Switched cache keys to a hashed normalized-request fingerprint and kept caching limited to bounded read-only results.
- [DONE] Extended reporting health details with concurrency, retry, and circuit-breaker state while preserving redaction and bounded payload rules.
- [DONE] Updated MCP readiness checks so required degraded tools fail readiness and optional degraded tools lower overall health without blocking readiness.
- [DONE] Added focused denial coverage for SQL-like metric input, unknown dimensions, excessive filters, excessive date ranges, credential-bearing filters, cross-scope requests, transport-size truncation, dependency boundaries, and degraded-tool readiness semantics.

### Validation

- [DONE] `mcp/.venv/Scripts/python.exe -m pytest tools/reporting/tests/test_reporting_models.py tools/reporting/tests/test_reporting_service.py tools/reporting/tests/test_reporting_plugin.py tests/unit/observability/test_health_readiness.py tests/unit/test_reporting_dependency_boundaries.py` -> `31 passed`

---

## Phase 8: Rollout and Operations

### Objective

Enable the capability gradually and reversibly.

### Tasks

1. Add config flag in `mcp/config/app.yaml`.
2. Deploy plugin disabled.
3. Enable with fixture provider in development.
4. Enable with real provider in integration.
5. Run backend discovery smoke test.
6. Enable for an internal use case and chart agent allowlist.
7. Monitor:
   - error rate;
   - latency;
   - result bytes;
   - row count;
   - truncation;
   - rate limits;
   - auth failures;
   - provider health.
8. Publish runbooks:
   - plugin failed to load;
   - provider unavailable;
   - schema mismatch;
   - result too large;
   - backend discovery mismatch;
   - auth/scope denial;
   - cache issue.
9. Define rollback:
   - disable plugin in config;
   - backend allowlist remains but reports unavailable;
   - chart agent falls back to user-provided data or a missing-data response;
   - no frontend change is required.

### Deliverables

- Deployment config
- Feature flag
- Dashboards and alerts
- Runbooks
- Rollback procedure
- Production readiness review

### Exit Criteria

- Tool can be disabled without restarting or changing other plugin code according to existing deployment behavior.
- Backend handles tool unavailability gracefully.
- Metrics and alerts are active.
- Operations owner approves production activation.

---

## 9. Configuration Example

### 9.1 Global MCP Configuration

```yaml
tools:
  reporting:
    enabled: false
    required: false
    config_file: config.yaml
```

### 9.2 Tool Configuration

```yaml
provider: fixture                 # fixture | approved_http | custom
schema_version: "1.0"

query:
  allowed_metrics:
    - income
    - expense
    - revenue
    - incident_count
    - response_time_ms
  allowed_dimensions:
    - day
    - week
    - month
    - quarter
    - category
    - department
  allowed_aggregations:
    - sum
    - avg
    - min
    - max
    - count
  max_metrics_per_query: 12
  max_filters: 10
  max_date_range_days: 3660
  default_granularity: month

limits:
  max_rows: 1000
  max_result_bytes: 262144
  max_warning_count: 10

runtime:
  timeout_seconds: 20
  retries: 1
  cache_seconds: 60

auth:
  outbound_profile: reporting_readonly

health:
  mode: shallow
  timeout_seconds: 3
```

---

## 10. Error Mapping

| MCP error | Backend normalized meaning | Recommended chart-agent behavior |
|---|---|---|
| `ReportingInvalidQuery` | Tool arguments invalid | Ask user to correct metric/date/filter |
| `ReportingMetricNotAllowed` | Unknown or disallowed metric | Explain supported metrics where safe |
| `ReportingDimensionNotAllowed` | Unknown or disallowed dimension | Ask for supported grouping |
| `ReportingScopeDenied` | Authorization denied | State data is unavailable for this scope |
| `ReportingNoData` | Valid query, no rows | Ask for another period/filter or explain no data |
| `ReportingResultTooLarge` | Query too broad | Ask to aggregate/filter |
| `ReportingProviderTimeout` | Temporary provider failure | Retry only per gateway policy; otherwise graceful failure |
| `ReportingProviderUnavailable` | External source unavailable | Fall back to other allowed data sources |
| `ReportingSchemaMismatch` | Provider contract failure | Mark plugin unhealthy and alert |
| `ReportingRateLimited` | Temporary limit | Apply retry/backoff policy |
| `ReportingCancelled` | Request cancelled | Stop work and return cancelled status |

---

## 11. Testing Matrix

| Layer | Required tests |
|---|---|
| Models | serialization, validation, scalar types, column/row consistency |
| Plugin | registration, schemas, config, health |
| Loader | enabled, disabled, optional failure, duplicate name |
| Service | query mapping, allowlists, aggregation, sorting |
| Provider | auth, timeout, error normalization |
| Results | bounds, bytes, truncation, provenance, empty results |
| FastMCP | discovery, call, invalid args, normalized response |
| Security | scope, secret fields, arbitrary SQL, cross-tenant access |
| Observability | trace correlation, safe logs, metrics |
| Contract | exact shared JSON fixtures |
| Backend integration | ToolGateway discovery/call/result mapping |
| Reliability | timeout, retry, cancellation, provider outage |
| Performance | concurrent calls, max rows, max bytes |

---

## 12. Risk Register

| Risk | Impact | Mitigation |
|---|---|---|
| MCP starts generating chart artifacts | Tier coupling | Explicit data-only contract and boundary tests |
| Arbitrary query language reaches provider | Injection/data exposure | Allowlisted metrics/dimensions and typed filters |
| Results too large | Transport/context pressure | Aggregation-first, row/byte limits, explicit truncation |
| Provider-specific fields leak into backend | Tight coupling | Provider-neutral dataset schema |
| Schema mismatch between tiers | Runtime failure | Versioned schema and shared fixtures |
| Raw tool result enters prompt | Context/data leak | Backend adapter and prompt-leak tests |
| Credentials leak | Security incident | Shared auth/secret services and redaction |
| Cross-tenant data query | Data breach | Trusted scope enforcement and negative tests |
| New tool auto-becomes callable | Policy bypass | Backend configured allowlist remains authoritative |
| Provider outage breaks chart chat | Poor availability | Optional plugin, graceful backend fallback |

---

## 13. Definition of Done

The MCP visualization data integration is complete when:

- A modular reporting plugin exists under `mcp/tools/reporting/`.
- The existing loader discovers it automatically.
- The registry exposes stable read-only reporting capabilities.
- Inputs are typed, allowlisted, bounded, and scope-aware.
- Outputs use the versioned structured dataset contract.
- Outputs include types, rows, counts, truncation, source, and safe provenance.
- The tool aggregates before returning data.
- Oversized or unsafe queries fail cleanly.
- Credentials and raw provider payloads never leave the plugin boundary.
- Backend calls the tool only through its existing `ToolGateway` and `MCPClientAdapter`.
- The backend chart agent can build charts from the result without provider-specific code.
- MCP never builds `ChartArtifact`, `ChartContextSummary`, renderer code, or workflow state.
- Unit, loader, FastMCP, security, contract, and backend smoke tests pass.
- The capability is observable, configurable, and reversible.

---

## 14. Implementation Checklist

### Contract
- [ ] Approve logical tool names.
- [ ] Approve request/response schema v1.
- [ ] Publish shared fixtures.
- [ ] Define errors and truncation.

### Plugin
- [ ] Add reporting folder.
- [ ] Add manifest/config.
- [ ] Add typed models.
- [ ] Add provider protocol.
- [ ] Add fixture provider.
- [ ] Add real provider adapter.
- [ ] Register FastMCP tools.
- [DONE] Add health.

### Controls
- [ ] Metric/dimension allowlists.
- [ ] Date/filter/row/byte limits.
- [ ] Scope enforcement.
- [ ] Auth and secret resolution.
- [ ] Rate limits and timeouts.
- [DONE] Redaction and trace correlation.

### Integration
- [DONE] Registry/capability discovery.
- [DONE] Backend allowlist mapping.
- [DONE] ToolGateway smoke test.
- [DONE] Structured dataset adapter test.
- [DONE] End-to-end tool-based chart test.

### Operations
- [ ] Feature flag.
- [ ] Metrics and alerts.
- [ ] Runbooks.
- [ ] Rollback.
