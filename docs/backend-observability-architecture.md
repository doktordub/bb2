# Observability Architecture

**Document:** `observability-architecture.md`  
**Version:** 1.0  
**Source alignment:** `backend-application-architecture.md`, `backend-foundation-architecture.md`, `backend-core-contracts-architecture.md`, and `configuration-architecture.md`  
**Scope:** Trace ID lifecycle, structured logging, trace event recording, redaction, health aggregation, lightweight metrics, startup diagnostics, test strategy, and acceptance criteria for the backend application tier.

---

## 1. Purpose

This document defines the fourth implementation-focused architecture document for the backend application tier.

It follows:

1. `backend-foundation-architecture.md`
2. `backend-core-contracts-architecture.md`
3. `configuration-architecture.md`
4. `observability-architecture.md` ← this document

The foundation phase establishes the backend shell, application factory, startup pattern, basic health route, logging baseline, and test layout. The core contracts phase defines the stable `TraceEvent`, `TraceStore`, health, and error contracts. The configuration phase defines how observability and health behavior are selected from YAML and environment variables.

This document turns those pieces into a practical observability foundation. It defines how the backend creates trace IDs, propagates correlation metadata, emits structured logs, records trace events, redacts sensitive data, builds health summaries, and exposes enough diagnostics to make later LLM, memory, MCP, workflow state, orchestration, and agent modules debuggable.

The goal is not to build a full production telemetry platform in V1. The goal is to make every request and important backend action traceable before concrete modules become complex.

---

## 2. Source Architecture Alignment

This document follows the established backend architecture rules:

- The backend is one deployable application tier in V1.
- Frontend communicates with the backend over REST / SSE.
- Backend communicates with the external MCP tier through a backend-side MCP client adapter.
- The backend does not implement the MCP server.
- Agents receive controlled capabilities through `OrchestrationContext`.
- Agents do not import provider SDKs, MCP clients, SQLite clients, ArcadeDB clients, external API clients, or `memory_store.service.MemoryService`.
- Trace events are operational records, not long-term memory.
- Trace events must be written through `TraceStore`.
- Trace payloads must be JSON-safe.
- Trace payloads, logs, errors, and health responses must not expose secrets or sensitive data.
- Observability settings are read from `ConfigurationView`.
- SQLite is the V1 trace storage engine behind an adapter, not something agents or API routes access directly.
- Detailed trace persistence query/debug behavior is refined later in `sqlite-trace-store-architecture.md`.

---

## 3. Position in the Backend Implementation Sequence

The backend implementation sequence is:

```text
Phase 1: Backend Foundation Skeleton
Phase 2: Core Contracts
Phase 3: Configuration Loader
Phase 4: Observability and Trace Foundation
Phase 5: Workflow State Store
Phase 6: API and Session Walking Skeleton
Phase 7: LLM Gateway
Phase 8: Memory Gateway
Phase 9: Tool Gateway and MCP Client Adapter
Phase 10: Orchestration Runtime and Strategies
Phase 11: Agent Plugins
Phase 12: Hardening and Deployment Readiness
```

This document expands Phase 4.

The output of this phase is not a fully implemented business runtime. The output is a traceable backend foundation that later phases can use from the beginning.

---

## 4. Observability Architecture Goals

The observability layer should be:

1. **Trace-first**  
   Every backend request gets a trace ID that follows the request through API, session, orchestration, gateways, agents, tools, state, and response handling.

2. **Structured**  
   Logs and trace events should be machine-readable and consistent.

3. **Safe by default**  
   Secrets, credentials, raw authorization headers, sensitive memory contents, raw prompts, and raw completions should not appear in logs, traces, health responses, or error messages.

4. **Configuration-driven**  
   Log level, structured logging, trace payload behavior, redaction, health detail, and local diagnostics are controlled through configuration.

5. **Adapter-friendly**  
   Observability should use the existing `TraceStore` contract and should not couple runtime code directly to SQLite.

6. **Low-friction for developers**  
   It should be easy for later modules to record a trace event without duplicating boilerplate.

7. **Useful for failures**  
   Known errors should include enough trace-safe metadata to diagnose what failed and where.

8. **Streaming-aware**  
   Streaming routes should record start, progress summary, completion, cancellation, and error events without logging every token as a database row.

9. **Testable with fakes**  
   Unit and integration tests should be able to use fake trace stores and assert emitted events.

10. **Incremental**  
    Phase 4 should establish the common patterns. Later documents can deepen SQLite persistence, API error mapping, gateway-specific telemetry, and deployment logging.

---

## 5. Observability Non-Goals

This phase should not implement:

- A full OpenTelemetry deployment.
- Distributed tracing across multiple services.
- Centralized log shipping.
- Prometheus scraping endpoints unless explicitly needed later.
- Detailed trace search UI.
- Full audit/compliance event model.
- Full SQLite trace query API.
- Provider-specific LLM telemetry adapters.
- MCP server-side observability.
- Frontend telemetry.
- User analytics.
- Runtime prompt/completion archival.
- Long-term memory inspection.

Those belong in later architecture or deployment documents if needed.

---

## 6. Recommended Observability Package Layout

Recommended layout:

```text
backend/
  app/
    observability/
      __init__.py
      context.py
      ids.py
      logging.py
      tracing.py
      events.py
      redaction.py
      health.py
      metrics.py
      middleware.py
      errors.py

    persistence/
      trace_store.py
      sqlite_trace_store.py          # initial append-only implementation only
      sqlite_trace_schema.py         # minimal schema bootstrap only

    contracts/
      trace.py
      health.py
      errors.py
      config.py

    config/
      view.py
      redaction.py

    testing/
      fakes/
        fake_trace.py
        fake_config.py

  tests/
    unit/
      observability/
        test_trace_id_generation.py
        test_trace_context.py
        test_structured_logging.py
        test_trace_recorder.py
        test_redaction.py
        test_health_aggregator.py
        test_metrics_counters.py
        test_error_observability.py

    integration/
      test_startup_observability.py
      test_trace_store_sqlite_smoke.py
```

