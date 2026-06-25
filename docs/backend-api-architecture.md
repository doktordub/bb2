# Backend API Architecture

**Document:** `backend-api-architecture.md`  
**Version:** 1.0  
**Source alignment:** `backend-application-architecture.md`, `backend-foundation-architecture.md`, `backend-core-contracts-architecture.md`, `backend-configuration-architecture.md`, `backend-observability-architecture.md`, `backend-persistence-architecture.md`, `backend-sqlite-workflow-state-architecture.md`, and `backend-sqlite-trace-store-architecture.md`  
**Scope:** Backend HTTP/SSE API boundary, route contracts, request/response DTOs, middleware, trace correlation, error mapping, health aggregation, capabilities discovery, protected debug trace access, frontend integration rules, testing strategy, and acceptance criteria for the V1 API/session walking skeleton.

---

## 1. Purpose

This document defines the eighth implementation-focused architecture document for the backend application tier.

It follows:

1. `backend-foundation-architecture.md`
2. `backend-core-contracts-architecture.md`
3. `backend-configuration-architecture.md`
4. `backend-observability-architecture.md`
5. `backend-persistence-architecture.md`
6. `backend-sqlite-workflow-state-architecture.md`
7. `backend-sqlite-trace-store-architecture.md`
8. `backend-api-architecture.md` ← this document

The previous document implemented the concrete SQLite-backed `TraceStore`. The workflow-state document implemented the concrete SQLite-backed `WorkflowStateStore`. This document uses those foundations to define the first end-to-end backend HTTP/SSE walking skeleton.

The goal is to expose a thin, stable API surface that the frontend can call while preserving the core backend architecture rule:

> API routes validate requests, resolve request/session metadata, call `SessionService`, map results to HTTP or SSE responses, and record safe boundary telemetry. API routes must not perform orchestration decisions, run SQL, call LLM providers, call MCP tools, search memory, or manipulate workflow state directly.

---

## 2. Source Architecture Alignment

This document follows the established backend rules:

- The backend is one deployable application tier in V1.
- Frontend communicates with backend over REST / SSE.
- Backend communicates with the external MCP tier only through the MCP client adapter.
- Backend does not implement the MCP server.
- API routes are thin request/response boundaries.
- API routes do not select agents, strategies, tools, or LLM profiles.
- API routes do not import SQLite, ArcadeDB, provider SDKs, MCP clients, or `memory_store.service.MemoryService`.
- API routes do not call `WorkflowStateStore` directly for normal chat behavior; that belongs to `SessionService`.
- API routes may call health aggregators and capability providers that internally depend on configured services.
- API routes use `TraceStore` only through an observability facade or request tracing helper.
- Workflow state remains short-term session/runtime state.
- Traces remain operational diagnostics.
- Long-term memory and document chunks remain behind `MemoryGateway`.
- Session reset clears workflow state only and must not delete memory, document chunks, traces, LLM configuration, MCP configuration, or policy configuration.
- API responses and errors must not expose secrets, raw authorization headers, provider credentials, sensitive connection strings, raw workflow state, raw trace payloads, raw provider responses, or full downstream tool payloads.

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

This document expands Phase 8.

The output of this phase is a working backend API shell that supports:

```text
POST /chat
POST /chat/stream
POST /sessions/{session_id}/reset
GET  /health
GET  /capabilities
```

Optional protected debug routes may also be added after the trace store exists:

```text
GET /debug/traces/{trace_id}
GET /debug/traces
```

The next document should be:

```text
backend-session-service-architecture.md
```

---

## 4. Architecture Goals

The backend API should be:

1. **Thin**  
   Routes validate input, call services, and map outputs. They do not contain business workflow logic.

2. **Frontend-friendly**  
   REST and SSE contracts are predictable, documented, versionable, and easy for the Flask/HTML/CSS/JS frontend to consume.

3. **Session-aware**  
   API requests carry or receive a `session_id`, but session lifecycle logic belongs to `SessionService`.

4. **Trace-correlated**  
   Every request receives a `trace_id`; all request-boundary events and downstream service events use that trace ID.

5. **Safe by default**  
   API responses, errors, health output, debug output, and logs are redacted and bounded.

6. **Streaming-capable**  
   `/chat/stream` uses SSE for incremental response events without saving workflow state on every token.

7. **Configuration-driven**  
   Enabled routes, CORS, request size limits, debug routes, API docs, and timeout behavior are controlled through configuration.

8. **Service-oriented**  
   API routes call `SessionService`, `HealthService`, `CapabilityService`, and optional `DebugTraceService`; they do not call infrastructure adapters directly.

9. **Error-normalizing**  
   Known backend errors map to stable API error responses and appropriate HTTP status codes.

10. **Testable**  
   API tests can run with fake session, fake health, fake capabilities, and fake trace/debug services.

---

## 5. Non-Goals

This document should not implement:

- Full session history shaping policy.
- Full session lifecycle internals.
- Full orchestration runtime behavior.
- Real LLM provider integration.
- Real memory integration.
- Real MCP tool integration.
- Agent plugin details.
- Advanced authentication and authorization.
- Multi-tenant access-control model.
- Frontend UI rendering.
- MCP server implementation.
- Raw prompt/completion archival.
- A public trace browsing UI.
- Long-term memory deletion routes.
- Data export/delete privacy workflows.
- Production gateway/load-balancer configuration.

Those concerns belong to later session, LLM, memory, tooling/MCP, orchestration, agents, policy, and deployment documents.

---

## 6. API Boundary

The API layer is the backend's HTTP/SSE boundary.

It owns:

- Route registration.
- Request DTO validation.
- Response DTO shaping.
- HTTP status mapping.
- SSE event formatting.
- Request trace ID extraction/generation.
- Request timing metadata.
- Safe request-boundary telemetry.
- Health and capabilities response shaping.
- CORS and request size limits.
- API documentation exposure.

It does not own:

- Session state load/save/reset internals.
- Orchestration decisions.
- Agent selection.
- LLM profile selection.
- Tool allowlist decisions.
- Memory search or upsert behavior.
- SQLite queries.
- ArcadeDB access.
- MCP client calls.
- Provider SDK calls.
- Long-term memory deletion.

### 6.1 Boundary Diagram

```text
Frontend
  -> Backend API routes
      -> Request validation / trace boundary / response mapping
      -> SessionService
          -> WorkflowStateStore
          -> OrchestrationRuntime
              -> LLMGateway
              -> MemoryGateway
              -> ToolGateway
              -> TraceStore
```

### 6.2 Practical Rule

API routes should do this:

```python
result = await session_service.handle_chat(chat_request, request_context)
return ChatResponse.from_result(result)
```

API routes should not do this:

```python
state = await workflow_state.load(session_id=session_id)
llm_response = await openai_client.chat.completions.create(...)
conn.execute("SELECT state_json FROM workflow_state_current WHERE session_id = ?", ...)
```

---

## 7. Recommended Package Layout

Recommended implementation layout:

