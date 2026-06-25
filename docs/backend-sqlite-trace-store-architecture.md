# Backend SQLite Trace Store Architecture

**Document:** `backend-sqlite-trace-store-architecture.md`  
**Version:** 1.0  
**Source alignment:** `backend-application-architecture.md`, `backend-foundation-architecture.md`, `backend-core-contracts-architecture.md`, `backend-configuration-architecture.md`, `backend-observability-architecture.md`, `backend-persistence-architecture.md`, and `backend-sqlite-workflow-state-architecture.md`  
**Scope:** SQLite-backed trace event persistence, schema, migrations, write/read/query behavior, redaction, payload safety, retention, health checks, observability integration, testing strategy, and acceptance criteria for the backend `TraceStore` implementation.

---

## 1. Purpose

This document defines the seventh implementation-focused architecture document for the backend application tier.

It follows:

1. `backend-foundation-architecture.md`
2. `backend-core-contracts-architecture.md`
3. `backend-configuration-architecture.md`
4. `backend-observability-architecture.md`
5. `backend-persistence-architecture.md`
6. `backend-sqlite-workflow-state-architecture.md`
7. `backend-sqlite-trace-store-architecture.md` ← this document

The persistence architecture established three separate persistence domains:

```text
Long-term memory and document chunks -> MemoryGateway -> memory_store -> ArcadeDB
Short-term workflow/session state    -> WorkflowStateStore -> SQLite
Operational traces                   -> TraceStore -> SQLite
```

The previous SQLite workflow-state document deepened the second domain. This document deepens only the third domain: operational trace persistence.

The goal is to implement the V1 `SqliteTraceStore` in a way that supports request-level diagnostics, safe event persistence, health reporting, and later debug/query routes while preserving the key backend architecture rule:

> API routes, orchestration, strategies, agents, LLM gateway, tool gateway, memory gateway, and session service use `TraceStore` or an observability facade; only the SQLite trace adapter knows SQLite tables, SQL statements, pragmas, migrations, file paths, and trace query SQL.

---

## 2. Source Architecture Alignment

This document follows the established backend rules:

- The backend is one deployable application tier in V1.
- Frontend communicates with backend over REST / SSE.
- Backend communicates with the external MCP tier only through the MCP client adapter.
- Backend does not implement the MCP server.
- Agents receive controlled capabilities through `OrchestrationContext`.
- Agents do not import SQLite, ArcadeDB, MCP clients, provider SDKs, external API clients, or `memory_store.service.MemoryService`.
- SQLite is hidden behind concrete persistence adapters.
- Workflow state is short-term session/runtime state, not long-term memory.
- Trace events are operational records, not workflow state and not long-term memory.
- Session reset clears workflow state only.
- Session reset must not delete long-term memory, document chunks, trace events, LLM configuration, MCP configuration, or policy configuration.
- Trace persistence is append-first and diagnostic-focused.
- Trace storage must not become a raw prompt/completion archive.
- Trace storage must not become a full request/response body store.
- Trace payloads must be redacted before persistence.
- Store configuration is loaded through typed configuration views, not raw environment reads inside runtime modules.
- Logs, traces, health responses, and errors must not expose secrets, raw authorization headers, provider credentials, sensitive connection strings, raw tool payloads, raw workflow state, or full prompt/completion content.

---

## 3. Position in the Backend Implementation Sequence

The backend implementation sequence is:

```text
Phase 1: Backend Foundation Skeleton
Phase 2: Core Contracts
Phase 3: Configuration Loader
Phase 4: Observability and Trace Foundation
Phase 5: Persistence Boundary and Store Foundations
Phase 6: SQLite Workflow State Store
Phase 7: SQLite Trace Store
Phase 8: API and Session Walking Skeleton
Phase 9: LLM Gateway
Phase 10: Memory Gateway
Phase 11: Tool Gateway and MCP Client Adapter
Phase 12: Orchestration Runtime and Strategies
Phase 13: Agent Plugins
Phase 14: Hardening and Deployment Readiness
```

This document expands Phase 7.

The output of this phase is a real SQLite-backed `TraceStore` that can record trace events, read a trace by `trace_id`, search recent traces for debugging, and health-check trace persistence before the API/session walking skeleton is implemented.

The next document should be:

```text
backend-api-architecture.md
```

---

## 4. Architecture Goals

The SQLite trace store should be:

1. **Contract-compatible**  
   It implements the existing `TraceStore` protocol without forcing higher layers to understand SQLite.

2. **Append-first**  
   Runtime events are recorded as append-only trace events. Summary rows may be updated for query performance.

3. **Trace-correlated**  
   Every request should have a `trace_id`; all events for that request share the same `trace_id`.

4. **Operational**  
   Trace records describe what happened, when, how long it took, and whether it succeeded. They are not user memories.

5. **Safe by default**  
   Trace payloads are redacted, bounded, and summarized before persistence.

6. **Queryable**  
   V1 supports reading one trace by ID and searching recent traces by time, status, event name, use case, agent, tool, LLM profile, and error type.

7. **Configurable**  
   Path, schema initialization, SQLite pragmas, payload size, retention, and debug-query limits are configuration-driven.

8. **SQLite-isolated**  
   SQL, schema, paths, migrations, pragmas, and query construction stay inside the adapter and SQLite helper modules.

9. **Workflow-state independent**  
   Trace writes are not part of workflow-state transactions. A trace write failure must not corrupt workflow state.

10. **Testable**  
    Unit tests can use a fake trace store; integration tests can use temporary SQLite files and verify schema/write/read/search/retention behavior.

---

## 5. Non-Goals

This document should not implement:

- Long-term memory storage.
- Document chunk ingestion.
- Workflow state storage.
- Session reset behavior.
- Full API route behavior.
- Full session-service behavior.
- Full OpenTelemetry collector/exporter integration.
- Distributed tracing across multiple backend services.
- High-volume analytics or OLAP reporting.
- Log aggregation replacement.
- Metrics time-series storage.
- Raw prompt/completion archival.
- Raw request/response body archival.
- Full external tool response archival.
- Full provider SDK response persistence.
- Compliance-grade immutable audit logging.
- Multi-writer SQLite cluster semantics.
- Cross-store transactions with `workflow_state.db` or ArcadeDB.
- A public trace browsing UI.

Those concerns belong to later API, session, observability, policy, deployment, and operational hardening documents.

---

## 6. Trace Store Boundary

The trace store persists operational events emitted by backend modules.

Allowed examples:

- Request received and response returned.
- Context created.
- Workflow state loaded/saved/reset summary.
- Strategy selected.
- Agent selected/started/completed.
- LLM call started/completed/failed summary.
- LLM fallback selected.
- Memory search started/completed summary.
- Tool call started/completed/failed summary.
- MCP client call summary.
- Policy decision summary.
- Error occurrence summary.
- Streaming lifecycle summary.
- Health or startup diagnostic event summary.

Disallowed examples:

- Full raw user prompts by default.
- Full raw assistant completions by default.
- Raw provider SDK request/response objects.
- Raw authorization headers.
- API keys or provider credentials.
- Raw cookies, JWTs, refresh tokens, or bearer tokens.
- Full workflow-state `state_json`.
- Long-term memory records.
- Document corpus chunks.
- Full downstream tool result payloads by default.
- Sensitive connection strings or local filesystem secrets.

### 6.1 Store Separation

```text
Observability / Runtime Modules
  -> TraceStore
      -> SqliteTraceStore
          -> trace.db
```

The trace store must not call:

```text
LLMGateway
MemoryGateway
WorkflowStateStore
ToolGateway
MCPClientAdapter
AgentPlugin
OrchestrationStrategy
PolicyService decision logic
```

The store persists trace records. It does not make orchestration, routing, memory, LLM, or policy decisions.

---

## 7. Recommended Package Layout

Recommended implementation layout:

```text
backend/
  app/
    persistence/
      trace_store.py
      sqlite_trace_store.py
      sqlite_trace_schema.py
      sqlite_trace_models.py
      sqlite_trace_queries.py

      sqlite/
        __init__.py
        connection.py
        pragmas.py
        migrations.py
        transactions.py

      serialization.py
      paths.py
      errors.py
      settings.py
      health.py

    contracts/
      trace.py
      errors.py
      health.py

    observability/
      tracing.py
      events.py
      metrics.py
      redaction.py
      trace_context.py
      event_factory.py

    testing/
      fakes/
        fake_trace_store.py

  tests/
    unit/
      persistence/
        test_trace_store_contract.py
        test_sqlite_trace_schema.py
        test_sqlite_trace_serialization.py
        test_sqlite_trace_redaction.py
        test_sqlite_trace_query_builder.py
        test_sqlite_trace_health.py
        test_fake_trace_store.py

    integration/
      persistence/
        test_sqlite_trace_store_smoke.py
        test_sqlite_trace_store_read_trace.py
        test_sqlite_trace_store_search.py
        test_sqlite_trace_store_retention.py
        test_sqlite_trace_store_migrations.py
        test_sqlite_trace_store_concurrency.py
```

