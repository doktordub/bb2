# Backend Session Service Architecture

**Document:** `backend-session-service-architecture.md`  
**Generated file:** `backend-session-service-architecture.md.md`  
**Version:** 1.0  
**Source alignment:** `backend-application-architecture.md`, `backend-foundation-architecture.md`, `backend-core-contracts-architecture.md`, `backend-configuration-architecture.md`, `backend-observability-architecture.md`, `backend-persistence-architecture.md`, `backend-sqlite-workflow-state-architecture.md`, `backend-sqlite-trace-store-architecture.md`, and `backend-api-architecture.md`  
**Scope:** Session lifecycle, session identity, chat request handoff, workflow-state load/save/reset, streaming finalization, safe history shaping, session concurrency, request-to-orchestration context mapping, trace correlation, API integration, testing strategy, and acceptance criteria for the V1 `SessionService` layer.

---

## 1. Purpose

This document defines the ninth implementation-focused architecture document for the backend application tier.

It follows:

1. `backend-foundation-architecture.md`
2. `backend-core-contracts-architecture.md`
3. `backend-configuration-architecture.md`
4. `backend-observability-architecture.md`
5. `backend-persistence-architecture.md`
6. `backend-sqlite-workflow-state-architecture.md`
7. `backend-sqlite-trace-store-architecture.md`
8. `backend-api-architecture.md`
9. `backend-session-service-architecture.md` ← this document

The previous document defined the backend HTTP/SSE boundary and established the rule that API routes validate requests, create request context, call `SessionService`, and return safe responses. This document deepens that session layer.

The goal is to define the service that bridges the API boundary and orchestration runtime while preserving the core backend architecture rule:

> `SessionService` owns session creation, resume, reset, workflow-state handoff, safe history shaping, and streaming finalization. It must not become the orchestrator, LLM router, memory gateway, tool gateway, or policy engine.

---

## 2. Source Architecture Alignment

This document follows the established backend rules:

- The backend is one deployable application tier in V1.
- Frontend communicates with backend through REST / SSE.
- API routes are thin and delegate chat/reset behavior to `SessionService`.
- Session service is the bridge between API requests and orchestration.
- Session service creates or resumes sessions.
- Session service loads and saves short-term workflow state through `WorkflowStateStore`.
- Session service calls `OrchestrationRuntime` through a narrow interface.
- Session service passes stable request metadata into `RequestContext`.
- Session service maps orchestration results into session-level results for API response mapping.
- Session reset clears short-term workflow state only.
- Session reset must not delete long-term memory, document chunks, trace records, LLM configuration, MCP configuration, policy configuration, or other sessions.
- Workflow state remains short-term runtime state.
- Long-term memory and document chunks remain behind `MemoryGateway`.
- Traces remain operational diagnostics behind `TraceStore` and observability helpers.
- Session service must not import SQLite, ArcadeDB clients, provider SDKs, MCP clients, or `memory_store.service.MemoryService`.
- Session service must not select concrete LLM providers, call LLM endpoints, call MCP tools, or directly search/upsert memory.

---

## 3. Position in the Backend Implementation Sequence

The backend implementation sequence is now:

```text
Phase 1: Backend Foundation Skeleton
Phase 2: Core Contracts
Phase 3: Configuration Loader
Phase 4: Observability and Trace Foundation
Phase 5: Persistence Boundary and Store Foundations
Phase 6: SQLite Workflow State Store
Phase 7: SQLite Trace Store
Phase 8: API and Session Walking Skeleton
Phase 9: Session Service Deepening
Phase 10: LLM Gateway
Phase 11: Memory Gateway
Phase 12: Tool Gateway and MCP Client Adapter
Phase 13: Orchestration Runtime and Strategies
Phase 14: Agent Plugins
Phase 15: Hardening and Deployment Readiness
```

This document expands Phase 9.

The output of this phase is a real `SessionService` layer that supports the API routes defined previously:

```text
POST /chat
POST /chat/stream
POST /sessions/{session_id}/reset
GET  /sessions/{session_id}/history optional
```

The next document should be:

```text
backend-llm-gateway-architecture.md
```

---

## 4. Architecture Goals

The session service should be:

1. **Lifecycle-aware**  
   It creates, resumes, validates, resets, and optionally summarizes sessions.

2. **State-safe**  
   It loads workflow state once at request start and saves state at stable completion boundaries.

3. **API-neutral**  
   It receives API request context but does not depend on HTTP framework objects, route handlers, or response classes.

4. **Orchestration-facing**  
   It builds `RequestContext`, hands workflow state to `OrchestrationRuntime`, and normalizes results.

5. **Streaming-capable**  
   It supports streaming events while avoiding workflow-state writes on every token.

6. **Trace-correlated**  
   It passes `trace_id`, `session_id`, and safe lifecycle metadata through all downstream calls.

7. **Reset-safe**  
   It clears only short-term workflow state and preserves memory, traces, configuration, and other sessions.

8. **Concurrency-aware**  
   It handles overlapping requests for the same session predictably through store versioning or service-level conflict policy.

9. **History-safe**  
   It can expose bounded, normalized conversation history without leaking raw workflow state, hidden scratchpads, tool payloads, provider payloads, or secrets.

10. **Testable**  
    It can be tested with fake workflow state, fake orchestration runtime, fake trace recorder, and fake clock/ID providers.

---

## 5. Non-Goals

This document should not implement:

- Real LLM provider integration.
- Real memory search or memory writes.
- Real MCP tool calls.
- Agent plugin internals.
- Full orchestration strategy behavior.
- Final authentication and authorization model.
- Multi-tenant access-control model.
- Long-term memory deletion workflows.
- Document chunk deletion workflows.
- Trace query/debug routes.
- Raw prompt/completion archival.
- Production distributed locking.
- Multi-writer cluster coordination.
- Complex event sourcing.
- Frontend UI behavior.
- MCP server implementation.

Those concerns belong to later LLM, memory, tooling/MCP, orchestration, agents, policy, and deployment documents.

---

## 6. Session Service Boundary

The session service sits between the API layer and orchestration runtime.

It owns:

- Session ID normalization and generation.
- Session creation and resume decisions.
- Workflow-state load/save/reset calls.
- Mapping API request DTOs into core `RequestContext`.
- Attaching `trace_id`, `request_id`, user identity, and client metadata to the request context.
- Calling `OrchestrationRuntime` or temporary walking-skeleton orchestrator.
- Normalizing orchestration results into `SessionChatResult`.
- Converting orchestration stream events into `SessionStreamEvent` objects.
- Save-on-completion behavior for non-streaming chat.
- Save-on-finalization behavior for streaming chat.
- Session reset semantics.
- Optional bounded safe history shaping.
- Session-level conflict handling.
- Safe session lifecycle trace events.

It does not own:

- HTTP request parsing.
- HTTP response formatting.
- SSE wire formatting.
- Agent selection policy internals.
- LLM profile resolution.
- LLM provider calls.
- Memory search/upsert behavior.
- MCP tool invocation.
- SQLite SQL implementation.
- ArcadeDB access.
- Trace-store SQL implementation.
- Tool allowlist decisions.
- Long-term memory lifecycle.

### 6.1 Boundary Diagram

```text
Frontend
  -> Backend API routes
      -> SessionService
          -> SessionIdProvider
          -> WorkflowStateStore
          -> OrchestrationRuntime
              -> LLMGateway
              -> MemoryGateway
              -> ToolGateway
              -> PolicyService
              -> TraceStore
          -> ObservabilityRecorder / Trace facade
```

### 6.2 Practical Rule

Session service should do this:

```python
state = await workflow_state.load(session_id=session_id)
request_context = build_request_context(chat_request, api_context, session_id)
result = await orchestrator.run(request=request_context, state=state)
await workflow_state.save(session_id=session_id, state=state_from_result(result))
return SessionChatResult.from_orchestration(result)
```

Session service should not do this:

```python
llm_response = await openai_client.chat.completions.create(...)
memories = await arcade_client.query("select from Memory")
await mcp_client.call_tool("tool.name", payload)
conn.execute("select state_json from workflow_state_current where session_id = ?", ...)
```