```text
backend/
  app/
    api/
      __init__.py
      app_factory.py
      dependencies.py
      middleware.py
      routes_chat.py
      routes_sessions.py
      routes_health.py
      routes_capabilities.py
      routes_debug_traces.py
      schemas.py
      sse.py
      errors.py
      openapi.py
      security.py
      versioning.py

    session/
      service.py
      models.py

    observability/
      trace_context.py
      request_logging.py
      events.py
      metrics.py
      redaction.py

    contracts/
      request.py
      results.py
      errors.py
      health.py
      trace.py

    config/
      schemas.py
      settings.py
      loader.py

    testing/
      fakes/
        fake_session_service.py
        fake_health_service.py
        fake_capability_service.py
        fake_debug_trace_service.py

  tests/
    unit/
      api/
        test_chat_schemas.py
        test_chat_route.py
        test_stream_route.py
        test_session_reset_route.py
        test_health_route.py
        test_capabilities_route.py
        test_error_mapping.py
        test_trace_id_middleware.py
        test_sse_formatting.py

    integration/
      api/
        test_api_walking_skeleton.py
        test_api_streaming_sse.py
        test_api_health_with_real_stores.py
        test_api_debug_traces_disabled.py
        test_api_debug_traces_enabled.py
```

### 7.1 Module Responsibilities

| Module | Responsibility |
|---|---|
| `app_factory.py` | Create and configure the FastAPI app. |
| `dependencies.py` | Provide route dependencies such as session service, config view, observability recorder, and request context. |
| `middleware.py` | Trace ID, request timing, CORS, size limits, and safe request logging. |
| `routes_chat.py` | `POST /chat` and `POST /chat/stream`. |
| `routes_sessions.py` | Session reset and optional history route. |
| `routes_health.py` | Health aggregation route. |
| `routes_capabilities.py` | Frontend capability discovery route. |
| `routes_debug_traces.py` | Optional protected trace read/search routes. |
| `schemas.py` | Pydantic request/response DTOs. |
| `sse.py` | SSE event normalization and encoding helpers. |
| `errors.py` | API error model and backend error mapping. |
| `openapi.py` | OpenAPI tags, examples, docs toggles. |
| `security.py` | V1 identity extraction and future auth hooks. |
| `versioning.py` | API version constants and response schema versioning. |

---

## 8. Dependency Direction Rules

Allowed:

```text
app/api/* -> app/session/service.py
app/api/* -> app/api/schemas.py
app/api/* -> app/contracts/errors.py
app/api/* -> app/contracts/results.py
app/api/* -> app/contracts/health.py
app/api/* -> app/observability/trace_context.py
app/api/* -> app/observability/events.py
app/api/* -> app/config/settings.py
```

Optional, through narrow service/facade interfaces:

```text
app/api/routes_health.py       -> HealthService
app/api/routes_capabilities.py -> CapabilityService
app/api/routes_debug_traces.py -> DebugTraceService
```

Avoid:

```text
app/api/* -> sqlite3
app/api/* -> arcadeDB client
app/api/* -> memory_store.service.MemoryService
app/api/* -> provider SDKs
app/api/* -> MCP client implementation
app/api/* -> AgentPlugin implementation
app/api/* -> OrchestrationStrategy implementation
app/api/* -> concrete SqliteWorkflowStateStore for chat/reset behavior
app/api/* -> concrete SqliteTraceStore query SQL
```

### 8.1 Dependency Rule by Route

| Route Group | Calls | Must Not Call |
|---|---|---|
| Chat routes | `SessionService` | SQLite, LLM providers, memory, MCP directly |
| Session routes | `SessionService` | Memory deletion, trace deletion, SQL directly |
| Health route | `HealthService` or service health facade | Raw DB clients from route code |
| Capabilities route | `CapabilityService` or config facade | Agent implementation internals |
| Debug trace routes | `DebugTraceService` | Raw SQL from route code |

---

## 9. API Configuration Integration

Recommended YAML:

```yaml
api:
  enabled: true
  host: ${env:BACKEND_HOST:0.0.0.0}
  port: ${env:BACKEND_PORT:8000}
  base_path: ""
  docs_enabled: true
  openapi_enabled: true

  cors:
    enabled: true
    allow_origins:
      - "http://localhost:5000"
      - "http://127.0.0.1:5000"
    allow_credentials: true
    allow_methods:
      - GET
      - POST
      - OPTIONS
    allow_headers:
      - Authorization
      - Content-Type
      - X-Request-Id
      - X-Trace-Id

  request_limits:
    max_body_bytes: 1048576
    max_message_chars: 20000
    max_metadata_bytes: 65536
    request_timeout_seconds: 120
    stream_timeout_seconds: 300

  sessions:
    accept_client_session_id: true
    create_session_when_missing: true
    session_id_header: X-Session-Id

  tracing:
    accept_client_trace_id: false
    response_trace_header: X-Trace-Id
    record_request_received: true
    record_response_returned: true
    record_validation_errors: true

  debug_routes:
    enabled: false
    require_localhost: true
    max_trace_events: 500
    max_search_results: 50

  sse:
    heartbeat_seconds: 15
    send_trace_id_event: true
    send_metadata_events: true
```

### 9.1 Settings Object

Recommended typed settings:

```python
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class CorsSettings:
    enabled: bool
    allow_origins: list[str]
    allow_credentials: bool
    allow_methods: list[str]
    allow_headers: list[str]


@dataclass(frozen=True, slots=True)
class ApiRequestLimitSettings:
    max_body_bytes: int
    max_message_chars: int
    max_metadata_bytes: int
    request_timeout_seconds: int
    stream_timeout_seconds: int


@dataclass(frozen=True, slots=True)
class ApiTracingSettings:
    accept_client_trace_id: bool
    response_trace_header: str
    record_request_received: bool
    record_response_returned: bool
    record_validation_errors: bool


@dataclass(frozen=True, slots=True)
class ApiDebugRouteSettings:
    enabled: bool
    require_localhost: bool
    max_trace_events: int
    max_search_results: int


@dataclass(frozen=True, slots=True)
class SseSettings:
    heartbeat_seconds: int
    send_trace_id_event: bool
    send_metadata_events: bool


@dataclass(frozen=True, slots=True)
class ApiSettings:
    enabled: bool
    host: str
    port: int
    base_path: str
    docs_enabled: bool
    openapi_enabled: bool
    cors: CorsSettings
    request_limits: ApiRequestLimitSettings
    tracing: ApiTracingSettings
    debug_routes: ApiDebugRouteSettings
    sse: SseSettings
```

### 9.2 Configuration Access Rule

The API layer receives resolved settings from the composition root.

Use:

```python
settings = config_view.api
app = create_api_app(settings=settings, container=container)
```

Avoid this inside route modules:

```python
os.getenv("BACKEND_PORT")
os.getenv("DEBUG_TRACE_ROUTES")
```

The configuration layer may read environment variables. Route modules should receive typed settings or dependencies.

---

## 10. Route Set