### 7.1 Module Responsibilities

| Module | Responsibility |
|---|---|
| `trace_store.py` | Contract import/re-export or canonical protocol location. |
| `sqlite_trace_store.py` | Concrete adapter implementing write/read/search/health behavior. |
| `sqlite_trace_schema.py` | Trace-specific table DDL and schema version. |
| `sqlite_trace_models.py` | Internal row/result dataclasses if needed. |
| `sqlite_trace_queries.py` | Query filters and SQL construction for debug reads/searches. |
| `sqlite/connection.py` | Shared SQLite connection helper. |
| `sqlite/pragmas.py` | Shared SQLite pragma application. |
| `sqlite/migrations.py` | Shared schema version helper. |
| `serialization.py` | JSON-safe conversion and stable dumps. |
| `paths.py` | Data-path resolution and parent directory creation. |
| `errors.py` | Persistence/SQLite error wrappers. |
| `observability/redaction.py` | Redaction and payload minimization before store writes. |
| `observability/trace_context.py` | Current trace ID, parent event/span IDs, and request correlation. |
| `testing/fakes/fake_trace_store.py` | In-memory contract-compatible fake. |

---

## 8. Dependency Direction Rules

Allowed:

```text
app/api/*                         -> app/observability/* or app/contracts/trace.py
app/session/*                     -> app/observability/* or app/contracts/trace.py
app/orchestration/*               -> app/observability/* or app/contracts/trace.py
app/llm/*                         -> app/observability/* or app/contracts/trace.py
app/tools/*                       -> app/observability/* or app/contracts/trace.py
app/memory/*                      -> app/observability/* or app/contracts/trace.py
app/persistence/sqlite_trace_*    -> app/contracts/trace.py
app/persistence/sqlite_trace_*    -> app/persistence/sqlite/*
app/persistence/sqlite_trace_*    -> app/persistence/serialization.py
app/persistence/sqlite_trace_*    -> app/persistence/errors.py
app/persistence/sqlite_trace_*    -> standard library sqlite3/json/pathlib/datetime/uuid/hashlib
```

Avoid:

```text
app/api/*             -> sqlite3
app/session/*         -> sqlite3
app/orchestration/*   -> sqlite3
app/agents/*          -> sqlite3
app/llm/*             -> sqlite3
app/tools/*           -> sqlite3
app/persistence/*     -> app/agents/*
app/persistence/*     -> provider SDKs
app/persistence/*     -> MCP client/server implementation
app/persistence/*     -> memory_store.service.MemoryService
app/persistence/*     -> app/orchestration/*
```

### 8.1 Practical Rule

Runtime modules should do this:

```python
await trace.record_event(
    TraceEvent(
        trace_id=request_context.trace_id,
        event_name="llm_call_completed",
        event_type="llm",
        status="completed",
        duration_ms=842,
        payload={
            "llm_profile": "research_reasoning",
            "provider": "openai_compatible",
            "input_tokens": 1200,
            "output_tokens": 240,
        },
    )
)
```

Runtime modules should not do this:

```python
sqlite3.connect("./data/trace.db")
conn.execute("INSERT INTO trace_events ...")
```

---

## 9. Configuration Integration

The trace store should be configured under the shared persistence configuration.

Recommended YAML:

```yaml
persistence:
  base_dir: ${env:APP_DATA_DIR:./data}

  trace:
    provider: sqlite
    sqlite:
      path: ${env:TRACE_DB:./data/trace.db}
      create_parent_dirs: true
      initialize_schema: true
      journal_mode: WAL
      synchronous: NORMAL
      busy_timeout_ms: 5000
      foreign_keys: true
      required: true
      max_event_payload_bytes: 32768
      max_error_detail_bytes: 4096
      max_events_per_trace_read: 1000
      max_search_results: 200
      store_raw_session_id: false
      store_session_id_hash: true
      store_raw_user_id: false
      store_user_id_hash: true
      capture_request_body: false
      capture_response_body: false
      capture_llm_prompts: false
      capture_llm_completions: false
      capture_tool_payloads: summaries_only
      capture_memory_queries: summaries_only
      retention:
        enabled: false
        keep_days: 30
        cleanup_batch_size: 1000
```

### 9.1 Settings Object

Recommended typed settings:

```python
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SqliteTraceStoreSettings:
    path: Path
    create_parent_dirs: bool
    initialize_schema: bool
    journal_mode: str
    synchronous: str
    busy_timeout_ms: int
    foreign_keys: bool
    required: bool
    max_event_payload_bytes: int
    max_error_detail_bytes: int
    max_events_per_trace_read: int
    max_search_results: int
    store_raw_session_id: bool
    store_session_id_hash: bool
    store_raw_user_id: bool
    store_user_id_hash: bool
    capture_request_body: bool
    capture_response_body: bool
    capture_llm_prompts: bool
    capture_llm_completions: bool
    capture_tool_payloads: str
    capture_memory_queries: str
    retention_enabled: bool
    retention_keep_days: int
    retention_cleanup_batch_size: int
```

### 9.2 Supported V1 Values

| Setting | Supported V1 Values | Recommended Default |
|---|---|---|
| `provider` | `sqlite`, `fake` for tests | `sqlite` |
| `journal_mode` | `WAL`, `DELETE` | `WAL` |
| `synchronous` | `NORMAL`, `FULL` | `NORMAL` |
| `capture_tool_payloads` | `none`, `summaries_only` | `summaries_only` |
| `capture_memory_queries` | `none`, `summaries_only` | `summaries_only` |
| `capture_llm_prompts` | `true`, `false` | `false` |
| `capture_llm_completions` | `true`, `false` | `false` |
| `retention.enabled` | `true`, `false` | `false` |
| `required` | `true`, `false` | `true` |

### 9.3 Configuration Access Rule

The adapter receives resolved settings from the composition root.

Use:

```python
settings = config_view.persistence().trace.sqlite
store = SqliteTraceStore(settings=settings, redactor=redactor)
```

Avoid this inside the adapter:

```python
os.getenv("TRACE_DB")
```

The configuration layer may read environment variables. Runtime modules and adapters should receive resolved values.

---

## 10. Core Store Contract

The canonical protocol should remain small but support both write and debug-read use cases.

```python
from typing import Any, Protocol, Sequence


class TraceStore(Protocol):
    async def record_event(self, event: "TraceEvent") -> None:
        ...

    async def record_events(self, events: Sequence["TraceEvent"]) -> None:
        ...

    async def read_trace(
        self,
        *,
        trace_id: str,
        limit: int | None = None,
    ) -> "TraceReadModel":
        ...

    async def search_traces(
        self,
        *,
        filters: "TraceSearchFilters",
    ) -> list["TraceSummary"]:
        ...

    async def health(self) -> dict[str, Any]:
        ...
```

### 10.1 Contract Behavior

| Method | Required Behavior |
|---|---|
| `record_event` | Redact, validate, bound, and persist one event. |
| `record_events` | Persist multiple events in one transaction when possible. |
| `read_trace` | Return one trace summary and ordered events by `trace_id`. |
| `search_traces` | Return safe trace summaries using bounded filters and limits. |
| `health` | Return safe readiness information without exposing event payloads or file secrets. |

### 10.2 Contract Stability Rule

Do not force API, session, orchestration, agents, LLM gateway, tool gateway, or memory gateway to depend on SQLite-specific concepts such as:

```text
row id
SQLite connection
schema_version table
journal mode
SQL error class
sequence number allocation SQL
payload_json storage shape
index names
```

Those are adapter internals.

---

## 11. Trace Event Model

Recommended event dataclass:

```python
from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class TraceEvent:
    trace_id: str
    event_name: str
    event_type: str
    status: str = "completed"
    severity: str = "info"
    timestamp: str | None = None
    event_id: str | None = None
    parent_event_id: str | None = None
    session_id: str | None = None
    session_id_hash: str | None = None
    user_id: str | None = None
    user_id_hash: str | None = None
    usecase: str | None = None
    agent_name: str | None = None
    strategy_name: str | None = None
    llm_profile: str | None = None
    provider: str | None = None
    model: str | None = None
    tool_name: str | None = None
    duration_ms: float | None = None
    error_type: str | None = None
    error_code: str | None = None
    retryable: bool | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)
```

### 11.1 Event Type Values

Recommended V1 event types:

```text
request
context
session
workflow_state
strategy
agent
llm
memory
tool
mcp
policy
stream
error
health
startup
shutdown
```

### 11.2 Status Values