---

## 7. Recommended Package Layout

Recommended implementation layout:

```text
backend/
  app/
    session/
      __init__.py
      service.py
      models.py
      lifecycle.py
      identifiers.py
      history.py
      concurrency.py
      mapping.py
      streaming.py
      errors.py
      settings.py

    orchestration/
      core.py
      context.py
      results.py
      events.py

    persistence/
      workflow_state_store.py
      models.py

    observability/
      trace_context.py
      events.py
      redaction.py
      recorder.py

    api/
      routes_chat.py
      routes_sessions.py
      schemas.py
      dependencies.py

    testing/
      fakes/
        fake_session_service.py
        fake_workflow_state_store.py
        fake_orchestration_runtime.py
        fake_session_id_provider.py
        fake_trace_recorder.py
        fake_clock.py

  tests/
    unit/
      session/
        test_session_id_provider.py
        test_session_request_mapping.py
        test_session_handle_chat.py
        test_session_stream_chat.py
        test_session_reset.py
        test_session_history.py
        test_session_concurrency.py
        test_session_error_mapping.py
        test_session_trace_events.py

    integration/
      session/
        test_session_with_sqlite_workflow_state_store.py
        test_session_with_api_chat_route.py
        test_session_streaming_finalization.py
        test_session_reset_clears_workflow_state_only.py
```

### 7.1 Module Responsibilities

| Module | Responsibility |
|---|---|
| `service.py` | Main `SessionService` implementation and public methods. |
| `models.py` | Session request/result/event models. |
| `lifecycle.py` | Create/resume/reset lifecycle helpers. |
| `identifiers.py` | Session ID generation, validation, and normalization. |
| `history.py` | Safe history projection from workflow state. |
| `concurrency.py` | Session conflict policy and optimistic version helpers. |
| `mapping.py` | API request context to core `RequestContext` mapping. |
| `streaming.py` | Stream event normalization and finalization helpers. |
| `errors.py` | Session-specific error taxonomy. |
| `settings.py` | Session service settings. |

---

## 8. Dependency Direction Rules

Allowed:

```text
app/session/* -> app/contracts/*
app/session/* -> app/orchestration/core.py
app/session/* -> app/orchestration/context.py
app/session/* -> app/orchestration/results.py
app/session/* -> app/persistence/workflow_state_store.py
app/session/* -> app/observability/recorder.py
app/session/* -> app/observability/events.py
app/session/* -> app/config/settings.py
```

Optional through narrow abstractions:

```text
app/session/* -> Clock
app/session/* -> IdProvider
app/session/* -> Redactor
app/session/* -> SessionPolicy facade, once policy exists
```

Avoid:

```text
app/session/* -> fastapi.Request
app/session/* -> fastapi.Response
app/session/* -> app/api/routes_*.py
app/session/* -> sqlite3
app/session/* -> ArcadeDB clients
app/session/* -> memory_store.service.MemoryService
app/session/* -> OpenAI / Google / provider SDKs
app/session/* -> raw HTTP LLM clients
app/session/* -> MCP client implementation
app/session/* -> AgentPlugin concrete classes
app/session/* -> OrchestrationStrategy concrete classes
```

### 8.1 Dependency Rule by Method

| Method | Calls | Must Not Call |
|---|---|---|
| `handle_chat` | `WorkflowStateStore`, `OrchestrationRuntime`, trace recorder | LLM providers, memory, MCP, SQL |
| `stream_chat` | `WorkflowStateStore`, streaming orchestrator, trace recorder | Provider stream objects directly, per-token state writes |
| `reset_session` | `WorkflowStateStore.reset`, trace recorder | Memory delete, trace delete, config mutation |
| `get_history` | `WorkflowStateStore.load` or history facade | Raw workflow state exposure, SQL directly |
| `get_session_status` optional | `WorkflowStateStore.metadata` or service registry | Memory/LLM/MCP details directly |

---

## 9. Session Configuration Integration

Recommended YAML:

```yaml
session:
  enabled: true

  identifiers:
    prefix: session
    accept_client_session_id: true
    generate_when_missing: true
    max_length: 128
    allowed_pattern: "^[A-Za-z0-9_.:-]{3,128}$"

  defaults:
    default_user_id: local_user
    default_usecase: default
    default_history_limit: 50
    max_history_limit: 200
    timezone_metadata_key: timezone

  lifecycle:
    create_on_first_chat: true
    resume_existing_sessions: true
    reject_unknown_client_session_id: false
    update_last_seen_on_load: true
    save_after_failed_orchestration: true
    save_after_cancelled_stream: true

  concurrency:
    mode: optimistic_version
    conflict_policy: reject
    max_retries: 1

  state:
    save_on_chat_completion: true
    save_on_stream_completion: true
    save_on_stream_cancellation: true
    save_on_stream_failure: true
    save_each_stream_delta: false

  history:
    enabled: false
    include_tool_summaries: false
    include_system_messages: false
    include_metadata: true
    max_message_chars: 4000
    redaction_enabled: true

  tracing:
    record_session_created: true
    record_session_resumed: true
    record_session_reset: true
    record_state_loaded: true
    record_state_saved: true
    record_history_returned: true
    record_stream_lifecycle: true
```

### 9.1 Settings Object

Recommended typed settings:

```python
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SessionIdentifierSettings:
    prefix: str
    accept_client_session_id: bool
    generate_when_missing: bool
    max_length: int
    allowed_pattern: str


@dataclass(frozen=True, slots=True)
class SessionDefaultsSettings:
    default_user_id: str
    default_usecase: str
    default_history_limit: int
    max_history_limit: int
    timezone_metadata_key: str


@dataclass(frozen=True, slots=True)
class SessionLifecycleSettings:
    create_on_first_chat: bool
    resume_existing_sessions: bool
    reject_unknown_client_session_id: bool
    update_last_seen_on_load: bool
    save_after_failed_orchestration: bool
    save_after_cancelled_stream: bool


@dataclass(frozen=True, slots=True)
class SessionConcurrencySettings:
    mode: str
    conflict_policy: str
    max_retries: int


@dataclass(frozen=True, slots=True)
class SessionStateSettings:
    save_on_chat_completion: bool
    save_on_stream_completion: bool
    save_on_stream_cancellation: bool
    save_on_stream_failure: bool
    save_each_stream_delta: bool


@dataclass(frozen=True, slots=True)
class SessionHistorySettings:
    enabled: bool
    include_tool_summaries: bool
    include_system_messages: bool
    include_metadata: bool
    max_message_chars: int
    redaction_enabled: bool


@dataclass(frozen=True, slots=True)
class SessionTracingSettings:
    record_session_created: bool
    record_session_resumed: bool
    record_session_reset: bool
    record_state_loaded: bool
    record_state_saved: bool
    record_history_returned: bool
    record_stream_lifecycle: bool


@dataclass(frozen=True, slots=True)
class SessionSettings:
    enabled: bool
    identifiers: SessionIdentifierSettings
    defaults: SessionDefaultsSettings
    lifecycle: SessionLifecycleSettings
    concurrency: SessionConcurrencySettings
    state: SessionStateSettings
    history: SessionHistorySettings
    tracing: SessionTracingSettings
```

### 9.2 Configuration Access Rule

The session service receives resolved settings from the composition root.

Use:

```python
session_service = DefaultSessionService(
    settings=config.session,
    workflow_state=workflow_state_store,
    orchestrator=orchestration_runtime,
    trace=trace_recorder,
    id_provider=session_id_provider,
    clock=clock,
)
```

Avoid this inside session modules:

```python
os.getenv("SESSION_HISTORY_ENABLED")
os.getenv("WORKFLOW_STATE_DB_PATH")
```

---

## 10. Public Session Service Interface

Recommended service protocol:

```python
from collections.abc import AsyncIterator
from typing import Protocol


class SessionService(Protocol):
    async def handle_chat(
        self,
        *,
        request: "SessionChatRequest",
        context: "SessionRequestContext",
    ) -> "SessionChatResult":
        ...

    async def stream_chat(
        self,
        *,
        request: "SessionChatRequest",
        context: "SessionRequestContext",
    ) -> AsyncIterator["SessionStreamEvent"]:
        ...

    async def reset_session(
        self,
        *,
        session_id: str,
        reason: str | None,
        context: "SessionRequestContext",
    ) -> "SessionResetResult":
        ...

    async def get_history(
        self,
        *,
        session_id: str,
        limit: int,
        context: "SessionRequestContext",
    ) -> "SessionHistoryResult":
        ...
```

### 10.1 API Adapter Note

The API document showed route-facing DTOs named `ChatRequest` and `ApiRequestContext`. To keep the session module independent of HTTP details, there are two acceptable implementation patterns:

1. The API layer maps `ChatRequest` + `ApiRequestContext` into `SessionChatRequest` + `SessionRequestContext` before calling the service.
2. The session service accepts API DTOs temporarily, then migrates to session DTOs once the contracts stabilize.

Preferred long-term pattern:

```text
API DTO -> Session DTO -> Core RequestContext -> OrchestrationRuntime
```

### 10.2 Temporary Compatibility Pattern

A temporary implementation may use:

```python
async def handle_chat(
    self,
    *,
    request: ChatRequest,
    context: ApiRequestContext,
) -> SessionChatResult:
    ...
```

This is acceptable during the API/session walking skeleton, but the service should not import FastAPI or API route modules.

---

## 11. Session Models

### 11.1 `SessionRequestContext`

Recommended model:

```python
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class SessionRequestContext:
    trace_id: str
    request_id: str
    user_id: str
    user_id_hash: str | None
    client_host: str | None
    user_agent: str | None
    path: str | None
    method: str | None
    metadata: dict[str, Any] = field(default_factory=dict)
```

### 11.2 `SessionChatRequest`

```python
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class SessionChatRequest:
    message: str
    session_id: str | None = None
    usecase: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

### 11.3 `SessionChatResult`

```python
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class SessionChatResult:
    trace_id: str
    session_id: str
    answer: str
    agent_name: str | None = None
    strategy_name: str | None = None
    llm_profile: str | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    memory_updates: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
```

### 11.4 `SessionResetResult`

```python
@dataclass(frozen=True, slots=True)
class SessionResetResult:
    trace_id: str
    session_id: str
    reset: bool
    message: str
    metadata: dict[str, Any] = field(default_factory=dict)
```

### 11.5 `SessionHistoryResult`

```python
@dataclass(frozen=True, slots=True)
class SessionHistoryMessage:
    role: str
    content: str
    created_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SessionHistoryResult:
    trace_id: str
    session_id: str
    messages: list[SessionHistoryMessage]
    truncated: bool
    metadata: dict[str, Any] = field(default_factory=dict)
```

---

## 12. Relationship to Core `RequestContext`

The core contract defines `RequestContext` as the orchestration-facing request object:

```python
@dataclass
class RequestContext:
    user_id: str
    session_id: str
    message: str
    usecase: str | None
    metadata: dict[str, Any]
```

`SessionService` is responsible for building this object from:

```text
SessionChatRequest
SessionRequestContext
resolved session_id
resolved usecase
safe metadata
```

### 12.1 Mapping Rule

Recommended mapping:

```python
def build_core_request_context(
    *,
    chat_request: SessionChatRequest,
    session_context: SessionRequestContext,
    session_id: str,
    default_usecase: str,
) -> RequestContext:
    metadata = {
        **chat_request.metadata,
        "trace_id": session_context.trace_id,
        "request_id": session_context.request_id,
        "user_id_hash": session_context.user_id_hash,
        "client_host": session_context.client_host,
        "user_agent": session_context.user_agent,
    }
    return RequestContext(
        user_id=session_context.user_id,
        session_id=session_id,
        message=chat_request.message,
        usecase=chat_request.usecase or default_usecase,
        metadata=metadata,
    )
```

### 12.2 Metadata Safety Rule

The session service may enrich metadata with safe operational fields:

```text
trace_id
request_id
user_id_hash
client_name
timezone
message_chars
session_created
session_resumed
```

It must not add:

```text
raw authorization header
bearer token
API keys
raw provider request
raw provider response
raw MCP payload
raw workflow state
hidden scratchpad
```

---

## 13. Session ID Lifecycle

Session ID behavior must be stable because the frontend stores and reuses `session_id` across chat requests.

### 13.1 Session ID Sources

A session ID may come from:

```text
request body session_id
X-Session-Id header mapped by API layer
server-generated ID when missing
```

The API validates basic identifier shape. The session service owns lifecycle decisions.

### 13.2 Session ID Generation

Recommended generated format:

```text
session_<ULID or UUID-safe string>
```

Example:

```python
class SessionIdProvider:
    def new_session_id(self) -> str:
        return f"session_{new_ulid()}"