### 10.1 Required V1 Routes

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/chat` | Non-streaming chat request. |
| `POST` | `/chat/stream` | Streaming chat request over SSE. |
| `POST` | `/sessions/{session_id}/reset` | Clear short-term workflow state for a session. |
| `GET` | `/health` | Safe backend health aggregation. |
| `GET` | `/capabilities` | Frontend-visible backend capabilities and enabled features. |

### 10.2 Optional V1 Routes

| Method | Path | Default | Purpose |
|---|---|---|---|
| `GET` | `/sessions/{session_id}/history` | Disabled or minimal | Return bounded safe session history if policy allows. |
| `GET` | `/debug/traces/{trace_id}` | Disabled | Read a single trace for local debugging. |
| `GET` | `/debug/traces` | Disabled | Search recent traces for local debugging. |
| `GET` | `/version` | Optional | Return backend version/build metadata. |

### 10.3 Route Versioning

Recommended V1 path style:

```text
/chat
/chat/stream
/sessions/{session_id}/reset
/health
/capabilities
```

Avoid adding `/v1` immediately unless the frontend and deployment topology require explicit API versioning. Instead include schema version fields in responses:

```json
{
  "schema_version": "1.0",
  "data": {}
}
```

A future deployment document may introduce `/api/v1` at the reverse-proxy or application level.

---

## 11. API Route Ownership

### 11.1 Chat Route Ownership

`POST /chat` owns:

- Parse JSON body.
- Validate `message`, `session_id`, `usecase`, and metadata limits.
- Resolve request identity metadata.
- Generate or attach `trace_id`.
- Call `SessionService.handle_chat`.
- Map `SessionChatResult` to `ChatResponse`.
- Return `X-Trace-Id` and `X-Session-Id` headers.

`POST /chat` must not:

- Load workflow state directly.
- Save workflow state directly.
- Select an agent.
- Select an LLM profile.
- Search memory.
- Call MCP tools.
- Write SQL.

### 11.2 Stream Route Ownership

`POST /chat/stream` owns:

- Validate the request body.
- Resolve trace/session metadata.
- Call `SessionService.stream_chat`.
- Convert service stream events into SSE events.
- Emit heartbeat events as configured.
- Handle client disconnects safely.

`POST /chat/stream` must not:

- Stream raw provider chunks directly from a provider SDK.
- Save workflow state per token.
- Emit secrets or raw tool payloads in stream events.
- Continue expensive processing after cancellation unless the session service intentionally finalizes state.

### 11.3 Session Reset Route Ownership

`POST /sessions/{session_id}/reset` owns:

- Validate `session_id` path parameter.
- Validate optional reset reason.
- Resolve trace metadata.
- Call `SessionService.reset_session`.
- Return safe reset confirmation.

It must not delete:

```text
long-term memory
ArcadeDB document chunks
trace events
LLM configuration
MCP configuration
policy configuration
other sessions
```

### 11.4 Health Route Ownership

`GET /health` owns:

- Call health aggregation service.
- Map health to safe response.
- Return suitable status code based on readiness policy.

It must not:

- Return raw database paths if sensitive.
- Return state payloads.
- Return trace payloads.
- Return credentials or connection strings.

### 11.5 Capabilities Route Ownership

`GET /capabilities` owns:

- Return frontend-visible capabilities.
- Hide internal provider credentials and private configuration.
- List only safe logical names, enabled features, and allowed client behaviors.

---

## 12. Request and Response DTO Standards

Use Pydantic models for API DTOs.

DTO rules:

- Use explicit fields.
- Bound string lengths.
- Bound metadata size.
- Prefer `dict[str, Any]` only for intentionally flexible metadata.
- Keep API DTOs separate from internal orchestration models.
- Do not expose provider SDK response objects.
- Do not expose SQLite row models.
- Do not expose full workflow state.
- Include `trace_id` and `session_id` in normal responses.
- Use stable error response shape.

### 12.1 Common Response Envelope

Recommended response envelope:

```json
{
  "schema_version": "1.0",
  "trace_id": "trace_...",
  "session_id": "session_...",
  "data": {},
  "metadata": {}
}
```

For simple endpoints like `/health`, the route may return a direct health object with `trace_id` included.

### 12.2 Metadata Rule

API metadata may include safe diagnostic fields such as:

```text
agent_name
strategy_name
llm_profile
usecase
message_count
latency_ms
tool_call_count
memory_result_count
```

API metadata must not include:

```text
api_key
authorization
bearer token
raw prompt
raw completion
raw workflow state
raw trace payload
provider request body
provider response body
full MCP payload
raw document chunk text by default
```

---

## 13. Chat Request DTO

Recommended Pydantic model:

```python
from typing import Any
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=20000)
    session_id: str | None = Field(default=None, max_length=128)
    usecase: str | None = Field(default=None, max_length=100)
    metadata: dict[str, Any] = Field(default_factory=dict)
```

### 13.1 Chat Request JSON

```json
{
  "message": "Summarize this document.",
  "session_id": "session_123",
  "usecase": "document_qa",
  "metadata": {
    "client": "web",
    "timezone": "America/Chicago"
  }
}
```

### 13.2 Request Validation Rules

| Field | Rule |
|---|---|
| `message` | Required, non-empty, max length from config. |
| `session_id` | Optional; generated when missing if config allows. |
| `usecase` | Optional; default resolved by session/orchestration config. |
| `metadata` | Optional; JSON-safe and bounded by size. |

### 13.3 Session ID Rule

The API may accept client-provided `session_id` for frontend continuity. However, the session service remains responsible for deciding whether to create, resume, reject, or reset the session.

Recommended validation pattern:

```text
API validates identifier shape.
SessionService validates ownership and lifecycle.
WorkflowStateStore validates identifier before persistence.
```

---

## 14. Chat Response DTO

Recommended Pydantic model:

```python
from typing import Any
from pydantic import BaseModel, Field


class ChatResponseData(BaseModel):
    answer: str
    agent_name: str | None = None
    strategy_name: str | None = None
    llm_profile: str | None = None
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    memory_updates: list[dict[str, Any]] = Field(default_factory=list)


class ChatResponse(BaseModel):
    schema_version: str = "1.0"
    trace_id: str
    session_id: str
    data: ChatResponseData
    metadata: dict[str, Any] = Field(default_factory=dict)
```

### 14.1 Chat Response JSON

```json
{
  "schema_version": "1.0",
  "trace_id": "trace_01HX...",
  "session_id": "session_abc123",
  "data": {
    "answer": "Here is the summary...",
    "agent_name": "document_qa_agent",
    "strategy_name": "direct_agent",
    "llm_profile": "research_reasoning",
    "tool_calls": [],
    "memory_updates": []
  },
  "metadata": {
    "duration_ms": 842,
    "usecase": "document_qa"
  }
}
```

### 14.2 Tool and Memory Summary Rule

`tool_calls` and `memory_updates` should be summaries, not raw payload stores.

Safe tool summary example:

```json
{
  "tool_name": "document.search",
  "status": "completed",
  "duration_ms": 120,
  "result_count": 5
}
```

Unsafe tool summary example:

```json
{
  "request_headers": {"Authorization": "Bearer ..."},
  "raw_response_body": "..."
}
```

---

## 15. Streaming Chat Route

`POST /chat/stream` returns Server-Sent Events.

Recommended content type:

```text
text/event-stream; charset=utf-8
```

Recommended headers:

```text
Cache-Control: no-cache
Connection: keep-alive
X-Trace-Id: trace_...
X-Session-Id: session_...
```

### 15.1 Streaming Flow

```text
1. API validates request.
2. API resolves trace/session metadata.
3. API calls SessionService.stream_chat(...).
4. Session service loads workflow state once.
5. Orchestration runtime streams safe events.
6. API maps stream events to SSE wire format.
7. Session service saves final state once at completion/cancellation/failure boundary.
8. API emits completed or error event.
```

### 15.2 Streaming Must Not

- Write workflow state for every token.
- Write trace events for every token by default.
- Expose raw provider event objects.
- Expose raw prompt/completion internals.
- Expose tool payloads or credentials.
- Continue streaming after client disconnect.

---

## 16. SSE Event Contract

Recommended V1 event types:

```text
response.started
response.delta
response.metadata
response.completed
response.error
heartbeat
```

Optional event types for richer frontend behavior:

```text
agent.started
agent.completed
tool.started
tool.completed
memory.search.completed
```

These optional events must contain safe summaries only.

### 16.1 SSE Encoding

Recommended helper:

```python
import json
from typing import Any