### 6.1 Why `app/observability/` Is Separate from `app/persistence/`

`app/observability/` owns runtime diagnostics concerns:

```text
Trace ID generation
Trace context propagation
Structured log formatting
Trace event construction
Redaction
Health aggregation
Metrics counters/timers
Request middleware hooks
```

`app/persistence/` owns concrete storage:

```text
TraceStore implementation
SQLite connection handling
Trace table schema creation
Append-only trace persistence
```

This keeps logging, redaction, and event construction independent from SQLite.

---

## 7. Dependency Direction Rules

Allowed:

```text
app/api/*             -> app/observability/*
app/session/*         -> app/observability/*
app/orchestration/*   -> app/observability/*
app/llm/*             -> app/observability/*
app/tools/*           -> app/observability/*
app/persistence/*     -> app/contracts/trace.py
app/observability/*   -> app/contracts/trace.py
app/observability/*   -> app/contracts/health.py
app/observability/*   -> app/contracts/errors.py
app/observability/*   -> app/contracts/config.py
```

Avoid:

```text
app/observability/* -> app/agents/*
app/observability/* -> app/orchestration/core.py
app/observability/* -> provider SDKs
app/observability/* -> MCP SDK/client implementation
app/observability/* -> memory_store.service.MemoryService
app/observability/* -> ArcadeDB clients
app/observability/* -> business workflow logic
```

The observability layer may depend on standard library modules such as `logging`, `contextvars`, `time`, `uuid`, `datetime`, and `json`. It should not depend on concrete LLM, MCP, memory, or agent implementations.

---

## 8. Observability Source Model

Observability data has three related but separate forms:

| Form | Purpose | Storage | Examples |
|---|---|---|---|
| Structured logs | Runtime diagnostics for humans and log processors | stdout / file / future collector | startup messages, request summary, warning, error |
| Trace events | Request-level operational timeline | `TraceStore` | `request_received`, `llm_call_started`, `agent_completed` |
| Health data | Current component status | HTTP response / logs | configured, reachable, degraded, error |
| Lightweight metrics | Local counters and timings | memory initially / future exporter | request duration, LLM call count, tool error count |

Rules:

- Logs are not a replacement for trace events.
- Trace events are not long-term memory.
- Health responses are not trace dumps.
- Metrics should not contain raw payloads.
- All four forms must use the same redaction rules.

---

## 9. Configuration Integration

The configuration phase defines the starting observability and health shape:

```yaml
observability:
  log_level: ${env:APP_LOG_LEVEL:INFO}
  structured_logging: true
  trace_payloads_enabled: true
  redact_secrets: true

health:
  expose_config_summary: true
  expose_provider_names: true
  expose_secret_values: false
```

This phase should extend the shape carefully while preserving compatibility:

```yaml
observability:
  log_level: ${env:APP_LOG_LEVEL:INFO}
  structured_logging: true
  trace_enabled: true
  trace_payloads_enabled: true
  trace_store_required: true
  redact_secrets: true
  include_stack_traces_in_logs: false
  include_stack_traces_in_traces: false
  max_trace_payload_chars: 8000
  slow_request_ms: 5000
  slow_llm_call_ms: 30000
  slow_tool_call_ms: 10000
  metrics_enabled: true

health:
  expose_config_summary: true
  expose_provider_names: true
  expose_secret_values: false
  include_component_details: true
```

### 9.1 Configuration Access Rule

Runtime code should read observability settings through `ConfigurationView` or small resolver helpers, not through raw environment variables.

Recommended helper:

```python
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ObservabilitySettings:
    log_level: str
    structured_logging: bool
    trace_enabled: bool
    trace_payloads_enabled: bool
    trace_store_required: bool
    redact_secrets: bool
    include_stack_traces_in_logs: bool
    include_stack_traces_in_traces: bool
    max_trace_payload_chars: int
    slow_request_ms: int
    slow_llm_call_ms: int
    slow_tool_call_ms: int
    metrics_enabled: bool
```

---

## 10. Trace ID Lifecycle

A trace ID identifies one backend request lifecycle.

### 10.1 Sources of Trace ID

Resolution order:

```text
1. Use inbound trace ID header if present and valid.
2. Use request field trace_id if present and valid.
3. Generate a new trace ID at the API boundary.
4. Attach trace ID to RequestContext.
5. Propagate trace ID through OrchestrationContext.
6. Include trace ID in OrchestrationResult.
7. Include trace ID in API response metadata and SSE events.
```

Recommended inbound headers:

```text
X-Trace-Id
X-Request-Id optional alias
```

Recommended generated format:

```text
trace_<uuid4_hex>
```

Example helper:

```python
from uuid import uuid4


def new_trace_id() -> str:
    return f"trace_{uuid4().hex}"
```

### 10.2 Trace ID Validation

A valid trace ID should be:

- Non-empty.
- Bounded in length.
- ASCII-safe.
- Free of spaces and control characters.
- Not a full authorization token or secret.

Recommended validation:

```python
import re

_TRACE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{8,128}$")


def is_valid_trace_id(value: str | None) -> bool:
    return bool(value and _TRACE_ID_PATTERN.fullmatch(value))
```

### 10.3 Trace ID Response Rule

Every non-health request should return the trace ID in the response, either in headers, response metadata, or both:

```text
X-Trace-Id: trace_...
```

For `/health`, trace ID is optional. For startup failures, the log should include a startup correlation ID if request trace ID does not exist.

---

## 11. Trace Context Propagation

Trace context carries request-level metadata needed for logs and trace events.

Recommended object:

```python
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class TraceContext:
    trace_id: str
    session_id: str | None = None
    user_id: str | None = None
    usecase: str | None = None
    request_id: str | None = None
    component: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

### 11.1 Runtime Storage

Use `contextvars` for log enrichment within the current async task:

```python
from contextvars import ContextVar

current_trace_context: ContextVar[TraceContext | None] = ContextVar(
    "current_trace_context",
    default=None,
)
```

### 11.2 Propagation Rules

- API middleware creates or resolves the trace ID.
- API layer attaches trace ID to request DTOs or request state.
- Session service copies trace ID into `RequestContext`.
- Orchestration runtime copies request metadata into `OrchestrationContext`.
- Gateway calls use `context.request.trace_id` and the current `TraceContext`.
- Background work is not part of V1 unless explicitly scheduled later; if added, it must create a new trace context or carry a parent trace ID.

---

## 12. Structured Logging

Structured logs should be emitted as JSON-compatible records in production-like modes and readable key-value logs in local development if desired.

### 12.1 Required Log Fields

Recommended base fields:

```text
timestamp
level
message
logger
component
trace_id
session_id
user_id_hash optional
usecase
event_type optional
operation optional
duration_ms optional
status optional
error_type optional
```

### 12.2 User Identifier Rule

Logs should avoid raw user identifiers when possible. For V1 local development, raw user IDs may be acceptable only if they are synthetic. Production-oriented logs should use a stable hash or omit user identifiers.

Recommended helper:

```python
import hashlib


def stable_hash(value: str | None) -> str | None:
    if not value:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
```

### 12.3 Logging Setup

Recommended setup flow:

```text
1. Initialize minimal console logging before config loads.
2. Load validated config.
3. Reconfigure log level and structured logging from config.
4. Install trace-context log filter.
5. Log redacted startup summary.
6. Log component construction summary.
```

### 12.4 Log Level Guidance

| Level | Use |
|---|---|
| `DEBUG` | Local debugging; must still redact secrets. |
| `INFO` | Request start/completion, startup summary, component wiring. |
| `WARNING` | Recoverable degraded behavior, fallback selected, slow operation. |
| `ERROR` | Failed request, gateway error, persistence error. |
| `CRITICAL` | Startup cannot continue or unsafe configuration detected. |

---

## 13. Redaction Model

Redaction must be shared by logs, trace payloads, health responses, config summaries, and error metadata.

### 13.1 Sensitive Keys

Default sensitive key fragments:

```text
api_key
authorization
auth
bearer
client_secret
connection_string
cookie
credential
jwt
key
password
refresh_token
secret
token
```

### 13.2 Sensitive Payload Types

Do not store or log by default:

- API keys.
- Tokens.
- Full authorization headers.
- Passwords.
- Sensitive connection strings.
- Raw prompts.
- Raw LLM completions.
- Full memory contents.
- Full document chunks.
- Full tool results that may contain downstream secrets or PII.
- Full request bodies unless explicitly safe.

### 13.3 Redaction Helper

Recommended behavior:

```python
REDACTED = "<redacted>"
TRUNCATED = "<truncated>"


def redact_value(key: str, value: object) -> object:
    lower = key.lower()
    if any(fragment in lower for fragment in SENSITIVE_KEY_FRAGMENTS):
        return REDACTED
    return value
```

### 13.4 Recursive Redaction

The redactor should:

- Traverse dictionaries and lists.
- Redact by key name.
- Optionally truncate long strings.
- Replace unsupported objects with safe strings.
- Never raise while handling an error path.

Example output:

```json
{
  "provider": "local_openai_compatible",
  "base_url": "http://192.168.1.80:8081/v1",
  "api_key": "<redacted>",
  "prompt_chars": 1840,
  "completion_chars": 420
}
```

---

## 14. Trace Event Contract Usage

The core contracts define this event shape:

```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class TraceEvent:
    trace_id: str
    session_id: str
    event_type: str
    component: str
    timestamp: datetime
    user_id: str | None = None
    usecase: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
```

This phase should not change the contract unless absolutely necessary. Instead, the observability layer should provide helpers that build valid `TraceEvent` objects consistently.

### 14.1 Trace Event Field Rules

| Field | Rule |
|---|---|
| `trace_id` | Required for every request-scoped event. |
| `session_id` | Required; use a safe placeholder such as `unknown_session` only during startup or pre-session failures. |
| `event_type` | Must use known constants where possible. |
| `component` | Should identify the source module, such as `api.chat`, `orchestration.runtime`, or `llm.gateway`. |
| `timestamp` | Timezone-aware UTC datetime. |
| `user_id` | Optional; avoid storing if not needed. |
| `usecase` | Optional but recommended after request/use-case resolution. |
| `payload` | JSON-safe, redacted, bounded. |

### 14.2 Trace Event Payload Rule

Payloads should describe the operation, not dump raw data.

Use:

```json
{
  "profile": "research_reasoning",
  "provider": "local_openai_compatible",
  "model": "configured_model_name",
  "input_tokens": 512,
  "output_tokens": 128,
  "duration_ms": 1840,
  "success": true
}
```

Avoid:

```json
{
  "messages": ["full prompt text"],
  "raw_response": "full model completion",
  "api_key": "..."
}
```

---

## 15. Trace Recorder Helper

Runtime modules should not manually construct repetitive trace event boilerplate.

Recommended helper:

```python
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.contracts.trace import TraceEvent, TraceStore