```

### 13.3 Session ID Validation

Recommended validation pattern:

```python
_SESSION_ID_PATTERN = r"^[A-Za-z0-9_.:-]{3,128}$"
```

Validation rules:

| Case | Behavior |
|---|---|
| Missing session ID and generation enabled | Generate new session ID. |
| Missing session ID and generation disabled | Raise `SessionIdRequiredError`. |
| Invalid session ID shape | Raise `InvalidSessionIdError`. |
| Unknown client-provided session ID and create-on-first-chat enabled | Create/resume as new session. |
| Unknown client-provided session ID and reject-unknown enabled | Raise `SessionNotFoundError`. |

### 13.4 Session ID Security Rule

A session ID is a routing and continuity identifier. It is not an authentication credential.

Do not treat possession of a session ID as final authorization once real auth is added. Future policy/auth documents should bind session ownership to identity.

---

## 14. Session Lifecycle States

Recommended conceptual lifecycle:

```text
missing -> created -> active -> reset -> active -> expired optional -> archived optional
```

V1 does not need a complex state machine, but it should record enough metadata to reason about session behavior.

### 14.1 Lifecycle Events

Recommended events:

| Event | Meaning |
|---|---|
| `session_requested` | A chat/reset/history request references a session. |
| `session_created` | A new session ID is created or first seen. |
| `session_resumed` | Existing workflow state is loaded. |
| `session_state_loaded` | Workflow state load completed. |
| `session_state_saved` | Workflow state save completed. |
| `session_reset` | Short-term workflow state was reset. |
| `session_history_returned` | Safe history projection returned. |
| `session_conflict_detected` | Concurrent update conflict detected. |
| `session_error` | Session operation failed. |

### 14.2 Lifecycle Metadata

Safe lifecycle metadata may include:

```json
{
  "session_id": "session_...",
  "trace_id": "trace_...",
  "operation": "handle_chat",
  "state_version_before": 3,
  "state_version_after": 4,
  "message_chars": 245,
  "created": false,
  "resumed": true
}
```

Do not include raw message text by default.

---

## 15. Workflow State Handoff

The session service owns the workflow-state handoff.

Normal chat flow:

```text
1. Resolve session ID.
2. Load workflow state.
3. Build core RequestContext.
4. Call OrchestrationRuntime.
5. Build updated workflow state from result.
6. Save workflow state.
7. Return SessionChatResult.
```

### 15.1 Workflow State Store Contract

The store interface was defined earlier. The session service should use only the interface, not SQLite implementation details.

Recommended abstract shape:

```python
class WorkflowStateStore(Protocol):
    async def load(self, *, session_id: str) -> WorkflowStateRecord | None:
        ...

    async def save(
        self,
        *,
        session_id: str,
        state: WorkflowStateDocument,
        expected_version: int | None = None,
        metadata: dict[str, object] | None = None,
    ) -> WorkflowStateSaveResult:
        ...

    async def reset(
        self,
        *,
        session_id: str,
        reason: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> WorkflowStateResetResult:
        ...
```

### 15.2 State Ownership Rule

The session service may shape state at boundaries, but it should not understand every internal orchestration detail.

It may own:

```text
conversation messages
last request metadata
last response metadata
version information
session timestamps
```

Orchestration owns:

```text
strategy-specific working state
agent-specific working state
pending tool checkpoints
intermediate execution summaries
```

### 15.3 State Document Shape

Recommended V1 logical shape:

```json
{
  "schema_version": "1.0",
  "session_id": "session_abc123",
  "conversation": {
    "messages": [
      {
        "role": "user",
        "content": "Hello",
        "created_at": "2026-06-24T18:00:00-05:00"
      },
      {
        "role": "assistant",
        "content": "Hi! How can I help?",
        "created_at": "2026-06-24T18:00:01-05:00"
      }
    ]
  },
  "runtime": {
    "last_agent_name": "support_agent",
    "last_strategy_name": "direct_agent",
    "last_llm_profile": "default_chat"
  },
  "checkpoints": {},
  "metadata": {
    "created_at": "2026-06-24T18:00:00-05:00",
    "updated_at": "2026-06-24T18:00:01-05:00"
  }
}
```

### 15.4 State Privacy Rule

Workflow state may contain user conversation content and operational context. It must be treated as private runtime state.

Do not expose full workflow state through API history, health, capabilities, or debug routes.

---

## 16. Non-Streaming Chat Flow

`handle_chat` is the standard request/response path.

### 16.1 Flow

```text
POST /chat
  -> API validates request
  -> API builds SessionRequestContext
  -> SessionService.handle_chat
      -> resolve session ID
      -> load workflow state
      -> build RequestContext
      -> append user message to in-memory state draft
      -> call OrchestrationRuntime.run
      -> append assistant response to state draft
      -> save workflow state once
      -> record safe trace events
      -> return SessionChatResult
  -> API maps result to ChatResponse
```

### 16.2 Handler Pattern

```python
async def handle_chat(
    self,
    *,
    request: SessionChatRequest,
    context: SessionRequestContext,
) -> SessionChatResult:
    session_id = self._resolve_session_id(request.session_id)
    loaded = await self._load_or_create_state(session_id=session_id, context=context)

    core_request = self._mapper.to_request_context(
        request=request,
        context=context,
        session_id=session_id,
    )

    draft_state = self._state_builder.append_user_message(
        loaded.state,
        message=request.message,
        created_at=self._clock.now(),
    )

    orchestration_result = await self._orchestrator.run(
        request=core_request,
        state=draft_state,
    )

    final_state = self._state_builder.apply_result(
        draft_state,
        result=orchestration_result,
        completed_at=self._clock.now(),
    )

    save_result = await self._save_state(
        session_id=session_id,
        state=final_state,
        expected_version=loaded.version,
        context=context,
    )

    return SessionChatResult(
        trace_id=context.trace_id,
        session_id=session_id,
        answer=orchestration_result.answer,
        agent_name=orchestration_result.agent_name,
        strategy_name=orchestration_result.strategy_name,
        llm_profile=orchestration_result.llm_profile,
        tool_calls=orchestration_result.tool_calls,
        memory_updates=orchestration_result.memory_updates,
        metadata={
            **orchestration_result.metadata,
            "state_version": save_result.version,
        },
    )
```

### 16.3 Save Boundary Rule

For non-streaming chat:

```text
Load once before orchestration.
Save once after orchestration completes.
Save failure metadata only if configured and safe.
Do not save repeatedly during one request unless a future checkpointing design requires it.
```

---

## 17. Streaming Chat Flow

`stream_chat` supports `/chat/stream` through API SSE mapping.

### 17.1 Flow

```text
POST /chat/stream
  -> API validates request
  -> API builds SessionRequestContext
  -> SessionService.stream_chat
      -> resolve session ID
      -> load workflow state once
      -> build RequestContext
      -> append user message to in-memory state draft
      -> call OrchestrationRuntime.stream
      -> yield safe session stream events
      -> accumulate assistant text and safe metadata
      -> on completion: save final workflow state once
      -> on cancellation/failure: save configured checkpoint once
  -> API maps SessionStreamEvent to SSE
```

### 17.2 Stream Event Types

Recommended session-level event types:

```text
session.started
response.started
response.delta
response.metadata
response.completed
response.error
session.state_saved
session.cancelled
heartbeat optional by API layer
```

The API layer may translate these into the API SSE contract:

```text
response.started
response.delta
response.metadata
response.completed
response.error
heartbeat
```

### 17.3 `SessionStreamEvent`

```python
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class SessionStreamEvent:
    event_type: str
    trace_id: str
    session_id: str
    data: dict[str, Any] = field(default_factory=dict)
    sequence_no: int | None = None
```

### 17.4 Streaming Handler Pattern

```python
async def stream_chat(
    self,
    *,
    request: SessionChatRequest,
    context: SessionRequestContext,
) -> AsyncIterator[SessionStreamEvent]:
    session_id = self._resolve_session_id(request.session_id)
    loaded = await self._load_or_create_state(session_id=session_id, context=context)

    core_request = self._mapper.to_request_context(
        request=request,
        context=context,
        session_id=session_id,
    )

    draft_state = self._state_builder.append_user_message(
        loaded.state,
        message=request.message,
        created_at=self._clock.now(),
    )

    assistant_parts: list[str] = []
    metadata: dict[str, object] = {}

    yield SessionStreamEvent(
        event_type="response.started",
        trace_id=context.trace_id,
        session_id=session_id,
        data={"schema_version": "1.0"},
    )

    try:
        async for event in self._orchestrator.stream(request=core_request, state=draft_state):
            session_event = self._stream_mapper.from_orchestration_event(
                event=event,
                trace_id=context.trace_id,
                session_id=session_id,
            )
            if session_event.event_type == "response.delta":
                assistant_parts.append(str(session_event.data.get("text", "")))
            metadata.update(self._stream_mapper.safe_metadata(event))
            yield session_event

        final_answer = "".join(assistant_parts)
        final_state = self._state_builder.append_assistant_message(
            draft_state,
            answer=final_answer,
            metadata=metadata,
            created_at=self._clock.now(),
        )
        save_result = await self._save_state(
            session_id=session_id,
            state=final_state,
            expected_version=loaded.version,
            context=context,
        )
        yield SessionStreamEvent(
            event_type="response.completed",
            trace_id=context.trace_id,
            session_id=session_id,
            data={"state_version": save_result.version},
        )

    except asyncio.CancelledError:
        await self._finalize_cancelled_stream(
            session_id=session_id,
            loaded=loaded,
            draft_state=draft_state,
            assistant_parts=assistant_parts,
            context=context,
        )
        raise
```

### 17.5 Streaming State Rule

For streaming chat:

```text
Load state once near stream start.
Do not save workflow state on every token.
Accumulate assistant output safely.
Save final state once at completion.
Save failure/cancellation checkpoint only if configured.
Record trace events for lifecycle boundaries, not every token by default.
```

---

## 18. Session Reset Flow

Session reset is the service-level operation behind:

```text
POST /sessions/{session_id}/reset
```

### 18.1 Flow

```text
API validates session_id
  -> SessionService.reset_session
      -> validate session ID
      -> record reset requested event
      -> call WorkflowStateStore.reset
      -> record reset completed event
      -> return SessionResetResult
```

### 18.2 Reset Handler Pattern

```python
async def reset_session(
    self,
    *,
    session_id: str,
    reason: str | None,
    context: SessionRequestContext,
) -> SessionResetResult:
    normalized_session_id = self._ids.validate(session_id)

    await self._trace.record_event(
        trace_id=context.trace_id,
        event_name="session_reset_requested",
        payload={
            "session_id": normalized_session_id,
            "reason": reason or "unspecified",
        },
    )

    result = await self._workflow_state.reset(
        session_id=normalized_session_id,
        reason=reason,
        metadata={
            "trace_id": context.trace_id,
            "request_id": context.request_id,
            "user_id_hash": context.user_id_hash,
        },
    )

    await self._trace.record_event(
        trace_id=context.trace_id,
        event_name="session_reset_completed",
        payload={
            "session_id": normalized_session_id,
            "reset": result.reset,
        },
    )

    return SessionResetResult(
        trace_id=context.trace_id,
        session_id=normalized_session_id,
        reset=True,
        message="Session workflow state was reset.",
        metadata={"reset_at": self._clock.now_iso()},
    )
```

### 18.3 Reset Boundary Rule

Session reset may clear:

```text
conversation history stored in workflow state
temporary scratch state
pending tool context
current workflow checkpoint
last agent/strategy runtime metadata
```

Session reset must not delete:

```text
long-term user memories
project memories
document chunks
ArcadeDB records
trace events
trace summaries
LLM profile configuration
MCP tool configuration
policy configuration
other sessions
```

---

## 19. Optional Session History Flow

The API document recommends the history route remain disabled or minimal until session policy is defined. This document defines the safe service boundary for when it is enabled.

Recommended optional route:

```text
GET /sessions/{session_id}/history?limit=50
```

### 19.1 Flow

```text
API validates session_id and limit
  -> SessionService.get_history
      -> validate session ID
      -> enforce configured max limit
      -> load workflow state
      -> project safe messages only
      -> redact message metadata
      -> truncate oversized message content if configured
      -> return SessionHistoryResult
```

### 19.2 History Projection

Recommended projector:

```python
class SessionHistoryProjector:
    def project(
        self,
        *,
        state: WorkflowStateDocument,
        limit: int,
        settings: SessionHistorySettings,
    ) -> SessionHistoryResult:
        ...
```

### 19.3 Safe History Message Shape

```json
{
  "role": "user",
  "content": "Summarize this document.",
  "created_at": "2026-06-24T18:00:00-05:00",
  "metadata": {
    "message_chars": 24
  }
}
```

### 19.4 History Must Not Return

- Full workflow state document.
- Raw provider request or response objects.
- Raw MCP tool payloads.
- Hidden chain-of-thought or scratchpad internals.
- Credentials, tokens, cookies, or connection strings.
- Raw trace events.
- Raw policy internals.
- Long-term memory records unless a separate memory API/policy explicitly allows it.

---

## 20. Session Concurrency

V1 can run locally in a single backend process, but concurrent requests for the same session can still happen.

Examples:

```text
User double-clicks send.
Browser retries a request.
Two browser tabs reuse the same session_id.
A stream is active while reset is requested.
```

### 20.1 Recommended V1 Concurrency Mode

Use optimistic versioning through `WorkflowStateStore`.

```text
1. Load state with version N.
2. Run orchestration.
3. Save with expected_version=N.
4. If current version is not N, raise conflict.
```

### 20.2 Conflict Policy

Recommended defaults:

| Operation | Conflict Behavior |
|---|---|
| `handle_chat` | Reject with `SessionConflictError`. |
| `stream_chat` | Reject early if conflict detected before streaming; avoid late merge in V1. |
| `reset_session` | Reset should either win by explicit operation or fail if active lock policy is enabled. |
| `get_history` | Read latest available state; no conflict. |

### 20.3 Service-Level Locking

A future deployment may add per-session locks. In V1, prefer store-level optimistic versioning rather than route-level locks.

Avoid:

```python
_global_session_locks: dict[str, asyncio.Lock] = {}
```

unless the lifecycle and cleanup policy are clearly defined. A local in-process lock will not protect multi-process deployments.

### 20.4 Active Stream and Reset

Recommended V1 policy:

```text
If reset occurs during an active stream, reset should mark current workflow state reset.
The active stream should fail to save final state if expected_version no longer matches.
The stream should emit or record a conflict/finalization event if possible.
```

This avoids reintroducing stale streamed output after the user clicked Clear.

---

## 21. Error Model

Session service should raise typed errors that the API error mapper can convert into stable HTTP responses.

### 21.1 Session Error Types

Recommended taxonomy:

```python
class SessionError(Exception):
    code = "session_error"
    retryable = False


class InvalidSessionIdError(SessionError):
    code = "invalid_session_id"


class SessionIdRequiredError(SessionError):
    code = "session_id_required"


class SessionNotFoundError(SessionError):
    code = "session_not_found"


class SessionConflictError(SessionError):
    code = "session_conflict"
    retryable = True


class SessionStateUnavailableError(SessionError):
    code = "workflow_state_unavailable"
    retryable = True


class SessionResetFailedError(SessionError):
    code = "session_reset_failed"
    retryable = True


class SessionHistoryDisabledError(SessionError):
    code = "session_history_disabled"


class SessionHistoryUnavailableError(SessionError):
    code = "session_history_unavailable"
    retryable = True
```

### 21.2 API Mapping

| Session Error | HTTP Status | API Code | Retryable |
|---|---:|---|---|
| `InvalidSessionIdError` | `400` | `invalid_session_id` | false |
| `SessionIdRequiredError` | `400` | `session_id_required` | false |
| `SessionNotFoundError` | `404` | `session_not_found` | false |
| `SessionConflictError` | `409` | `session_conflict` | true |
| `SessionStateUnavailableError` | `503` | `workflow_state_unavailable` | true |
| `SessionResetFailedError` | `503` | `session_reset_failed` | true |
| `SessionHistoryDisabledError` | `404` or `403` | `session_history_disabled` | false |
| `SessionHistoryUnavailableError` | `503` | `session_history_unavailable` | true |

### 21.3 Error Safety Rule

Session errors must not expose:

```text
raw workflow state
raw SQL
SQLite path if sensitive
stack traces
raw user message
raw provider response
raw tool response
credentials
connection strings
```

---

## 22. Trace and Observability Integration

The session service should emit safe lifecycle events through an observability facade or trace recorder.

### 22.1 Recommended Trace Events

| Event | Emitted By | Notes |
|---|---|---|
| `session_requested` | Session service | Safe session/message metadata. |
| `session_created` | Session service | New session ID created. |
| `session_resumed` | Session service | Existing state found. |
| `workflow_state_load_started` | Session service | No raw state. |
| `workflow_state_loaded` | Session service | Version and size summary only. |
| `orchestration_started` | Session service or runtime | Runtime may emit more details later. |
| `orchestration_completed` | Session service or runtime | Safe result summary. |
| `workflow_state_save_started` | Session service | Expected version metadata. |
| `workflow_state_saved` | Session service | Saved version metadata. |
| `session_reset_requested` | Session service | Reason summary only. |
| `session_reset_completed` | Session service | Reset confirmation. |
| `session_history_returned` | Session service | Count/truncated only. |
| `session_conflict_detected` | Session service | Version metadata only. |
| `session_stream_started` | Session service | Stream lifecycle. |
| `session_stream_completed` | Session service | Duration and finish reason. |
| `session_stream_cancelled` | Session service | Cancellation summary. |
| `session_stream_failed` | Session service | Safe error type/code. |

### 22.2 Trace Payload Examples

Safe payload:

```json
{
  "session_id": "session_abc123",
  "operation": "handle_chat",
  "message_chars": 245,
  "state_version": 3,
  "created": false
}
```

Unsafe payload:

```json
{
  "message": "full user prompt...",
  "state": {"conversation": {"messages": []}},
  "authorization": "Bearer ..."
}
```

### 22.3 Metrics

Recommended metrics:

```text
backend.session.chat.total
backend.session.chat.duration_ms
backend.session.stream.total
backend.session.stream.duration_ms
backend.session.reset.total
backend.session.history.total
backend.session.state.load.duration_ms
backend.session.state.save.duration_ms
backend.session.conflicts.total
backend.session.errors.total
```

Allowed tags:

```text
operation
success
error_type
streaming
conflict
created
resumed
```

Avoid metric tags:

```text
session_id
trace_id
raw_user_id
message text
provider URL
```

---

## 23. Request Context and Identity

V1 may use synthetic local identity.

Recommended defaults:

```text
user_id: local_user
user_id_hash: hash(local_user) optional
identity source: API identity hook
```

### 23.1 Identity Rule

Session service receives identity from API/security dependencies. It should not parse authorization headers itself.

Correct:

```text
API identity dependency -> SessionRequestContext.user_id -> SessionService -> RequestContext
```

Avoid:

```text
SessionService reads Authorization header directly.
SessionService validates JWT directly.
```

Future policy/auth documents can replace the identity provider without changing session lifecycle code.

### 23.2 Session Ownership Placeholder

V1 may not enforce session ownership, but the architecture should keep a placeholder for it:

```python
class SessionOwnershipValidator(Protocol):
    async def validate_access(
        self,
        *,
        session_id: str,
        user_id: str,
        operation: str,
    ) -> None:
        ...
```

Default local implementation:

```text
Allow all local_user operations.
```

Future implementation:

```text
Require authenticated user to own or be allowed to access session_id.
```

---

## 24. Orchestration Runtime Integration

The session service calls the orchestration runtime through a narrow interface.

### 24.1 Runtime Interface

Recommended shape:

```python
from collections.abc import AsyncIterator
from typing import Protocol


class OrchestrationRuntime(Protocol):
    async def run(
        self,
        *,
        request: RequestContext,
        state: WorkflowStateDocument,
    ) -> OrchestrationResult:
        ...

    async def stream(
        self,
        *,
        request: RequestContext,
        state: WorkflowStateDocument,
    ) -> AsyncIterator[OrchestrationStreamEvent]:
        ...
```

### 24.2 Runtime Result Mapping

`SessionService` maps `OrchestrationResult` to `SessionChatResult` without exposing runtime internals.

Allowed result fields:

```text
answer
session_id
agent_name
strategy_name
llm_profile
tool_calls summaries
memory_updates summaries
trace_id
safe metadata
```

Do not expose:

```text
raw prompt
raw completion
provider SDK object
raw tool payload
hidden reasoning/scratchpad
full memory records by default
```

### 24.3 Temporary Walking Skeleton Orchestrator

Until the full orchestration runtime exists, the session service may call a stub runtime.

Recommended stub behavior:

```text
Input: RequestContext + WorkflowStateDocument
Output: OrchestrationResult(answer=f"Echo: {message}")
Trace: safe started/completed events
State: no provider, memory, or MCP dependency
```

This keeps the API/session/state/trace vertical slice working before real LLM integration.

---

## 25. State Builder

The session service should use a small state builder/helper to avoid scattering state mutation logic through service methods.

### 25.1 Responsibilities

State builder owns:

- Creating an empty workflow state document.
- Appending user messages.
- Appending assistant messages.
- Applying orchestration metadata.
- Applying stream completion metadata.
- Applying failure/cancellation metadata.
- Trimming or summarizing conversation history if configured later.

It does not own:

- LLM summarization.
- Memory upserts.
- Tool payload interpretation.
- SQLite serialization.

### 25.2 State Builder Interface

```python
class SessionStateBuilder:
    def new_state(self, *, session_id: str, created_at: str) -> WorkflowStateDocument:
        ...

    def append_user_message(
        self,
        state: WorkflowStateDocument,
        *,
        message: str,
        created_at: str,
    ) -> WorkflowStateDocument:
        ...

    def apply_result(
        self,
        state: WorkflowStateDocument,
        *,
        result: OrchestrationResult,
        completed_at: str,
    ) -> WorkflowStateDocument:
        ...

    def apply_stream_failure(
        self,
        state: WorkflowStateDocument,
        *,
        partial_answer: str,
        error_code: str,
        failed_at: str,
    ) -> WorkflowStateDocument:
        ...
```

### 25.3 Immutable Update Preference

Prefer immutable-style updates:

```python
new_state = state_builder.append_user_message(old_state, message=message, created_at=now)
```

instead of mutating shared state in-place across async boundaries.

---

## 26. Conversation History Storage

Workflow state may store short-term conversation messages for session continuity.

### 26.1 Message Shape

Recommended internal message shape:

```json
{
  "id": "msg_01HX...",
  "role": "user",
  "content": "Hello",
  "created_at": "2026-06-24T18:00:00-05:00",
  "metadata": {
    "trace_id": "trace_...",
    "message_chars": 5
  }
}
```

### 26.2 Roles

Recommended roles:

```text
user
assistant
system optional internal only
tool optional summary only
```

For V1, keep history simple:

```text
Store user messages.
Store assistant answers.
Store safe tool summaries only if required.
Do not store hidden reasoning.
```

### 26.3 History Trimming

V1 may keep bounded state using simple limits:

```yaml
session:
  history:
    max_messages_in_state: 100
    max_message_chars: 4000
```

A future LLM/orchestration document may add summarization through an LLM profile. The session service should not call an LLM directly for summarization.

---

## 27. Streaming Cancellation and Failure

Streaming is the most error-prone session path because output is visible before final state is saved.

### 27.1 Completion

On successful stream completion:

```text
assistant_parts -> final assistant message -> save state once -> emit response.completed
```

### 27.2 Cancellation

On client disconnect or task cancellation:

```text
record stream_cancelled trace event
optionally save partial assistant output as cancelled metadata
avoid emitting more events after API disconnect
raise cancellation to caller when appropriate
```

Recommended default:

```text
Do not store partial assistant content as a normal assistant answer unless the stream completed.
If storing partial content, mark it clearly as partial/cancelled.
```

### 27.3 Failure

On stream failure:

```text
record stream_failed trace event
save failure checkpoint if configured
return response.error event through API if connection is still open
```

Failure checkpoint should include:

```json
{
  "last_error": {
    "code": "llm_unavailable",
    "retryable": true,
    "failed_at": "2026-06-24T18:00:00-05:00"
  }
}
```

Do not include raw stack traces or provider payloads.

---

## 28. Session Service and Trace Store Relationship

Session service should not use concrete `SqliteTraceStore` directly.

Correct:

```text
SessionService -> ObservabilityRecorder -> TraceStore interface -> SqliteTraceStore
```

Avoid:

```text
SessionService -> SqliteTraceStore SQL
SessionService -> sqlite3 connection
```

### 28.1 Trace Failure Policy

Trace writes should usually be non-fatal for chat behavior.

Recommended policy:

| Operation | Trace Failure Behavior |
|---|---|
| Chat lifecycle event | Log redacted warning; continue if possible. |
| Stream lifecycle event | Log redacted warning; continue if possible. |
| Reset event | Log redacted warning; continue reset if workflow state succeeds. |
| Debug trace route | Not owned by session service. |

---

## 29. Session Service and Workflow State Store Relationship

Workflow state is required for session continuity.

### 29.1 State Store Failure Policy

| Operation | State Failure | Behavior |
|---|---|---|
| `handle_chat` load fails | Required dependency unavailable | Raise `SessionStateUnavailableError`. |
| `handle_chat` save fails | State not persisted | Raise `SessionStateUnavailableError` or return error depending on API policy. |
| `stream_chat` initial load fails | Cannot start stream safely | Emit/raise error before streaming. |
| `stream_chat` final save fails | Response may have streamed but state not persisted | Emit final error if possible and record trace. |
| `reset_session` reset fails | State not cleared | Raise `SessionResetFailedError`. |
| `get_history` load fails | History unavailable | Raise `SessionHistoryUnavailableError`. |

### 29.2 No Cross-Store Transactions

Do not attempt one transaction across workflow state, traces, memory, and tools.

Recommended consistency model:

```text
Workflow state save is authoritative for session continuity.
Trace writes are best-effort operational telemetry.
Memory writes happen later through MemoryGateway and policy, not session reset.
```

---

## 30. Session Service and Memory Boundary

Session service must not directly call memory.

Correct future path:

```text
SessionService -> OrchestrationRuntime -> MemoryGateway -> MemoryStoreAdapter -> memory_store -> ArcadeDB
```

Avoid:

```text
SessionService -> MemoryGateway.search
SessionService -> MemoryService.upsert
SessionService -> ArcadeDB query
```

### 30.1 Reset and Memory

Session reset must not delete memory.

Reason:

```text
Session state is short-term conversation/runtime state.
Memory is long-term user/project/document knowledge.
Resetting a chat session is not a privacy deletion request.
```

A future privacy or memory document should define explicit memory deletion routes and scope controls.

---

## 31. Session Service and LLM Boundary

Session service must not directly call LLM providers or `LLMGateway` for normal behavior.

Correct future path:

```text
SessionService -> OrchestrationRuntime -> LLMGateway -> ProviderAdapter
```

Avoid:

```text
SessionService -> OpenAI SDK
SessionService -> Google SDK
SessionService -> local /v1/chat/completions endpoint
SessionService -> LLMGateway.complete directly for routing
```

### 31.1 History Summarization Note

If future history compression requires LLM summarization, it should be implemented through orchestration or a dedicated summarization service using `LLMGateway`, not directly inside basic session lifecycle code.

---

## 32. Session Service and Tool/MCP Boundary

Session service must not call MCP tools or tool gateway directly.

Correct future path:

```text
SessionService -> OrchestrationRuntime -> ToolGateway -> MCPClientAdapter -> Single MCP Server
```

Avoid:

```text
SessionService -> MCPClientAdapter
SessionService -> FastMCP client
SessionService -> external API call
```

### 32.1 Pending Tool State

Workflow state may contain pending tool checkpoints, but session service should treat them as opaque runtime state except for reset clearing.

Example:

```json
{
  "checkpoints": {
    "pending_tool_call": {
      "id": "tool_call_...",
      "status": "waiting_for_approval"
    }
  }
}
```

Session reset may clear this state. It should not execute, cancel, or inspect external tool behavior directly.

---

## 33. Input Validation Responsibilities

API validates HTTP request DTOs first. Session service performs domain validation.

### 33.1 API Validation

API owns:

```text
JSON body parse
required fields
message length
metadata size
path parameter syntax
HTTP headers
```

### 33.2 Session Validation

Session service owns:

```text
session ID lifecycle decision
unknown session behavior
usecase defaulting
session ownership placeholder
history enabled/disabled
conflict policy
reset semantics
```

### 33.3 Defense in Depth

Even if API validates `session_id`, session service should validate it again because it may be called from tests, CLI, or future non-HTTP entrypoints.

---

## 34. Use Case Handling

The chat request may include an optional `usecase`.

### 34.1 Session Service Role

Session service may:

```text
apply default usecase when missing
pass usecase into RequestContext
preserve usecase in workflow state metadata
record safe trace metadata
```

It must not:

```text
resolve agent lists
resolve strategy implementations
resolve LLM profiles
resolve tool allowlists
```

Those belong to orchestration/config/policy layers.

### 34.2 Use Case Change in Same Session

Recommended V1 behavior:

```text
Allow usecase to be provided per request.
Store last_usecase in workflow state metadata.
Let orchestration decide how to handle different usecase context.
```

Optional stricter behavior:

```text
Reject usecase changes within a session unless configured.
```

Configuration:

```yaml
session:
  lifecycle:
    allow_usecase_change_in_session: true
```

---

## 35. Idempotency and Retries

V1 does not require idempotency keys for chat, but the session layer should leave room for them.

### 35.1 Optional Future Fields

```text
Idempotency-Key header -> API context metadata
request_fingerprint -> session metadata
last_processed_request_id -> workflow state metadata
```

### 35.2 V1 Behavior

Recommended:

```text
Do not claim chat requests are idempotent.
Use optimistic concurrency to detect conflicting updates.
Allow frontend retry only after failed request with safe UX messaging.
```

---

## 36. Composition Root Integration

The composition root wires concrete session dependencies.

### 36.1 Wiring Pattern

```python
def build_session_service(config: AppConfig) -> SessionService:
    workflow_state = build_workflow_state_store(config.persistence.workflow_state)
    trace_recorder = build_trace_recorder(config.observability)
    orchestrator = build_orchestration_runtime(config)

    return DefaultSessionService(
        settings=config.session,
        workflow_state=workflow_state,
        orchestrator=orchestrator,
        trace=trace_recorder,
        id_provider=UlidSessionIdProvider(prefix=config.session.identifiers.prefix),
        clock=SystemClock(),
        redactor=build_redactor(config.observability.redaction),
    )
```

### 36.2 Early Walking Skeleton Wiring

Before full orchestration exists:

```python
session_service = DefaultSessionService(
    settings=config.session,
    workflow_state=workflow_state_store,
    orchestrator=EchoOrchestrationRuntime(),
    trace=trace_recorder,
    id_provider=UlidSessionIdProvider(prefix="session"),
    clock=SystemClock(),
    redactor=redactor,
)
```

### 36.3 API Registration

```python
app = create_api_app(
    settings=config.api,
    services=ApiServices(
        session=session_service,
        health=health_service,
        capabilities=capability_service,
        trace_debug=debug_trace_service,
    ),
)
```

---

## 37. Health and Capabilities Integration

The session service may expose a small health/status method for health aggregation.

### 37.1 Optional Health Interface

```python
class SessionServiceHealth(Protocol):
    async def health(self) -> dict[str, object]:
        ...
```

Recommended output:

```json
{
  "status": "ok",
  "configured": true,
  "workflow_state_required": true,
  "history_enabled": false,
  "concurrency_mode": "optimistic_version"
}
```

Do not include:

```text
session IDs
user IDs
conversation content
workflow state payloads
DB paths if sensitive
```

### 37.2 Capabilities

Capabilities route may expose session-level flags:

```json
{
  "sessions": {
    "reset_enabled": true,
    "history_enabled": false,
    "client_session_id_enabled": true
  }
}
```

These flags should come from configuration and service readiness, not hard-coded route behavior.

---

## 38. Privacy and Data Handling

Session service handles user conversation state, so privacy defaults matter.

### 38.1 Redaction

Redact before:

```text
trace events
logs
history metadata
error details
failure checkpoints
```

Sensitive fragments:

```text
api_key
authorization
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

### 38.2 Raw Messages

Raw chat messages may be stored in workflow state for session continuity. They should not be logged or traced by default.

Allowed trace metadata:

```json
{
  "message_chars": 245,
  "metadata_keys_count": 3
}
```

Avoid trace payload:

```json
{
  "message": "full user prompt..."
}
```

### 38.3 Privacy Deletion Boundary

Session reset is not privacy deletion.

A future policy/privacy architecture should define:

```text
delete by user scope
delete by project scope
delete memory records
delete document chunks
delete traces by retention policy
export user data
```

---

## 39. Recommended Implementation Order

### Step 1: Add Session Settings

Deliverables:

- `SessionSettings`
- identifier settings
- lifecycle settings
- concurrency settings
- state save settings
- history settings
- tracing settings

Success criteria:

- Config validates default session behavior.
- Invalid identifier patterns, limits, or conflict modes fail fast.

### Step 2: Add Session Models

Deliverables:

- `SessionRequestContext`
- `SessionChatRequest`
- `SessionChatResult`
- `SessionStreamEvent`
- `SessionResetResult`
- `SessionHistoryResult`

Success criteria:

- Models are independent of FastAPI.
- API DTOs can map into session models.

### Step 3: Add Session ID Provider

Deliverables:

- `SessionIdProvider`
- validation helper
- generation helper
- deterministic fake ID provider for tests

Success criteria:

- Missing session ID generates a valid ID when configured.
- Invalid session IDs are rejected.
- Tests can use predictable session IDs.

### Step 4: Add Request Mapping

Deliverables:

- API/session to `RequestContext` mapper
- metadata redaction/normalization helper
- usecase defaulting

Success criteria:

- `RequestContext` includes session ID, user ID, message, usecase, and safe metadata.
- Metadata does not include raw auth tokens.

### Step 5: Add State Builder

Deliverables:

- new state document builder
- append user message
- apply orchestration result
- apply stream result
- apply failure/cancellation metadata

Success criteria:

- State updates are consistent across chat and stream paths.
- History projection has a stable source format.

### Step 6: Implement `handle_chat`

Deliverables:

- session ID resolution
- workflow state load/create
- orchestration runtime call
- workflow state save
- result mapping
- safe trace events

Success criteria:

- Non-streaming chat exercises real `WorkflowStateStore`.
- Response includes stable `session_id` and `trace_id`.
- State is saved exactly once on successful completion.

### Step 7: Implement `stream_chat`

Deliverables:

- streaming orchestration adapter
- session stream event mapping
- assistant delta accumulation
- completion finalization
- cancellation/failure finalization

Success criteria:

- Stream emits safe session events.
- Workflow state is not saved on every token.
- Final state is saved once on completion.

### Step 8: Implement `reset_session`

Deliverables:

- reset method
- reset trace events
- reset result mapping

Success criteria:

- Reset calls only `WorkflowStateStore.reset` for state clearing.
- Reset does not delete memory, traces, LLM config, MCP config, policy config, or other sessions.

### Step 9: Implement Optional History Projection

Deliverables:

- history projector
- bounded result limits
- redacted message metadata
- disabled-by-default behavior

Success criteria:

- History route can call `SessionService.get_history` when enabled.
- History does not expose full workflow state.

### Step 10: Add Concurrency Handling

Deliverables:

- optimistic version save support
- conflict detection mapping
- `SessionConflictError`

Success criteria:

- Concurrent saves for the same session produce deterministic conflict behavior.
- Conflicts map to API 409.

### Step 11: Add Health/Capability Hooks

Deliverables:

- optional session health method
- capability flags source

Success criteria:

- `/health` can include safe session readiness.
- `/capabilities` can expose safe session feature flags.

### Step 12: Replace Echo Runtime With Orchestration Runtime

Deliverables:

- session service uses real `OrchestrationRuntime` interface
- fake runtime remains for tests

Success criteria:

- Session service does not change when real LLM, memory, tool, and agent components are added later.

---

## 40. Testing Strategy

### 40.1 Unit Tests

| Test | Purpose |
|---|---|
| Generates session ID when missing | Proves creation behavior. |
| Rejects invalid session ID | Proves domain validation. |
| Resumes existing session state | Proves load path. |
| Creates empty state for new session | Proves first chat behavior. |
| Maps chat request to `RequestContext` | Proves orchestration handoff. |
| `handle_chat` calls orchestrator once | Proves service boundary. |
| `handle_chat` saves state once | Proves save boundary. |
| `handle_chat` maps orchestration result | Proves response contract. |
| `stream_chat` emits started/delta/completed | Proves stream event contract. |
| `stream_chat` does not save per delta | Proves streaming state rule. |
| `stream_chat` saves once on completion | Proves finalization. |
| `stream_chat` handles cancellation | Proves cancellation policy. |
| `reset_session` calls store reset | Proves reset boundary. |
| `reset_session` does not call memory/trace deletion | Proves safety. |
| History disabled raises configured error | Proves default safety. |
| History projection excludes raw workflow state | Proves privacy. |
| Optimistic conflict maps to session conflict | Proves concurrency handling. |
| Trace events omit raw message body | Proves observability privacy. |

### 40.2 Integration Tests

| Test | Purpose |
|---|---|
| API `/chat` uses real session service | Proves API/session integration. |
| Session service with SQLite store persists state | Proves real store compatibility. |
| Multiple chat requests reuse same session state | Proves continuity. |
| Reset clears workflow state | Proves reset behavior. |
| Reset does not remove traces | Proves trace preservation. |
| Reset does not call memory gateway | Proves memory isolation. |
| Streaming route finalizes state on completion | Proves stream state persistence. |
| Stream cancellation does not corrupt state | Proves cancellation safety. |
| Concurrent chat requests detect conflict | Proves version enforcement. |
| History route returns safe projection when enabled | Proves history shaping. |

### 40.3 Fake Dependencies

Recommended fakes:

```text
FakeWorkflowStateStore
FakeOrchestrationRuntime
FakeStreamingOrchestrationRuntime
FakeSessionIdProvider
FakeTraceRecorder
FakeClock
FakeRedactor
```

### 40.4 Fixture Configs

Recommended fixtures:

```text
tests/fixtures/config/session_basic.yaml
tests/fixtures/config/session_history_disabled.yaml
tests/fixtures/config/session_history_enabled.yaml
tests/fixtures/config/session_conflict_reject.yaml
tests/fixtures/config/session_streaming.yaml
tests/fixtures/config/session_reject_unknown_client_id.yaml
tests/fixtures/config/session_with_real_sqlite_store.yaml
```

---

## 41. Acceptance Criteria

This architecture is complete when:

- `SessionService` exposes `handle_chat`, `stream_chat`, `reset_session`, and optional `get_history` methods.
- Session models are independent of FastAPI and HTTP response classes.
- API DTOs can be mapped into session DTOs.
- Session service validates and resolves session IDs.
- Missing session IDs generate server-side IDs when configured.
- Session service creates or resumes workflow state through `WorkflowStateStore`.
- Session service maps requests into core `RequestContext`.
- Session service calls `OrchestrationRuntime` through an interface.
- Session service does not call LLM providers, memory stores, MCP clients, or tools directly.
- Session service does not import SQLite, ArcadeDB, provider SDKs, MCP clients, or `memory_store.service.MemoryService`.
- `handle_chat` loads workflow state once and saves once on successful completion.
- `stream_chat` loads workflow state once and saves final state once on completion.
- `stream_chat` does not save workflow state on every token/delta.
- Stream cancellation and failure paths are defined and safely traced.
- Reset clears short-term workflow state only.
- Reset does not delete long-term memory, document chunks, traces, configuration, or other sessions.
- Optional history projection is bounded, redacted, and disabled by default unless configured.
- History projection does not expose raw workflow state or hidden scratchpads.
- Session conflicts are detected through optimistic versioning or configured policy.
- Session errors map cleanly to API error responses.
- Session lifecycle trace events are safe and do not include raw message bodies by default.
- Session health/capability output is safe and does not expose session data.
- Unit tests cover lifecycle, mapping, streaming, reset, history, concurrency, and trace safety.
- Integration tests prove API/session/workflow-state continuity.
- The backend is ready for the next document: `backend-llm-gateway-architecture.md`.

---

## 42. Anti-Patterns to Avoid

Avoid these during implementation:

- Putting orchestration strategy logic in `SessionService`.
- Selecting concrete agents in `SessionService`.
- Selecting concrete LLM providers in `SessionService`.
- Calling OpenAI, Google, local OpenAI-compatible endpoints, or custom LLM endpoints from `SessionService`.
- Calling `MemoryGateway`, `memory_store`, ArcadeDB, or document chunk search directly from `SessionService`.
- Calling MCP tools directly from `SessionService`.
- Importing `sqlite3` in session modules.
- Returning raw workflow state from `get_history`.
- Logging raw chat messages by default.
- Storing hidden chain-of-thought or scratchpad content in user-visible history.
- Saving workflow state on every streamed token.
- Treating session reset as memory deletion.
- Deleting traces during session reset.
- Using session ID as authentication.
- Hard-coding usecase, agent, LLM profile, or provider names in session code.
- Letting session service know provider URLs or API keys.
- Implementing production distributed locks as ad hoc in-memory locks.
- Letting tests depend on local `./data` files without isolated temp directories.

---

## 43. Future Documents That Depend on This Session Layer

| Future Document | Dependency |
|---|---|
| `backend-llm-gateway-architecture.md` | Session service remains unchanged while orchestration starts calling provider-neutral LLM profiles. |
| `backend-memory-store-adapter-architecture.md` | Session reset remains workflow-state-only while memory is integrated behind `MemoryGateway`. |
| `backend-tooling-mcp-client-architecture.md` | Session service remains tool-neutral while agents call allowed MCP tools through `ToolGateway`. |
| `backend-orchestration-architecture.md` | Defines the full runtime called by `SessionService`. |
| `backend-workflow-strategies-architecture.md` | Adds strategy behavior behind orchestration without changing session lifecycle. |
| `backend-agents-architecture.md` | Adds agent plugins behind orchestration without changing API/session contracts. |
| `backend-policy-architecture.md` | Defines session ownership, history access, memory deletion, and route permissions. |
| `backend-deployment-architecture.md` | Defines process model, timeouts, concurrency, and runtime settings for sessions. |

---

## 44. Summary

`backend-session-service-architecture.md` defines the backend layer that turns validated API requests into traceable, stateful orchestration requests.

It owns session creation, resume, reset, workflow-state load/save, streaming finalization, optional safe history projection, and session-level conflict handling. It intentionally does not own orchestration decisions, LLM provider access, memory access, MCP tool calls, database implementation details, or frontend response formatting.

The most important implementation rule is:

> **The session service is the stateful handoff layer, not the brain. It manages session continuity and workflow-state boundaries, then delegates actual reasoning and action to orchestration.**