def encode_sse(event: str, data: dict[str, Any], event_id: str | None = None) -> str:
    lines: list[str] = []
    if event_id:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    lines.append(f"data: {payload}")
    return "\n".join(lines) + "\n\n"
```

### 16.2 `response.started`

```text
event: response.started
data: {"trace_id":"trace_...","session_id":"session_...","schema_version":"1.0"}
```

### 16.3 `response.delta`

```text
event: response.delta
data: {"text":"partial answer text"}
```

### 16.4 `response.metadata`

```text
event: response.metadata
data: {"agent_name":"support_agent","strategy_name":"direct_agent"}
```

### 16.5 `response.completed`

```text
event: response.completed
data: {"trace_id":"trace_...","session_id":"session_...","finish_reason":"stop","duration_ms":1400}
```

### 16.6 `response.error`

```text
event: response.error
data: {"error":{"code":"backend_error","message":"The request failed.","retryable":true},"trace_id":"trace_..."}
```

### 16.7 Heartbeat

```text
event: heartbeat
data: {"trace_id":"trace_..."}
```

### 16.8 SSE Event Safety Rule

SSE events are client-visible. Treat every SSE field as public to the current user session.

Do not send:

```text
raw authorization headers
provider request bodies
provider responses
raw tool responses
raw workflow state
trace payloads
database paths
stack traces
secrets
```

---

## 17. Session Reset Route

Recommended route:

```text
POST /sessions/{session_id}/reset
```

Recommended request body:

```json
{
  "reason": "user_requested"
}
```

Recommended response:

```json
{
  "schema_version": "1.0",
  "trace_id": "trace_...",
  "session_id": "session_abc123",
  "data": {
    "reset": true,
    "message": "Session workflow state was reset."
  },
  "metadata": {}
}
```

### 17.1 Reset Handler Pattern

```python
@router.post("/sessions/{session_id}/reset")
async def reset_session(
    session_id: str,
    request: ResetSessionRequest,
    context: ApiRequestContext = Depends(get_api_request_context),
    session_service: SessionService = Depends(get_session_service),
) -> ResetSessionResponse:
    result = await session_service.reset_session(
        session_id=session_id,
        reason=request.reason,
        request_context=context,
    )
    return ResetSessionResponse.from_result(result)
```

### 17.2 Reset Boundary Rule

The reset route clears short-term workflow state through `SessionService` and `WorkflowStateStore` only.

It must not call:

```text
MemoryGateway.delete
TraceStore.delete
ArcadeDB delete APIs
LLM config mutation
MCP config mutation
policy config mutation
```

---

## 18. Optional Session History Route

Recommended optional route:

```text
GET /sessions/{session_id}/history?limit=50
```

Default V1 recommendation:

```text
Disabled or minimal until session-service policy is defined.
```

Reason: workflow state may contain raw conversation history, tool summaries, and pending approval context. The API should not expose raw workflow state as history.

### 18.1 If Enabled

The route should call:

```text
SessionService.get_history(session_id, limit)
```

It should return a normalized safe shape:

```json
{
  "schema_version": "1.0",
  "trace_id": "trace_...",
  "session_id": "session_abc123",
  "data": {
    "messages": [
      {
        "role": "user",
        "content": "Hello",
        "created_at": "2026-06-24T18:00:00-05:00"
      }
    ]
  },
  "metadata": {
    "limit": 50,
    "truncated": false
  }
}
```

### 18.2 History Must Not Return

- Full workflow state document.
- Internal state metadata.
- Sensitive tool payloads.
- Provider raw request/response objects.
- Credentials.
- Hidden chain-of-thought or scratchpad internals.

---

## 19. Health Route

Recommended route:

```text
GET /health
```

The health route should use a health aggregation service or facade.

Recommended response:

```json
{
  "status": "ok",
  "trace_id": "trace_...",
  "backend": {
    "configured": true
  },
  "api": {
    "configured": true,
    "docs_enabled": true,
    "streaming_enabled": true
  },
  "workflow_state": {
    "status": "ok",
    "provider": "sqlite",
    "configured": true,
    "schema_initialized": true
  },
  "trace": {
    "status": "ok",
    "provider": "sqlite",
    "configured": true,
    "schema_initialized": true
  },
  "memory": {
    "status": "unknown",
    "configured": false
  },
  "llm": {
    "status": "unknown",
    "providers_configured": false
  },
  "mcp": {
    "status": "unknown",
    "main_mcp_configured": false
  }
}
```

### 19.1 Health Status Mapping

| Aggregate Status | HTTP Status | Meaning |
|---|---:|---|
| `ok` | `200` | Required components are ready. |
| `degraded` | `200` or `503` by config | Optional or non-critical components are unhealthy. |
| `error` | `503` | Required components are not ready. |

### 19.2 Health Must Not Include

- Raw workflow state.
- Trace event payloads.
- Session IDs.
- User IDs.
- Raw DB paths if sensitive.
- Connection strings.
- API keys.
- Provider credentials.
- Stack traces.
- Raw SQL.

---

## 20. Capabilities Route

Recommended route:

```text
GET /capabilities
```

Purpose: allow the frontend to discover what the backend supports without reading private configuration.

Recommended response:

```json
{
  "schema_version": "1.0",
  "trace_id": "trace_...",
  "data": {
    "chat": {
      "enabled": true,
      "streaming_enabled": true,
      "max_message_chars": 20000
    },
    "sessions": {
      "reset_enabled": true,
      "history_enabled": false,
      "client_session_id_enabled": true
    },
    "usecases": [
      {
        "name": "default",
        "display_name": "Default Assistant",
        "description": "General assistant use case."
      }
    ],
    "debug": {
      "trace_routes_enabled": false
    }
  },
  "metadata": {}
}
```

### 20.1 Capability Safety Rule

The capabilities route may expose:

```text
logical use-case names
display names
frontend feature flags
message size limits
streaming availability
session reset availability
```

It must not expose:

```text
provider base URLs
API keys
model credentials
MCP access tokens
ArcadeDB paths
SQLite paths
internal prompt templates by default
policy internals
hidden tool credentials
```

---

## 21. Optional Protected Debug Trace Routes

The trace-store architecture enables safe trace read/search behavior. The API may expose protected debug routes for local development only.

Recommended defaults:

```yaml
api:
  debug_routes:
    enabled: false
    require_localhost: true
```

Recommended routes:

```text
GET /debug/traces/{trace_id}
GET /debug/traces?status=error&limit=25
```

### 21.1 Debug Trace Route Ownership

Debug trace routes should call a `DebugTraceService` that wraps `TraceStore` read/search behavior.

They should not contain raw SQL.

```python
trace = await debug_trace_service.read_trace(trace_id=trace_id, max_events=max_events)
```

### 21.2 Debug Trace Output

The output should preserve the trace store's redacted payloads and enforce additional API-level limits.

Recommended read response:

```json
{
  "schema_version": "1.0",
  "trace_id": "trace_...",
  "data": {
    "summary": {
      "status": "error",
      "started_at": "2026-06-24T18:00:00-05:00",
      "completed_at": "2026-06-24T18:00:02-05:00",
      "duration_ms": 2050,
      "error_type": "LLMProviderUnavailableError"
    },
    "events": [
      {
        "sequence_no": 1,
        "event_name": "request_received",
        "created_at": "2026-06-24T18:00:00-05:00",
        "payload": {
          "method": "POST",
          "path": "/chat"
        }
      }
    ]
  },
  "metadata": {
    "truncated": false
  }
}
```

### 21.3 Debug Trace Route Safety Rule

Do not expose debug trace routes in production until policy and access control are defined.

---

## 22. API Request Context

The API should build an API-level context for each request and pass safe fields to `SessionService`.

Recommended model:

```python
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ApiRequestContext:
    trace_id: str
    request_id: str
    user_id: str
    user_id_hash: str | None
    client_host: str | None
    user_agent: str | None
    path: str
    method: str
    headers_safe: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
