# Backend SQLite Workflow State Architecture

**Document:** `backend-sqlite-workflow-state-architecture.md`  
**Version:** 1.0  
**Source alignment:** `backend-application-architecture.md`, `backend-foundation-architecture.md`, `backend-core-contracts-architecture.md`, `backend-configuration-architecture.md`, `backend-observability-architecture.md`, and `backend-persistence-architecture.md`  
**Scope:** SQLite-backed workflow/session state storage, schema, migrations, load/save/reset behavior, serialization, concurrency, health checks, observability integration, testing strategy, and acceptance criteria for the backend `WorkflowStateStore` implementation.

---

## 1. Purpose

This document defines the sixth implementation-focused architecture document for the backend application tier.

It follows:

1. `backend-foundation-architecture.md`
2. `backend-core-contracts-architecture.md`
3. `backend-configuration-architecture.md`
4. `backend-observability-architecture.md`
5. `backend-persistence-architecture.md`
6. `backend-sqlite-workflow-state-architecture.md` ← this document

The persistence architecture established three separate persistence domains:

```text
Long-term memory and document chunks -> MemoryGateway -> memory_store -> ArcadeDB
Short-term workflow/session state    -> WorkflowStateStore -> SQLite
Operational traces                   -> TraceStore -> SQLite
```

This document deepens only the second domain: short-term workflow/session state.

The goal is to implement the V1 `SqliteWorkflowStateStore` in a way that supports the upcoming API/session walking skeleton while preserving the key backend architecture rule:

> API routes, orchestration, strategies, and agents use `WorkflowStateStore`; only the SQLite adapter knows SQLite tables, SQL statements, pragmas, migrations, or file paths.

---

## 2. Source Architecture Alignment

This document follows the established backend rules:

- The backend is one deployable application tier in V1.
- Frontend communicates with backend over REST / SSE.
- Backend communicates with the external MCP tier only through the MCP client adapter.
- Backend does not implement the MCP server.
- Agents receive controlled capabilities through `OrchestrationContext`.
- Agents do not import SQLite, ArcadeDB, MCP clients, provider SDKs, external API clients, or `memory_store.service.MemoryService`.
- Workflow state is short-term session/runtime state, not long-term memory.
- Trace events are operational records, not workflow state.
- Session reset clears workflow state only.
- Session reset must not delete long-term memory, document chunks, trace events, LLM configuration, MCP configuration, or policy configuration.
- SQLite is hidden behind `SqliteWorkflowStateStore`.
- Store configuration is loaded through typed configuration views, not raw environment reads inside runtime modules.
- Logs, traces, health responses, and errors must not expose secrets, raw authorization headers, provider credentials, sensitive connection strings, or full state payloads.
- Workflow-state operations should emit trace-safe observability events and metrics.

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
Phase 7: API and Session Walking Skeleton
Phase 8: LLM Gateway
Phase 9: Memory Gateway
Phase 10: Tool Gateway and MCP Client Adapter
Phase 11: Orchestration Runtime and Strategies
Phase 12: Agent Plugins
Phase 13: Hardening and Deployment Readiness
```

This document expands Phase 6.

The output of this phase is a real SQLite-backed `WorkflowStateStore` that can load, save, reset, and health-check session state before the API/session walking skeleton is implemented.

The next document should be:

```text
backend-sqlite-trace-store-architecture.md
```

---

## 4. Architecture Goals

The SQLite workflow state store should be:

1. **Contract-compatible**  
   It implements the existing `WorkflowStateStore` protocol without forcing higher layers to understand SQLite.

2. **Session-scoped**  
   All workflow state is keyed by `session_id` and represents current session continuity only.

3. **Reset-safe**  
   Reset clears short-term state while preserving independent persistence domains.

4. **JSON-first**  
   V1 stores workflow state as a JSON document with searchable metadata columns for diagnostics and health.

5. **Atomic**  
   `save` and `reset` are single-transaction operations.

6. **Traceable**  
   Load/save/reset operations produce safe trace events, logs, and metrics through the observability layer.

7. **Configurable**  
   Path, schema initialization, SQLite pragmas, max state size, and reset behavior are configuration-driven.

8. **Safe by default**  
   State payloads are not logged or emitted in health responses. Secrets and provider credentials are rejected or redacted.

9. **Concurrency-aware**  
   V1 supports SQLite WAL, short transactions, busy timeouts, row versioning, and optional optimistic conflict detection.

10. **Testable**  
   Unit tests can use fake stores; integration tests can create temporary SQLite files and verify schema/load/save/reset behavior.

---

## 5. Non-Goals

This document should not implement:

- Long-term memory storage.
- Document chunk ingestion.
- Trace event query/debug APIs.
- Full session-service behavior.
- Full API route behavior.
- Full conversation summarization.
- Cross-session memory promotion.
- Distributed transactions.
- Multi-writer cluster semantics.
- SQLite sharding.
- Complex event sourcing.
- A workflow-state UI.
- Frontend local-state persistence.
- MCP server-side persistence.
- Raw prompt/completion archival.

Those concerns belong to later API, session, orchestration, memory, trace-store, policy, and deployment documents.

---

## 6. Workflow State Boundary

Workflow state stores short-term state needed to continue a session.

Allowed examples:

- Current conversation history needed for the session.
- Current workflow step.
- Active checkpoint metadata.
- Temporary scratch variables.
- Pending tool-call summaries.
- Pending approval context.
- Agent routing hints for the current session.
- Last agent/strategy result metadata.
- Last activity timestamp.

Disallowed examples:

- Long-term user preferences.
- Durable project facts.
- Document corpus chunks.
- Memory embeddings.
- Trace-event history.
- Raw API keys.
- Raw authorization headers.
- Provider credentials.
- Full provider SDK response objects.
- Durable facts intended for future sessions.

### 6.1 Store Separation

```text
SessionService
  -> WorkflowStateStore
      -> SqliteWorkflowStateStore
          -> workflow_state.db