@dataclass(slots=True)
class TraceRecorder:
    store: TraceStore
    settings: ObservabilitySettings
    redactor: "Redactor"

    async def record(
        self,
        *,
        trace_id: str,
        session_id: str,
        event_type: str,
        component: str,
        user_id: str | None = None,
        usecase: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        if not self.settings.trace_enabled:
            return

        safe_payload = {}
        if self.settings.trace_payloads_enabled and payload:
            safe_payload = self.redactor.redact_and_bound(
                payload,
                max_chars=self.settings.max_trace_payload_chars,
            )

        event = TraceEvent(
            trace_id=trace_id,
            session_id=session_id,
            event_type=event_type,
            component=component,
            timestamp=datetime.now(UTC),
            user_id=user_id,
            usecase=usecase,
            payload=safe_payload,
        )
        await self.store.record_event(event)
```

### 15.1 Failure Behavior

Trace recording failure should not normally break the user request unless `trace_store_required` is true.

Recommended behavior:

| Setting | Behavior |
|---|---|
| `trace_store_required: true` | Trace store failure can fail startup or mark service unhealthy. |
| `trace_store_required: false` | Trace store failure logs an error and request may continue. |

During local development, either setting can be used. For production-like V1, prefer `true` to avoid silent loss of diagnostics.

---

## 16. Event Naming Conventions

Use lowercase snake_case event names.

Pattern:

```text
<noun_or_component>_<verb_or_state>
```

Examples:

```text
request_received
context_created
llm_call_started
llm_call_completed
llm_call_failed
tool_call_started
tool_call_completed
tool_call_failed
```

Do not create overly specific event names for every provider or agent. Provider, agent, profile, and tool names belong in the payload.

Use:

```text
llm_call_completed
payload.provider = "openai_compatible"
payload.profile = "research_reasoning"
```

Avoid:

```text
qwen_research_model_call_completed
openai_document_agent_call_completed
```

---

## 17. Minimum Trace Event Taxonomy

The core contracts already define the minimum event constants. This architecture groups them by lifecycle.

### 17.1 Request and Response Events

```text
request_received
context_created
response_returned
error_occurred
```

Recommended payloads:

```json
{
  "method": "POST",
  "route": "/chat",
  "usecase": "default_chat",
  "client": "frontend",
  "streaming": false
}
```

```json
{
  "status_code": 200,
  "duration_ms": 830,
  "streaming": false
}
```

### 17.2 Workflow State Events

```text
workflow_state_loaded
workflow_state_saved
```

Recommended payloads:

```json
{
  "state_keys_count": 4,
  "duration_ms": 12,
  "provider": "sqlite"
}
```

Do not store full conversation state in trace payloads.

### 17.3 Memory Events

```text
memory_search_started
memory_search_completed
```

Recommended payloads:

```json
{
  "scope": {
    "usecase": "default_chat",
    "project_id": "project_1"
  },
  "memory_types": ["project_fact", "document_chunk"],
  "limit": 10
}
```

```json
{
  "result_count": 6,
  "duration_ms": 44,
  "top_score": 0.82
}
```

Do not store full memory text or full document chunk text in trace payloads.

### 17.4 LLM Events

```text
llm_call_started
llm_call_completed
llm_call_failed
llm_fallback_selected
```

Recommended payloads:

```json
{
  "component": "agent.document_qa_agent",
  "profile": "research_reasoning",
  "provider": "local_openai_compatible",
  "model": "configured_model_name",
  "temperature": 0.2,
  "max_tokens": 1200
}
```

```json
{
  "profile": "research_reasoning",
  "input_tokens": 1280,
  "output_tokens": 340,
  "total_tokens": 1620,
  "duration_ms": 5410,
  "success": true
}
```

Do not store raw prompts, raw messages, raw completions, API keys, or authorization headers.

### 17.5 Strategy and Agent Events

```text
strategy_selected
agent_selected
agent_started
agent_completed
```

Recommended payloads:

```json
{
  "strategy": "direct_agent",
  "reason": "usecase_default",
  "agent_count": 1
}
```

```json
{
  "agent_name": "document_qa_agent",
  "llm_profile": "research_reasoning",
  "tool_call_count": 1,
  "memory_update_count": 0,
  "duration_ms": 6100
}
```

Do not store full agent answer in trace payloads unless explicitly enabled for local debugging and redacted/truncated.

### 17.6 Tool and MCP Events

```text
tool_call_started
tool_call_completed
tool_call_failed
```

Recommended payloads:

```json
{
  "tool_name": "documents.search",
  "source": "mcp",
  "argument_keys": ["query", "limit"],
  "requires_approval": false
}
```

```json
{
  "tool_name": "documents.search",
  "success": true,
  "duration_ms": 230,
  "result_summary": {
    "items_count": 5
  }
}
```

Do not store complete tool arguments or full downstream API responses unless explicitly safe.

---

## 18. Additional Recommended Event Types

The minimum set is enough for the early walking skeleton. The following event names are recommended as later modules become concrete:

```text
startup_started
startup_completed
startup_failed
config_loaded
config_validation_failed
health_checked
policy_evaluated
policy_denied
session_created
session_resumed
session_reset
stream_started
stream_completed
stream_cancelled
stream_failed
mcp_tools_listed
mcp_call_started
mcp_call_completed
mcp_call_failed
memory_upsert_started
memory_upsert_completed
memory_upsert_failed
workflow_state_reset
```

Rules:

- Add constants in one place, such as `app/observability/events.py`.
- Avoid scattering literal event names across modules.
- Keep backward compatibility once event names appear in persisted traces.

---

## 19. Operation Timing

The observability layer should provide a simple timer helper.

```python
from contextlib import asynccontextmanager
from time import perf_counter
from typing import AsyncIterator


@asynccontextmanager
async def timed_operation() -> AsyncIterator[callable]:
    start = perf_counter()

    def elapsed_ms() -> int:
        return int((perf_counter() - start) * 1000)

    yield elapsed_ms
```

Usage pattern:

```python
async with timed_operation() as elapsed_ms:
    response = await context.llm.complete(request, context)

await trace.record(
    trace_id=context.request.trace_id,
    session_id=context.request.session_id,
    event_type="llm_call_completed",
    component="llm.gateway",
    payload={"duration_ms": elapsed_ms()},
)
```

### 19.1 Slow Operation Warnings

Emit warning logs for slow operations:

| Operation | Config path | Default |
|---|---|---:|
| HTTP request | `observability.slow_request_ms` | 5000 |
| LLM call | `observability.slow_llm_call_ms` | 30000 |
| MCP/tool call | `observability.slow_tool_call_ms` | 10000 |

Slow warnings should include trace ID, component, operation, duration, and safe resource names.

---

## 20. Error Observability

Known backend errors should be logged and traced consistently.

### 20.1 Error Categories

The core contracts define these categories:

```text
BackendError
ConfigurationError
PolicyDeniedError
GatewayError
LLMGatewayError
ToolGatewayError
MemoryGatewayError
WorkflowStateError
TraceStoreError
```

### 20.2 Error Payload Shape

Recommended trace-safe payload:

```json
{
  "error_type": "LLMGatewayError",
  "component": "llm.gateway",
  "operation": "complete",
  "profile": "research_reasoning",
  "provider": "local_openai_compatible",
  "retryable": true,
  "duration_ms": 30000
}
```

Avoid:

```json
{
  "exception": "full provider exception with API key...",
  "request_body": "full prompt...",
  "authorization": "Bearer ..."
}
```

### 20.3 Stack Trace Rule

Stack traces should be controlled by config:

```yaml
observability:
  include_stack_traces_in_logs: false
  include_stack_traces_in_traces: false
```

For local debugging, enabling stack traces can be useful. Stack traces must still pass through redaction or be limited to logs only.

---

## 21. Health Aggregation

The backend should expose a safe health response that aggregates component health checks.

Recommended route remains:

```text
GET /health
```

### 21.1 Health Aggregator

Recommended implementation:

```python
from dataclasses import dataclass
from typing import Any

from app.contracts.health import ComponentHealth, HealthCheck


@dataclass(slots=True)
class HealthAggregator:
    checks: dict[str, HealthCheck]
    redactor: "Redactor"

    async def check_all(self) -> dict[str, Any]:
        components: dict[str, Any] = {}
        overall = "ok"

        for name, check in self.checks.items():
            try:
                result = await check.health()
                safe_result = self.redactor.redact(result)
                components[name] = safe_result
                status = safe_result.get("status", "unknown") if isinstance(safe_result, dict) else "unknown"
            except Exception as exc:
                components[name] = {
                    "status": "error",
                    "error_type": type(exc).__name__,
                }
                status = "error"

            if status == "error":
                overall = "error"
            elif status == "degraded" and overall != "error":
                overall = "degraded"

        return {
            "status": overall,
            "components": components,
        }
```

### 21.2 Initial Health Sections

Recommended health output:

```json
{
  "status": "ok",
  "backend": {
    "configured": true,
    "environment": "local"
  },
  "configuration": {
    "loaded": true,
    "active_usecase": "default_chat"
  },
  "observability": {
    "trace_enabled": true,
    "structured_logging": true,
    "trace_store_configured": true
  },
  "trace": {
    "status": "ok",
    "provider": "sqlite"
  },
  "workflow_state": {
    "configured": true,
    "provider": "sqlite"
  },
  "memory": {
    "configured": true,
    "provider": "memory_store"
  },
  "llm": {
    "providers_configured": true,
    "profiles_count": 2
  },
  "mcp": {
    "main_mcp_configured": true
  }
}
```

### 21.3 Health Safety Rule

Health responses must not include:

- API keys.
- Tokens.
- Full authorization headers.
- Passwords.
- Sensitive connection strings.
- Raw prompts.
- Raw completions.
- Memory contents.
- Full tool responses.
- Full stack traces.

---

## 22. Lightweight Metrics Foundation

V1 does not need a full metrics platform, but a small local metrics abstraction makes future deployment easier.

### 22.1 Metrics Interface

Recommended lightweight interface:

```python
from typing import Protocol


class MetricsRecorder(Protocol):
    def increment(self, name: str, value: int = 1, tags: dict[str, str] | None = None) -> None:
        ...

    def timing(self, name: str, duration_ms: int, tags: dict[str, str] | None = None) -> None:
        ...
```

### 22.2 Initial Metrics

Recommended counters/timers:

```text
backend.requests.total
backend.requests.errors
backend.requests.duration_ms
backend.llm.calls.total
backend.llm.calls.errors
backend.llm.calls.duration_ms
backend.llm.tokens.input
backend.llm.tokens.output
backend.memory.search.total
backend.memory.search.duration_ms
backend.tools.calls.total
backend.tools.calls.errors
backend.tools.calls.duration_ms
backend.state.load.duration_ms
backend.state.save.duration_ms
backend.trace.events.total
backend.trace.events.errors
```

### 22.3 Metrics Tags

Allowed low-cardinality tags:

```text
route
method
status_code
component
provider
profile
tool_name
event_type
success
```

Avoid high-cardinality or sensitive tags:

```text
raw_user_id
session_id
trace_id
prompt_text
completion_text
memory_text
tool_arguments
```

Trace IDs belong in logs and trace events, not metrics tags.

---

## 23. Initial SQLite Trace Store Boundary

Phase 4 may include an initial `SqliteTraceStore` because the backend application architecture lists it as a deliverable for observability. However, detailed persistence design belongs to later documents.

### 23.1 Scope for This Phase

This phase may implement:

- SQLite file path resolution from config.
- Trace table creation if missing.
- Append-only `record_event`.
- Basic health check.
- Unit/smoke tests.

This phase should not implement:

- Advanced trace queries.
- Retention policies.
- Compression.
- Archival.
- Index tuning beyond minimal useful indexes.
- Trace search APIs.
- Debug UI.
- Data migration framework beyond simple schema bootstrap.

Those are refined in `sqlite-trace-store-architecture.md`.

### 23.2 Minimal Trace Table Preview

A minimal schema can be used for Phase 4 smoke testing:

```sql
CREATE TABLE IF NOT EXISTS trace_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    user_id TEXT NULL,
    usecase TEXT NULL,
    event_type TEXT NOT NULL,
    component TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_trace_events_trace_id
    ON trace_events(trace_id);

CREATE INDEX IF NOT EXISTS idx_trace_events_session_id
    ON trace_events(session_id);

CREATE INDEX IF NOT EXISTS idx_trace_events_timestamp
    ON trace_events(timestamp);
```

### 23.3 SQLite Trace Store Rule

Only `SqliteTraceStore` should know the SQLite schema. Runtime modules should call:

```python
await trace_store.record_event(event)
```

They should not run SQL directly.

---

## 24. API Boundary Observability

The API layer should remain thin but should own request-boundary telemetry.

API middleware should:

- Resolve or generate trace ID.
- Set trace context.
- Record request start log.
- Call downstream route/session handler.
- Record response log.
- Add `X-Trace-Id` response header.
- Convert unhandled exceptions into known error responses later in `backend-api-architecture.md`.

### 24.1 API Request Event

On request start:

```text
request_received
```

Payload:

```json
{
  "method": "POST",
  "route": "/chat",
  "client_host_present": true,
  "streaming": false
}
```

Do not include raw request body.

### 24.2 API Response Event

On request completion:

```text
response_returned
```

Payload:

```json
{
  "status_code": 200,
  "duration_ms": 834,
  "streaming": false
}
```

---

## 25. Session Boundary Observability

The session service should emit trace events for session lifecycle decisions once the session module is implemented.

Recommended events:

```text
session_created
session_resumed
session_reset
workflow_state_loaded
workflow_state_saved
workflow_state_reset
```

Payloads should summarize state, not dump state:

```json
{
  "session_id": "session_123",
  "state_keys_count": 5,
  "history_message_count": 8,
  "provider": "sqlite"
}
```

Do not store full conversation history in traces.

---

## 26. Orchestration Boundary Observability

The orchestration runtime should emit trace events for coordination decisions:

```text
context_created
strategy_selected
agent_selected
agent_started
agent_completed
error_occurred
```

Recommended payloads:

```json
{
  "usecase": "default_chat",
  "strategy": "direct_agent",
  "allowed_agents": ["document_qa_agent"],
  "features": {
    "memory_enabled": true,
    "tools_enabled": true,
    "streaming_enabled": true
  }
}
```

Rules:

- Do not store full user message unless explicitly local/debug and redacted/truncated.
- Prefer counts, names, selected profile names, and durations.
- Include `strategy_name` and `agent_name` in completion events.

---

## 27. Gateway Observability Rules

Each gateway should record its own operation events. This keeps orchestration from knowing provider details.

### 27.1 LLM Gateway

LLM gateway records:

```text
llm_call_started
llm_call_completed
llm_call_failed
llm_fallback_selected
```

Payload should include:

```text
component
profile
provider
model
timeout_seconds
fallback_profile optional
input_tokens optional
output_tokens optional
total_tokens optional
duration_ms
retry_count
success
```

Payload must not include:

```text
raw messages
raw prompts
raw completions
API keys
authorization headers
provider raw response object
```

### 27.2 Memory Gateway

Memory gateway records:

```text
memory_search_started
memory_search_completed
memory_upsert_started
memory_upsert_completed
memory_upsert_failed
```

Payload should include counts and scope summary only.

### 27.3 Tool Gateway and MCP Client Adapter

Tool gateway records:

```text
tool_call_started
tool_call_completed
tool_call_failed
mcp_call_started
mcp_call_completed
mcp_call_failed
```

Payload should include logical tool name, source, argument keys, duration, success, and result summary.

### 27.4 Workflow State Store

Workflow state store records or allows callers to record:

```text
workflow_state_loaded
workflow_state_saved
workflow_state_reset
```

Detailed persistence design is handled later.

---

## 28. Streaming Observability

Streaming should not write a trace event for every token. That would create noisy traces and unnecessary SQLite writes.

Recommended streaming event pattern:

```text
stream_started
content_delta summarized in logs only when debug enabled
stream_completed
stream_cancelled
stream_failed
```

### 28.1 Stream Completion Payload

```json
{
  "duration_ms": 12400,
  "chunks_sent": 84,
  "approx_output_chars": 2480,
  "final_status": "completed"
}
```

### 28.2 Stream Cancellation Payload

```json
{
  "duration_ms": 3100,
  "chunks_sent": 12,
  "final_status": "client_cancelled"
}
```

Cancellation should not always be logged as an error. It may be normal client behavior.

---

## 29. Startup Observability

Startup should be observable before the first request arrives.

Recommended startup sequence:

```text
1. Initialize minimal console logger.
2. Create startup correlation ID.
3. Load settings.
4. Load and validate configuration.
5. Configure structured logging.
6. Build redactor.
7. Build trace store.
8. Initialize trace schema if configured.
9. Build health aggregator.
10. Build remaining services.
11. Log redacted startup summary.
12. Start API server.
```

Recommended startup events/logs:

```text
startup_started
config_loaded
config_validated
trace_store_initialized
startup_completed
startup_failed
```

Startup trace events may use:

```text
trace_id = startup_<uuid4_hex>
session_id = startup
component = backend.startup
```

---

## 30. Redacted Startup Summary

The startup summary should help developers verify wiring without exposing secrets.

Example:

```json
{
  "environment": "local",
  "active_usecase": "default_chat",
  "structured_logging": true,
  "trace_enabled": true,
  "trace_provider": "sqlite",
  "trace_db_configured": true,
  "llm_profiles_count": 2,
  "llm_providers": ["local_openai_compatible"],
  "mcp_main_configured": true,
  "memory_provider": "memory_store",
  "workflow_state_provider": "sqlite"
}
```

Do not log:

- API keys.
- Secret environment variable values.
- Full database connection strings when sensitive.
- Prompt text.
- Tool credentials.

---

## 31. Developer Diagnostics

V1 should include simple developer diagnostics that are safe and useful locally.

Recommended optional routes:

```text
GET /health
GET /capabilities future phase
```

Avoid adding a trace dump route in this phase. Trace query/debug endpoints belong after `sqlite-trace-store-architecture.md` and `backend-api-architecture.md` define safe query behavior and API error/security rules.

### 31.1 Local Debug Mode

Local debug mode may enable:

```yaml
observability:
  log_level: DEBUG
  include_stack_traces_in_logs: true
  trace_payloads_enabled: true
  max_trace_payload_chars: 12000
```

Even in debug mode, redaction remains on by default.

---

## 32. Error Handling Interaction

This document defines how errors are logged and traced. It does not define final HTTP response mapping.

Error-to-response mapping belongs in `backend-api-architecture.md`.

Recommended generic flow:

```text
Known BackendError
  -> log warning/error with trace ID
  -> record error_occurred trace event
  -> API maps to structured error response later

Unknown Exception
  -> log error with trace ID
  -> record error_occurred trace event with generic type
  -> API maps to 500 later
```

### 32.1 Error Event Example

```json
{
  "error_type": "PolicyDeniedError",
  "component": "tools.gateway",
  "operation": "call_tool",
  "resource": "support.create_ticket",
  "reason_code": "tool_not_allowed"
}
```

Do not put sensitive exception text in payloads.

---

## 33. Testing Strategy

Observability should be heavily tested because it becomes the diagnostic backbone for later phases.

### 33.1 Unit Tests

| Test | Purpose |
|---|---|
| Trace ID generation returns valid ID | Ensures request IDs are safe and unique enough. |
| Inbound trace ID validation | Rejects invalid/unsafe IDs. |
| Trace context set/reset | Prevents context leakage across requests. |
| Structured log fields include trace ID | Ensures log correlation works. |
| Redactor redacts nested secrets | Prevents secret leaks. |
| Redactor truncates long payloads | Keeps trace payloads bounded. |
| TraceRecorder writes expected event | Proves core trace helper works. |
| TraceRecorder skips payload when disabled | Proves config behavior. |
| TraceRecorder handles store failure | Proves safe failure behavior. |
| HealthAggregator returns degraded/error | Proves component status rollup. |
| Metrics recorder accepts low-cardinality tags | Prepares future metrics export. |
| Error event payload is trace-safe | Prevents exception leakage. |

### 33.2 Integration Tests

| Test | Purpose |
|---|---|
| Startup configures logging | Proves config-driven log setup. |
| SQLite trace smoke write | Proves initial trace store can append. |
| Health route redacts secrets | Proves health safety. |
| Request middleware attaches trace ID | Proves API boundary correlation. |
| Fake walking skeleton emits trace events | Proves end-to-end diagnostic path. |

### 33.3 Test Fixtures

Recommended fixtures:

```text
tests/fixtures/config/observability_enabled.yaml
tests/fixtures/config/observability_trace_payloads_disabled.yaml
tests/fixtures/config/observability_unstructured_logging.yaml
tests/fixtures/config/health_minimal.yaml
tests/fixtures/config/health_detailed.yaml
```

---

## 34. Recommended Implementation Order Inside This Phase

### Step 1: Add Event Constants

Deliverables:

- `app/observability/events.py`
- Constants for minimum event taxonomy
- Tests for duplicate event names

Success criteria:

- Event names are centralized.
- Runtime modules do not need string literals for common events.

### Step 2: Add Trace ID Helpers

Deliverables:

- `app/observability/ids.py`
- `new_trace_id`
- `is_valid_trace_id`
- Unit tests

Success criteria:

- Trace IDs are generated consistently.
- Unsafe inbound trace IDs are ignored or replaced.

### Step 3: Add Trace Context

Deliverables:

- `app/observability/context.py`
- `TraceContext`
- `contextvars` helper functions
- Unit tests for set/reset behavior

Success criteria:

- Logs can be enriched with current trace context.
- Async tests do not leak context between requests.

### Step 4: Add Redaction Utility

Deliverables:

- `app/observability/redaction.py`
- Recursive redaction
- Truncation
- Safe serialization helper
- Unit tests

Success criteria:

- Sensitive keys are redacted.
- Large payloads are bounded.
- Unsupported values become safe strings.

### Step 5: Add Structured Logging Setup

Deliverables:

- `app/observability/logging.py`
- Log configuration from `ConfigurationView`
- Trace-context log filter
- Unit tests

Success criteria:

- Logs include trace IDs when available.
- Log level comes from config.
- Startup summary is redacted.

### Step 6: Add Trace Recorder

Deliverables:

- `app/observability/tracing.py`
- `TraceRecorder`
- Tests with `FakeTraceStore`

Success criteria:

- Runtime modules can record safe trace events with minimal boilerplate.
- Trace payload behavior follows config.

### Step 7: Add Initial Trace Store Bootstrap

Deliverables:

- `app/persistence/sqlite_trace_store.py`
- `app/persistence/sqlite_trace_schema.py`
- Smoke test with temporary SQLite file

Success criteria:

- Trace events can be appended to SQLite.
- Schema initializes at startup.
- No runtime module outside the trace store runs trace SQL.

### Step 8: Add Health Aggregator

Deliverables:

- `app/observability/health.py`
- Component registration pattern
- Unit tests

Success criteria:

- Health output is safe and redacted.
- Component errors do not crash health endpoint.

### Step 9: Add Metrics Stub

Deliverables:

- `app/observability/metrics.py`
- `NoopMetricsRecorder`
- Optional in-memory metrics recorder for tests

Success criteria:

- Later modules can emit metrics without choosing a metrics backend.

### Step 10: Add Startup Integration

Deliverables:

- Composition root updates
- Startup logging summary
- Trace store construction
- Health aggregator registration

Success criteria:

- Backend startup configures observability before building the rest of the runtime.
- Startup failures are diagnosable and redacted.

---

## 35. Walking Skeleton Enabled by Observability

After this phase, the backend should be ready for a traceable walking skeleton:

```text
Startup
  -> load config
  -> configure logging
  -> create redactor
  -> initialize trace store
  -> build TraceRecorder
  -> build HealthAggregator

POST /chat future phase
  -> API middleware creates trace ID
  -> request_received trace event
  -> SessionService loads workflow state
  -> workflow_state_loaded trace event
  -> OrchestrationRuntime creates context
  -> context_created trace event
  -> DirectStrategy selects agent
  -> strategy_selected / agent_selected trace events
  -> FakeAgent or future real agent runs
  -> LLMGateway or fake LLM emits llm events
  -> response_returned trace event
  -> X-Trace-Id returned to frontend
```

The important outcome is that the system becomes diagnosable before LLM, memory, MCP, and orchestration complexity are added.

---

## 36. Acceptance Criteria

This architecture is complete when:

- The backend generates one trace ID per request.
- Valid inbound trace IDs can be accepted and propagated.
- Invalid inbound trace IDs are ignored or replaced safely.
- Trace ID is attached to `RequestContext.trace_id`.
- Trace ID is included in `OrchestrationResult.trace_id` when available.
- Trace ID is returned to clients through `X-Trace-Id` or response metadata.
- Structured logging is configured from YAML.
- Logs include trace ID, component, event type, status, and duration where applicable.
- Logs do not include secrets, credentials, raw authorization headers, raw prompts, raw completions, or sensitive memory contents.
- A shared redaction utility is used by logs, traces, health, config summaries, and errors.
- `TraceRecorder` can write events through the existing `TraceStore` contract.
- Trace payloads are JSON-safe, redacted, and bounded.
- Initial `SqliteTraceStore` can append trace events if implemented in this phase.
- Detailed trace query/debug behavior is deferred to `sqlite-trace-store-architecture.md`.
- Health aggregator can combine component health checks.
- Health responses do not expose secrets or sensitive payloads.
- Lightweight metrics interface exists or a no-op implementation is available.
- Startup logs a redacted configuration and component summary.
- Startup failures are logged with trace-safe error information.
- Unit tests validate trace ID helpers, redaction, trace recorder, structured logging, health aggregation, and metrics stubs.
- Integration tests can prove a request or fake walking skeleton emits trace events.
- The backend is ready for the next document: `persistence-architecture.md`.

---

## 37. Anti-Patterns to Avoid

Avoid these during the observability phase:

- Logging raw prompts by default.
- Logging raw LLM completions by default.
- Logging full memory contents or document chunks.
- Logging full tool responses without redaction.
- Storing API keys or authorization headers in trace payloads.
- Letting every module invent its own event names.
- Writing SQL from orchestration, agents, LLM gateway, or tool gateway.
- Treating traces as long-term memory.
- Treating metrics as logs or trace dumps.
- Using high-cardinality values such as `trace_id` or `session_id` as metric tags.
- Creating trace events for every streamed token.
- Returning stack traces or connection strings in `/health`.
- Allowing trace store failure to silently hide all diagnostics without at least an error log.
- Coupling observability to a specific LLM provider SDK.
- Coupling observability to the MCP server implementation.
- Making debug mode disable redaction.

---

## 38. Future Documents That Depend on Observability

| Future Document | Observability Dependency |
|---|---|
| `persistence-architecture.md` | Uses trace, state, and memory persistence boundaries and common health behavior. |
| `sqlite-workflow-state-architecture.md` | Uses structured logs, trace IDs, state timing, and health check patterns. |
| `sqlite-trace-store-architecture.md` | Expands initial `SqliteTraceStore`, schema, indexes, query/debug patterns, and retention. |
| `backend-api-architecture.md` | Uses trace middleware, response headers, structured error logging, and health route behavior. |
| `session-service-architecture.md` | Uses session lifecycle trace events and state timing. |
| `llm-gateway-architecture.md` | Uses LLM call trace events, fallback events, token usage logs, slow call warnings, and redaction rules. |
| `memory-store-adapter-architecture.md` | Uses memory search/upsert trace events, result summaries, and memory-content redaction rules. |
| `tooling-mcp-client-architecture.md` | Uses tool/MCP call trace events, allowlist diagnostics, and downstream error redaction. |
| `orchestration-architecture.md` | Uses context, strategy, agent, and runtime result trace events. |
| `workflow-strategies-architecture.md` | Uses strategy selection/routing trace events and router LLM diagnostics. |
| `agents-architecture.md` | Uses agent start/completion events, tool summaries, memory summaries, and trace-safe agent metadata. |
| `policy-architecture.md` | Uses policy evaluated/denied trace events and deny-by-default diagnostics. |
| `deployment-architecture.md` | Uses log level, stdout logging, data paths, health checks, and future telemetry export strategy. |

---

## 39. Summary

The observability layer is the diagnostic backbone of the backend application.

It should be implemented immediately after configuration because every later module needs trace IDs, structured logs, trace events, redaction, health summaries, and basic metrics from the beginning. This keeps the walking skeleton debuggable and prevents provider, persistence, MCP, and orchestration failures from becoming opaque.

The most important implementation rule is:

> **Every important backend action should be traceable, but no observability output should leak secrets, raw prompts, raw completions, sensitive memory contents, or provider-specific infrastructure details.**