```

### 22.1 Relationship to `RequestContext`

The existing core `RequestContext` remains the orchestration-facing request object:

```python
@dataclass
class RequestContext:
    user_id: str
    session_id: str
    message: str
    usecase: str | None
    metadata: dict[str, Any]
```

`SessionService` can map `ApiRequestContext` + `ChatRequest` into the orchestration-facing `RequestContext`.

Recommended metadata fields:

```json
{
  "trace_id": "trace_...",
  "request_id": "req_...",
  "client": "web",
  "timezone": "America/Chicago"
}
```

### 22.2 Identity Rule

For local V1, identity can be synthetic:

```text
anonymous
local_user
hash of configured local identity
```

Do not design API DTOs around a final auth model until the policy/auth document defines it.

---

## 23. Trace ID and Request Correlation

Every request must have a `trace_id`.

Recommended trace ID flow:

```text
1. Middleware checks X-Trace-Id only if config allows client trace IDs.
2. If absent or not accepted, middleware generates trace_id.
3. Middleware stores trace_id in request state/context variable.
4. API route passes trace_id to SessionService through ApiRequestContext.
5. SessionService and orchestration runtime pass trace_id to TraceStore events.
6. API response includes X-Trace-Id header and response field.
```

### 23.1 Trace ID Format

Recommended shape:

```text
trace_<ULID or UUID-safe string>
```

Validation:

```text
^[A-Za-z0-9_.:-]{8,128}$
```

### 23.2 Request ID vs Trace ID

| Identifier | Purpose |
|---|---|
| `trace_id` | Correlates all backend events for one logical request. |
| `request_id` | Identifies one HTTP request at the API boundary. |
| `session_id` | Identifies session continuity across requests. |

For non-streaming chat, `request_id` and `trace_id` may map one-to-one. For streaming or retries, keep them conceptually separate.

---

## 24. Middleware Pipeline

Recommended middleware order:

```text
1. Trusted host / proxy headers if configured
2. CORS
3. Request size limit
4. Trace ID / request ID creation
5. Request timing
6. Safe request logging
7. Route handling
8. Exception normalization
9. Response header injection
10. Safe response logging
```

### 24.1 Trace Middleware Responsibilities

```python
async def trace_middleware(request, call_next):
    trace_id = resolve_or_create_trace_id(request)
    request.state.trace_id = trace_id
    start = monotonic()
    try:
        response = await call_next(request)
        return response
    finally:
        duration_ms = elapsed_ms(start)
        # Record safe boundary metrics/logs; avoid recursive failure loops.
```

### 24.2 Request Body Logging Rule

Do not log raw request bodies.

Safe request log example:

```json
{
  "event": "api_request_completed",
  "trace_id": "trace_...",
  "method": "POST",
  "path": "/chat",
  "status_code": 200,
  "duration_ms": 842,
  "request_size_bytes": 1024
}
```

Unsafe request log example:

```json
{
  "body": {
    "message": "full user prompt with private data..."
  },
  "authorization": "Bearer ..."
}
```

---

## 25. Error Model

API errors should use one stable response shape.

Recommended model:

```python
class ApiErrorDetail(BaseModel):
    code: str
    message: str
    retryable: bool = False
    details: dict[str, Any] = Field(default_factory=dict)


class ApiErrorResponse(BaseModel):
    schema_version: str = "1.0"
    trace_id: str
    error: ApiErrorDetail
```

### 25.1 Error Response JSON

```json
{
  "schema_version": "1.0",
  "trace_id": "trace_...",
  "error": {
    "code": "validation_error",
    "message": "The request is invalid.",
    "retryable": false,
    "details": {
      "field": "message",
      "reason": "required"
    }
  }
}
```

### 25.2 Error Mapping

| Backend Error | HTTP Status | API Code | Retryable |
|---|---:|---|---|
| Request validation error | `422` | `validation_error` | false |
| Invalid session ID | `400` | `invalid_session_id` | false |
| Session not found | `404` | `session_not_found` | false |
| Session conflict | `409` | `session_conflict` | true/false by details |
| Policy denied | `403` | `policy_denied` | false |
| Unknown use case | `400` | `unknown_usecase` | false |
| Workflow state unavailable | `503` | `workflow_state_unavailable` | true |
| Trace store unavailable | `503` or non-fatal by route | `trace_store_unavailable` | true |
| LLM provider unavailable | `503` | `llm_unavailable` | true |
| Tool unavailable | `502` or `503` | `tool_unavailable` | true |
| MCP timeout | `504` | `tool_timeout` | true |
| Request timeout | `504` | `request_timeout` | true |
| Unexpected exception | `500` | `internal_error` | false |

### 25.3 Error Safety Rule

API errors must not include:

- Raw SQL.
- Full stack traces.
- Raw request body.
- Raw user prompt unless explicitly safe and needed.
- Raw provider response.
- Raw tool response.
- Credentials.
- Connection strings.
- Database file paths if sensitive.

Stack traces may be logged internally in debug mode after redaction, but must not be returned to the client.

---

## 26. Validation and Request Limits

The API layer is the first enforcement point for request shape and size.

Recommended limits:

| Limit | Default |
|---|---:|
| `max_body_bytes` | `1048576` |
| `max_message_chars` | `20000` |
| `max_metadata_bytes` | `65536` |
| `request_timeout_seconds` | `120` |
| `stream_timeout_seconds` | `300` |
| `max_trace_events` for debug route | `500` |
| `max_debug_search_results` | `50` |

### 26.1 Metadata Validation

Metadata must be:

```text
JSON-safe
bounded
redacted before logging/tracing
free of obvious credentials
```

Reject or redact keys matching sensitive fragments:

```text
api_key
authorization
bearer
client_secret
connection_string
cookie
credential
jwt
password
refresh_token
secret
token
```

### 26.2 Path Parameter Validation

Validate path identifiers before service calls:

```python
_SESSION_ID_PATTERN = r"^[A-Za-z0-9_.:-]{3,128}$"
_TRACE_ID_PATTERN = r"^[A-Za-z0-9_.:-]{8,128}$"
```

Still use parameterized SQL in stores. API validation is not a substitute for adapter-level validation.

---

## 27. Authentication and Identity Boundary

V1 may run in local/development mode with synthetic identity.

Recommended V1 identity model:

```text
No production auth assumption in API architecture.
Use an identity extraction hook.
Default identity: local_user or anonymous.
Pass identity into SessionService as metadata.
Do not persist raw auth tokens.
```

### 27.1 Future Auth Hook

Recommended dependency:

```python
async def get_current_identity(request: Request) -> ApiIdentity:
    return ApiIdentity(
        user_id="local_user",
        user_id_hash="...",
        auth_mode="local",
    )