Recommended V1 status values:

```text
started
completed
failed
cancelled
skipped
degraded
```

### 11.3 Severity Values

Recommended V1 severity values:

```text
debug
info
warning
error
critical
```

### 11.4 Event Payload Rule

`payload` should contain only safe, summarized metadata. It should not include raw message bodies, raw prompt/completion text, raw authorization headers, secrets, provider credentials, full workflow state, raw memory records, or full tool response payloads.

---

## 12. Minimum Event Taxonomy

The observability foundation established a minimum backend trace event set. The SQLite trace store must be able to persist these events safely.

```text
request_received
context_created
workflow_state_loaded
memory_search_started
memory_search_completed
llm_call_started
llm_call_completed
llm_call_failed
llm_fallback_selected
strategy_selected
agent_selected
agent_started
agent_completed
tool_call_started
tool_call_completed
tool_call_failed
workflow_state_saved
response_returned
error_occurred
```

### 12.1 Additional Recommended Events

The trace store should also support these without schema changes:

```text
backend_startup_completed
backend_shutdown_started
configuration_loaded
policy_decision_recorded
session_created
session_resumed
session_reset
workflow_state_reset
stream_started
stream_completed
stream_cancelled
stream_failed
mcp_call_started
mcp_call_completed
mcp_call_failed
memory_upsert_started
memory_upsert_completed
memory_upsert_failed
health_check_completed
trace_retention_cleanup_completed
```

### 12.2 Event Naming Rule

Use stable snake_case event names.

Good:

```text
llm_call_completed
tool_call_failed
workflow_state_saved
```

Avoid:

```text
LLM finished!
Tool call failed for weather
Saved workflow state in SqliteWorkflowStateStore
```

Stable names make query filters, dashboards, and tests reliable.

---

## 13. SQLite Storage Model

Use one SQLite database file for trace events:

```text
./data/trace.db
```

Recommended tables:

```text
schema_version
trace_runs
trace_events
trace_retention_runs
```

### 13.1 Why Use Run Summary Plus Event Rows

Trace queries usually need two access patterns:

1. Read all events for one `trace_id` in sequence.
2. Search recent traces by status, time range, event name, use case, agent, tool, LLM profile, or error type.

The `trace_events` table is the source of event detail. The `trace_runs` table is a safe summary table that makes recent trace search efficient without scanning every event payload.

---

## 14. Schema Version Table

Each SQLite database should maintain a schema version table.

```sql
CREATE TABLE IF NOT EXISTS schema_version (
    name TEXT PRIMARY KEY,
    version INTEGER NOT NULL,
    applied_at TEXT NOT NULL
);
```

For this store:

```text
name = trace_store
version = 1
```

### 14.1 Schema Version Rules

- Schema initialization is idempotent.
- Opening an already-initialized database is safe.
- Startup validates the expected schema version.
- Destructive migrations are not automatic in V1.
- Tests must cover fresh database creation and re-opening an existing database.

---

## 15. `trace_runs` Table

The `trace_runs` table stores one row per trace/request and keeps a query-friendly summary.