```

The store must not call:

```text
LLMGateway
MemoryGateway
ToolGateway
MCPClientAdapter
AgentPlugin
OrchestrationStrategy
```

The store persists state. It does not make runtime decisions.

---

## 7. Recommended Package Layout

Recommended implementation layout:

```text
backend/
  app/
    persistence/
      workflow_state_store.py
      sqlite_workflow_state_store.py
      sqlite_workflow_state_schema.py
      sqlite_workflow_state_models.py

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
      workflow_state.py
      errors.py
      health.py

    observability/
      tracing.py
      events.py
      metrics.py
      redaction.py

    testing/
      fakes/
        fake_workflow_state.py

  tests/
    unit/
      persistence/
        test_workflow_state_contract.py
        test_sqlite_workflow_state_schema.py
        test_sqlite_workflow_state_serialization.py
        test_sqlite_workflow_state_reset.py
        test_sqlite_workflow_state_health.py
        test_fake_workflow_state_store.py

    integration/
      persistence/
        test_sqlite_workflow_state_store_smoke.py
        test_sqlite_workflow_state_store_concurrency.py
        test_sqlite_workflow_state_store_migrations.py
```

### 7.1 Module Responsibilities

| Module | Responsibility |
|---|---|
| `workflow_state_store.py` | Contract import/re-export or canonical protocol location. |
| `sqlite_workflow_state_store.py` | Concrete adapter implementing `load`, `save`, `reset`, and `health`. |
| `sqlite_workflow_state_schema.py` | Store-specific table DDL and schema version. |
| `sqlite_workflow_state_models.py` | Internal row/result dataclasses if needed. |
| `sqlite/connection.py` | Shared SQLite connection helper. |
| `sqlite/pragmas.py` | Shared SQLite pragma application. |
| `sqlite/migrations.py` | Shared schema version helper. |
| `serialization.py` | JSON-safe conversion and stable dumps. |
| `paths.py` | Data-path resolution and parent directory creation. |
| `errors.py` | Persistence/SQLite error wrappers. |
| `testing/fakes/fake_workflow_state.py` | In-memory contract-compatible fake. |

---

## 8. Dependency Direction Rules

Allowed:

```text
app/session/*                         -> app/contracts/workflow_state.py
app/orchestration/*                   -> app/contracts/workflow_state.py
app/persistence/sqlite_workflow_*     -> app/contracts/workflow_state.py
app/persistence/sqlite_workflow_*     -> app/persistence/sqlite/*
app/persistence/sqlite_workflow_*     -> app/persistence/serialization.py
app/persistence/sqlite_workflow_*     -> app/persistence/errors.py
app/persistence/sqlite_workflow_*     -> standard library sqlite3/json/pathlib/hashlib/datetime
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
```

### 8.1 Practical Rule

Runtime modules should do this:

```python
state = await workflow_state.load(session_id=session_id)
await workflow_state.save(session_id=session_id, state=next_state)
await workflow_state.reset(session_id=session_id)
```

Runtime modules should not do this:

```python
sqlite3.connect("./data/workflow_state.db")
conn.execute("SELECT state_json FROM workflow_state_current ...")
```

---

## 9. Configuration Integration

The workflow-state store should be configured under the shared persistence configuration.

Recommended YAML:

```yaml
persistence:
  base_dir: ${env:APP_DATA_DIR:./data}

  workflow_state:
    provider: sqlite
    sqlite:
      path: ${env:WORKFLOW_STATE_DB:./data/workflow_state.db}
      create_parent_dirs: true
      initialize_schema: true
      journal_mode: WAL
      synchronous: NORMAL
      busy_timeout_ms: 5000
      foreign_keys: true
      required: true
      max_state_bytes: 1048576
      max_history_messages: 50
      reset_mode: replace_with_empty_state
      store_user_id: false
      store_user_id_hash: true
```

### 9.1 Settings Object

Recommended typed settings:

```python
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SqliteWorkflowStateSettings:
    path: Path
    create_parent_dirs: bool
    initialize_schema: bool
    journal_mode: str
    synchronous: str
    busy_timeout_ms: int
    foreign_keys: bool
    required: bool
    max_state_bytes: int
    max_history_messages: int
    reset_mode: str
    store_user_id: bool
    store_user_id_hash: bool
```

### 9.2 Supported V1 Values

| Setting | Supported V1 Values | Recommended Default |
|---|---|---|
| `provider` | `sqlite`, `fake` for tests | `sqlite` |
| `journal_mode` | `WAL`, `DELETE` | `WAL` |
| `synchronous` | `NORMAL`, `FULL` | `NORMAL` |
| `reset_mode` | `replace_with_empty_state`, `delete_state_row` | `replace_with_empty_state` |
| `required` | `true`, `false` | `true` |

### 9.3 Configuration Access Rule

The adapter receives resolved settings from the composition root.

Use:

```python
settings = config_view.persistence().workflow_state.sqlite
store = SqliteWorkflowStateStore(settings=settings, ...)
```

Avoid this inside the adapter:

```python
os.getenv("WORKFLOW_STATE_DB")
```

The configuration layer may read environment variables. Runtime modules and adapters should receive resolved values.

---

## 10. Core Store Contract

The canonical protocol remains small:

```python
from typing import Any, Protocol


class WorkflowStateStore(Protocol):
    async def load(self, *, session_id: str) -> dict[str, Any]:
        ...

    async def save(self, *, session_id: str, state: dict[str, Any]) -> None:
        ...

    async def reset(self, *, session_id: str) -> None:
        ...

    async def health(self) -> dict[str, Any]:
        ...
```

### 10.1 Contract Behavior

| Method | Required Behavior |
|---|---|
| `load` | Return existing state for `session_id`; return default empty state when no state exists. |
| `save` | Validate and persist a JSON-safe state document atomically. |
| `reset` | Clear short-term state for the session only. |
| `health` | Return safe readiness information without exposing state content or file secrets. |

### 10.2 Contract Stability Rule

Do not force API, session, orchestration, or agents to depend on SQLite-specific concepts such as:

```text
row id
SQLite connection
schema version table
state_hash
WAL mode
SQL error class
reset_generation
```

Those are adapter internals.

---

## 11. Workflow State Document Shape

Recommended default state object:

```json
{
  "version": 1,
  "session_id": "session_123",
  "conversation": {
    "messages": []
  },
  "workflow": {
    "current_step": null,
    "checkpoint": null,
    "scratch": {},
    "pending_actions": []
  },
  "last_result": {
    "agent_name": null,
    "strategy_name": null,
    "llm_profile": null
  },
  "metadata": {}
}
```

### 11.1 Message Shape

If conversation history is stored in workflow state, use a normalized message shape:

```json
{
  "role": "user",
  "content": "message text",
  "created_at": "2026-06-23T23:00:00+00:00",
  "metadata": {
    "message_id": "msg_..."
  }
}
```

Allowed roles should be bounded, for example:

```text
system
user
assistant
tool
agent
```

### 11.2 State Metadata Reserved Keys

Reserved internal metadata keys:

```text
_state_version
_expected_state_version
_state_hash
_reset_generation
_saved_at
_loaded_at
```

Higher layers may ignore these. The adapter may use them when available.

### 11.3 State Content Rule

The workflow state document may include raw session messages when required for continuity, but it must not include credentials, API keys, raw authorization headers, or durable memory records.

If raw message storage is disabled by policy or configuration, the session service should store compact summaries, message counts, or references instead. The detailed summarization policy belongs in the session-service and policy documents.

---

## 12. SQLite Storage Model

Use one SQLite database file for workflow state:

```text
./data/workflow_state.db
```

Recommended tables:

```text
schema_version
workflow_sessions
workflow_state_current
workflow_state_resets
```

### 12.1 Why Store State as JSON Plus Metadata Columns

V1 should avoid over-normalizing conversation state before the session and orchestration modules stabilize.

Use:

```text
state_json        -> canonical workflow state document
metadata columns  -> diagnostics, indexing, concurrency, health, cleanup
```

This gives the backend a stable storage contract while keeping enough indexed fields for operational use.

---

## 13. Schema Version Table

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
name = workflow_state
version = 1
```

### 13.1 Schema Version Rules

- Schema initialization is idempotent.
- Opening an already-initialized database is safe.
- Startup validates the expected schema version.
- Destructive migrations are not automatic in V1.
- Tests must cover fresh database creation and re-opening an existing database.

---

## 14. `workflow_sessions` Table

The `workflow_sessions` table stores session-level metadata.

```sql
CREATE TABLE IF NOT EXISTS workflow_sessions (
    session_id TEXT PRIMARY KEY,
    user_id TEXT NULL,
    user_id_hash TEXT NULL,
    usecase TEXT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_activity_at TEXT NOT NULL,
    reset_count INTEGER NOT NULL DEFAULT 0,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
```

### 14.1 Column Rules

| Column | Rule |
|---|---|
| `session_id` | Safe bounded identifier. Primary key. |
| `user_id` | Optional. Prefer disabled or synthetic in local V1 unless needed. |
| `user_id_hash` | Preferred diagnostic identity field when user correlation is needed. |
| `usecase` | Optional active use-case name. |
| `status` | `active`, `reset`, `expired`, or future values. |
| `created_at` | UTC ISO timestamp. |
| `updated_at` | UTC ISO timestamp. |
| `last_activity_at` | UTC ISO timestamp updated on save/reset. |
| `reset_count` | Monotonic count of resets for this session. |
| `metadata_json` | Safe session metadata only. |

### 14.2 User ID Storage Rule

Prefer storing `user_id_hash` rather than raw `user_id` unless the application requires raw user IDs for session ownership checks.

If raw user IDs are stored, they must not be exposed in health responses or high-cardinality metrics tags.

---

## 15. `workflow_state_current` Table

The `workflow_state_current` table stores the current state document for each session.

```sql
CREATE TABLE IF NOT EXISTS workflow_state_current (
    session_id TEXT PRIMARY KEY,
    state_version INTEGER NOT NULL DEFAULT 1,
    state_json TEXT NOT NULL,
    state_hash TEXT NOT NULL,
    state_size_bytes INTEGER NOT NULL,
    message_count INTEGER NOT NULL DEFAULT 0,
    current_step TEXT NULL,
    checkpoint_name TEXT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    reset_generation INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (session_id)
        REFERENCES workflow_sessions(session_id)
        ON DELETE CASCADE
);
```

### 15.1 Column Rules

| Column | Rule |
|---|---|
| `session_id` | Same as `workflow_sessions.session_id`. |
| `state_version` | Monotonic row version incremented on every save/reset. |
| `state_json` | Canonical JSON-safe workflow state. |
| `state_hash` | SHA-256 hash of canonical JSON. |
| `state_size_bytes` | UTF-8 byte size of `state_json`. |
| `message_count` | Derived count from `conversation.messages`. |
| `current_step` | Derived from `workflow.current_step`. |
| `checkpoint_name` | Derived from checkpoint metadata if present. |
| `created_at` | UTC ISO timestamp for first state row creation. |
| `updated_at` | UTC ISO timestamp for current version. |
| `reset_generation` | Monotonic reset generation for this session. |

### 15.2 State Hash Rule

Use canonical JSON to calculate `state_hash`:

```python
import hashlib
import json


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def state_hash(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
```

State hashes are useful for debugging, conflict detection, and test assertions. Do not treat them as cryptographic proof of data integrity.

---

## 16. `workflow_state_resets` Table

The `workflow_state_resets` table records reset operations without storing the cleared state.

```sql
CREATE TABLE IF NOT EXISTS workflow_state_resets (
    reset_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    trace_id TEXT NULL,
    reason TEXT NULL,
    reset_generation INTEGER NOT NULL,
    cleared_state_version INTEGER NULL,
    reset_at TEXT NOT NULL,
    FOREIGN KEY (session_id)
        REFERENCES workflow_sessions(session_id)
        ON DELETE CASCADE
);
```

### 16.1 Reset Record Rules

- Store reset metadata, not the cleared state payload.
- `reason` must be short and safe.
- `trace_id` is optional and comes from the current request context if available.
- Reset records are operational metadata, not user memory.
- Trace store still records reset events independently through observability.

---

## 17. Indexes

Recommended indexes:

```sql
CREATE INDEX IF NOT EXISTS idx_workflow_sessions_user_hash
    ON workflow_sessions(user_id_hash);

CREATE INDEX IF NOT EXISTS idx_workflow_sessions_usecase
    ON workflow_sessions(usecase);

CREATE INDEX IF NOT EXISTS idx_workflow_sessions_last_activity
    ON workflow_sessions(last_activity_at);

CREATE INDEX IF NOT EXISTS idx_workflow_state_updated_at
    ON workflow_state_current(updated_at);

CREATE INDEX IF NOT EXISTS idx_workflow_state_current_step
    ON workflow_state_current(current_step);

CREATE INDEX IF NOT EXISTS idx_workflow_resets_session_id
    ON workflow_state_resets(session_id);

CREATE INDEX IF NOT EXISTS idx_workflow_resets_reset_at
    ON workflow_state_resets(reset_at);
```

### 17.1 Indexing Rule

V1 should keep indexes minimal.

Do not add indexes for fields that are not queried by health, cleanup, debugging, or session lookup.

---

## 18. SQLite Pragmas

Recommended pragmas applied when opening connections:

```sql
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA busy_timeout = 5000;
PRAGMA foreign_keys = ON;
```

### 18.1 Pragmas by Configuration

```python
def apply_pragmas(conn: sqlite3.Connection, settings: SqliteWorkflowStateSettings) -> None:
    conn.execute(f"PRAGMA journal_mode = {settings.journal_mode}")
    conn.execute(f"PRAGMA synchronous = {settings.synchronous}")
    conn.execute(f"PRAGMA busy_timeout = {settings.busy_timeout_ms}")
    conn.execute(f"PRAGMA foreign_keys = {'ON' if settings.foreign_keys else 'OFF'}")
```

### 18.2 WAL Rationale

WAL mode is recommended because workflow state has frequent reads and short writes by session. WAL improves local concurrency for normal V1 usage.

---

## 19. Connection Lifecycle

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

Request operation
  -> open short-lived connection
  -> apply pragmas
  -> execute operation in transaction
  -> commit or rollback
  -> close connection
```

### 19.1 Why Short-Lived Connections Are Acceptable in V1

Short-lived connections keep the implementation simple and avoid async pooling concerns while request volume is low. A future connection manager or pool can be introduced behind the same adapter without changing `WorkflowStateStore`.

### 19.2 Async Boundary

If the backend is async, there are two acceptable V1 choices:

1. Use `aiosqlite` behind the adapter.
2. Use standard `sqlite3` in a controlled thread/executor boundary.

Do not make higher-level modules care which approach is used.

---

## 20. Schema Initialization

Recommended schema initializer:

```python
WORKFLOW_STATE_SCHEMA_NAME = "workflow_state"
WORKFLOW_STATE_SCHEMA_VERSION = 1


def initialize_workflow_state_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(WORKFLOW_STATE_DDL)
    conn.execute(
        """
        INSERT INTO schema_version(name, version, applied_at)
        VALUES (?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET
            version = excluded.version,
            applied_at = excluded.applied_at
        """,
        (WORKFLOW_STATE_SCHEMA_NAME, WORKFLOW_STATE_SCHEMA_VERSION, utc_now_iso()),
    )
```

### 20.1 Initialization Rules

- Create tables only when `initialize_schema: true`.
- Validate schema version during health and startup.
- Fail startup if the store is required and schema initialization or validation fails.
- Do not silently downgrade or destructively migrate.

---

## 21. Default Empty State

When `load` does not find a row, it should return a default empty state rather than `None`.

Recommended helper:

```python
from datetime import UTC, datetime
from typing import Any


def default_workflow_state(session_id: str) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    return {
        "version": 1,
        "session_id": session_id,
        "conversation": {"messages": []},
        "workflow": {
            "current_step": None,
            "checkpoint": None,
            "scratch": {},
            "pending_actions": [],
        },
        "last_result": {
            "agent_name": None,
            "strategy_name": None,
            "llm_profile": None,
        },
        "metadata": {
            "created_at": now,
            "loaded_empty": True,
        },
    }
```

### 21.1 Empty Load Rule

`load(session_id)` must be deterministic:

```text
No row exists -> return default empty state
Row exists    -> return stored state_json plus adapter metadata if desired
```

The session service can decide whether to immediately save the empty state or wait until a request completes.

---

## 22. Load Behavior

Recommended `load` flow:

```text
1. Validate session_id.
2. Open SQLite connection.
3. Apply pragmas.
4. Select state_json/state_version/reset_generation by session_id.
5. If not found, return default empty state.
6. Decode JSON.
7. Add internal metadata if useful.
8. Emit workflow_state_loaded event through caller/helper if configured.
9. Return state dictionary.
```

### 22.1 Load SQL

```sql
SELECT
    s.session_id,
    s.usecase,
    c.state_version,
    c.state_json,
    c.state_hash,
    c.updated_at,
    c.reset_generation
FROM workflow_state_current c
JOIN workflow_sessions s ON s.session_id = c.session_id
WHERE c.session_id = ?;
```

### 22.2 Load Result Metadata

The adapter may add internal metadata under a reserved key:

```json
{
  "metadata": {
    "_state_version": 3,
    "_state_hash": "...",
    "_reset_generation": 1,
    "_loaded_at": "2026-06-23T23:00:00+00:00"
  }
}
```

Do not require agents to read these fields.

---

## 23. Save Behavior

Recommended `save` flow:

```text
1. Validate session_id.
2. Validate state is a dictionary.
3. Normalize state session_id.
4. Convert state to JSON-safe data.
5. Reject or redact disallowed sensitive keys if configured.
6. Enforce max_state_bytes.
7. Derive message_count/current_step/checkpoint_name.
8. Calculate state_hash.
9. Open SQLite connection.
10. Begin transaction.
11. Upsert workflow_sessions row.
12. Upsert workflow_state_current row.
13. Increment state_version.
14. Commit.
15. Emit safe metrics/trace events.
```

### 23.1 Save SQL Pattern

SQLite upsert pattern:

```sql
INSERT INTO workflow_sessions (
    session_id,
    user_id,
    user_id_hash,
    usecase,
    status,
    created_at,
    updated_at,
    last_activity_at,
    metadata_json
)
VALUES (?, ?, ?, ?, 'active', ?, ?, ?, ?)
ON CONFLICT(session_id) DO UPDATE SET
    user_id = COALESCE(excluded.user_id, workflow_sessions.user_id),
    user_id_hash = COALESCE(excluded.user_id_hash, workflow_sessions.user_id_hash),
    usecase = COALESCE(excluded.usecase, workflow_sessions.usecase),
    status = 'active',
    updated_at = excluded.updated_at,
    last_activity_at = excluded.last_activity_at,
    metadata_json = excluded.metadata_json;
```

```sql
INSERT INTO workflow_state_current (
    session_id,
    state_version,
    state_json,
    state_hash,
    state_size_bytes,
    message_count,
    current_step,
    checkpoint_name,
    created_at,
    updated_at,
    reset_generation
)
VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?, 0)
ON CONFLICT(session_id) DO UPDATE SET
    state_version = workflow_state_current.state_version + 1,
    state_json = excluded.state_json,
    state_hash = excluded.state_hash,
    state_size_bytes = excluded.state_size_bytes,
    message_count = excluded.message_count,
    current_step = excluded.current_step,
    checkpoint_name = excluded.checkpoint_name,
    updated_at = excluded.updated_at;
```

### 23.2 Save Payload Rule

Do not log or trace `state_json`.

Safe trace payload example:

```json
{
  "provider": "sqlite",
  "operation": "save",
  "state_keys_count": 5,
  "history_message_count": 8,
  "state_size_bytes": 28400,
  "state_version": 4,
  "duration_ms": 12,
  "success": true
}
```

---

## 24. Reset Behavior

Session reset clears short-term workflow state only.

Recommended `reset` flow:

```text
1. Validate session_id.
2. Open SQLite connection.
3. Begin transaction.
4. Ensure workflow_sessions row exists.
5. Read current state_version/reset_generation if present.
6. Increment reset_count on workflow_sessions.
7. Insert workflow_state_resets row.
8. Either replace current state with empty state or delete current state row based on reset_mode.
9. Commit.
10. Emit workflow_state_reset event and metric.
```

### 24.1 Recommended Reset Mode

Recommended V1 default:

```yaml
reset_mode: replace_with_empty_state
```

This preserves a current row and makes health/debug behavior simpler.

### 24.2 Reset SQL Pattern

```sql
UPDATE workflow_sessions
SET
    status = 'active',
    reset_count = reset_count + 1,
    updated_at = ?,
    last_activity_at = ?
WHERE session_id = ?;
```

```sql
INSERT INTO workflow_state_resets (
    reset_id,
    session_id,
    trace_id,
    reason,
    reset_generation,
    cleared_state_version,
    reset_at
)
VALUES (?, ?, ?, ?, ?, ?, ?);
```

For `replace_with_empty_state`:

```sql
INSERT INTO workflow_state_current (
    session_id,
    state_version,
    state_json,
    state_hash,
    state_size_bytes,
    message_count,
    current_step,
    checkpoint_name,
    created_at,
    updated_at,
    reset_generation
)
VALUES (?, 1, ?, ?, ?, 0, NULL, NULL, ?, ?, ?)
ON CONFLICT(session_id) DO UPDATE SET
    state_version = workflow_state_current.state_version + 1,
    state_json = excluded.state_json,
    state_hash = excluded.state_hash,
    state_size_bytes = excluded.state_size_bytes,
    message_count = 0,
    current_step = NULL,
    checkpoint_name = NULL,
    updated_at = excluded.updated_at,
    reset_generation = excluded.reset_generation;
```

For `delete_state_row`:

```sql
DELETE FROM workflow_state_current
WHERE session_id = ?;
```

### 24.3 Reset Must Not Touch

Reset must not delete or modify:

```text
memory_store records
ArcadeDB document chunks
trace.db rows
LLM provider/profile config
MCP tool config
policy config
other sessions
```

---

## 25. Optimistic Concurrency

V1 may start with last-write-wins, but the schema should support conflict detection.

### 25.1 Recommended V1 Behavior

Default behavior:

```text
save without expected version -> last write wins, state_version increments
save with expected version    -> compare-and-set if present in metadata
```

Optional internal metadata:

```json
{
  "metadata": {
    "_expected_state_version": 3
  }
}
```

If `_expected_state_version` is present, the adapter may use:

```sql
UPDATE workflow_state_current
SET
    state_version = state_version + 1,
    state_json = ?,
    state_hash = ?,
    state_size_bytes = ?,
    message_count = ?,
    current_step = ?,
    checkpoint_name = ?,
    updated_at = ?
WHERE session_id = ?
  AND state_version = ?;
```

If zero rows are updated, raise a known conflict error such as `WorkflowStateConflictError`.

### 25.2 Conflict Policy

Early walking skeleton may tolerate last-write-wins. When streaming, multi-tab UI, or long tool calls are added, the session-service architecture should decide whether conflict errors are retried, merged, or returned to the client.

---

## 26. Serialization and Validation

Workflow state must be JSON-safe.

Allowed values:

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
def dumps_state_json(state: dict[str, Any]) -> str:
    safe = to_json_safe(state)
    return json.dumps(safe, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
```

### 26.2 Size Limit

Enforce configured max size:

```yaml
max_state_bytes: 1048576
```

If exceeded, raise `WorkflowStateSizeError` with safe metadata:

```json
{
  "operation": "save",
  "state_size_bytes": 1500000,
  "max_state_bytes": 1048576
}
```

Do not include the state payload in the error.

---

## 27. Sensitive Data Handling

The adapter should defend against obvious sensitive fields.

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

### 27.1 Reject vs Redact

Recommended V1 behavior:

| Situation | Behavior |
|---|---|
| Sensitive key appears in state metadata | Redact or reject based on strictness setting. |
| Raw authorization header appears anywhere | Reject save by default. |
| API key/provider credential appears anywhere | Reject save by default. |
| Tool result contains unknown payload | Store summary only; detailed tool result persistence belongs to session/orchestration policy. |

### 27.2 Adapter Responsibility

The adapter should not be the only privacy boundary. The session service and orchestration runtime should avoid putting sensitive payloads into workflow state in the first place.

The adapter is the final safety net.

---

## 28. Derived Metadata

The store should derive safe metadata from the state document.

### 28.1 Message Count

```python
def extract_message_count(state: dict[str, object]) -> int:
    conversation = state.get("conversation")
    if not isinstance(conversation, dict):
        return 0
    messages = conversation.get("messages")
    if not isinstance(messages, list):
        return 0
    return len(messages)
```

### 28.2 Current Step

```python
def extract_current_step(state: dict[str, object]) -> str | None:
    workflow = state.get("workflow")
    if not isinstance(workflow, dict):
        return None
    value = workflow.get("current_step")
    return value if isinstance(value, str) else None
```

### 28.3 Checkpoint Name

```python
def extract_checkpoint_name(state: dict[str, object]) -> str | None:
    workflow = state.get("workflow")
    if not isinstance(workflow, dict):
        return None
    checkpoint = workflow.get("checkpoint")
    if not isinstance(checkpoint, dict):
        return None
    value = checkpoint.get("name")
    return value if isinstance(value, str) else None
```

Derived metadata allows health and cleanup without reading and parsing every state document.

---

## 29. Session ID Validation

Session IDs must be safe before they are used in SQL or logs.

Recommended validation:

```python
import re

_SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{3,128}$")


def validate_session_id(session_id: str) -> None:
    if not _SESSION_ID_PATTERN.fullmatch(session_id):
        raise WorkflowStateError(
            message="Invalid session_id.",
            retryable=False,
            details={"reason": "invalid_identifier"},
        )
```

Even with validation, SQL must still be parameterized.

---

## 30. Transaction Model

### 30.1 Load Transaction

A load is one consistent read.

```text
BEGIN read transaction optional
SELECT current state
COMMIT optional
```

For V1, a single `SELECT` without an explicit transaction is acceptable.

### 30.2 Save Transaction

A save must be atomic.

```text
BEGIN IMMEDIATE
UPSERT workflow_sessions
UPSERT workflow_state_current
COMMIT
```

If any step fails, roll back.

### 30.3 Reset Transaction

A reset must be atomic.

```text
BEGIN IMMEDIATE
UPSERT/UPDATE workflow_sessions
INSERT workflow_state_resets
REPLACE or DELETE workflow_state_current
COMMIT
```

If any step fails, roll back.

### 30.4 Cross-Store Rule

Do not attempt a distributed transaction between:

```text
workflow_state.db
trace.db
memory_store/ArcadeDB
```

A workflow-state save should not roll back a memory update or trace event unless a future architecture explicitly adds an outbox/transaction pattern.

---

## 31. Error Model

SQLite exceptions should be wrapped in known backend errors.

Recommended error types:

```text
WorkflowStateError
WorkflowStateUnavailableError
WorkflowStateSerializationError
WorkflowStateSizeError
WorkflowStateConflictError
WorkflowStateConfigurationError
WorkflowStateMigrationError
```

### 31.1 Error Wrapper Example

```python
try:
    ...
except sqlite3.OperationalError as exc:
    raise WorkflowStateUnavailableError(
        message="Workflow state store is unavailable.",
        retryable=True,
        details={
            "operation": "save",
            "provider": "sqlite",
        },
    ) from exc
```

### 31.2 Error Safety Rule

Errors must not include:

- Raw SQL.
- Full state documents.
- Credentials.
- Connection strings.
- Authorization headers.
- Raw provider responses.
- Full stack traces in API responses or health output.

Stack traces may be logged only when debug settings permit them and after redaction.

---

## 32. Observability Integration

The store should integrate with the observability foundation without coupling to API/session internals.

### 32.1 Recommended Trace Events

| Operation | Event |
|---|---|
| Load existing state | `workflow_state_loaded` |
| Load missing state | `workflow_state_loaded` with `found: false` |
| Save state | `workflow_state_saved` |
| Reset state | `workflow_state_reset` |
| Store error | `error_occurred` |

### 32.2 Safe Payloads

Load event:

```json
{
  "provider": "sqlite",
  "operation": "load",
  "found": true,
  "state_version": 3,
  "history_message_count": 8,
  "duration_ms": 5,
  "success": true
}
```

Save event:

```json
{
  "provider": "sqlite",
  "operation": "save",
  "state_version": 4,
  "state_size_bytes": 18420,
  "history_message_count": 9,
  "duration_ms": 12,
  "success": true
}
```

Reset event:

```json
{
  "provider": "sqlite",
  "operation": "reset",
  "reset_generation": 2,
  "cleared_state_version": 4,
  "duration_ms": 8,
  "success": true
}
```

### 32.3 Metrics

Recommended metrics:

```text
backend.state.load.total
backend.state.load.duration_ms
backend.state.load.miss_total
backend.state.save.total
backend.state.save.duration_ms
backend.state.save.bytes
backend.state.reset.total
backend.state.reset.duration_ms
backend.state.errors
backend.state.conflicts
```

Allowed metric tags:

```text
operation
provider
success
error_type
```

Avoid metric tags:

```text
session_id
trace_id
raw_user_id
message text
state hash
```

---

## 33. Health Check

The store must expose a safe health check.

Recommended behavior:

```text
1. Verify configured path exists or parent directory is creatable.
2. Open SQLite connection.
3. Apply pragmas.
4. Verify schema_version row.
5. Optionally run SELECT 1.
6. Return safe status.
```

### 33.1 Health Output

Example:

```json
{
  "status": "ok",
  "provider": "sqlite",
  "configured": true,
  "schema_initialized": true,
  "schema_version": 1,
  "journal_mode": "wal",
  "required": true
}
```

### 33.2 Health Must Not Include

- Full database path if it may reveal sensitive deployment layout.
- Raw workflow state.
- Raw SQL.
- Connection strings.
- Stack traces.
- User IDs.
- Session IDs.
- State hashes.

For local debug mode, the health aggregator may include a redacted or basename-only path such as `workflow_state.db`.

---

## 34. Startup Integration

Recommended startup sequence:

```text
1. Load configuration.
2. Build observability/redactor/metrics.
3. Resolve persistence settings.
4. Resolve workflow_state.db path.
5. Create parent directories if configured.
6. Build SqliteWorkflowStateStore.
7. Initialize schema if configured.
8. Validate schema version.
9. Register workflow_state health check.
10. Log redacted startup summary.
```

### 34.1 Startup Failure Behavior

| Setting | Behavior |
|---|---|
| `required: true` | Fail startup if database cannot initialize or validate. |
| `required: false` | Mark health as degraded and allow startup for local/prototype mode. |

Recommended V1 value:

```yaml
required: true
```

because session continuity depends on workflow state.

---

## 35. Session Service Integration

The session service will use the store as its short-term state backend.

Expected future flow:

```text
POST /chat
  -> API resolves or creates session_id
  -> SessionService.load_state(session_id)
  -> WorkflowStateStore.load(session_id)
  -> OrchestrationRuntime.run(request_context, state)
  -> SessionService.prepare_next_state(...)
  -> WorkflowStateStore.save(session_id, next_state)
  -> API returns response
```

### 35.1 Reset Flow

```text
POST /sessions/{session_id}/reset
  -> API validates session_id
  -> SessionService.reset(session_id)
  -> WorkflowStateStore.reset(session_id)
  -> API returns reset confirmation
```

The session service may also emit session lifecycle events such as:

```text
session_created
session_resumed
session_reset
```

The workflow store should remain focused on state persistence events.

---

## 36. Orchestration Integration

The orchestration runtime receives loaded state and may return updated state metadata through the session service.

Recommended pattern:

```text
SessionService owns load/save timing.
OrchestrationRuntime receives current state as input.
Agents may read/write state through context only if explicitly exposed.
SqliteWorkflowStateStore does not call agents or strategies.
```

### 36.1 State Update Ownership

In V1, prefer this ownership:

| Concern | Owner |
|---|---|
| Load state | Session service |
| Build `RequestContext` | Session service/API boundary |
| Build `OrchestrationContext` | Orchestration runtime |
| Decide workflow transitions | Orchestration runtime/strategy |
| Produce next state | Session service + orchestration result |
| Persist next state | Session service through `WorkflowStateStore` |
| Reset state | Session service through `WorkflowStateStore` |

---

## 37. Streaming Considerations

Streaming routes should avoid saving workflow state for every token or chunk.

Recommended pattern:

```text
stream_started
  -> load state once
  -> run orchestration streaming
  -> accumulate final response metadata
stream_completed
  -> save final state once
stream_cancelled
  -> save cancellation metadata only if useful
stream_failed
  -> save failure checkpoint only if safe
```

### 37.1 Streaming State Rule

Do not write one SQLite transaction per streamed token.

Persist final state at completion, cancellation, or meaningful checkpoint boundaries only.

---

## 38. Cleanup and Retention

V1 does not require complex retention, but the schema should support future cleanup.

### 38.1 Optional Cleanup Inputs

Useful columns:

```text
workflow_sessions.last_activity_at
workflow_sessions.status
workflow_state_current.updated_at
workflow_state_resets.reset_at
```

### 38.2 Future Cleanup Policy

Potential future configuration:

```yaml
persistence:
  workflow_state:
    cleanup:
      enabled: true
      expire_inactive_sessions_days: 30
      keep_reset_records_days: 30
```

Do not implement automatic destructive cleanup unless a policy/deployment document defines it.

---

## 39. Privacy and Data Minimization

Workflow state may contain conversation history. This requires careful minimization.

### 39.1 Minimization Rules

- Store only the conversation history needed for session continuity.
- Cap stored message count through `max_history_messages` or session-service policy.
- Store tool result summaries instead of full downstream responses.
- Store pending approval metadata without secrets.
- Avoid storing raw provider request/response objects.
- Do not promote workflow state to long-term memory without explicit memory policy.

### 39.2 Deletion Boundaries

| Operation | Store Impact |
|---|---|
| Session reset | Clears workflow state only. |
| Memory forget | Clears memory only through `MemoryGateway`. |
| Trace retention cleanup | Clears trace events only through `TraceStore` future policy. |
| Delete session | May remove workflow state for that session only. |

---

## 40. Fake Store Compatibility

The fake store should match the real contract, not the real schema.

```python
class FakeWorkflowStateStore:
    def __init__(self) -> None:
        self._states: dict[str, dict[str, object]] = {}

    async def load(self, *, session_id: str) -> dict[str, object]:
        return dict(self._states.get(session_id, default_workflow_state(session_id)))

    async def save(self, *, session_id: str, state: dict[str, object]) -> None:
        self._states[session_id] = dict(state)

    async def reset(self, *, session_id: str) -> None:
        self._states[session_id] = default_workflow_state(session_id)

    async def health(self) -> dict[str, object]:
        return {"status": "ok", "provider": "fake"}
```

### 40.1 Fake Store Rule

Higher-level tests should assert behavior, not SQLite implementation details.

Use fake store tests for:

```text
Session service
Orchestration runtime
Strategies
Agents
API route unit tests
```

Use SQLite integration tests only for the adapter itself.

---

## 41. Recommended Implementation Order

### Step 1: Add Settings

Deliverables:

- `SqliteWorkflowStateSettings`
- Config mapping from YAML
- Validation for path, max size, reset mode, required flag

Success criteria:

- Config can select SQLite workflow state.
- Invalid reset mode fails fast.

### Step 2: Add Schema Module

Deliverables:

- `sqlite_workflow_state_schema.py`
- DDL constants
- Schema version constants
- Initialization function

Success criteria:

- Schema initializes idempotently.
- Schema version row is present.

### Step 3: Add SQLite Connection Helpers

Deliverables:

- Path resolution
- Parent directory creation
- Pragma application
- Transaction helper

Success criteria:

- Temporary test databases can be created safely.
- WAL/busy timeout/foreign keys can be configured.

### Step 4: Implement Load

Deliverables:

- `SqliteWorkflowStateStore.load`
- Missing-state default behavior
- JSON decode handling
- Unit/integration tests

Success criteria:

- Existing state loads.
- Missing state returns default empty state.
- Corrupt JSON raises a known error.

### Step 5: Implement Save

Deliverables:

- `SqliteWorkflowStateStore.save`
- JSON-safe serialization
- Size validation
- Session/state upserts
- State hash and metadata extraction

Success criteria:

- State is saved atomically.
- State can be loaded after save.
- Version increments on repeated save.

### Step 6: Implement Reset

Deliverables:

- `SqliteWorkflowStateStore.reset`
- Reset record insert
- Empty state replacement or row deletion per config
- Tests proving memory/trace are untouched by reset boundaries

Success criteria:

- Reset clears workflow state.
- Load after reset returns empty state.
- Reset metadata is recorded safely.

### Step 7: Add Health Check

Deliverables:

- `health` method
- Schema validation
- Safe output

Success criteria:

- Healthy DB returns `ok`.
- Missing schema returns degraded/error depending on required behavior.
- Health does not expose state content.

### Step 8: Add Observability Hooks

Deliverables:

- Safe logs for load/save/reset failures
- Metrics for load/save/reset duration
- Optional trace recorder calls from session or store boundary

Success criteria:

- Persistence operations are diagnosable without leaking state payloads.

### Step 9: Add Integration Tests

Deliverables:

- Smoke test for fresh DB
- Re-open existing DB test
- Save/load/reset test
- Size-limit test
- Conflict test if optimistic metadata is implemented

Success criteria:

- Adapter works with temporary SQLite files.
- Tests do not write to project `./data`.

### Step 10: Update Composition Root

Deliverables:

- `build_workflow_state_store(settings)`
- Health registration
- Redacted startup summary update

Success criteria:

- Backend can start with SQLite workflow state configured.
- The next API/session walking skeleton can use the real store.

---

## 42. Testing Strategy

### 42.1 Unit Tests

| Test | Purpose |
|---|---|
| Settings parse valid config | Proves configuration mapping. |
| Invalid reset mode fails | Prevents undefined reset behavior. |
| Path resolution uses temp dir | Prevents writing to real data files. |
| Schema DDL contains required tables | Prevents accidental table removal. |
| Schema initialization is idempotent | Allows repeated startup. |
| Default empty state shape is stable | Supports session-service expectations. |
| Session ID validation rejects unsafe IDs | Prevents unsafe identifiers. |
| Serialization converts datetimes/enums | Prevents JSON failures. |
| Size limit rejects oversized state | Prevents unbounded state growth. |
| Sensitive key handling rejects/redacts | Prevents credential persistence. |
| Metadata extraction counts messages | Supports diagnostics. |
| Fake store load/save/reset | Supports higher-level tests. |

### 42.2 Integration Tests

| Test | Purpose |
|---|---|
| Fresh SQLite DB initializes | Proves schema bootstrap. |
| Re-open existing DB succeeds | Proves idempotent startup. |
| Save then load returns equivalent state | Proves core persistence path. |
| Load missing session returns empty state | Proves contract behavior. |
| Repeated save increments state version | Proves version metadata. |
| Reset clears state | Proves reset behavior. |
| Reset records metadata only | Prevents cleared-state archival. |
| Health returns safe status | Proves health behavior. |
| Required DB failure fails startup path | Proves required-store behavior. |
| Concurrent saves do not corrupt DB | Proves WAL/busy timeout baseline. |

### 42.3 Fixture Configs

Recommended fixtures:

```text
tests/fixtures/config/workflow_state_sqlite.yaml
tests/fixtures/config/workflow_state_sqlite_no_schema_init.yaml
tests/fixtures/config/workflow_state_sqlite_delete_reset.yaml
tests/fixtures/config/workflow_state_sqlite_small_max_size.yaml
tests/fixtures/config/workflow_state_fake.yaml
```

---

## 43. Acceptance Criteria

This architecture is complete when:

- `SqliteWorkflowStateStore` implements `WorkflowStateStore`.
- `load`, `save`, `reset`, and `health` are available.
- SQLite details are isolated to the persistence adapter and SQLite helper modules.
- API, session, orchestration, strategies, agents, LLM gateway, and tool gateway do not import SQLite.
- The workflow state database path is configurable.
- Parent directory creation is configuration-controlled.
- SQLite pragmas are applied from configuration.
- Schema initialization is idempotent.
- Schema version is recorded and validated.
- `load` returns default empty state when no session state exists.
- `save` persists JSON-safe state atomically.
- `save` enforces max state size.
- `save` does not log or trace raw state content.
- `reset` clears short-term workflow state only.
- `reset` does not delete memory, document chunks, traces, LLM config, MCP config, or policy config.
- Reset metadata is recorded without storing cleared state payloads.
- State rows include version, hash, size, message count, timestamps, and reset generation.
- Health checks verify SQLite reachability and schema readiness.
- Health responses do not expose raw state, user IDs, session IDs, SQL, connection strings, or stack traces.
- Store errors are wrapped in known backend errors.
- Observability emits safe load/save/reset summaries and metrics.
- Tests cover fresh DB initialization, re-opening existing DB, save/load/reset, missing session load, size limits, and health.
- The backend is ready for the next document: `backend-sqlite-trace-store-architecture.md`.

---

## 44. Anti-Patterns to Avoid

Avoid these during implementation:

- Letting API routes run SQL.
- Letting session service know table names.
- Letting orchestration code know SQLite row shapes.
- Letting agents read or write SQLite directly.
- Storing long-term memories in workflow state.
- Storing document chunks in workflow state.
- Storing trace events in workflow state.
- Deleting memory during session reset.
- Deleting traces during session reset.
- Logging full `state_json`.
- Returning state payloads from `/health`.
- Storing raw authorization headers.
- Storing API keys or provider credentials.
- Saving full provider SDK response objects.
- Writing state on every streamed token.
- Creating broad indexes before access patterns exist.
- Using string interpolation for SQL parameters.
- Silently ignoring SQLite initialization failure when store is required.
- Making tests depend on real local `./data/workflow_state.db`.

---

## 45. Future Documents That Depend on This Store

| Future Document | Dependency |
|---|---|
| `backend-sqlite-trace-store-architecture.md` | Shares SQLite helper patterns, schema versioning, path handling, and health conventions. |
| `backend-api-architecture.md` | Uses workflow state reset behavior and request/session persistence flow. |
| `backend-session-service-architecture.md` | Deepens session lifecycle, state shaping, history management, and reset semantics. |
| `backend-llm-gateway-architecture.md` | Avoids raw prompt/completion persistence and uses state only through session/orchestration flow. |
| `backend-memory-store-adapter-architecture.md` | Preserves separation between workflow state and long-term memory. |
| `backend-tooling-mcp-client-architecture.md` | Uses workflow state for safe pending tool context and approval metadata. |
| `backend-orchestration-architecture.md` | Uses loaded state to build orchestration context and produce next state. |
| `backend-workflow-strategies-architecture.md` | Uses checkpoints/current step fields for direct/router/sequential strategies. |
| `backend-agents-architecture.md` | Uses workflow state only through context/session abstractions. |
| `backend-policy-architecture.md` | Defines whether raw messages, summaries, or tool result metadata may be persisted. |
| `backend-deployment-architecture.md` | Defines volume mapping, backups, data paths, and retention/cleanup. |

---

## 46. Summary

`SqliteWorkflowStateStore` is the first concrete state persistence implementation for the backend walking skeleton.

It stores session-scoped workflow state in `workflow_state.db`, keeps SQLite isolated behind the `WorkflowStateStore` contract, supports atomic load/save/reset behavior, and preserves the separation between short-term state, long-term memory, and operational traces.

The most important implementation rule is:

> **Workflow state is session continuity data. It must be persisted through `WorkflowStateStore`, isolated behind SQLite adapter boundaries, and reset without touching memory, traces, tools, LLM configuration, or policy configuration.**