```

Future policy/auth documents may replace the implementation with JWT, OAuth, or reverse-proxy identity extraction without changing route logic.

### 27.2 Authorization Boundary

The API may perform coarse route authorization in the future. Fine-grained permissions belong to `PolicyService`.

Examples:

```text
Route auth: can caller access /debug/traces?
Policy service: can this agent call this tool or use this LLM profile?
```

---

## 28. CORS and Frontend Integration

The frontend is a separate deployable tier and calls backend through REST/SSE.

Recommended local origins:

```text
http://localhost:5000
http://127.0.0.1:5000
```

If the frontend uses another local port, it should be added through configuration, not hard-coded in route modules.

### 28.1 Headers Exposed to Frontend

Recommended exposed headers:

```text
X-Trace-Id
X-Session-Id
Content-Type
```

### 28.2 Frontend Responsibilities

The frontend should:

- Store `session_id` for current chat session.
- Send `session_id` on subsequent requests.
- Use `POST /sessions/{session_id}/reset` for Clear button behavior.
- Render SSE events from `/chat/stream`.
- Show user-friendly error messages and optionally display trace ID for debugging.

The frontend should not:

- Call SQLite databases.
- Call MCP server directly.
- Call LLM providers directly.
- Store backend secrets.

---

## 29. OpenAPI Documentation

OpenAPI should be available in local/dev mode by default.

Recommended settings:

```yaml
api:
  docs_enabled: true
  openapi_enabled: true
```

### 29.1 Documentation Rules

OpenAPI docs should include:

- Route descriptions.
- DTO schemas.
- Example requests.
- Example responses.
- Error response shapes.
- SSE event examples in route descriptions.

OpenAPI docs must not include:

- Provider API keys.
- Internal prompt templates by default.
- Hidden model credentials.
- Private MCP access tokens.
- Raw deployment secrets.

### 29.2 Tags

Recommended tags:

```text
chat
sessions
health
capabilities
debug
```

---

## 30. Session Service Integration

The API layer depends on `SessionService` for chat and session lifecycle behavior.

Expected non-streaming flow:

```text
POST /chat
  -> API validates ChatRequest
  -> API builds ApiRequestContext with trace_id
  -> SessionService.handle_chat(request, context)
  -> SessionService loads workflow state
  -> SessionService calls OrchestrationRuntime
  -> SessionService saves updated workflow state
  -> API maps result to ChatResponse
```

Expected reset flow:

```text
POST /sessions/{session_id}/reset
  -> API validates path/body
  -> API builds ApiRequestContext with trace_id
  -> SessionService.reset_session(session_id, reason, context)
  -> SessionService calls WorkflowStateStore.reset
  -> API maps result to ResetSessionResponse
```

Expected streaming flow:

```text
POST /chat/stream
  -> API validates ChatRequest
  -> API builds ApiRequestContext with trace_id
  -> SessionService.stream_chat(request, context)
  -> API maps service stream events to SSE
```

### 30.1 API-to-Session Contract

Recommended service interface:

```python
class SessionService(Protocol):
    async def handle_chat(
        self,
        *,
        request: ChatRequest,
        context: ApiRequestContext,
    ) -> SessionChatResult:
        ...

    async def stream_chat(
        self,
        *,
        request: ChatRequest,
        context: ApiRequestContext,
    ) -> AsyncIterator[SessionStreamEvent]:
        ...

    async def reset_session(
        self,
        *,
        session_id: str,
        reason: str | None,
        context: ApiRequestContext,
    ) -> SessionResetResult:
        ...
```

### 30.2 Temporary Walking Skeleton Session Service

For the first API walking skeleton, `SessionService` may use a stub orchestrator or echo agent while still exercising real state and trace stores.

Recommended first vertical slice:

```text
POST /chat
  -> SessionService
  -> WorkflowStateStore.load
  -> StubOrchestrator or EchoAgent
  -> WorkflowStateStore.save
  -> TraceStore records request/state/response summaries
  -> ChatResponse
```

---

## 31. Workflow State and Trace Boundaries

### 31.1 Workflow State Boundary

API routes must not call `WorkflowStateStore` for normal chat behavior.

Correct:

```text
API -> SessionService -> WorkflowStateStore
```

Avoid:

```text
API -> WorkflowStateStore
```

Exception:

```text
HealthService may call WorkflowStateStore.health through a health facade.
```

### 31.2 Trace Boundary

API routes may emit request-boundary telemetry through an observability facade.

Correct:

```text
API middleware -> ObservabilityRecorder -> TraceStore
```

Avoid:

```text
API route -> SqliteTraceStore SQL
```

### 31.3 Cross-Store Rule

The API must not coordinate cross-store transactions.

Do not attempt:

```text
one API transaction spanning workflow_state.db, trace.db, and ArcadeDB
```

Trace failures should be handled as observability failures unless the route specifically depends on trace reading, such as debug trace routes.

---

## 32. Orchestration Boundary

The API layer does not call `OrchestrationRuntime` directly in the final architecture.

Preferred path:

```text
API -> SessionService -> OrchestrationRuntime
```

Reason:

- Session service owns session creation/resume/reset.
- Session service owns workflow-state handoff.
- Session service can enforce history shaping before orchestration.
- Session service can finalize state after streaming completion.

### 32.1 Temporary Exception for Early Skeleton

A temporary early skeleton may wire API directly to a stub service that internally behaves like `SessionService`. Do not let this temporary shortcut become the long-term route architecture.

---

## 33. LLM, Memory, Tool, and MCP Boundaries

API routes must not directly call:

```text
LLMGateway
MemoryGateway
ToolGateway
MCPClientAdapter
provider SDKs
memory_store
ArcadeDB
```

The only normal path is:

```text
API -> SessionService -> OrchestrationRuntime -> Gateways
```

### 33.1 Why This Matters

This preserves:

- Provider-neutral agent behavior.
- Tool allowlist enforcement.
- LLM profile policy enforcement.
- Memory scope enforcement.
- Trace consistency.
- Testability with fake gateways.

---

## 34. Streaming Lifecycle and Cancellation

Streaming needs explicit lifecycle handling.

Recommended lifecycle events:

```text
stream_started
stream_first_delta_sent
stream_completed
stream_cancelled
stream_failed
```

### 34.1 Client Disconnect

When the client disconnects:

```text
1. API detects disconnect if framework supports it.
2. API cancels or signals cancellation to SessionService.
3. SessionService decides whether to save cancellation metadata.
4. Trace event `stream_cancelled` is recorded safely.
5. No further SSE events are sent.
```

### 34.2 Save-on-Completion Rule

For streaming chat:

```text
Load state once near start.
Save final state once at completion.
Save failure/cancellation checkpoint only if safe and useful.
Do not save on every token.
```

### 34.3 Heartbeat Rule

Heartbeat events should be sent only to keep the HTTP connection alive.

They should not contain sensitive metadata.

---

## 35. Response Header Policy

Recommended headers for successful chat responses:

```text
X-Trace-Id: trace_...
X-Session-Id: session_...
Content-Type: application/json
```

Recommended headers for SSE:

```text
X-Trace-Id: trace_...
X-Session-Id: session_...
Content-Type: text/event-stream; charset=utf-8
Cache-Control: no-cache
Connection: keep-alive
```

### 35.1 Header Safety Rule

Do not expose:

```text
provider IDs if sensitive
internal file paths
API keys
policy internals
raw error traces
```

---

## 36. Observability Integration

The API layer should emit safe boundary events and metrics.

### 36.1 Recommended Trace Events

| Event | Emitted By | Notes |
|---|---|---|
| `request_received` | API middleware/route | Safe method/path/size metadata only. |
| `request_validated` | API route | Optional. No body payload. |
| `response_returned` | API middleware/route | Status code and duration only. |
| `stream_started` | Stream route/session | Safe stream metadata. |
| `stream_completed` | Stream route/session | Duration and finish reason. |
| `stream_cancelled` | Stream route/session | Cancellation summary. |
| `api_validation_failed` | Exception handler | Field/reason summary. |
| `error_occurred` | Exception handler | Safe error type/code. |

### 36.2 API Metrics

Recommended metrics:

```text
backend.api.requests.total
backend.api.requests.duration_ms
backend.api.requests.in_flight
backend.api.errors.total
backend.api.validation_errors.total
backend.api.streams.total
backend.api.streams.duration_ms
backend.api.streams.cancelled_total
backend.api.response.bytes
```

Allowed metric tags:

```text
method
route
status_code
success
error_type
streaming
```

Avoid metric tags:

```text
session_id
trace_id
raw_user_id
message text
provider URL
API key
```

---

## 37. Security and Privacy

### 37.1 Redaction

All request metadata, headers, trace payloads, logs, and errors should pass through the redaction layer before storage or output.

Default sensitive fragments:

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

### 37.2 Request Body Privacy

The API should not log raw chat messages by default.

Trace events may include message metadata such as:

```json
{
  "message_chars": 240,
  "metadata_keys_count": 3
}
```

but not:

```json
{
  "message": "full user prompt..."
}
```

### 37.3 Debug Route Privacy

Debug trace routes are still API routes. They must enforce:

- Config-based enablement.
- Localhost or future auth requirement.
- Bounded result size.
- Redacted payloads only.
- No raw SQL or stack traces.

---

## 38. Concurrency, Timeouts, and Idempotency

### 38.1 Concurrency

The API should allow concurrent requests, but session-level conflict handling belongs to `SessionService` and `WorkflowStateStore`.

API behavior:

```text
Receive concurrent requests.
Pass each request to SessionService with trace/session metadata.
Map known session conflict errors to 409.
Do not implement ad hoc locks in route code.
```

### 38.2 Timeouts

Recommended timeout boundaries:

| Operation | Owner |
|---|---|
| HTTP request timeout | API/middleware/server config |
| Streaming timeout | API/session streaming boundary |
| LLM timeout | LLM Gateway |
| MCP/tool timeout | Tool Gateway / MCP adapter |
| SQLite busy timeout | Store adapter config |

### 38.3 Idempotency

V1 does not require idempotency keys for chat.

Future route support may add:

```text
Idempotency-Key header
request replay protection
session-level duplicate detection
```

Do not implement partial idempotency in API routes without session-service support.

---

## 39. Health Aggregation Service

Recommended service interface:

```python
class HealthService(Protocol):
    async def get_health(self) -> dict[str, object]:
        ...
