# MCP Phase 7 Implementation Plan: Observability and Operations

**Document:** `mcp-phase-07-observability-operations-plan.md`  
**Phase:** 7 of 8 [DONE]  
**Architecture phase:** Observability and Operations  
**Version:** 1.0  

**Source alignment:** `mcp-architecture.md`, `pluggable_agentic_ai_overall_architecture.md`, `backend-application-architecture.md`, `backend-tooling-mcp-client-architecture.md`, `backend-tooling-mcp-client-plan.md`, `backend-policy-architecture.md`, and `backend-observability-plan.md`  
**Repository rule:** all MCP server runtime code lives under `mcp/`  
**Runtime stack:** Python 3.12+, FastMCP, Pydantic, PyYAML, HTTPX, pytest, ruff, mypy

---


## 1. Purpose

This plan adds operational visibility to the MCP server. It introduces trace correlation from backend MCP calls, safe tool-call events, metrics recording, readiness checks, and startup diagnostics. This makes the MCP tier diagnosable without leaking secrets, raw tool inputs, or raw tool outputs.

Core rule for this phase:

> Every tool call should produce safe trace-correlated observability data, but raw arguments, raw results, credentials, and downstream payloads are not logged or traced by default.

## 2. Scope

In scope:

- Trace/request context propagation.
- Event catalog.
- Trace recorder.
- Tool-call wrapper for started/completed/failed/timeout/cancelled events.
- Metrics recorder interface and in-memory/no-op implementations.
- Health/readiness/liveness checks.
- Startup diagnostics.
- Safe operation summaries.

Out of scope:

- External metrics backend deployment.
- Distributed tracing vendor integration.
- Log aggregation setup.
- Backend UI trace lookup.
- Long-term operational database.

## 3. Target Repository Shape

Create or update:

```text
mcp/app/observability/
  __init__.py
  context.py
  events.py
  tracing.py
  metrics.py
  logging.py
mcp/app/
  health.py
  capabilities.py
  loader.py
  server.py
  bootstrap.py
mcp/app/tools_base/
  decorators.py
  results.py
mcp/tests/unit/observability/
  test_trace_context.py
  test_event_catalog.py
  test_trace_recorder.py
  test_metrics.py
  test_tool_call_events.py
  test_health_readiness.py
  test_startup_diagnostics.py
```

## 4. Implementation Steps

### [DONE] Step 1: Add Trace Context

Create `mcp/app/observability/context.py` with:

- `TraceContext` dataclass.
- `new_trace_id()` helper for MCP-generated trace IDs.
- inbound `x-trace-id` and `x-request-id` validation.
- contextvars for async-safe propagation.

Rules:

- Accept backend-provided trace IDs only after validation.
- Generate a new trace ID if missing or invalid.
- Clear context after each request/tool call.

### [DONE] Step 2: Add Event Catalog

Create `mcp/app/observability/events.py` with constants:

```text
mcp_startup_started
mcp_config_loaded
mcp_config_invalid
mcp_tool_discovery_started
mcp_tool_manifest_loaded
mcp_tool_config_loaded
mcp_tool_registered
mcp_tool_registration_failed
mcp_tool_call_started
mcp_tool_call_completed
mcp_tool_call_failed
mcp_tool_call_timeout
mcp_tool_call_cancelled
mcp_health_checked
mcp_shutdown_started
mcp_shutdown_completed
```

Add tests to prevent duplicate event names.

### [DONE] Step 3: Add Trace Recorder

Create `mcp/app/observability/tracing.py` with:

- `TraceRecorder` protocol.
- `NoopTraceRecorder`.
- `InMemoryTraceRecorder` for tests.
- `record_event(event_name, payload)` method that redacts and truncates payloads.

Safe trace fields:

```text
trace_id
request_id
server_name
tool_name
capability_name
status
duration_ms
error_code
truncated
result_count
```

Unsafe by default:

```text
raw arguments
raw results
authorization headers
OAuth tokens
JWTs
raw downstream responses
stack traces in production
```

### [DONE] Step 4: Add Metrics Recorder

Create `mcp/app/observability/metrics.py` with:

- `MetricsRecorder` protocol.
- `NoopMetricsRecorder`.
- `InMemoryMetricsRecorder` for tests.
- `increment(name, tags)` and `timing(name, value_ms, tags)` methods.

Recommended metrics:

```text
mcp.tool.call.count
mcp.tool.error.count
mcp.tool.duration_ms
mcp.tool.timeout.count
mcp.tool.rate_limited.count
mcp.registry.loaded_tools
mcp.registry.unhealthy_tools
```

Keep tags low-cardinality:

```text
tool_name
capability_name
status
error_code
```

Do not use trace IDs, session IDs, user prompts, queries, URLs, or raw error messages as metric tags.

### [DONE] Step 5: Add Tool-Call Observability Wrapper

Create a decorator or helper in `mcp/app/tools_base/decorators.py` that wraps tool execution:

```text
record started event
start timer
execute tool
record completed event and metrics
on validation/rate-limit/downstream errors: record failed event and metrics
on timeout: record timeout event and metrics
on cancellation: record cancelled event and metrics
return safe result or safe error
```

Integrate the wrapper with `websearch.search`.

### [DONE] Step 6: Add Readiness Checks

Deepen `mcp/app/health.py` with:

- process liveness
- config loaded
- registry loaded
- required tools loaded
- optional failed tools count
- security mode valid
- websearch local readiness

Health statuses:

```text
ok
degraded
unhealthy
```

Readiness should fail when required tools fail or config is invalid.

### [DONE] Step 7: Add Startup Diagnostics

During startup, record safe diagnostics:

- config loaded
- server name/version/environment
- tools directory
- enabled tool count
- disabled tool count
- failed optional tool count
- inbound auth mode
- TLS mode

Do not log raw config, secrets, private keys, tokens, or raw tool configs.

### [DONE] Step 8: Update Capabilities

Capabilities should include safe operational metadata only:

- tool name
- capability name
- risk level
- enabled
- status
- version

Do not expose raw input examples with secrets or private downstream URLs.

## 5. Boundary Rules

- Observability code does not call backend trace store.
- MCP traces are local MCP operational diagnostics, not backend workflow state.
- Metrics use low-cardinality tags.
- Logs/traces never include raw credentials or raw payloads.
- Tool outputs remain data, not instructions.

## 6. Tests

Add tests for:

| Test File | Purpose |
|---|---|
| `test_trace_context.py` | Trace ID validation, alias handling, context reset. |
| `test_event_catalog.py` | Event names are unique and complete. |
| `test_trace_recorder.py` | Redaction/truncation and no-raise behavior. |
| `test_metrics.py` | Counters/timings and low-cardinality tags. |
| `test_tool_call_events.py` | Tool success/failure emits safe events. |
| `test_health_readiness.py` | Readiness reflects registry/tool health. |
| `test_startup_diagnostics.py` | Startup logs are safe and useful. |

Recommended checks:

```bash
cd mcp
python -m pytest tests/unit/observability
python -m ruff check app tools tests
python -m mypy app
```

## 7. Acceptance Criteria

This phase is complete when:

- Every tool call emits safe trace-correlated events.
- Tool metrics include call count, error count, timeout count, and duration.
- Health shows loaded/unhealthy tool counts.
- Readiness fails when required tools fail.
- Startup diagnostics summarize configuration and tool loading safely.
- Raw arguments, raw results, and credentials are not logged or traced by default.

## 8. Handoff to Phase 8

Phase 8 should connect the already-working backend to the local MCP server and prove the backend can discover and call `websearch.search` through its existing MCP client/tooling boundary.
