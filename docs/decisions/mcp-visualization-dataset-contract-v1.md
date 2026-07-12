# MCP Visualization Dataset Contract V1 Decision Record

**Status:** Accepted for MCP visualization phase 0  
**Date:** 2026-07-10  
**Scope:** MCP visualization dataset contract freeze, baseline capture, and provider decision before reporting-tool implementation

## Purpose

Freeze the MCP-owned visualization dataset contract before phase 1 adds shared models, validation, and the reporting plugin.

## Baseline Validation Commands

The MCP visualization phase-0 baseline is defined by these commands from `mcp/`:

- `.venv\Scripts\python.exe -m pytest tests/unit/test_visualization_phase0_contract.py`
- `.venv\Scripts\python.exe -m pytest`

The full `pytest` suite already covers the current unit, loader, manifest, FastMCP HTTP smoke, and integration-smoke layers. Live backend and outbound-network checks remain opt-in and are expected to skip unless their environment flags are enabled.

## Baseline Validation Result (2026-07-10)

- Focused visualization contract validation passed: `.venv\Scripts\python.exe -m pytest tests/unit/test_visualization_phase0_contract.py` -> `4 passed`.
- Full MCP `pytest` baseline is green after the phase-0 additions: `.venv\Scripts\python.exe -m pytest` -> `94 passed`, `3 skipped`.
- The skipped coverage remains the expected opt-in live backend and external-network smoke checks. No non-skipped MCP unit, loader, manifest, FastMCP HTTP, or integration tests failed.

## Current MCP Contract Surfaces

| Surface | Current owner | Phase-0 note |
|---|---|---|
| Plugin protocol | `mcp/app/tools_base/plugin.py` | Plugins implement `name`, `version`, `capabilities`, `register(FastMCP)`, and async `health()`. |
| Manifest schema | `mcp/app/tools_base/manifest.py` | Tool folders must declare `mcp.tools.<name>` packages, unique capability/tool names, and bounded tool descriptors. |
| Config merge behavior | `mcp/app/loader.py` | Merge precedence is `defaults` -> app-level tool settings -> local `config.yaml`, with environment placeholder resolution after merge. |
| Tool result envelope | `mcp/app/tools_base/results.py` | Successful and failed tool payloads are bounded JSON only and reject secret-like keys plus raw HTTP objects. |
| Trace propagation | `mcp/app/tools_base/decorators.py` and `mcp/app/observability/context.py` | Tool calls prefer auth request context trace ids, then fall back to inbound `x-trace-id` or `traceparent`. |
| Auth context | `mcp/app/context.py`, `mcp/app/security/auth.py`, and `mcp/app/tools_base/decorators.py` | Shared auth is exposed through `ToolRuntimeContext.auth`; tool handlers validate request context through `guard_tool_call()`. |
| Health output | `mcp/app/health.py` | `mcp.health` returns server, tool-count, security, config, services, and checks payloads. |
| Capabilities output | `mcp/app/capabilities.py` | `mcp.capabilities` and `mcp.tools.list` summarize registry capabilities and tool metadata without leaking secrets. |
| Runtime defaults | `mcp/config/app.yaml` | Current transport defaults are `timeout_seconds=30`, `max_result_bytes=262144`, `max_argument_bytes=65536`, and `max_results=10`. |

## Phase-0 Contract Decisions

1. The primary public capability name is `reporting.metric_series.read`, exposed through the MCP tool name `reporting.query_metric_series`.
2. The optional secondary capability name is `reporting.category_summary.read`, exposed through the MCP tool name `reporting.query_category_summary`.
3. The request schema frozen in phase 0 is `query_metric_series_request_v1.schema.json`, with provider-neutral fields for metrics, dimension, date bounds, filters, aggregation, granularity, sort order, and a bounded `limit`.
4. The response schema frozen in phase 0 is `structured_dataset_response_v1.schema.json`, using `schema_version="1.0"`, typed columns, bounded rows, `row_count`, optional `total_row_count`, explicit `truncated`, safe `source`, safe `query_summary`, optional `time_range`, bounded `warnings`, and scalar-only `provenance`.
5. The canonical output schema name for the future manifest is `structured_dataset_v1`.
6. Truncation semantics are frozen as: `row_count == len(rows)`, `truncated=true` is explicit, and `total_row_count` carries the pre-truncation count when known.
7. V1 transport limits are frozen at `limit <= 100` rows for the dataset contract and `max_result_bytes <= 262144` bytes unless a specific tool manifest declares a lower limit.
8. MCP dataset responses are transport data only. They must not contain chart-type selection, renderer names, frontend options, `ChartArtifact`, `ChartContextSummary`, workflow-state objects, raw provider payloads, SQL text, credentials, headers, connection strings, or internal endpoint URLs.
9. The phase-0 error catalog is frozen to these codes: `invalid_query`, `unsupported_metric`, `unsupported_dimension`, `invalid_date_range`, `unauthorized_scope`, `provider_unavailable`, `timeout`, `rate_limited`, `result_too_large`, `schema_mismatch`, and `internal_error`.
10. The V1 provider decision is `fixture/local adapter for development plus a provider interface`. Production provider wiring remains phase-3 work.
11. Arbitrary SQL is explicitly out of contract. Requests carry only approved logical metrics, dimensions, filters, and aggregations.

## Frozen Phase-0 Artifacts

- `mcp/tests/fixtures/visualization/query_metric_series_request_v1.schema.json`
- `mcp/tests/fixtures/visualization/structured_dataset_response_v1.schema.json`
- `mcp/tests/fixtures/visualization/query_metric_series_request_v1.json`
- `mcp/tests/fixtures/visualization/structured_dataset_response_v1.json`
- `mcp/tests/fixtures/visualization/structured_dataset_response_truncated_v1.json`
- `mcp/tests/fixtures/visualization/query_metric_series_error_v1.json`
- `mcp/tests/fixtures/visualization/reporting_error_catalog_v1.json`