```

The health service may call:

```text
WorkflowStateStore.health
TraceStore.health
MemoryGateway.health
LLMGateway.health
ToolGateway.health
MCPClientAdapter.health
Configuration health checks
```

The API route only maps the returned health result to HTTP.

### 39.1 Required vs Optional Components

Recommended V1 readiness policy:

| Component | Required Early V1 | Notes |
|---|---|---|
| API config | yes | Backend cannot serve without it. |
| Workflow state store | yes | Required for session continuity. |
| Trace store | yes or degraded by config | Recommended required after trace-store phase. |
| Session service | yes | Required for chat routes. |
| LLM gateway | optional until LLM phase | May be fake/stub in API walking skeleton. |
| Memory gateway | optional until memory phase | May be fake/disabled. |
| Tool gateway/MCP | optional until tooling phase | May be fake/disabled. |

---

## 40. Startup Integration

Recommended startup sequence:

```text
1. Load settings and YAML configuration.
2. Build observability/redactor/metrics.
3. Build SQLite workflow state store and validate health.
4. Build SQLite trace store and validate health.
5. Build fake or real session service depending on phase.
6. Build health service.
7. Build capability service.
8. Build optional debug trace service if enabled.
9. Create FastAPI app.
10. Register middleware.
11. Register exception handlers.
12. Register routes.
13. Register OpenAPI metadata.
14. Log redacted startup summary.
```

### 40.1 Composition Root Pattern

```python
def build_app() -> FastAPI:
    settings = load_settings()
    config = load_and_validate_config(settings.app_config_path)

    redactor = build_redactor(config)
    trace_store = build_trace_store(config)
    workflow_state = build_workflow_state_store(config)

    session_service = build_session_service(
        config=config,
        workflow_state=workflow_state,
        trace_store=trace_store,
    )

    health_service = build_health_service(
        config=config,
        workflow_state=workflow_state,
        trace_store=trace_store,
    )

    capability_service = build_capability_service(config=config)

    app = create_api_app(
        settings=config.api,
        services=ApiServices(
            session=session_service,
            health=health_service,
            capabilities=capability_service,
            trace_debug=build_debug_trace_service(config, trace_store),
        ),
        redactor=redactor,
    )
    return app