```sql
CREATE TABLE IF NOT EXISTS trace_runs (
    trace_id TEXT PRIMARY KEY,
    parent_trace_id TEXT NULL,
    session_id TEXT NULL,
    session_id_hash TEXT NULL,
    user_id TEXT NULL,
    user_id_hash TEXT NULL,
    usecase TEXT NULL,
    operation TEXT NULL,
    route_template TEXT NULL,
    status TEXT NOT NULL DEFAULT 'started',
    severity TEXT NOT NULL DEFAULT 'info',
    started_at TEXT NOT NULL,
    ended_at TEXT NULL,
    last_event_at TEXT NOT NULL,
    duration_ms REAL NULL,
    event_count INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    agent_name TEXT NULL,
    strategy_name TEXT NULL,
    llm_profile TEXT NULL,
    tool_name TEXT NULL,
    error_type TEXT NULL,
    error_code TEXT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

### 15.1 Column Rules

| Column | Rule |
|---|---|
| `trace_id` | Safe bounded identifier. Primary key. |
| `parent_trace_id` | Optional parent trace correlation for future multi-step workflows. |
| `session_id` | Optional. Disabled by default unless raw IDs are explicitly allowed. |
| `session_id_hash` | Preferred session correlation field. |
| `user_id` | Optional. Disabled by default unless raw IDs are explicitly required. |
| `user_id_hash` | Preferred user correlation field. |
| `usecase` | Optional active use-case name. |
| `operation` | Request or backend operation name, for example `chat`, `chat_stream`, `session_reset`, or `health`. |
| `route_template` | Safe route template such as `/chat`, not a full URL with query secrets. |
| `status` | Current trace status. |
| `severity` | Highest severity seen in the trace. |
| `started_at` | UTC ISO timestamp for the first event. |
| `ended_at` | UTC ISO timestamp when response/stream/error completion is recorded. |
| `last_event_at` | UTC ISO timestamp for most recent event. |
| `duration_ms` | Request/trace duration when known. |
| `event_count` | Count of persisted events for this trace. |
| `error_count` | Count of failed/error events. |
| `agent_name` | Last or primary agent name when known. |
| `strategy_name` | Last or primary strategy name when known. |
| `llm_profile` | Last or primary LLM profile when known. |
| `tool_name` | Last or primary tool name when known. |
| `error_type` | Last or primary error type when known. |
| `error_code` | Last or primary safe error code when known. |
| `metadata_json` | Safe summary metadata only. |

### 15.2 Raw ID Storage Rule

Prefer storing hashes instead of raw IDs:

```yaml
store_raw_session_id: false
store_session_id_hash: true
store_raw_user_id: false
store_user_id_hash: true
```

If raw IDs are enabled for local debugging, they must not be emitted as metric tags or exposed from public health responses.

---

## 16. `trace_events` Table

The `trace_events` table stores ordered events for each trace.

```sql
CREATE TABLE IF NOT EXISTS trace_events (
    event_id TEXT PRIMARY KEY,
    trace_id TEXT NOT NULL,
    sequence_no INTEGER NOT NULL,
    parent_event_id TEXT NULL,
    event_name TEXT NOT NULL,
    event_type TEXT NOT NULL,
    status TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'info',
    timestamp TEXT NOT NULL,
    duration_ms REAL NULL,
    session_id TEXT NULL,
    session_id_hash TEXT NULL,
    user_id TEXT NULL,
    user_id_hash TEXT NULL,
    usecase TEXT NULL,
    agent_name TEXT NULL,
    strategy_name TEXT NULL,
    llm_profile TEXT NULL,
    provider TEXT NULL,
    model TEXT NULL,
    tool_name TEXT NULL,
    error_type TEXT NULL,
    error_code TEXT NULL,
    retryable INTEGER NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    payload_size_bytes INTEGER NOT NULL DEFAULT 2,
    redaction_version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    FOREIGN KEY (trace_id)
        REFERENCES trace_runs(trace_id)
        ON DELETE CASCADE,
    UNIQUE(trace_id, sequence_no)
);
```

### 16.1 Column Rules

| Column | Rule |
|---|---|
| `event_id` | Unique event identifier. Generated if caller does not provide one. |
| `trace_id` | Parent trace identifier. Required. |
| `sequence_no` | Monotonic event order within a trace. Allocated by adapter. |
| `parent_event_id` | Optional event/span parent correlation. |
| `event_name` | Stable snake_case event name. |
| `event_type` | Bounded category such as `llm`, `tool`, or `workflow_state`. |
| `status` | Bounded event status. |
| `severity` | Bounded severity. |
| `timestamp` | UTC ISO timestamp. |
| `duration_ms` | Optional duration for completed/failed operations. |
| `session_id` | Optional raw session ID, disabled by default. |
| `session_id_hash` | Preferred session correlation field. |
| `user_id` | Optional raw user ID, disabled by default. |
| `user_id_hash` | Preferred user correlation field. |
| `usecase` | Optional use-case name. |
| `agent_name` | Optional agent name. |
| `strategy_name` | Optional strategy name. |
| `llm_profile` | Optional logical LLM profile name. |
| `provider` | Optional provider name, not a URL or secret. |
| `model` | Optional model identifier if policy allows. |
| `tool_name` | Optional normalized tool name. |
| `error_type` | Safe error class/type. |
| `error_code` | Safe error code. |
| `retryable` | `1`, `0`, or `NULL`. |
| `payload_json` | Redacted, JSON-safe, bounded payload summary. |
| `payload_size_bytes` | UTF-8 byte size of stored payload. |
| `redaction_version` | Redaction rule version applied before persistence. |

### 16.2 Event Ordering Rule

Allocate `sequence_no` inside a transaction using `BEGIN IMMEDIATE`:

```sql
SELECT COALESCE(MAX(sequence_no), 0) + 1
FROM trace_events
WHERE trace_id = ?;
```

Then insert the event with the selected sequence number.

This is simple and sufficient for V1. If later event volume grows, this can be replaced behind the adapter without changing the `TraceStore` contract.

---

## 17. `trace_retention_runs` Table

The `trace_retention_runs` table records cleanup operations without storing deleted event payloads.

```sql
CREATE TABLE IF NOT EXISTS trace_retention_runs (
    retention_run_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    completed_at TEXT NULL,
    cutoff_at TEXT NOT NULL,
    deleted_trace_count INTEGER NOT NULL DEFAULT 0,
    deleted_event_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'started',
    error_type TEXT NULL,
    error_code TEXT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
```

### 17.1 Retention Record Rules

- Store cleanup metadata, not deleted payloads.
- Retention is disabled by default in V1 unless deployment policy enables it.
- Cleanup should delete whole traces older than the cutoff, not individual events from active traces.
- Cleanup should be batched.
- Cleanup must not touch workflow state or long-term memory.

---

## 18. Indexes

Recommended indexes:

```sql
CREATE INDEX IF NOT EXISTS idx_trace_runs_started_at
    ON trace_runs(started_at);

CREATE INDEX IF NOT EXISTS idx_trace_runs_last_event_at
    ON trace_runs(last_event_at);

CREATE INDEX IF NOT EXISTS idx_trace_runs_status
    ON trace_runs(status);

CREATE INDEX IF NOT EXISTS idx_trace_runs_usecase
    ON trace_runs(usecase);

CREATE INDEX IF NOT EXISTS idx_trace_runs_session_hash
    ON trace_runs(session_id_hash);

CREATE INDEX IF NOT EXISTS idx_trace_runs_error_type
    ON trace_runs(error_type);

CREATE INDEX IF NOT EXISTS idx_trace_events_trace_sequence
    ON trace_events(trace_id, sequence_no);

CREATE INDEX IF NOT EXISTS idx_trace_events_timestamp
    ON trace_events(timestamp);

CREATE INDEX IF NOT EXISTS idx_trace_events_event_name
    ON trace_events(event_name);

CREATE INDEX IF NOT EXISTS idx_trace_events_event_type
    ON trace_events(event_type);

CREATE INDEX IF NOT EXISTS idx_trace_events_status
    ON trace_events(status);

CREATE INDEX IF NOT EXISTS idx_trace_events_agent_name
    ON trace_events(agent_name);

CREATE INDEX IF NOT EXISTS idx_trace_events_llm_profile
    ON trace_events(llm_profile);

CREATE INDEX IF NOT EXISTS idx_trace_events_tool_name
    ON trace_events(tool_name);

CREATE INDEX IF NOT EXISTS idx_trace_events_error_type
    ON trace_events(error_type);
```

### 18.1 Indexing Rule

V1 should keep indexes focused on known debug and health access patterns.

Do not add indexes for fields that are not queried by trace read, trace search, health, retention, or debugging.

---

## 19. SQLite Pragmas

Recommended pragmas applied when opening connections:

```sql
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA busy_timeout = 5000;
PRAGMA foreign_keys = ON;
```

### 19.1 Pragmas by Configuration

```python
def apply_pragmas(conn: sqlite3.Connection, settings: SqliteTraceStoreSettings) -> None:
    conn.execute(f"PRAGMA journal_mode = {settings.journal_mode}")
    conn.execute(f"PRAGMA synchronous = {settings.synchronous}")
    conn.execute(f"PRAGMA busy_timeout = {settings.busy_timeout_ms}")
    conn.execute(f"PRAGMA foreign_keys = {'ON' if settings.foreign_keys else 'OFF'}")
```

### 19.2 WAL Rationale

WAL mode is recommended because trace storage performs frequent appends and occasional reads. WAL improves local read/write behavior for normal V1 usage.

---

## 20. Connection Lifecycle

Recommended V1 pattern:

```text
Startup
  -> resolve path
  -> create parent directories if configured
  -> open connection
  -> apply pragmas
  -> initialize schema if configured
  -> validate schema version
  -> close connection

Trace write operation
  -> open short-lived connection
  -> apply pragmas
  -> execute insert/update in one short transaction
  -> commit or rollback
  -> close connection

Trace read/search operation
  -> open short-lived connection
  -> apply pragmas
  -> execute bounded query
  -> close connection
```

### 20.1 Why Short-Lived Connections Are Acceptable in V1

Short-lived connections keep the implementation simple and avoid async pooling concerns while request volume is low. A future connection manager, write queue, or pool can be introduced behind the same adapter without changing `TraceStore`.

### 20.2 Async Boundary

If the backend is async, there are two acceptable V1 choices:

1. Use `aiosqlite` behind the adapter.
2. Use standard `sqlite3` in a controlled thread/executor boundary.

Do not make higher-level modules care which approach is used.

---

## 21. Schema Initialization

Recommended schema initializer:

```python
TRACE_SCHEMA_NAME = "trace_store"
TRACE_SCHEMA_VERSION = 1


def initialize_trace_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(TRACE_STORE_DDL)
    conn.execute(
        """
        INSERT INTO schema_version(name, version, applied_at)
        VALUES (?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET
            version = excluded.version,
            applied_at = excluded.applied_at
        """,
        (TRACE_SCHEMA_NAME, TRACE_SCHEMA_VERSION, utc_now_iso()),
    )
```

### 21.1 Initialization Rules

- Create tables only when `initialize_schema: true`.
- Validate schema version during health and startup.
- Fail startup if the store is required and schema initialization or validation fails.
- Do not silently downgrade or destructively migrate.

---

## 22. Write Behavior

Recommended `record_event` flow:

```text
1. Validate trace_id.
2. Validate or generate event_id.
3. Validate event_name, event_type, status, and severity.
4. Normalize timestamp to UTC ISO format.
5. Apply raw ID storage policy.
6. Hash user/session IDs if configured.
7. Redact and minimize payload.
8. Convert payload to JSON-safe data.
9. Enforce max_event_payload_bytes.
10. Open SQLite connection.
11. Begin transaction.
12. Upsert trace_runs summary row.
13. Allocate sequence_no for this trace.
14. Insert trace_events row.
15. Update trace_runs counters and summary fields.
16. Commit.
17. Emit metric/log only if it will not recurse endlessly.
```

### 22.1 Trace Run Upsert Pattern

```sql
INSERT INTO trace_runs (
    trace_id,
    parent_trace_id,
    session_id,
    session_id_hash,
    user_id,
    user_id_hash,
    usecase,
    operation,
    route_template,
    status,
    severity,
    started_at,
    last_event_at,
    event_count,
    error_count,
    agent_name,
    strategy_name,
    llm_profile,
    tool_name,
    error_type,
    error_code,
    metadata_json,
    created_at,
    updated_at
)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(trace_id) DO UPDATE SET
    session_id = COALESCE(excluded.session_id, trace_runs.session_id),
    session_id_hash = COALESCE(excluded.session_id_hash, trace_runs.session_id_hash),
    user_id = COALESCE(excluded.user_id, trace_runs.user_id),
    user_id_hash = COALESCE(excluded.user_id_hash, trace_runs.user_id_hash),
    usecase = COALESCE(excluded.usecase, trace_runs.usecase),
    operation = COALESCE(excluded.operation, trace_runs.operation),
    route_template = COALESCE(excluded.route_template, trace_runs.route_template),
    last_event_at = excluded.last_event_at,
    status = excluded.status,
    severity = excluded.severity,
    agent_name = COALESCE(excluded.agent_name, trace_runs.agent_name),
    strategy_name = COALESCE(excluded.strategy_name, trace_runs.strategy_name),
    llm_profile = COALESCE(excluded.llm_profile, trace_runs.llm_profile),
    tool_name = COALESCE(excluded.tool_name, trace_runs.tool_name),
    error_type = COALESCE(excluded.error_type, trace_runs.error_type),
    error_code = COALESCE(excluded.error_code, trace_runs.error_code),
    updated_at = excluded.updated_at;
```

### 22.2 Event Insert Pattern

```sql
INSERT INTO trace_events (
    event_id,
    trace_id,
    sequence_no,
    parent_event_id,
    event_name,
    event_type,
    status,
    severity,
    timestamp,
    duration_ms,
    session_id,
    session_id_hash,
    user_id,
    user_id_hash,
    usecase,
    agent_name,
    strategy_name,
    llm_profile,
    provider,
    model,
    tool_name,
    error_type,
    error_code,
    retryable,
    payload_json,
    payload_size_bytes,
    redaction_version,
    created_at
)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
```

### 22.3 Summary Counter Update

```sql
UPDATE trace_runs
SET
    event_count = event_count + 1,
    error_count = error_count + ?,
    ended_at = COALESCE(?, ended_at),
    duration_ms = COALESCE(?, duration_ms),
    updated_at = ?
WHERE trace_id = ?;
```

### 22.4 Write Failure Rule

Trace write failures should be visible but should not usually fail the business request.

Recommended behavior:

| Situation | Behavior |
|---|---|
| Trace store unavailable and `required: true` during startup | Fail startup. |
| Trace write fails during request | Log redacted error, increment metric, continue request if safe. |
| Trace read/search fails | Return known debug/query error. |
| Payload too large | Store truncated/redacted summary or reject event based on configuration. |

Trace writes should not roll back workflow state, memory writes, LLM calls, or tool calls.

---

## 23. Batch Write Behavior

`record_events` should persist events for one or more traces.

Recommended V1 behavior:

```text
1. Validate events are non-empty.
2. Group by trace_id only if needed for sequence allocation.
3. Open one connection.
4. Begin transaction.
5. For each event, perform the same validation/redaction/insert logic as record_event.
6. Commit once.
7. Roll back all event inserts in that batch if any event fails validation after DB transaction begins.
```

### 23.1 Batch Size Rule

Keep batch sizes bounded.

Recommended future setting:

```yaml
max_batch_events: 100
```

Large-scale event buffering is not required in V1. It can be introduced later behind the same contract.

---

## 24. Read Trace Behavior

`read_trace(trace_id)` should return one trace summary and ordered events.

Recommended flow:

```text
1. Validate trace_id.
2. Clamp limit to max_events_per_trace_read.
3. Open SQLite connection.
4. Select trace_runs summary by trace_id.
5. If missing, return not-found read model or raise known not-found error.
6. Select trace_events ordered by sequence_no.
7. Decode payload_json.
8. Return safe TraceReadModel.
```

### 24.1 Read SQL

```sql
SELECT
    trace_id,
    parent_trace_id,
    session_id_hash,
    user_id_hash,
    usecase,
    operation,
    route_template,
    status,
    severity,
    started_at,
    ended_at,
    last_event_at,
    duration_ms,
    event_count,
    error_count,
    agent_name,
    strategy_name,
    llm_profile,
    tool_name,
    error_type,
    error_code,
    metadata_json
FROM trace_runs
WHERE trace_id = ?;
```

```sql
SELECT
    event_id,
    trace_id,
    sequence_no,
    parent_event_id,
    event_name,
    event_type,
    status,
    severity,
    timestamp,
    duration_ms,
    session_id_hash,
    user_id_hash,
    usecase,
    agent_name,
    strategy_name,
    llm_profile,
    provider,
    model,
    tool_name,
    error_type,
    error_code,
    retryable,
    payload_json,
    payload_size_bytes,
    redaction_version
FROM trace_events
WHERE trace_id = ?
ORDER BY sequence_no ASC
LIMIT ?;
```

### 24.2 Read Output Shape

Recommended read model:

```json
{
  "trace_id": "trc_...",
  "status": "completed",
  "started_at": "2026-06-24T23:00:00+00:00",
  "ended_at": "2026-06-24T23:00:03+00:00",
  "duration_ms": 3000,
  "event_count": 12,
  "error_count": 0,
  "events": [
    {
      "sequence_no": 1,
      "event_name": "request_received",
      "event_type": "request",
      "status": "started",
      "severity": "info",
      "timestamp": "2026-06-24T23:00:00+00:00",
      "payload": {
        "method": "POST",
        "route_template": "/chat"
      }
    }
  ]
}
```

### 24.3 Read Safety Rule

Read APIs should return exactly what the trace store persisted after redaction. They should not enrich with raw workflow state, memory records, or external provider payloads.

---

## 25. Search Traces Behavior

`search_traces(filters)` should return trace summaries, not full event payloads.

Recommended filters:

```python
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TraceSearchFilters:
    started_after: str | None = None
    started_before: str | None = None
    status: str | None = None
    severity: str | None = None
    usecase: str | None = None
    session_id_hash: str | None = None
    user_id_hash: str | None = None
    event_name: str | None = None
    event_type: str | None = None
    agent_name: str | None = None
    strategy_name: str | None = None
    llm_profile: str | None = None
    tool_name: str | None = None
    error_type: str | None = None
    errors_only: bool = False
    limit: int = 100
```

### 25.1 Search Query Pattern

Search from `trace_runs` for summary filters. Use `EXISTS` for event-specific filters.

```sql
SELECT
    r.trace_id,
    r.usecase,
    r.operation,
    r.route_template,
    r.status,
    r.severity,
    r.started_at,
    r.ended_at,
    r.duration_ms,
    r.event_count,
    r.error_count,
    r.agent_name,
    r.strategy_name,
    r.llm_profile,
    r.tool_name,
    r.error_type,
    r.error_code
FROM trace_runs r
WHERE r.started_at >= ?
  AND r.started_at < ?
  AND (? IS NULL OR r.status = ?)
  AND (? IS NULL OR r.usecase = ?)
  AND (? = 0 OR r.error_count > 0)
  AND (
      ? IS NULL
      OR EXISTS (
          SELECT 1
          FROM trace_events e
          WHERE e.trace_id = r.trace_id
            AND e.event_name = ?
      )
  )
ORDER BY r.started_at DESC
LIMIT ?;
```

### 25.2 Search Safety Rule

Search must be bounded:

- Require a default time window or default recent limit.
- Clamp `limit` to `max_search_results`.
- Do not allow arbitrary SQL from API parameters.
- Do not return full payloads from search results.
- Use parameterized SQL.

---

## 26. Payload Serialization and Redaction

Trace payloads must be JSON-safe and redacted before persistence.

Allowed JSON values:

```text
null
bool
int
float
str
list
dict with string keys
```

Recommended helper:

```python
import json
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any


def to_json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return to_json_safe(asdict(value))
    if isinstance(value, dict):
        return {str(k): to_json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_json_safe(v) for v in value]
    return str(value)
```

### 26.1 Stable JSON Dump

```python
def dumps_payload_json(payload: dict[str, Any]) -> str:
    safe = to_json_safe(payload)
    return json.dumps(safe, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
```

### 26.2 Redaction Rules

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

Recommended default behavior:

| Payload Content | Behavior |
|---|---|
| Raw authorization header | Redact and mark `redacted: true`. |
| API key/provider credential | Redact and mark `redacted: true`. |
| Raw prompt/completion | Do not store unless explicit debug policy enables it. |
| Raw tool result | Store summary only. |
| Raw memory record | Store summary/counts only. |
| Workflow state document | Store size/version/message count only. |
| Error stack trace | Store safe error type/code; stack only in local debug mode after redaction. |

### 26.3 Size Limit

Enforce configured max size:

```yaml
max_event_payload_bytes: 32768
```

If exceeded, replace payload with a bounded summary such as:

```json
{
  "truncated": true,
  "original_payload_size_bytes": 120000,
  "stored_summary": "payload exceeded max_event_payload_bytes",
  "safe_keys": ["provider", "duration_ms", "status"]
}
```

Do not include the oversized payload in the error, log, or stored summary.

---

## 27. Event-Specific Payload Guidelines

### 27.1 Request Events

Safe payload example:

```json
{
  "method": "POST",
  "route_template": "/chat",
  "client_request_id_present": true,
  "streaming": false
}
```

Do not store request body, raw query strings, cookies, bearer tokens, or IP addresses by default.

### 27.2 Workflow State Events

Safe payload example:

```json
{
  "provider": "sqlite",
  "operation": "save",
  "state_version": 4,
  "state_size_bytes": 18420,
  "history_message_count": 9,
  "success": true
}
```

Do not store `state_json`.

### 27.3 LLM Events

Safe payload example:

```json
{
  "llm_profile": "research_reasoning",
  "provider": "openai_compatible",
  "model": "configured-profile-model-name",
  "input_tokens": 1200,
  "output_tokens": 240,
  "temperature": 0.7,
  "duration_ms": 842,
  "success": true
}
```

Do not store raw prompts, raw completions, provider API keys, base URLs with secrets, or raw provider responses by default.

### 27.4 Memory Events

Safe payload example:

```json
{
  "operation": "search",
  "scope": "project",
  "top_k": 10,
  "vector_candidates": 30,
  "bm25_candidates": 30,
  "reranked_count": 10,
  "duration_ms": 120,
  "success": true
}
```

Do not store raw memory text, raw document chunks, or full search query text by default. If needed for debugging, store a query hash and query length.

### 27.5 Tool and MCP Events

Safe payload example:

```json
{
  "tool_name": "weather.lookup",
  "mcp_server": "main",
  "allowed_by_policy": true,
  "input_keys": ["location"],
  "result_size_bytes": 2048,
  "duration_ms": 560,
  "success": true
}
```

Do not store full tool input/output payloads by default.

### 27.6 Error Events

Safe payload example:

```json
{
  "error_type": "LLMProviderTimeoutError",
  "error_code": "llm_timeout",
  "retryable": true,
  "operation": "llm.complete",
  "safe_message": "LLM provider timed out."
}
```

Do not store unredacted stack traces, raw SQL, credentials, raw prompt/completion content, or raw provider responses.

---

## 28. Identifier Validation

### 28.1 Trace ID Validation

Trace IDs must be safe before they are used in SQL or logs.

```python
import re

_TRACE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{8,128}$")


def validate_trace_id(trace_id: str) -> None:
    if not _TRACE_ID_PATTERN.fullmatch(trace_id):
        raise TraceStoreError(
            message="Invalid trace_id.",
            retryable=False,
            details={"reason": "invalid_identifier"},
        )
```

### 28.2 Event Name Validation

```python
_EVENT_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,96}$")
```

### 28.3 Name Field Validation

Fields such as `agent_name`, `strategy_name`, `llm_profile`, `provider`, and `tool_name` should be bounded strings. Unknown values should be normalized or rejected before insert.

Even with validation, SQL must still be parameterized.

---

## 29. Transaction Model

### 29.1 Single Event Write Transaction

A single event write should be atomic.

```text
BEGIN IMMEDIATE
UPSERT trace_runs
SELECT next sequence_no
INSERT trace_events
UPDATE trace_runs counters/summary
COMMIT
```

If any step fails, roll back.

### 29.2 Batch Event Write Transaction

A batch write should be atomic for that batch.

```text
BEGIN IMMEDIATE
FOR event IN events:
  UPSERT trace_runs
  SELECT next sequence_no
  INSERT trace_events
  UPDATE trace_runs
COMMIT
```

If any step fails after the transaction begins, roll back the batch.

### 29.3 Read Transaction

For V1, a bounded `SELECT` without an explicit transaction is acceptable.

### 29.4 Cross-Store Rule

Do not attempt a distributed transaction between:

```text
trace.db
workflow_state.db
memory_store/ArcadeDB
```

A trace event should not roll back a workflow-state save, and a workflow-state save should not roll back a trace event. If future reliability requirements demand stronger guarantees, introduce an outbox pattern in a later architecture document.

---

## 30. Error Model

SQLite exceptions should be wrapped in known backend errors.

Recommended error types:

```text
TraceStoreError
TraceStoreUnavailableError
TraceStoreSerializationError
TraceStorePayloadTooLargeError
TraceStoreConfigurationError
TraceStoreMigrationError
TraceStoreQueryError
TraceStoreNotFoundError
```

### 30.1 Error Wrapper Example

```python
try:
    ...
except sqlite3.OperationalError as exc:
    raise TraceStoreUnavailableError(
        message="Trace store is unavailable.",
        retryable=True,
        details={
            "operation": "record_event",
            "provider": "sqlite",
        },
    ) from exc
```

### 30.2 Error Safety Rule

Errors must not include:

- Raw SQL.
- Full event payloads.
- Credentials.
- Connection strings.
- Authorization headers.
- Raw prompt/completion content.
- Raw provider responses.
- Raw tool results.
- Full stack traces in API responses or health output.

Stack traces may be logged only when debug settings permit them and after redaction.

---

## 31. Observability Integration

The trace store is part of the observability foundation, but it should not recursively trace every internal trace write.

### 31.1 Recorder Pattern

Recommended pattern:

```text
Runtime module
  -> ObservabilityRecorder
      -> structured log
      -> metrics
      -> TraceStore.record_event(...)
```

The recorder handles trace context, redaction, event factory helpers, and metric/log fanout. The `SqliteTraceStore` persists the event.

### 31.2 Avoid Recursive Trace Writes

Do not emit a normal trace event every time `SqliteTraceStore.record_event` succeeds. That would create recursive trace events.

For trace-store write failures, emit a structured log and metric such as:

```text
backend.trace.write.errors
```

Only emit a trace event for trace-store failures if the recorder has explicit recursion protection.

### 31.3 Recommended Metrics

```text
backend.trace.record.total
backend.trace.record.duration_ms
backend.trace.record.bytes
backend.trace.record.errors
backend.trace.read.total
backend.trace.read.duration_ms
backend.trace.search.total
backend.trace.search.duration_ms
backend.trace.search.results
backend.trace.retention.deleted_traces
backend.trace.retention.deleted_events
```

Allowed metric tags:

```text
operation
provider
success
error_type
event_type
event_name
```

Avoid metric tags:

```text
trace_id
session_id
user_id
raw prompt text
raw completion text
raw tool payload
state hash
```

---

## 32. Health Check

The store must expose a safe health check.

Recommended behavior:

```text
1. Verify configured path exists or parent directory is creatable.
2. Open SQLite connection.
3. Apply pragmas.
4. Verify schema_version row.
5. Optionally run SELECT 1.
6. Optionally count recent events with a bounded query.
7. Return safe status.
```

### 32.1 Health Output

Example:

```json
{
  "status": "ok",
  "provider": "sqlite",
  "configured": true,
  "schema_initialized": true,
  "schema_version": 1,
  "journal_mode": "wal",
  "required": true,
  "retention_enabled": false
}
```

### 32.2 Health Must Not Include

- Full database path if it may reveal sensitive deployment layout.
- Event payloads.
- Raw SQL.
- Connection strings.
- Stack traces.
- User IDs.
- Session IDs.
- Raw trace payloads.
- Raw prompt/completion content.

For local debug mode, the health aggregator may include a redacted or basename-only path such as `trace.db`.

---

## 33. Startup Integration

Recommended startup sequence:

```text
1. Load configuration.
2. Build redactor/metrics/structured logger.
3. Resolve persistence settings.
4. Resolve trace.db path.
5. Create parent directories if configured.
6. Build SqliteTraceStore.
7. Initialize schema if configured.
8. Validate schema version.
9. Register trace health check.
10. Register TraceStore with ObservabilityRecorder.
11. Log redacted startup summary.
```

### 33.1 Startup Failure Behavior

| Setting | Behavior |
|---|---|
| `required: true` | Fail startup if database cannot initialize or validate. |
| `required: false` | Mark health as degraded and allow startup for local/prototype mode. |

Recommended V1 value:

```yaml
required: true
```

because request diagnostics and debugging depend on trace persistence.

---

## 34. API and Debug Route Integration

The next API architecture document may expose trace information for local debugging or protected administration.

Potential routes:

```text
GET /traces/{trace_id}
GET /traces?started_after=...&status=failed&limit=50
```

### 34.1 Route Safety Rules

Trace routes should be disabled or protected unless explicitly enabled by configuration.

Recommended API config:

```yaml
api:
  debug_routes:
    traces_enabled: false
    require_admin: true
```

Trace routes must not:

- Return raw prompts or completions unless explicit local debug policy enables capture and readback.
- Return raw request/response bodies.
- Return raw provider credentials.
- Return raw authorization headers.
- Return raw workflow state.
- Return full tool payloads by default.

### 34.2 API Layer Boundary

The API layer may call `TraceStore.read_trace` and `TraceStore.search_traces` through a service/facade. It must not query SQLite directly.

---

## 35. Session Service Integration

The session service will use the observability recorder or `TraceStore` to record session lifecycle events.

Expected future flow:

```text
POST /chat
  -> API creates/resolves trace_id
  -> API records request_received
  -> SessionService.load_state(session_id)
  -> record workflow_state_loaded
  -> OrchestrationRuntime.run(...)
  -> SessionService persists final workflow state
  -> record workflow_state_saved
  -> API records response_returned
```

### 35.1 Reset Flow

```text
POST /sessions/{session_id}/reset
  -> API records request_received
  -> SessionService.reset(session_id)
  -> WorkflowStateStore.reset(session_id)
  -> TraceStore records session_reset/workflow_state_reset summary
  -> API records response_returned
```

Session reset must not delete trace rows. Trace retention cleanup is a separate operational concern.

---

## 36. Orchestration Integration

The orchestration runtime should emit trace events for major decisions and boundaries.

Recommended events:

```text
context_created
strategy_selected
agent_selected
agent_started
agent_completed
memory_search_started
memory_search_completed
llm_call_started
llm_call_completed
llm_call_failed
llm_fallback_selected
tool_call_started
tool_call_completed
tool_call_failed
error_occurred
```

### 36.1 State Update Ownership

The trace store records summaries of state operations. It does not decide state transitions.

| Concern | Owner |
|---|---|
| Load workflow state | Session service through `WorkflowStateStore`. |
| Record state load event | Session service or observability recorder. |
| Select strategy | Orchestration runtime. |
| Record strategy selected | Orchestration runtime or observability recorder. |
| Call LLM | LLM gateway. |
| Record LLM call events | LLM gateway or observability recorder. |
| Persist trace event | Trace store. |

---

## 37. LLM Gateway Integration

The LLM gateway should trace provider calls with safe summaries.

### 37.1 LLM Started Event

```json
{
  "event_name": "llm_call_started",
  "event_type": "llm",
  "status": "started",
  "payload": {
    "llm_profile": "research_reasoning",
    "provider": "openai_compatible",
    "model": "configured-profile-model-name",
    "streaming": false,
    "temperature": 0.7
  }
}
```

### 37.2 LLM Completed Event

```json
{
  "event_name": "llm_call_completed",
  "event_type": "llm",
  "status": "completed",
  "duration_ms": 842,
  "payload": {
    "input_tokens": 1200,
    "output_tokens": 240,
    "finish_reason": "stop"
  }
}
```

### 37.3 LLM Failed Event

```json
{
  "event_name": "llm_call_failed",
  "event_type": "llm",
  "status": "failed",
  "severity": "error",
  "error_type": "LLMProviderTimeoutError",
  "error_code": "llm_timeout",
  "retryable": true,
  "payload": {
    "safe_message": "LLM provider timed out."
  }
}
```

### 37.4 LLM Payload Rule

Do not store raw prompts or raw completions by default. Store counts, durations, provider/profile identifiers, and safe error metadata.

---

## 38. Tool Gateway and MCP Integration

The tool gateway and MCP client adapter should trace tool access with safe summaries.

### 38.1 Tool Started Event

```json
{
  "event_name": "tool_call_started",
  "event_type": "tool",
  "status": "started",
  "payload": {
    "tool_name": "document.search",
    "allowed_by_policy": true,
    "input_keys": ["query", "top_k"]
  }
}
```

### 38.2 Tool Completed Event

```json
{
  "event_name": "tool_call_completed",
  "event_type": "tool",
  "status": "completed",
  "duration_ms": 215,
  "payload": {
    "tool_name": "document.search",
    "result_count": 5,
    "result_size_bytes": 4096
  }
}
```

### 38.3 MCP Call Event

```json
{
  "event_name": "mcp_call_completed",
  "event_type": "mcp",
  "status": "completed",
  "duration_ms": 180,
  "payload": {
    "mcp_server": "main",
    "tool_name": "document.search"
  }
}
```

### 38.4 Tool Payload Rule

Do not store full MCP requests or responses by default. Store names, allowed/denied state, input keys, result counts, result size, duration, and safe error metadata.

---

## 39. Memory Gateway Integration

The memory gateway should trace memory operations with safe summaries.

### 39.1 Memory Search Event

```json
{
  "event_name": "memory_search_completed",
  "event_type": "memory",
  "status": "completed",
  "duration_ms": 120,
  "payload": {
    "scope": "project",
    "top_k": 10,
    "query_length": 84,
    "query_hash": "sha256:...",
    "vector_candidates": 30,
    "bm25_candidates": 30,
    "reranked_count": 10
  }
}
```

### 39.2 Memory Payload Rule

Do not store raw memory text, document chunks, embeddings, or reranker inputs/outputs in trace payloads by default.

---

## 40. Streaming Considerations

Streaming routes should not write a trace event for every token.

Recommended pattern:

```text
stream_started
  -> record one event
stream_chunk_generated
  -> do not record every chunk in SQLite by default
stream_completed
  -> record summary event with token/chunk counts
stream_cancelled
  -> record cancellation summary if useful
stream_failed
  -> record safe failure summary
```

### 40.1 Streaming Trace Rule

Do not write one SQLite transaction per streamed token or chunk.

Persist summary events at start, completion, cancellation, failure, and meaningful checkpoint boundaries only.

---

## 41. Retention and Cleanup

Trace data can grow quickly. V1 should include schema support and optional cleanup behavior, but destructive cleanup should be explicitly configured.

### 41.1 Recommended Default

```yaml
retention:
  enabled: false
  keep_days: 30
  cleanup_batch_size: 1000
```

### 41.2 Cleanup Flow

```text
1. Confirm retention.enabled is true.
2. Calculate cutoff_at from keep_days.
3. Insert trace_retention_runs row.
4. Select a bounded batch of trace_ids older than cutoff.
5. Delete from trace_runs where trace_id in selected batch.
6. Rely on ON DELETE CASCADE to remove trace_events.
7. Update trace_retention_runs counts and status.
8. Repeat in later scheduled call if more rows remain.
```

### 41.3 Cleanup SQL Pattern

```sql
DELETE FROM trace_runs
WHERE trace_id IN (
    SELECT trace_id
    FROM trace_runs
    WHERE started_at < ?
    ORDER BY started_at ASC
    LIMIT ?
);
```

### 41.4 Retention Rule

Trace retention cleanup must not delete:

```text
workflow_state.db rows
memory_store records
ArcadeDB document chunks
LLM provider/profile config
MCP tool config
policy config
```

---

## 42. Privacy and Data Minimization

Trace events are diagnostic records. They must be minimized.

### 42.1 Minimization Rules

- Store event names, status, timing, counts, and safe identifiers.
- Store hashed user/session identifiers by default.
- Store route templates, not full URLs with query strings.
- Store LLM token counts and timing, not raw prompts or completions.
- Store tool input keys and result counts/sizes, not raw payloads.
- Store memory search counts and hashes, not raw memory content.
- Store workflow state size/version/counts, not full workflow state.
- Store safe error type/code/message, not unredacted stack traces.

### 42.2 Deletion Boundaries

| Operation | Store Impact |
|---|---|
| Session reset | Does not delete traces. |
| Memory forget | Clears memory only through `MemoryGateway`; traces are governed by trace retention/privacy policy. |
| Trace retention cleanup | Deletes trace rows only. |
| Delete session | May delete workflow state; trace deletion requires separate retention/privacy policy. |

### 42.3 Future Privacy Controls

Future policy/deployment documents should define:

- Whether trace deletion by session/user hash is required.
- Whether admin trace readback is enabled.
- Whether local debug mode may capture prompts/completions.
- Whether trace exports are allowed.
- How retention differs between local development and production-like use.

---

## 43. Fake Store Compatibility

The fake store should match the real contract, not the real schema.

```python
class FakeTraceStore:
    def __init__(self) -> None:
        self._events: dict[str, list[TraceEvent]] = {}

    async def record_event(self, event: TraceEvent) -> None:
        self._events.setdefault(event.trace_id, []).append(event)

    async def record_events(self, events: Sequence[TraceEvent]) -> None:
        for event in events:
            await self.record_event(event)

    async def read_trace(self, *, trace_id: str, limit: int | None = None) -> TraceReadModel:
        events = self._events.get(trace_id, [])
        if limit is not None:
            events = events[:limit]
        return TraceReadModel.from_events(trace_id=trace_id, events=events)

    async def search_traces(self, *, filters: TraceSearchFilters) -> list[TraceSummary]:
        return [
            TraceSummary.from_events(trace_id=trace_id, events=events)
            for trace_id, events in self._events.items()
        ][: filters.limit]

    async def health(self) -> dict[str, object]:
        return {"status": "ok", "provider": "fake"}
```

### 43.1 Fake Store Rule

Higher-level tests should assert behavior, not SQLite implementation details.

Use fake trace store tests for:

```text
Session service
Orchestration runtime
Strategies
Agents
LLM gateway unit tests
Tool gateway unit tests
API route unit tests
```

Use SQLite integration tests only for the adapter itself.

---

## 44. Recommended Implementation Order

### Step 1: Add Settings

Deliverables:

- `SqliteTraceStoreSettings`
- Config mapping from YAML
- Validation for path, max payload size, query limits, raw ID storage flags, retention settings, and required flag

Success criteria:

- Config can select SQLite trace store.
- Invalid capture/retention settings fail fast.

### Step 2: Add Trace Models

Deliverables:

- `TraceEvent`
- `TraceReadModel`
- `TraceSummary`
- `TraceSearchFilters`
- Valid enums or bounded string validators for event type/status/severity

Success criteria:

- Core trace objects compile.
- Fake and SQLite stores can share the same model objects.

### Step 3: Add Schema Module

Deliverables:

- `sqlite_trace_schema.py`
- DDL constants
- Schema version constants
- Initialization function

Success criteria:

- Schema initializes idempotently.
- Schema version row is present.

### Step 4: Add SQLite Connection Helpers

Deliverables:

- Path resolution
- Parent directory creation
- Pragma application
- Transaction helper

Success criteria:

- Temporary test databases can be created safely.
- WAL/busy timeout/foreign keys can be configured.

### Step 5: Add Redaction and Serialization Helpers

Deliverables:

- JSON-safe conversion
- Payload redaction
- Payload size enforcement
- Raw ID hashing helper

Success criteria:

- Sensitive fields are redacted before persistence.
- Oversized payloads are summarized safely.

### Step 6: Implement `record_event`

Deliverables:

- Trace ID validation
- Event ID generation
- Event field validation
- Trace run upsert
- Event insert
- Summary counter update

Success criteria:

- One event can be persisted and read from SQLite.
- Sequence numbers are assigned in order.
- Payloads are stored redacted and bounded.

### Step 7: Implement `record_events`

Deliverables:

- Batch validation
- Batch transaction
- Per-trace sequence allocation

Success criteria:

- Multiple events can be written in one transaction.
- Batch rollback works on failure.

### Step 8: Implement `read_trace`

Deliverables:

- Trace summary select
- Ordered event select
- Payload decode
- Limit enforcement

Success criteria:

- Reading a known trace returns ordered events.
- Missing trace returns known not-found behavior.
- Read limit is clamped.

### Step 9: Implement `search_traces`

Deliverables:

- `TraceSearchFilters`
- Parameterized query builder
- Bounded search results

Success criteria:

- Recent traces can be searched by status, use case, error type, event name, agent, LLM profile, and tool name.
- Search does not return full payloads.

### Step 10: Implement Health Check

Deliverables:

- `health` method
- Schema validation
- Safe output

Success criteria:

- Healthy DB returns `ok`.
- Missing schema returns degraded/error depending on required behavior.
- Health does not expose payload content or sensitive paths.

### Step 11: Add Optional Retention Cleanup

Deliverables:

- Retention configuration
- Cleanup method or internal helper
- `trace_retention_runs` records

Success criteria:

- Cleanup is disabled by default.
- Enabled cleanup deletes only old trace rows in bounded batches.

### Step 12: Update Composition Root

Deliverables:

- `build_trace_store(settings)`
- Health registration
- Observability recorder wiring
- Redacted startup summary update

Success criteria:

- Backend can start with SQLite trace store configured.
- The next API/session walking skeleton can use the real store.

---

## 45. Testing Strategy

### 45.1 Unit Tests

| Test | Purpose |
|---|---|
| Settings parse valid config | Proves configuration mapping. |
| Invalid capture mode fails | Prevents undefined payload behavior. |
| Invalid retention settings fail | Prevents destructive cleanup mistakes. |
| Path resolution uses temp dir | Prevents writing to real data files. |
| Schema DDL contains required tables | Prevents accidental table removal. |
| Schema initialization is idempotent | Allows repeated startup. |
| Trace ID validation rejects unsafe IDs | Prevents unsafe identifiers. |
| Event name validation rejects unsafe names | Keeps event taxonomy stable. |
| Serialization converts datetimes/enums | Prevents JSON failures. |
| Sensitive key handling redacts credentials | Prevents credential persistence. |
| Oversized payload is summarized | Prevents unbounded trace growth. |
| Fake store record/read/search | Supports higher-level tests. |
| Query builder uses parameters | Prevents SQL injection. |

### 45.2 Integration Tests

| Test | Purpose |
|---|---|
| Fresh SQLite DB initializes | Proves schema bootstrap. |
| Re-open existing DB succeeds | Proves idempotent startup. |
| Record event then read trace | Proves core persistence path. |
| Record multiple events preserves order | Proves sequence allocation. |
| Batch write commits all events | Proves batch persistence. |
| Batch write rollback on invalid event | Proves transaction behavior. |
| Search traces by status/usecase/error | Proves debug query path. |
| Payload redaction persists redacted output | Proves privacy behavior. |
| Health returns safe status | Proves health behavior. |
| Required DB failure fails startup path | Proves required-store behavior. |
| Retention cleanup deletes only trace rows | Proves cleanup boundary. |
| Concurrent writes do not corrupt DB | Proves WAL/busy timeout baseline. |

### 45.3 Fixture Configs

Recommended fixtures:

```text
tests/fixtures/config/trace_sqlite.yaml
tests/fixtures/config/trace_sqlite_no_schema_init.yaml
tests/fixtures/config/trace_sqlite_small_payload.yaml
tests/fixtures/config/trace_sqlite_retention_enabled.yaml
tests/fixtures/config/trace_fake.yaml
```

---

## 46. Acceptance Criteria

This architecture is complete when:

- `SqliteTraceStore` implements `TraceStore`.
- `record_event`, `record_events`, `read_trace`, `search_traces`, and `health` are available.
- SQLite details are isolated to the persistence adapter and SQLite helper modules.
- API, session, orchestration, strategies, agents, LLM gateway, tool gateway, memory gateway, and policy service do not import SQLite.
- The trace database path is configurable.
- Parent directory creation is configuration-controlled.
- SQLite pragmas are applied from configuration.
- Schema initialization is idempotent.
- Schema version is recorded and validated.
- Trace events are correlated by `trace_id`.
- Trace events are ordered by monotonic `sequence_no` within each trace.
- Trace run summaries support bounded debug search.
- Trace payloads are JSON-safe.
- Trace payloads are redacted before persistence.
- Trace payload size is bounded.
- Raw prompts and completions are not persisted by default.
- Raw request/response bodies are not persisted by default.
- Raw tool payloads are not persisted by default.
- Raw workflow state is not persisted in traces.
- Trace write failures are handled safely and do not corrupt workflow state.
- Session reset does not delete trace events.
- Trace retention cleanup, if enabled, deletes only trace rows.
- Health checks verify SQLite reachability and schema readiness.
- Health responses do not expose event payloads, user IDs, session IDs, SQL, connection strings, or stack traces.
- Store errors are wrapped in known backend errors.
- Observability emits safe metrics/logs for trace read/write/query failures without recursive trace writes.
- Tests cover fresh DB initialization, re-opening existing DB, record/read/search, redaction, payload limits, retention boundaries, and health.
- The backend is ready for the next document: `backend-api-architecture.md`.

---

## 47. Anti-Patterns to Avoid

Avoid these during implementation:

- Letting API routes run trace SQL.
- Letting session service know trace table names.
- Letting orchestration code know SQLite row shapes.
- Letting agents read or write SQLite directly.
- Storing long-term memories in trace payloads.
- Storing document chunks in trace payloads.
- Storing workflow state JSON in trace payloads.
- Treating traces as durable user memory.
- Deleting traces during session reset.
- Logging full event payloads after redaction failed.
- Returning trace payloads from `/health`.
- Storing raw authorization headers.
- Storing API keys or provider credentials.
- Saving full provider SDK response objects.
- Saving raw prompts/completions by default.
- Saving full MCP request/response payloads by default.
- Writing a trace event for every streamed token.
- Creating broad indexes before access patterns exist.
- Using string interpolation for SQL parameters.
- Allowing arbitrary SQL through trace search filters.
- Silently ignoring SQLite initialization failure when store is required.
- Making tests depend on real local `./data/trace.db`.
- Emitting trace events recursively for every trace-store write.

---

## 48. Future Documents That Depend on This Store

| Future Document | Dependency |
|---|---|
| `backend-api-architecture.md` | Uses trace IDs, request/response trace events, health integration, and optional protected debug trace routes. |
| `backend-session-service-architecture.md` | Records session lifecycle, state load/save/reset summaries, and session correlation fields. |
| `backend-llm-gateway-architecture.md` | Emits safe LLM call, fallback, token, duration, and provider error events. |
| `backend-memory-store-adapter-architecture.md` | Emits safe memory search/upsert summaries without persisting memory text. |
| `backend-tooling-mcp-client-architecture.md` | Emits safe tool/MCP call summaries and policy allow/deny metadata. |
| `backend-orchestration-architecture.md` | Emits strategy, agent, workflow, and error events under one request trace. |
| `backend-workflow-strategies-architecture.md` | Uses trace events to explain routing and workflow transitions. |
| `backend-agents-architecture.md` | Uses trace events for agent lifecycle diagnostics without exposing raw agent prompts. |
| `backend-policy-architecture.md` | Defines trace capture policy, debug-route access, prompt/completion capture rules, and privacy deletion behavior. |
| `backend-deployment-architecture.md` | Defines volume mapping, backups, retention, cleanup schedule, and local/prod trace settings. |

---

## 49. Summary

`SqliteTraceStore` is the concrete operational trace persistence implementation for the backend walking skeleton.

It stores request and runtime diagnostic events in `trace.db`, keeps SQLite isolated behind the `TraceStore` contract, supports safe append/read/search behavior, and preserves the separation between short-term workflow state, long-term memory, and operational traces.

The most important implementation rule is:

> **Traces are operational diagnostics. They must be persisted through `TraceStore`, isolated behind SQLite adapter boundaries, redacted before storage, queryable for debugging, and never treated as workflow state, long-term memory, or a raw prompt/completion archive.**