```

---

## 41. Recommended Implementation Order

### Step 1: Add API Settings

Deliverables:

- `ApiSettings`
- CORS settings
- Request limit settings
- Debug route settings
- SSE settings

Success criteria:

- Config can enable/disable docs and debug routes.
- Invalid CORS and timeout values fail fast.

### Step 2: Add API Schemas

Deliverables:

- `ChatRequest`
- `ChatResponse`
- `ResetSessionRequest`
- `ResetSessionResponse`
- `HealthResponse`
- `CapabilitiesResponse`
- `ApiErrorResponse`
- SSE event schema helpers

Success criteria:

- DTOs validate required fields and limits.
- Response examples serialize cleanly.

### Step 3: Add Error Mapping

Deliverables:

- Known backend error mapper
- Exception handlers
- Safe fallback `internal_error`

Success criteria:

- Validation errors return 422.
- Known service errors map to stable HTTP status codes.
- Unexpected errors do not leak stack traces.

### Step 4: Add Middleware

Deliverables:

- Trace ID middleware
- Request timing
- Response header injection
- Safe request logging
- CORS
- Request size guard

Success criteria:

- Every response includes `X-Trace-Id`.
- Request bodies are not logged.
- Oversized requests are rejected safely.

### Step 5: Add Fake Session Service

Deliverables:

- `FakeSessionService`
- Non-streaming echo response
- Streaming echo response
- Reset result stub

Success criteria:

- API tests can run without real orchestration.
- Session ID is stable in response.

### Step 6: Add `POST /chat`

Deliverables:

- Route handler
- Service dependency
- Response mapping
- Trace event boundaries

Success criteria:

- Valid request returns `ChatResponse`.
- Missing session ID can produce a new session ID.
- Invalid request returns safe error.

### Step 7: Add `POST /chat/stream`

Deliverables:

- Route handler
- SSE encoder
- Heartbeat support
- Stream error event mapping

Success criteria:

- Route returns valid `text/event-stream`.
- Delta and completion events are well-formed.
- Stream errors return `response.error` event.

### Step 8: Add Session Reset Route

Deliverables:

- `POST /sessions/{session_id}/reset`
- Session ID validation
- Reset response mapping

Success criteria:

- Valid reset calls `SessionService.reset_session`.
- Invalid session ID returns 400.
- Reset route does not call memory or trace deletion.

### Step 9: Add Health Route

Deliverables:

- `HealthService`
- `GET /health`
- HTTP status mapping

Success criteria:

- Healthy stores return `ok`.
- Required component failure returns 503.
- Health response is redacted.

### Step 10: Add Capabilities Route

Deliverables:

- `CapabilityService`
- `GET /capabilities`
- Frontend feature flags

Success criteria:

- Frontend can discover streaming/reset availability.
- Sensitive config is not exposed.

### Step 11: Add Optional Debug Trace Routes

Deliverables:

- `DebugTraceService`
- `GET /debug/traces/{trace_id}`
- `GET /debug/traces`
- Config guard

Success criteria:

- Routes are disabled by default.
- Enabled routes return bounded redacted trace data.
- No raw SQL exists in route handlers.

### Step 12: Replace Fake Session With Walking Skeleton Session

Deliverables:

- Session service loads workflow state.
- Stub orchestrator or echo agent runs.
- Session service saves workflow state.
- Trace store records safe request lifecycle events.

Success criteria:

- `POST /chat` exercises real workflow-state and trace stores.
- `/chat/stream` exercises route/SSE boundary.
- `/sessions/{session_id}/reset` clears workflow state only.

---

## 42. Testing Strategy

### 42.1 Unit Tests

| Test | Purpose |
|---|---|
| Chat request validates message | Proves required body behavior. |
| Chat request rejects oversized message | Enforces API limits. |
| Metadata rejects obvious secrets | Prevents credential leakage. |
| Chat route calls session service once | Proves thin route behavior. |
| Chat route maps result to response | Proves DTO mapping. |
| Stream route emits valid SSE | Proves wire-format helper. |
| Stream route emits error event | Proves streaming error handling. |
| Reset route validates session ID | Prevents unsafe identifiers. |
| Reset route calls session service | Proves route boundary. |
| Health route maps aggregate status | Proves readiness behavior. |
| Capabilities route hides secrets | Proves safe config exposure. |
| Error mapper handles known errors | Proves stable API error contract. |
| Trace middleware injects header | Proves request correlation. |
| Request body is not logged | Proves privacy behavior. |
| Debug trace routes disabled by default | Prevents accidental exposure. |

### 42.2 Integration Tests

| Test | Purpose |
|---|---|
| API starts with configured app | Proves composition root wiring. |
| `POST /chat` returns 200 with fake session | Proves route skeleton. |
| `POST /chat` with real stores persists state | Proves walking skeleton persistence. |
| `POST /chat/stream` returns SSE events | Proves streaming route. |
| Reset clears workflow state only | Proves reset boundary. |
| Health includes workflow and trace sections | Proves health aggregation. |
| Capabilities returns frontend flags | Proves discovery route. |
| Trace ID appears in response and trace store | Proves request correlation. |
| Validation error records safe trace event | Proves error observability. |
| Debug trace read works only when enabled | Proves protected debug behavior. |
| CORS allows configured frontend origin | Proves frontend integration. |

### 42.3 Fixture Configs

Recommended fixtures:

```text
tests/fixtures/config/api_basic.yaml
tests/fixtures/config/api_streaming_enabled.yaml
tests/fixtures/config/api_debug_traces_disabled.yaml
tests/fixtures/config/api_debug_traces_enabled.yaml
tests/fixtures/config/api_small_request_limits.yaml
tests/fixtures/config/api_cors_localhost.yaml
tests/fixtures/config/api_with_real_sqlite_stores.yaml
```

---

## 43. Acceptance Criteria

This architecture is complete when:

- API routes are registered for `/chat`, `/chat/stream`, `/sessions/{session_id}/reset`, `/health`, and `/capabilities`.
- Optional debug trace routes are disabled by default and protected when enabled.
- API routes are thin and delegate chat/reset behavior to `SessionService`.
- API routes do not import SQLite, ArcadeDB, provider SDKs, MCP clients, `memory_store.service.MemoryService`, agent implementations, or strategy implementations.
- API request and response DTOs are explicit and validated.
- Responses include `trace_id` and `session_id` where applicable.
- Response headers include `X-Trace-Id` and `X-Session-Id` where applicable.
- Middleware creates or resolves trace IDs for every request.
- Request-boundary trace events are safe and redacted.
- Request bodies are not logged by default.
- Validation errors map to stable API error responses.
- Known backend errors map to appropriate HTTP status codes.
- Unexpected errors do not expose stack traces or secrets.
- `/chat` can run through a fake or walking-skeleton session service.
- `/chat/stream` emits valid SSE events.
- Streaming routes do not save workflow state per token.
- Reset route clears short-term workflow state only through `SessionService`.
- Reset route does not delete memory, document chunks, traces, LLM config, MCP config, policy config, or other sessions.
- Health route aggregates safe component health without exposing sensitive paths, payloads, or credentials.
- Capabilities route exposes frontend-safe feature flags and logical use-case metadata only.
- CORS is configurable for the separate frontend tier.
- OpenAPI docs are configurable and safe.
- API tests can use fake services.
- Integration tests verify real workflow-state and trace-store walking skeleton behavior.
- The backend is ready for the next document: `backend-session-service-architecture.md`.

---

## 44. Anti-Patterns to Avoid

Avoid these during implementation:

- Putting business workflow branching inside API routes.
- Selecting agents in API routes.
- Selecting LLM profiles in API routes.
- Calling LLM providers directly from API routes.
- Calling MCP tools directly from API routes.
- Searching or writing memory directly from API routes.
- Running SQL from API routes.
- Importing `sqlite3` in API route modules.
- Returning full workflow state from API responses.
- Returning trace payloads from `/health`.
- Enabling debug trace routes by default in production-like settings.
- Logging raw request bodies.
- Logging raw chat messages by default.
- Returning stack traces to clients.
- Returning provider SDK errors verbatim.
- Sending raw tool payloads over SSE.
- Writing workflow state on every streamed token.
- Deleting memory during session reset.
- Deleting traces during session reset.
- Hard-coding frontend origins.
- Hard-coding provider URLs or model names in API routes.
- Letting API tests depend on real local `./data` files.

---

## 45. Future Documents That Depend on This API Layer

| Future Document | Dependency |
|---|---|
| `backend-session-service-architecture.md` | Deepens `SessionService.handle_chat`, `stream_chat`, reset, session creation/resume, history shaping, and state handoff. |
| `backend-llm-gateway-architecture.md` | API remains unchanged while session/orchestration calls provider-neutral LLM profiles. |
| `backend-memory-store-adapter-architecture.md` | API remains unchanged while agents search/upsert memory through `MemoryGateway`. |
| `backend-tooling-mcp-client-architecture.md` | API remains unchanged while agents call allowed MCP tools through `ToolGateway`. |
| `backend-orchestration-architecture.md` | Session service continues to call orchestration behind the API boundary. |
| `backend-workflow-strategies-architecture.md` | API remains strategy-neutral and reports only safe strategy metadata. |
| `backend-agents-architecture.md` | New agents can be added without changing API routes. |
| `backend-policy-architecture.md` | Defines auth, route permissions, debug-route access, trace capture policy, and data exposure rules. |
| `backend-deployment-architecture.md` | Defines host/port, reverse proxy, CORS, TLS, process model, and environment-specific API settings. |

---

## 46. Summary

`backend-api-architecture.md` defines the backend's HTTP/SSE boundary and the first end-to-end API walking skeleton.

It exposes stable frontend-facing routes for chat, streaming chat, session reset, health, and capabilities while keeping route handlers thin and infrastructure-agnostic. It uses the previously defined workflow-state and trace-store foundations without leaking SQLite details into the API layer.

The most important implementation rule is:

> **The API is a boundary, not the brain. It validates requests, creates traceable request context, delegates to `SessionService`, and returns safe REST/SSE responses. Orchestration, persistence, memory, tools, LLM access, and policy decisions stay behind their dedicated services and gateways.**
