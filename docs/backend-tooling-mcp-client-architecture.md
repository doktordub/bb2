# Backend Tooling and MCP Client Architecture

**Document:** `backend-tooling-mcp-client-architecture.md`  
**Version:** 1.0  
**Source alignment:** `backend-application-architecture.md`, `backend-foundation-architecture.md`, `backend-core-contracts-architecture.md`, `backend-configuration-architecture.md`, `backend-observability-architecture.md`, `backend-persistence-architecture.md`, `backend-sqlite-workflow-state-architecture.md`, `backend-sqlite-trace-store-architecture.md`, `backend-api-architecture.md`, `backend-session-service-architecture.md`, `backend-llm-gateway-architecture.md`, and `backend-memory-store-adapter-architecture.md`  
**Scope:** Provider-neutral backend tool access, `ToolGateway`, MCP client adapter, single external MCP server integration, tool discovery, tool registry, tool schemas, tool policy checks, OAuth/JWT credential handling, timeout/retry/cancellation behavior, result normalization, trace correlation, safe summaries, health checks, testing strategy, and acceptance criteria for the V1 tooling layer.

---

## 1. Purpose

This document defines the twelfth implementation-focused architecture document for the backend application tier.

It follows:

1. `backend-foundation-architecture.md`
2. `backend-core-contracts-architecture.md`
3. `backend-configuration-architecture.md`
4. `backend-observability-architecture.md`
5. `backend-persistence-architecture.md`
6. `backend-sqlite-workflow-state-architecture.md`
7. `backend-sqlite-trace-store-architecture.md`
8. `backend-api-architecture.md`
9. `backend-session-service-architecture.md`
10. `backend-llm-gateway-architecture.md`
11. `backend-memory-store-adapter-architecture.md`
12. `backend-tooling-mcp-client-architecture.md` ← this document

The previous document established `MemoryGateway` as the only orchestration-facing boundary for long-term memory and document chunk access. It also preserved the tooling boundary: memory search and memory writes must not execute MCP tools.

This document defines that tooling boundary.

The goal is to allow orchestration strategies and agent plugins to call external capabilities through a backend-owned tool abstraction while keeping the MCP server as a separate deployable tier.

The core architecture rule is:

> `ToolGateway` is the only orchestration-facing boundary for tool execution. `MCPClientAdapter` is the only backend adapter that speaks MCP protocol to the single external MCP server. Agents and strategies request logical tool calls; they must not import MCP server code, call MCP endpoints directly, manage OAuth/JWT tokens, or depend on provider-specific tool response objects.

---

## 2. Source Architecture Alignment

This document follows the established backend rules:

- The backend is one deployable application tier in V1.
- Frontend communicates with backend through REST / SSE.
- The MCP server is a separate deployable tier.
- Backend communicates with MCP only through a backend MCP client adapter.
- V1 uses one MCP endpoint, not separate support/document MCP endpoints.
- API routes are thin and delegate chat/reset behavior to `SessionService`.
- `SessionService` calls `OrchestrationRuntime` and does not execute tools directly for normal chat behavior.
- `OrchestrationRuntime`, strategies, and agents access external tools through `ToolGateway` only.
- `ToolGateway` exposes provider-neutral tool contracts to the rest of the backend.
- `MCPClientAdapter` owns MCP protocol communication and hides FastMCP/protocol details from agents, strategies, sessions, and API routes.
- LLM calls remain behind `LLMGateway`; the tooling layer must not call concrete LLM providers directly.
- Long-term memory remains behind `MemoryGateway`; the tooling layer must not search or write memory directly.
- SQLite remains the backend store for workflow state and trace data only.
- ArcadeDB-backed memory remains behind the memory adapter and must not leak into tool execution code.
- Workflow state remains short-term session/runtime state.
- Traces remain operational diagnostics.
- Tool calls must be trace-correlated with the active `trace_id`.
- Tool trace events must be safe, bounded, and redacted.
- Raw tool payloads must not be logged, traced, streamed, or returned to the frontend by default.
- Tool authorization, allowlists, user scope, project scope, and argument validation must happen before MCP execution.
- MCP credentials, OAuth tokens, JWTs, authorization headers, refresh tokens, and raw downstream error payloads must never be returned to the frontend.

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
Phase 11: Memory Gateway and Memory Store Adapter
Phase 12: Tool Gateway and MCP Client Adapter
Phase 13: Orchestration Runtime and Strategies
Phase 14: Agent Plugins
Phase 15: Hardening and Deployment Readiness
```

This document expands Phase 12.

The output of this phase is a backend tooling layer that supports:

```text
ToolGateway.list_tools(...)
ToolGateway.get_tool(...)
ToolGateway.execute(...)
ToolGateway.stream_execute(...)
ToolGateway.health(...)
ToolGateway.capabilities(...)

ToolRegistry.register(...)
ToolRegistry.resolve(...)
ToolRegistry.list(...)

MCPClientAdapter.list_tools(...)
MCPClientAdapter.call_tool(...)
MCPClientAdapter.stream_tool(...)
MCPClientAdapter.health(...)
```

The next document should be:

```text
backend-orchestration-runtime-architecture.md
```

---

## 4. Architecture Goals

The tooling layer should be:

1. **Provider-neutral to callers**  
   Agents and strategies use logical backend tool contracts, not MCP protocol objects or FastMCP implementation details.

2. **Single-MCP-endpoint focused**  
   V1 communicates with one configured MCP server endpoint through one MCP client adapter.

3. **Policy-first**  
   Tool availability, argument access, user scope, project scope, and tool execution must be checked before MCP calls.

4. **Schema-aware**  
   Tool inputs and outputs are validated against normalized schemas before execution and before returning results upstream.

5. **Trace-correlated**  
   Every tool execution emits safe trace events with the active `trace_id` and safe tool metadata.

6. **Redacted by default**  
   Secrets, raw tool arguments, raw tool results, authorization headers, and downstream payloads are not logged or traced by default.

7. **Composable with orchestration**  
   Orchestration strategies and agents can call tools as part of a workflow without embedding MCP protocol details.

8. **LLM-tool boundary preserving**  
   LLMs may propose tool intents, but tool execution happens only through `ToolGateway` and policy checks.

9. **Memory boundary preserving**  
   Tools may receive memory-derived context only when orchestration explicitly passes it; `ToolGateway` does not search memory.

10. **Timeout and cancellation aware**  
    Tool calls are bounded, cancellable, and mapped to normalized errors.

11. **Testable**  
    The gateway can run with fake MCP adapters and deterministic fixture tools.

12. **Extensible**  
    Additional tool transports or multiple MCP servers can be added later behind new adapters without changing agents or API routes.

---

## 5. Non-Goals

This document should not implement:

- API route behavior.
- Session lifecycle behavior.
- Full orchestration strategy behavior.
- Agent prompt design.
- LLM provider integration.
- Memory search or memory writes.
- MCP server implementation.
- FastMCP server internals.
- SQLite workflow-state persistence.
- SQLite trace-store SQL behavior.
- ArcadeDB memory implementation.
- Browser automation policy.
- Human approval workflow.
- Full production identity and authorization model.
- Multi-MCP routing.
- Tool marketplace behavior.
- Long-running distributed job orchestration.
- Public tool browsing UI.
- Production secrets vault implementation.

Those concerns belong to API, session, LLM, memory, orchestration, agents, policy, approval, deployment, and future tool platform documents.

---

## 6. Tooling Boundary

The tooling layer sits behind the orchestration runtime.

It owns:

- Logical tool registry.
- Tool discovery from the configured MCP server.
- Tool metadata normalization.
- Tool input schema validation.
- Tool output/result normalization.
- Tool allowlist and policy checks.
- Tool timeout, retry, cancellation, and result bounds.
- Tool execution trace events.
- MCP client adapter invocation.
- Safe tool health and capability summaries.
- Tool error normalization.

It does not own:

- API request parsing.
- Session creation/resume/reset.
- Short-term workflow state storage.
- Operational trace storage implementation.
- Agent selection.
- LLM provider/model selection.
- LLM calls.
- Memory search or writes.
- MCP server implementation.
- Business workflow branching.
- User-facing response formatting.

### 6.1 Boundary Diagram

```text
API
  -> SessionService
      -> OrchestrationRuntime
          -> Strategy / Agent
              -> ToolGateway
                  -> ToolPolicy / ToolScopeValidator
                  -> ToolRegistry
                  -> ToolArgumentValidator
                  -> MCPClientAdapter
                      -> Single external MCP Server
                          -> Downstream APIs / systems
                  -> ObservabilityRecorder / TraceStore
```

### 6.2 Practical Rule

Agents and strategies should do this:

```python
result = await context.tools.execute(
    request=ToolExecutionRequest(
        tool_name="documents.search",
        arguments={"query": "backend memory architecture", "limit": 5},
        scopes=ToolScopes(project_id=context.request.project_id),
        metadata={"agent_name": self.name, "operation": "document_lookup"},
    ),
    context=context.request,
)
```

Agents and strategies should not do this:

```python
mcp_client = FastMCPClient("http://localhost:9001/mcp")
result = await mcp_client.call_tool("documents.search", {"query": "..."})
```

They should also not do this:

```python
requests.post("http://localhost:9001/mcp", json={...}, headers={"Authorization": token})
```

The endpoint, protocol, auth, retry, error handling, and result normalization belong in `MCPClientAdapter` and `ToolGateway`.

---

## 7. Recommended Package Layout

Recommended implementation layout:

```text
backend/
  app/
    tools/
      __init__.py
      gateway.py
      models.py
      errors.py
      registry.py
      discovery.py
      schema_validation.py
      result_normalizer.py
      redaction.py
      retry.py
      health.py
      capabilities.py

      mcp/
        __init__.py
        client_adapter.py
        transport.py
        auth.py
        protocol_models.py
        event_stream.py
        errors.py
        fake.py

    orchestration/
      context.py
      runtime.py
      strategies/

    agents/
      base.py
      registry.py

    policy/
      service.py
      models.py

    observability/
      events.py
      trace_context.py
      redaction.py
      metrics.py

    config/
      schemas.py
      settings.py
      loader.py

    contracts/
      request.py
      errors.py
      results.py
      trace.py

    testing/
      fakes/
        fake_tool_gateway.py
        fake_mcp_client_adapter.py
        fake_tool_registry.py
```

### 7.1 Module Responsibilities

| Module | Responsibility |
|---|---|
| `gateway.py` | Public `ToolGateway` implementation and orchestration-facing entry point. |
| `models.py` | Tool request/result/config models. |
| `errors.py` | Tool-specific normalized errors. |
| `registry.py` | Normalized logical tool registry and lookup. |
| `discovery.py` | Tool discovery and cache refresh from MCP. |
| `schema_validation.py` | Input/output schema validation and argument bounds. |
| `result_normalizer.py` | Normalize MCP results into backend-safe result objects. |
| `redaction.py` | Tool-specific redaction helpers. |
| `retry.py` | Retry and timeout policy helpers. |
| `health.py` | Tool/MCP health checks. |
| `capabilities.py` | Safe tool feature summaries. |
| `mcp/client_adapter.py` | Backend adapter that speaks MCP to the external server. |
| `mcp/transport.py` | HTTP/SSE/WebSocket transport details if needed. |
| `mcp/auth.py` | OAuth/JWT/token provider and header construction. |
| `mcp/protocol_models.py` | Internal protocol DTOs hidden from agents. |
| `mcp/event_stream.py` | Streaming tool result normalization. |
| `mcp/fake.py` | Deterministic fake adapter for tests. |

---

## 8. Dependency Direction Rules

Allowed:

```text
app/orchestration/* -> app/tools/gateway.py
app/agents/*        -> app/tools/models.py through OrchestrationContext
app/tools/*         -> app/config/schemas.py
app/tools/*         -> app/policy/service.py through interface
app/tools/*         -> app/observability/events.py through facade
app/tools/mcp/*     -> MCP client/protocol libraries or HTTP clients
```

Avoid:

```text
app/api/*           -> app/tools/mcp/*
app/session/*       -> app/tools/gateway.py for normal chat behavior
app/agents/*        -> MCP client libraries
app/agents/*        -> HTTP clients for MCP endpoints
app/orchestration/* -> app/tools/mcp/client_adapter.py
app/tools/*         -> app/llm/providers/*
app/tools/*         -> memory_store.service.MemoryService
app/tools/*         -> sqlite3
app/tools/*         -> ArcadeDB client
app/tools/mcp/*     -> app/agents/*
```

### 8.1 Route and Session Boundary Rule

Correct path:

```text
API -> SessionService -> OrchestrationRuntime -> ToolGateway -> MCPClientAdapter -> MCP Server
```

Avoid:

```text
API -> MCP Server
API -> ToolGateway
SessionService -> MCPClientAdapter
SessionService -> MCP Server
```

### 8.2 Agent Boundary Rule

Agents may depend on provider-neutral tool request/result models exposed through `OrchestrationContext`.

Agents must not know:

```text
MCP endpoint URL
MCP transport details
OAuth/JWT token format
provider auth header names
raw MCP protocol envelope shape
raw downstream API payload shape
MCP server process layout
```

---

## 9. Tooling Configuration Integration

Tooling and MCP settings should be configured in YAML and resolved by the configuration loader before composition.

Recommended YAML:

```yaml
tooling:
  enabled: true

  defaults:
    timeout_seconds: 60
    stream_timeout_seconds: 300
    max_retries: 1
    max_argument_bytes: 65536
    max_result_bytes: 262144
    trace_arguments: false
    trace_results: false
    discovery_on_startup: true
    discovery_refresh_seconds: 300

  mcp:
    server:
      name: main_mcp
      enabled: true
      endpoint: ${env:MCP_SERVER_URL:http://localhost:9001/mcp}
      transport: http
      timeout_seconds: 60
      stream_timeout_seconds: 300

      auth:
        mode: ${env:MCP_AUTH_MODE:none}   # none | bearer | jwt | oauth_client_credentials
        token: ${env:MCP_BEARER_TOKEN:}
        jwt: ${env:MCP_JWT:}
        oauth:
          token_url: ${env:MCP_OAUTH_TOKEN_URL:}
          client_id: ${env:MCP_OAUTH_CLIENT_ID:}
          client_secret: ${env:MCP_OAUTH_CLIENT_SECRET:}
          scopes: []

  registry:
    allow_discovered_tools: true
    require_configured_allowlist: true
    tools:
      documents.search:
        enabled: true
        mcp_tool_name: documents.search
        description: Search indexed documents through the MCP server.
        allowed_for:
          usecases: [default, document_qa]
          agents: [document_qa_agent, architecture_writer_agent]
          strategies: [direct_agent, router_strategy]
        timeout_seconds: 45
        max_result_bytes: 131072
        approval_required: false

      support.lookup_ticket:
        enabled: false
        mcp_tool_name: support.lookup_ticket
        description: Lookup support ticket by ID.
        allowed_for:
          usecases: [support]
          agents: [support_agent]
          strategies: [direct_agent]
        timeout_seconds: 30
        approval_required: false
```

### 9.1 Single MCP Endpoint Rule

V1 should have one configured MCP endpoint:

```yaml
mcp:
  server:
    endpoint: http://localhost:9001/mcp
```

Avoid:

```yaml
MCP_SUPPORT_URL: http://localhost:9001/mcp
MCP_DOCUMENT_URL: http://localhost:9100/mcp
```

If tools need different downstream systems, that routing belongs inside the separate MCP server or behind logical tool names, not inside the backend as multiple MCP endpoints in V1.

### 9.2 Configuration Safety Rule

Health and capabilities may expose safe logical tool names only when needed.

Do not expose:

```text
OAuth client secrets
bearer tokens
JWTs
authorization headers
private MCP endpoints when sensitive
raw downstream service URLs
raw tool result samples
```

---

## 10. Typed Tooling Settings

Recommended dataclasses:

```python
from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(frozen=True, slots=True)
class ToolingDefaultsSettings:
    timeout_seconds: int
    stream_timeout_seconds: int
    max_retries: int
    max_argument_bytes: int
    max_result_bytes: int
    trace_arguments: bool = False
    trace_results: bool = False
    discovery_on_startup: bool = True
    discovery_refresh_seconds: int = 300


@dataclass(frozen=True, slots=True)
class MCPAuthSettings:
    mode: Literal["none", "bearer", "jwt", "oauth_client_credentials"] = "none"
    token: str | None = None
    jwt: str | None = None
    token_url: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    scopes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MCPServerSettings:
    name: str
    enabled: bool
    endpoint: str
    transport: Literal["http", "sse", "websocket"] = "http"
    timeout_seconds: int = 60
    stream_timeout_seconds: int = 300
    auth: MCPAuthSettings = field(default_factory=MCPAuthSettings)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ToolDefinitionSettings:
    name: str
    enabled: bool
    mcp_tool_name: str
    description: str | None = None
    allowed_for: dict[str, list[str]] = field(default_factory=dict)
    timeout_seconds: int | None = None
    max_argument_bytes: int | None = None
    max_result_bytes: int | None = None
    approval_required: bool = False
    input_schema_override: dict[str, Any] | None = None
    output_schema_override: dict[str, Any] | None = None
    tags: tuple[str, ...] = ()
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ToolRegistrySettings:
    allow_discovered_tools: bool
    require_configured_allowlist: bool
    tools: dict[str, ToolDefinitionSettings]


@dataclass(frozen=True, slots=True)
class ToolingSettings:
    enabled: bool
    defaults: ToolingDefaultsSettings
    mcp_server: MCPServerSettings
    registry: ToolRegistrySettings
```

### 10.1 Settings Validation

Configuration validation should fail fast when:

- Tooling is enabled but MCP server is disabled.
- MCP endpoint is missing or malformed.
- More than one MCP endpoint is configured for V1.
- Unknown MCP transport is configured.
- Auth mode requires credentials that are missing.
- OAuth mode is enabled without token URL, client ID, or client secret.
- Tool names are duplicated.
- A configured logical tool maps to an empty MCP tool name.
- A tool is enabled but missing allowlist metadata when `require_configured_allowlist` is true.
- Timeout, retry, argument size, or result size values are invalid.
- Tool schema overrides are not valid JSON Schema objects.
- A configured tool name conflicts with a reserved internal tool name.

---

## 11. Tool Scopes

Every tool execution must carry scope.

Recommended scope model:

```python
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ToolScopes:
    user_id: str | None = None
    project_id: str | None = None
    tenant_id: str | None = None
    session_id: str | None = None
    agent_name: str | None = None
    usecase: str | None = None
    tool_group: str | None = None
    tags: tuple[str, ...] = ()
    metadata: dict[str, str] = field(default_factory=dict)
```

### 11.1 Scope Rules

Recommended V1 rules:

```text
At least session_id should be available for runtime correlation.
Durable scopes such as user_id, project_id, or tenant_id should be present for tools that read/write durable downstream systems.
Tool execution should combine request scope, agent scope, use-case scope, and configured tool allowlist.
User-provided metadata must not override durable scope without policy approval.
```

### 11.2 Scope Examples

Project-scoped document tool call:

```python
ToolScopes(
    user_id="local_user",
    project_id="bb1_poc",
    usecase="document_qa",
    agent_name="document_qa_agent",
)
```

Session-scoped utility tool call:

```python
ToolScopes(
    user_id="local_user",
    session_id="session_abc123",
    usecase="default",
)
```

### 11.3 Scope Safety Rule

Avoid:

```text
User sends metadata.project_id = "other_project".
ToolGateway passes it to MCP as trusted scope.
```

Allowed:

```text
RequestContext contains validated user/project scope.
Strategy passes that scope into ToolGateway.
Policy approves the tool call.
ToolGateway passes bounded, approved scope metadata to MCP.
```

---

## 12. Public Tool Gateway Interface

Recommended interface:

```python
from collections.abc import AsyncIterator
from typing import Protocol


class ToolGateway(Protocol):
    async def list_tools(
        self,
        *,
        context: "RequestContext",
        filters: "ToolListFilters | None" = None,
    ) -> "ToolListResult":
        ...

    async def get_tool(
        self,
        *,
        tool_name: str,
        context: "RequestContext",
    ) -> "ToolDefinition | None":
        ...

    async def execute(
        self,
        *,
        request: "ToolExecutionRequest",
        context: "RequestContext",
    ) -> "ToolExecutionResult":
        ...

    async def stream_execute(
        self,
        *,
        request: "ToolExecutionRequest",
        context: "RequestContext",
    ) -> AsyncIterator["ToolStreamEvent"]:
        ...

    async def health(self) -> "ToolHealthResult":
        ...

    async def capabilities(self) -> "ToolCapabilitiesResult":
        ...
```

### 12.1 Method Ownership

| Method | Purpose |
|---|---|
| `list_tools` | Return policy-filtered logical tools available to the current context. |
| `get_tool` | Return a single safe tool definition. |
| `execute` | Execute a non-streaming tool call and return normalized result. |
| `stream_execute` | Execute a streaming tool call and yield normalized stream events. |
| `health` | Return safe MCP/tooling readiness. |
| `capabilities` | Return frontend/orchestration-safe tool feature flags. |

### 12.2 Gateway Call Flow

```text
1. Receive ToolExecutionRequest and RequestContext.
2. Validate request shape and size limits.
3. Resolve logical tool name in ToolRegistry.
4. Check whether tool is enabled.
5. Check policy for user/usecase/agent/strategy/tool access.
6. Validate arguments against tool input schema.
7. Redact and record `tool_call_started` trace event.
8. Call MCPClientAdapter with resolved MCP tool name and safe arguments.
9. Normalize MCP response into ToolExecutionResult or ToolStreamEvent.
10. Bound result size and redact unsafe fields.
11. Record success/failure/cancellation trace event.
12. Return normalized result or normalized tool error.
```

---

## 13. Tool Definition Model

Recommended provider-neutral tool definition:

```python
from dataclasses import dataclass, field
from typing import Any, Literal


ToolExecutionMode = Literal["sync", "async", "streaming"]
ToolSafetyLevel = Literal["read_only", "write", "destructive", "external_side_effect"]


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str | None
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None = None
    enabled: bool = True
    execution_modes: tuple[ToolExecutionMode, ...] = ("sync",)
    safety_level: ToolSafetyLevel = "read_only"
    approval_required: bool = False
    tags: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
```

### 13.1 Logical Tool Name Rule

Agents and strategies call logical backend tool names:

```text
documents.search
calendar.create_event
support.lookup_ticket
filesystem.read_project_file
```

The registry maps logical names to MCP tool names:

```text
logical tool name -> configured MCP tool name -> MCP protocol call
```

This allows backend-facing tool names to remain stable even if MCP server internals change.

### 13.2 Tool Safety Levels

Recommended V1 safety levels:

| Safety Level | Meaning | Default Handling |
|---|---|---|
| `read_only` | Reads data without changing downstream state. | Allowed if configured and policy approves. |
| `write` | Creates or updates downstream state. | Policy check required; approval may be required later. |
| `destructive` | Deletes or irreversibly changes downstream state. | Disabled by default in V1 unless explicitly configured. |
| `external_side_effect` | Sends email, posts, purchases, triggers external action. | Requires explicit policy and likely future human approval. |

### 13.3 Tool Metadata Safety Rule

Safe metadata examples:

```text
display_name
category
tags
safety_level
schema_version
supports_streaming
```

Unsafe metadata examples:

```text
api_key
bearer_token
jwt
raw_endpoint
private_service_url
sample_auth_header
raw_downstream_response
```

---

## 14. Tool Execution Request and Result Models

Recommended request model:

```python
@dataclass(frozen=True, slots=True)
class ToolExecutionRequest:
    tool_name: str
    arguments: dict[str, Any]
    scopes: ToolScopes
    timeout_seconds: int | None = None
    idempotency_key: str | None = None
    stream: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
```

Recommended result model:

```python
@dataclass(frozen=True, slots=True)
class ToolExecutionResult:
    tool_name: str
    status: Literal["completed", "failed", "cancelled", "timeout"]
    content: list["ToolResultContent"] = field(default_factory=list)
    structured_content: dict[str, Any] | None = None
    summary: "ToolResultSummary | None" = None
    duration_ms: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

Recommended content model:

```python
@dataclass(frozen=True, slots=True)
class ToolResultContent:
    type: Literal["text", "json", "table", "file_ref", "image_ref"]
    text: str | None = None
    json_value: Any | None = None
    uri: str | None = None
    mime_type: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

Recommended summary model:

```python
@dataclass(frozen=True, slots=True)
class ToolResultSummary:
    result_count: int | None = None
    bytes_returned: int | None = None
    truncated: bool = False
    safe_message: str | None = None
```

### 14.1 Result Shape Rule

Tool results returned to agents should be useful but bounded.

Recommended behavior:

```text
Return structured results when policy allows.
Return bounded text/table/file references rather than unbounded raw payloads.
Mark truncated results explicitly.
Preserve enough provenance for agents to cite or reason about the result.
```

Avoid:

```text
Returning raw downstream HTTP response objects.
Returning full private documents by default.
Returning authorization headers or cookies.
Returning unbounded arrays or binary payloads inline.
```

### 14.2 Tool Request Metadata

Allowed metadata examples:

```text
agent_name
strategy_name
operation
trace_id
session_id
usecase
reason
```

Metadata must not include:

```text
api keys
authorization headers
cookies
JWTs
raw LLM prompt text
hidden scratchpads
raw workflow state
raw memory records unless policy allows
```

---

## 15. Stream Event Contract

Some tools may return incremental progress or streaming content.

Recommended stream events:

```python
@dataclass(frozen=True, slots=True)
class ToolStreamEvent:
    type: Literal[
        "started",
        "progress",
        "delta",
        "metadata",
        "completed",
        "error",
        "cancelled",
    ]
    tool_name: str
    text: str | None = None
    progress: float | None = None
    result: ToolExecutionResult | None = None
    error: "ToolErrorDetail | None" = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

### 15.1 Gateway-to-Session Streaming Path

```text
MCP stream/progress event
  -> MCPClientAdapter normalizes protocol event
  -> ToolGateway yields ToolStreamEvent
  -> Agent/Strategy maps to OrchestrationStreamEvent
  -> SessionService maps to SessionStreamEvent
  -> API maps to SSE event
```

### 15.2 Streaming Safety Rule

Tool stream events must not expose:

- MCP raw protocol envelopes.
- Authorization headers.
- OAuth/JWT tokens.
- Raw downstream request or response objects.
- Hidden LLM scratchpads.
- Full tool payloads unless explicitly safe and bounded.
- Provider stack traces.

---

## 16. MCP Client Adapter Interface

Recommended interface:

```python
from collections.abc import AsyncIterator
from typing import Protocol


class MCPClientAdapter(Protocol):
    async def list_tools(self) -> list["MCPToolDefinition"]:
        ...

    async def call_tool(
        self,
        *,
        request: "MCPToolCallRequest",
    ) -> "MCPToolCallResult":
        ...

    async def stream_tool(
        self,
        *,
        request: "MCPToolCallRequest",
    ) -> AsyncIterator["MCPToolStreamEvent"]:
        ...

    async def health(self) -> "MCPHealthResult":
        ...
```

### 16.1 Internal MCP Request Model

`MCPToolCallRequest` is internal to the tooling adapter and should not be visible to agents:

```python
@dataclass(frozen=True, slots=True)
class MCPToolCallRequest:
    mcp_tool_name: str
    arguments: dict[str, Any]
    timeout_seconds: int
    trace_id: str
    session_id: str | None = None
    idempotency_key: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

### 16.2 Adapter Responsibility

`MCPClientAdapter` owns:

- MCP endpoint construction.
- MCP protocol request and response mapping.
- MCP auth header construction.
- Token refresh or token provider usage.
- MCP-specific timeout handling.
- MCP streaming event parsing.
- MCP error normalization into adapter errors.
- Safe MCP health checks.

`MCPClientAdapter` must not own:

- Agent selection.
- Strategy selection.
- LLM tool-intent parsing.
- Memory search.
- Workflow state persistence.
- API response formatting.
- Business policy decisions beyond protocol-level auth failure handling.

---

## 17. Tool Discovery and Registry

The registry provides stable logical tool definitions to agents and strategies.

Recommended behavior:

```text
1. Load configured allowlist from YAML.
2. Optionally discover available MCP tools at startup.
3. Merge discovered MCP schemas with configured logical tool definitions.
4. Apply schema overrides where configured.
5. Reject enabled tools missing from MCP when strict mode is enabled.
6. Expose policy-filtered logical tools to orchestration.
```

### 17.1 Static vs Discovered Tools

Recommended V1 mode:

```text
Configured allowlist is authoritative.
Discovery enriches schema and health status.
Unknown discovered tools are not callable unless allowlisted.
```

This prevents a newly added MCP server tool from becoming available to agents without backend configuration and policy review.

### 17.2 Registry Interface

```python
class ToolRegistry:
    def register(self, definition: ToolDefinition, *, mcp_tool_name: str) -> None: ...
    def resolve(self, logical_name: str) -> "ResolvedToolDefinition": ...
    def list(self, filters: "ToolListFilters | None" = None) -> list[ToolDefinition]: ...
    def refresh_from_mcp(self, discovered: list[MCPToolDefinition]) -> "ToolRegistryRefreshResult": ...
```

### 17.3 Resolved Tool Definition

```python
@dataclass(frozen=True, slots=True)
class ResolvedToolDefinition:
    logical_tool: ToolDefinition
    mcp_tool_name: str
    settings: ToolDefinitionSettings
    discovered_schema: dict[str, Any] | None = None
```

---

## 18. Tool Policy Integration

The tool gateway should call policy before MCP execution.

Recommended policy check:

```python
allowed = await policy.can_execute_tool(
    user_id=context.user_id,
    session_id=context.session_id,
    usecase=context.usecase,
    agent_name=request.metadata.get("agent_name"),
    strategy_name=request.metadata.get("strategy_name"),
    tool_name=resolved.logical_tool.name,
    safety_level=resolved.logical_tool.safety_level,
    scopes=request.scopes,
    arguments_summary=summarize_arguments(request.arguments),
)
```

### 18.1 V1 Policy Defaults

Recommended V1 defaults:

```text
Deny unknown tools.
Deny disabled tools.
Deny discovered-but-not-allowlisted tools when configured allowlist is required.
Allow only configured tool/usecase/agent/strategy combinations.
Deny destructive tools by default.
Deny external-side-effect tools by default unless explicitly enabled.
Deny user-supplied tool name aliases that bypass logical registry.
Deny raw auth/token arguments.
Trace all tool calls with safe metadata.
Do not trace raw arguments/results by default.
```

### 18.2 User-Supplied Tool Override Rule

User input must not be allowed to directly select arbitrary MCP tool names.

Allowed:

```text
Agent requests logical tool `documents.search`.
ToolRegistry maps it to configured MCP tool name.
Policy approves use.
ToolGateway calls MCPClientAdapter.
```

Avoid:

```text
User sends metadata.mcp_tool_name = "dangerous.delete_all".
Gateway calls it directly.
```

---

## 19. Tool Argument Validation

Tool arguments must be validated before MCP execution.

Validation should include:

- JSON-serializable shape.
- Maximum serialized size.
- Required fields.
- Type checks against JSON Schema.
- Enum checks.
- String length limits.
- Array length limits.
- Obvious secret detection.
- Tool-specific denylisted fields.
- Scope consistency checks.

### 19.1 Argument Sanitization Rule

Do not silently rewrite user arguments in a way that changes tool meaning.

Allowed:

```text
Trim harmless surrounding whitespace for string fields if schema allows it.
Add trusted scope metadata from RequestContext when policy allows.
Reject fields that are unknown or dangerous.
```

Avoid:

```text
Silently replacing project_id with another value.
Silently dropping dangerous fields and executing anyway.
Passing unvalidated raw LLM JSON directly to MCP.
```

### 19.2 Secret Detection

Reject or redact argument keys containing:

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

If a tool legitimately needs a credential, that credential should come from trusted configuration or a secure token provider, not from agent-generated arguments.

---

## 20. MCP Transport and Authentication

V1 should support a simple HTTP-based MCP client adapter first, with room for SSE/WebSocket transports if required by the selected MCP stack.

Recommended transport abstraction:

```python
class MCPTransport(Protocol):
    async def request(self, *, method: str, payload: dict[str, Any], timeout_seconds: int) -> dict[str, Any]: ...
    async def stream(self, *, method: str, payload: dict[str, Any], timeout_seconds: int) -> AsyncIterator[dict[str, Any]]: ...
    async def health(self) -> MCPHealthResult: ...
```

### 20.1 Auth Provider

Recommended auth provider:

```python
class MCPAuthProvider(Protocol):
    async def get_headers(self) -> dict[str, str]: ...
```

Supported V1 modes:

| Mode | Use Case |
|---|---|
| `none` | Local development with no MCP auth. |
| `bearer` | Static bearer token from environment. |
| `jwt` | JWT provided through environment or future identity layer. |
| `oauth_client_credentials` | Service-to-service OAuth token acquisition. |

### 20.2 Credential Safety Rule

MCP auth code may construct headers internally.

Agents, strategies, API routes, session service, and orchestration runtime must never pass raw auth headers or MCP tokens.

Unsafe:

```python
ToolExecutionRequest(
    tool_name="documents.search",
    arguments={"query": "...", "Authorization": "Bearer ..."},
)
```

Safe:

```text
MCPAuthProvider resolves token from trusted configuration.
MCPClientAdapter attaches header internally.
```

---

## 21. Tool Result Normalization

MCP responses should normalize into `ToolExecutionResult`.

Recommended normalized fields:

| Field | Meaning |
|---|---|
| `tool_name` | Logical backend tool name, not necessarily raw MCP tool name. |
| `status` | Normalized execution status. |
| `content` | Bounded content blocks safe for agent consumption. |
| `structured_content` | Optional normalized JSON object. |
| `summary` | Safe summary metadata for API/session/trace. |
| `duration_ms` | Gateway-observed duration. |
| `metadata` | Bounded safe diagnostics. |

### 21.1 Result Bounds

Recommended defaults:

```text
max_result_bytes: 262144
max_text_block_chars: 12000
max_content_blocks: 20
max_table_rows: 100
max_file_refs: 50
```

If the MCP result exceeds bounds:

```text
Truncate safely when possible.
Mark result as truncated.
Prefer file/document references over inline large payloads.
Fail with ToolResultTooLargeError if safe truncation is not possible.
```

### 21.2 Result Summaries for API Responses

Tool summaries returned to API/session results should be compact:

```json
{
  "tool_name": "documents.search",
  "status": "completed",
  "duration_ms": 180,
  "result_count": 5,
  "truncated": false
}
```

Do not return raw MCP payloads in API responses by default.

---

## 22. LLM Tool Intent Boundary

The LLM gateway may return text or structured output that describes a desired tool call. It must not execute tools.

Correct path:

```text
LLMGateway returns normalized output
  -> Strategy/Agent parses tool intent
  -> OrchestrationRuntime validates flow
  -> ToolGateway checks policy and executes
  -> MCPClientAdapter calls MCP server
```

Avoid:

```text
LLMGateway -> ToolGateway
LLMGateway -> MCPClientAdapter
LLMGateway -> MCP Server
```

### 22.1 Tool Intent Model

A strategy may normalize LLM output into a tool intent:

```python
@dataclass(frozen=True, slots=True)
class ToolIntent:
    tool_name: str
    arguments: dict[str, Any]
    reason: str | None = None
    confidence: float | None = None
```

The intent is not execution. Execution begins only after policy and validation inside `ToolGateway`.

### 22.2 V1 Recommendation

For V1, prefer explicit strategy-controlled tool calling over provider-native auto-tool execution.

If provider-native tool call structures are used later, normalize them into `ToolIntent` objects and execute only through `ToolGateway`.

---

## 23. Memory Boundary

The tooling layer must not search or write memory.

Correct memory-to-tool flow:

```text
Agent/Strategy -> MemoryGateway.search
Agent/Strategy selects relevant memory context
Agent/Strategy -> ToolGateway.execute with explicit approved arguments
ToolGateway -> MCPClientAdapter
```

Avoid:

```text
ToolGateway -> MemoryGateway.search
ToolGateway -> memory_store.service.MemoryService
MCPClientAdapter -> ArcadeDB
```

### 23.1 Tool Results Becoming Memory

Tool results should not automatically become long-term memory.

Correct flow:

```text
ToolGateway returns bounded result
Agent/Strategy decides whether result is durable
Agent/Strategy -> MemoryGateway.upsert if policy allows
```

Avoid:

```text
ToolGateway writes every tool result into memory
MCPClientAdapter writes tool result into ArcadeDB
```

---

## 24. Orchestration Integration

The orchestration runtime injects `ToolGateway` into `OrchestrationContext`.

Recommended context shape:

```python
@dataclass
class OrchestrationContext:
    request: RequestContext
    llm: LLMGateway
    memory: MemoryGateway
    tools: ToolGateway
    state: WorkflowStateStore
    trace: TraceStore
    policy: PolicyService
    config: dict[str, Any]
```

### 24.1 Strategy Usage

A strategy may call tools after selecting an agent or interpreting tool intent:

```python
tool_result = await context.tools.execute(
    request=ToolExecutionRequest(
        tool_name="documents.search",
        arguments={"query": user_query, "limit": 5},
        scopes=ToolScopes(
            user_id=context.request.user_id,
            project_id=context.request.project_id,
            session_id=context.request.session_id,
            usecase=context.request.usecase,
        ),
        metadata={"strategy_name": "direct_agent", "operation": "retrieve_documents"},
    ),
    context=context.request,
)
```

### 24.2 Agent Usage

An agent may use tools through the context only:

```python
result = await context.tools.execute(
    request=ToolExecutionRequest(
        tool_name=self.required_tool,
        arguments=validated_args,
        scopes=current_scopes,
        metadata={"agent_name": self.name},
    ),
    context=context.request,
)
```

### 24.3 Session Service Boundary Reminder

`SessionService` does not call `ToolGateway` directly for normal chat behavior.

Correct:

```text
SessionService -> OrchestrationRuntime -> ToolGateway
```

Avoid:

```text
SessionService -> ToolGateway.execute
SessionService -> MCPClientAdapter
```

---

## 25. Timeout, Retry, and Cancellation Behavior

Tool calls should be bounded.

Recommended timeout order:

```text
request.timeout_seconds
configured tool.timeout_seconds
mcp.server.timeout_seconds
tooling.defaults.timeout_seconds
```

Streaming timeout order:

```text
request.timeout_seconds
mcp.server.stream_timeout_seconds
tooling.defaults.stream_timeout_seconds
```

### 25.1 Retry Policy

Retries should be conservative by default.

Recommended retryable conditions:

```text
transient network failure
MCP timeout before downstream action started
HTTP 429 / rate limit if retryable
HTTP 502 / 503 / 504
connection reset before result started
```

Recommended non-retryable conditions:

```text
unknown tool
policy denied
argument validation error
authentication failure
authorization failure
destructive action after execution may have started
external-side-effect action after execution may have started
schema mismatch caused by caller
```

### 25.2 Idempotency

For write or external-side-effect tools, support optional `idempotency_key`.

Recommended behavior:

```text
Read-only tools may retry without idempotency key if safe.
Write tools should require idempotency key if retry is enabled.
External-side-effect tools should not retry by default.
Destructive tools should not retry by default.
```

### 25.3 Cancellation

Cancellation lifecycle:

```text
1. Upstream stream/API detects disconnect or strategy cancels task.
2. OrchestrationRuntime cancels tool task.
3. ToolGateway attempts to cancel or close MCP request.
4. MCPClientAdapter closes transport where possible.
5. ToolGateway records `tool_call_cancelled` trace event.
6. SessionService decides whether/how to save workflow state.
```

---

## 26. Observability and Trace Integration

The tool gateway should emit safe trace events through the observability facade or `TraceStore` interface.

Recommended trace events:

| Event | Emitted By | Notes |
|---|---|---|
| `tool_registry_loaded` | Registry/composition | Logical tool count only. |
| `tool_discovery_started` | Discovery service | Safe MCP server name only. |
| `tool_discovery_completed` | Discovery service | Tool counts, not raw schemas if large. |
| `tool_policy_checked` | Gateway/policy facade | Allowed/denied summary only. |
| `tool_call_started` | Gateway | No raw arguments by default. |
| `tool_call_completed` | Gateway | Duration, status, result summary. |
| `tool_call_failed` | Gateway | Safe error type/code only. |
| `tool_call_cancelled` | Gateway | Cancellation summary. |
| `tool_retry_scheduled` | Gateway | Attempt number and safe retry reason. |
| `mcp_request_started` | MCP adapter | Safe method/tool metadata only. |
| `mcp_request_completed` | MCP adapter | Duration/status only. |
| `mcp_health_checked` | Health service/adapter | Safe readiness summary. |

### 26.1 Safe Trace Payload Example

```json
{
  "event_name": "tool_call_completed",
  "trace_id": "trace_...",
  "payload": {
    "tool_name": "documents.search",
    "mcp_tool_name": "documents.search",
    "duration_ms": 180,
    "argument_bytes": 86,
    "result_bytes": 3200,
    "result_count": 5,
    "status": "completed",
    "truncated": false
  }
}
```

### 26.2 Unsafe Trace Payload Example

```json
{
  "arguments": {
    "query": "full private user request...",
    "Authorization": "Bearer ..."
  },
  "raw_mcp_response": {...},
  "oauth_token": "..."
}
```

### 26.3 Metrics

Recommended metrics:

```text
backend.tools.calls.total
backend.tools.calls.duration_ms
backend.tools.calls.in_flight
backend.tools.calls.failed_total
backend.tools.streams.total
backend.tools.streams.duration_ms
backend.tools.streams.cancelled_total
backend.tools.retries.total
backend.mcp.requests.total
backend.mcp.requests.duration_ms
backend.mcp.requests.failed_total
backend.mcp.health.status
```

Allowed metric tags:

```text
tool_name
safety_level
status
error_type
streaming
retry_count
```

Avoid metric tags:

```text
session_id
trace_id
raw_user_id
raw arguments
raw result text
MCP endpoint if sensitive
API key
OAuth token
```

---

## 27. Privacy and Redaction

The tooling layer must assume tool arguments and results can contain user-sensitive data.

Default behavior:

```text
Do not log raw tool arguments.
Do not log raw tool results.
Do not store raw tool arguments in trace events.
Do not store raw tool results in trace events.
Do not return MCP error bodies verbatim.
Do not expose MCP credentials or headers.
```

### 27.1 Redaction Targets

Redact metadata keys containing:

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

### 27.2 Debug Capture

Optional argument/result capture must be disabled by default.

If enabled in a local development profile, it should require explicit configuration:

```yaml
tooling:
  defaults:
    trace_arguments: false
    trace_results: false
```

A future policy document should define whether argument/result capture can ever be enabled outside local development.

---

## 28. Error Model

Recommended tool errors:

```python
class ToolError(Exception):
    code: str
    retryable: bool


class ToolNotFoundError(ToolError): ...
class ToolDisabledError(ToolError): ...
class ToolPolicyDeniedError(ToolError): ...
class ToolArgumentValidationError(ToolError): ...
class ToolUnsupportedModeError(ToolError): ...
class ToolResultTooLargeError(ToolError): ...
class ToolTimeoutError(ToolError): ...
class ToolRateLimitError(ToolError): ...
class ToolUnavailableError(ToolError): ...
class ToolAuthenticationError(ToolError): ...
class ToolAuthorizationError(ToolError): ...
class ToolMalformedResponseError(ToolError): ...
class ToolStreamingError(ToolError): ...
class ToolCancelledError(ToolError): ...
class MCPProtocolError(ToolError): ...
```

### 28.1 Error Mapping

| Tool Error | Retryable | API Mapping Later |
|---|---:|---|
| `ToolNotFoundError` | false | `400 unknown_tool` |
| `ToolDisabledError` | false | `403 tool_disabled` |
| `ToolPolicyDeniedError` | false | `403 policy_denied` |
| `ToolArgumentValidationError` | false | `400 invalid_tool_arguments` |
| `ToolUnsupportedModeError` | false | `400 unsupported_tool_mode` |
| `ToolResultTooLargeError` | false | `502 tool_result_too_large` |
| `ToolTimeoutError` | true | `504 tool_timeout` |
| `ToolRateLimitError` | true | `503 tool_rate_limited` |
| `ToolUnavailableError` | true | `503 tool_unavailable` |
| `ToolAuthenticationError` | false | `503 tool_authentication_failed` internally; do not expose credentials |
| `ToolAuthorizationError` | false | `403 tool_authorization_failed` |
| `ToolMalformedResponseError` | true/false by tool | `502 tool_malformed_response` |
| `ToolStreamingError` | true/false by stage | SSE `response.error` through session/API |
| `ToolCancelledError` | false | cancellation path, normally no user-visible error |
| `MCPProtocolError` | true/false by stage | `502 mcp_protocol_error` |

### 28.2 Error Safety Rule

Normalized tool errors must not expose:

- Raw MCP response body.
- Raw MCP request body.
- Authorization headers.
- OAuth/JWT tokens.
- API keys.
- Stack traces.
- Raw tool arguments.
- Raw tool results.

---

## 29. Health Integration

The tool gateway should expose safe health status for the registry and MCP adapter.

Recommended result:

```python
@dataclass(frozen=True, slots=True)
class ToolHealthResult:
    status: str
    tooling_enabled: bool
    mcp_configured: bool
    mcp_status: str
    tools_configured: int
    tools_discovered: int | None
    tools_enabled: int
    registry_status: str
    metadata: dict[str, Any] = field(default_factory=dict)
```

Recommended health response section:

```json
{
  "tools": {
    "status": "ok",
    "tooling_enabled": true,
    "mcp_configured": true,
    "mcp_status": "ok",
    "tools_configured": 8,
    "tools_discovered": 8,
    "tools_enabled": 5,
    "registry_status": "ok"
  }
}
```

### 29.1 Health Safety Rule

Health output must not include:

```text
MCP auth tokens
OAuth client secret
JWTs
authorization headers
private endpoint URL if classified sensitive
raw MCP health response
raw exception stack trace
```

### 29.2 Health Check Depth

Recommended V1 behavior:

```text
Startup validation checks configuration shape.
Health route reports MCP configured/discovered status.
Optional deep MCP ping is configurable.
Tool discovery status is reported as count/status, not raw schemas.
```

---

## 30. Capabilities Integration

The capabilities service may include safe tooling feature flags.

Recommended capability section:

```json
{
  "tools": {
    "enabled": true,
    "mcp_configured": true,
    "streaming_supported": false,
    "available_logical_tools": [
      {
        "name": "documents.search",
        "display_name": "Search Documents",
        "safety_level": "read_only"
      }
    ]
  }
}
```

### 30.1 Capability Safety Rule

Expose only frontend-safe logical names and feature flags.

Do not expose:

```text
MCP endpoint URL
OAuth token URL if sensitive
client IDs/secrets
JWTs
raw MCP tool schema if it leaks internals
private downstream service names
internal prompt/tool routing policy
```

If logical tool names reveal sensitive internals, expose display labels instead.

---

## 31. Composition Root Integration

The composition root builds the MCP adapter, registry, and tool gateway, then injects `ToolGateway` into orchestration.

Recommended startup sequence:

```text
1. Load settings and YAML configuration.
2. Validate tooling/MCP config.
3. Build redactor and observability recorder.
4. Build policy service.
5. Build MCPAuthProvider from config.
6. Build MCPTransport from config.
7. Build MCPClientAdapter.
8. Build ToolRegistry from configured allowlist.
9. Optionally discover tools from MCP and refresh registry.
10. Build ToolGateway.
11. Build orchestration runtime with tools=tool_gateway.
12. Build session service with orchestration runtime.
13. Build API app.
14. Log redacted tooling startup summary.
```

### 31.1 Composition Example

```python
def build_tool_gateway(config, policy, observability) -> ToolGateway:
    auth_provider = build_mcp_auth_provider(config.tooling.mcp_server.auth)
    transport = build_mcp_transport(
        settings=config.tooling.mcp_server,
        auth_provider=auth_provider,
    )
    mcp_adapter = DefaultMCPClientAdapter(
        settings=config.tooling.mcp_server,
        transport=transport,
        redactor=observability.redactor,
    )

    registry = ToolRegistry.from_settings(config.tooling.registry)

    return DefaultToolGateway(
        settings=config.tooling,
        registry=registry,
        mcp=mcp_adapter,
        policy=policy,
        observability=observability,
        redactor=observability.redactor,
    )
```

### 31.2 Redacted Startup Summary

Safe startup log:

```json
{
  "event": "tool_gateway_configured",
  "mcp_server": "main_mcp",
  "tools_configured": 8,
  "tools_enabled": 5,
  "discovery_on_startup": true
}
```

Unsafe startup log:

```json
{
  "endpoint": "private URL if sensitive",
  "Authorization": "Bearer ...",
  "client_secret": "..."
}
```

---

## 32. MCP Client Adapter Design

The MCP client adapter is the backend's only MCP protocol boundary.

Recommended responsibilities:

- Build MCP requests.
- Attach auth headers internally.
- Parse MCP responses.
- Support tool discovery.
- Support tool call execution.
- Support streaming/progress events if configured.
- Normalize protocol errors.
- Respect timeout/cancellation.
- Avoid leaking protocol objects upward.

### 32.1 Tool Discovery Mapping

MCP discovered tool:

```json
{
  "name": "documents.search",
  "description": "Search documents",
  "inputSchema": {
    "type": "object",
    "properties": {
      "query": {"type": "string"},
      "limit": {"type": "integer"}
    },
    "required": ["query"]
  }
}
```

Normalized logical tool definition:

```python
ToolDefinition(
    name="documents.search",
    description="Search documents",
    input_schema={...},
    safety_level="read_only",
    execution_modes=("sync",),
)
```

### 32.2 Tool Call Mapping

Provider-neutral request:

```python
ToolExecutionRequest(
    tool_name="documents.search",
    arguments={"query": "session service architecture", "limit": 5},
    scopes=ToolScopes(project_id="bb1_poc"),
)
```

Internal MCP request:

```python
MCPToolCallRequest(
    mcp_tool_name="documents.search",
    arguments={"query": "session service architecture", "limit": 5},
    timeout_seconds=45,
    trace_id="trace_...",
)
```

### 32.3 Adapter Output Rule

The MCP adapter should not return raw MCP JSON to `ToolGateway` callers.

It returns gateway-internal response models, which `ToolGateway` converts into public `ToolExecutionResult` or `ToolStreamEvent` objects.

---

## 33. Approval Boundary

V1 can mark tools as `approval_required` without implementing a full human approval workflow.

Recommended V1 behavior:

```text
If approval_required is false, execute after policy and validation.
If approval_required is true and no approval service exists, fail with ToolPolicyDeniedError or ToolApprovalRequiredError.
Do not silently execute approval-required tools.
```

### 33.1 Future Approval Flow

A future approval document may introduce:

```text
Tool intent created
Approval request stored in workflow state
Frontend asks user to approve
SessionService resumes workflow
ToolGateway executes after approval token is validated
```

Until then, approval-required tools should be treated as unavailable for autonomous execution.

---

## 34. Tool Result Use in Prompt Context

Agents may include safe tool results in LLM messages.

Recommended flow:

```text
Agent calls ToolGateway.
ToolGateway returns bounded ToolExecutionResult.
Agent selects relevant tool result fields.
Agent constructs LLM messages.
Agent calls LLMGateway.
```

The tooling layer should not construct business prompts and should not call `LLMGateway`.

### 34.1 Prompt Context Safety Rule

Tool results can be large or sensitive. Agents should include only what is needed.

Recommended agent behavior:

```text
Prefer summaries and selected fields.
Respect result truncation markers.
Avoid pasting raw JSON when a smaller structured summary is sufficient.
Do not include secrets or credentials in LLM prompts.
```

---

## 35. Workflow State Boundary

ToolGateway does not persist workflow state.

Correct state flow:

```text
OrchestrationRuntime decides tool step.
ToolGateway executes tool.
OrchestrationRuntime/Strategy records safe step summary in workflow state.
SessionService saves final workflow state.
```

Avoid:

```text
ToolGateway writes directly to WorkflowStateStore.
MCPClientAdapter writes directly to workflow_state.db.
```

### 35.1 Tool Step Summary

Safe workflow-state summary example:

```json
{
  "step_type": "tool_call",
  "tool_name": "documents.search",
  "status": "completed",
  "result_count": 5,
  "duration_ms": 180
}
```

Avoid storing raw tool payloads in workflow state unless a future policy explicitly allows it.

---

## 36. Security

### 36.1 Credential Handling

MCP credentials should come from environment-resolved configuration or a future secure token provider.

Credentials must not be:

- Logged.
- Stored in trace events.
- Returned in health/capabilities.
- Passed to agents.
- Persisted in workflow state.
- Included in LLM prompts.

### 36.2 Downstream Side Effects

Tools that modify downstream systems must be explicitly identified.

Recommended safety defaults:

```text
Read-only tools can be enabled first.
Write tools require explicit allowlist and policy.
Destructive tools are disabled by default.
External-side-effect tools are disabled by default until approval policy exists.
```

### 36.3 Prompt Injection and Tool Use

Tool results may include untrusted text.

Agents and strategies should treat tool outputs as data, not instructions.

Recommended rule:

```text
Tool result text must not override system, developer, policy, or agent instructions.
```

A future prompt/security document may define a standard tool-result quoting format.

---

## 37. Testing Strategy

### 37.1 Unit Tests

| Test | Purpose |
|---|---|
| Tool settings validate | Proves config safety. |
| Single MCP endpoint enforced | Prevents accidental multi-endpoint V1 drift. |
| Missing MCP auth fails when required | Proves credential config validation. |
| Tool registry loads allowlist | Proves logical tool setup. |
| Discovered unknown tool not callable | Enforces allowlist behavior. |
| Logical tool resolves to MCP tool | Proves registry mapping. |
| Unknown tool fails | Prevents arbitrary MCP calls. |
| Disabled tool fails | Enforces config disable. |
| Policy denied blocks call | Enforces policy before MCP. |
| Arguments validate against schema | Prevents malformed tool calls. |
| Secret-like arguments rejected/redacted | Proves argument safety. |
| MCP result normalizes | Prevents raw protocol leakage. |
| Oversized result truncates or fails safely | Enforces result bounds. |
| Timeout maps to normalized error | Proves error mapping. |
| Rate limit maps to normalized error | Proves retry/failure behavior. |
| Raw arguments not traced by default | Proves privacy behavior. |
| Raw results not traced by default | Proves privacy behavior. |
| Health output hides credentials | Proves safe health response. |

### 37.2 Integration Tests

| Test | Purpose |
|---|---|
| Gateway starts with fake MCP adapter | Proves composition wiring. |
| Tool discovery refreshes registry | Proves discovery path. |
| Gateway executes fake read-only tool | Proves end-to-end non-streaming tool call. |
| Gateway streams fake tool events | Proves stream contract. |
| Orchestration calls ToolGateway | Proves orchestration integration. |
| LLM tool intent executes through ToolGateway | Proves boundary path. |
| Tool result can be summarized into workflow state | Proves safe state handoff. |
| Trace events recorded for call | Proves observability. |
| API/session remain unchanged | Proves boundary stability. |

### 37.3 Optional Local MCP Test

For environments with the local MCP server running:

```text
MCP endpoint: http://localhost:9001/mcp
Transport: http or configured FastMCP-compatible transport
Auth: none or configured local token
```

This test should be marked optional or integration-local so CI does not depend on a private local MCP server.

---

## 38. Fixture Configs

Recommended fixtures:

```text
tests/fixtures/config/tooling_fake_basic.yaml
tests/fixtures/config/tooling_fake_streaming.yaml
tests/fixtures/config/tooling_fake_policy_denied.yaml
tests/fixtures/config/tooling_fake_disabled_tool.yaml
tests/fixtures/config/tooling_fake_unknown_tool.yaml
tests/fixtures/config/tooling_fake_discovery_allowlist.yaml
tests/fixtures/config/tooling_fake_result_too_large.yaml
tests/fixtures/config/tooling_mcp_local.yaml
tests/fixtures/config/tooling_mcp_auth_missing.yaml
tests/fixtures/config/tooling_multiple_mcp_endpoints_invalid.yaml
```

Recommended fake tools:

```text
documents.search
project.read_file
calendar.lookup
support.lookup_ticket
utility.echo
utility.stream_echo
utility.fail_retryable
utility.fail_non_retryable
```

---

## 39. Recommended Implementation Order

### Step 1: Add Tooling Config Schemas

Deliverables:

- `ToolingSettings`
- `MCPServerSettings`
- `MCPAuthSettings`
- `ToolDefinitionSettings`
- validation for single endpoint, auth, timeouts, schemas, and allowlist

Success criteria:

- Valid fake/local config loads.
- Multiple MCP endpoint config fails fast in V1.
- Secrets are environment-resolved but not logged.

### Step 2: Add Tool Models and Errors

Deliverables:

- `ToolScopes`
- `ToolDefinition`
- `ToolExecutionRequest`
- `ToolExecutionResult`
- `ToolStreamEvent`
- normalized tool errors

Success criteria:

- Models serialize/validate cleanly.
- Errors expose safe code/retryable values.

### Step 3: Add MCP Client Adapter Protocol

Deliverables:

- `MCPClientAdapter`
- internal MCP request/result models
- MCP health result model
- fake MCP adapter

Success criteria:

- Gateway can call fake MCP adapter without external services.

### Step 4: Add Tool Registry

Deliverables:

- logical tool registry
- mapping to MCP tool names
- static allowlist loading
- discovery merge behavior

Success criteria:

- Configured tools resolve correctly.
- Unknown discovered tools are not callable when allowlist is required.

### Step 5: Add Schema Validation

Deliverables:

- argument schema validation
- result bounds
- secret-like key detection
- safe summaries

Success criteria:

- Invalid arguments fail before MCP call.
- Oversized results are truncated or rejected safely.

### Step 6: Add Default ToolGateway

Deliverables:

- `list_tools`
- `get_tool`
- `execute`
- `stream_execute`
- `health`
- `capabilities`
- policy hook integration
- observability hook integration

Success criteria:

- Fake non-streaming and streaming calls work.
- Trace events are emitted safely.
- Policy denial blocks MCP execution.

### Step 7: Add MCP Transport and Auth

Deliverables:

- HTTP/FastMCP-compatible transport
- auth provider for none/bearer/JWT/OAuth client credentials
- timeout handling
- safe health check

Success criteria:

- Local MCP endpoint can be called when configured.
- Credentials do not leak into logs, traces, health, or capabilities.

### Step 8: Add Retry, Timeout, and Cancellation

Deliverables:

- retry helper
- retryable error classification
- cancellation handling
- optional idempotency key propagation

Success criteria:

- Retryable fake failures can retry safely.
- Non-idempotent tools do not retry blindly.
- Cancellation records safe trace event.

### Step 9: Add Orchestration Wiring

Deliverables:

- inject `ToolGateway` into `OrchestrationContext`
- update stub strategy or direct strategy to call a fake tool
- update agent examples to use logical tools

Success criteria:

- `POST /chat` path can use fake or local MCP tools through orchestration without changing API/session code.

### Step 10: Add Health and Capabilities Integration

Deliverables:

- tooling health section
- safe tool capability summaries
- optional discovery status

Success criteria:

- `/health` includes safe tooling readiness.
- `/capabilities` does not expose credentials or private MCP details.

---

## 40. Acceptance Criteria

This architecture is complete when:

- `ToolGateway` provides provider-neutral `list_tools`, `get_tool`, `execute`, `stream_execute`, `health`, and `capabilities` methods.
- `MCPClientAdapter` is the only backend component that speaks MCP protocol to the external MCP server.
- V1 configuration supports one MCP endpoint.
- Agents and strategies use `ToolGateway` through `OrchestrationContext` only.
- API routes do not call MCP server, MCP client adapter, or `ToolGateway` directly for normal chat behavior.
- `SessionService` does not call MCP server, MCP client adapter, or `ToolGateway` directly for normal chat behavior.
- Logical tool names are resolved through `ToolRegistry`.
- Discovered MCP tools are not executable unless allowlisted when configured.
- Tool execution is policy-checked before MCP calls.
- Tool arguments are schema-validated before MCP calls.
- Secret-like arguments are rejected or redacted according to policy.
- Tool results normalize into `ToolExecutionResult` and `ToolStreamEvent` objects.
- MCP protocol objects do not leak into agents, orchestration results, session results, API DTOs, workflow state, or traces.
- Tool calls are trace-correlated with `trace_id` and `session_id` where available.
- Trace events contain safe metadata only by default.
- Raw tool arguments and results are not logged or traced by default.
- MCP credentials are never exposed in logs, traces, health, capabilities, API responses, workflow state, or LLM prompts.
- Unknown tools fail clearly.
- Disabled tools fail clearly.
- Policy denial prevents MCP execution.
- Streaming MCP/tool events normalize into `ToolStreamEvent` objects.
- Tool failures normalize into stable backend errors.
- Retry behavior is explicit, bounded, and safe for idempotency.
- Destructive and external-side-effect tools are disabled by default unless policy explicitly allows them.
- Health checks report safe MCP/tool readiness.
- Fake MCP adapter tests can run without external services.
- Optional local MCP tests are isolated from CI.
- The backend is ready for the next document: `backend-orchestration-runtime-architecture.md`.

---

## 41. Anti-Patterns to Avoid

Avoid these during implementation:

- Calling the MCP server directly from API routes.
- Calling the MCP server directly from `SessionService`.
- Calling the MCP server directly from agents.
- Importing FastMCP server/client implementation details in agents.
- Hard-coding MCP endpoints in agents, strategies, sessions, or API routes.
- Reintroducing multiple MCP endpoints in V1.
- Letting users directly select arbitrary raw MCP tool names.
- Letting discovered tools become callable without allowlist/policy review.
- Passing raw LLM-generated JSON directly to MCP without validation.
- Passing credentials as tool arguments.
- Logging raw tool arguments by default.
- Logging raw tool results by default.
- Tracing raw MCP payloads by default.
- Returning raw MCP protocol objects to agents.
- Returning raw MCP errors to the frontend.
- Storing raw tool results in workflow state by default.
- Letting `ToolGateway` call LLM providers.
- Letting `ToolGateway` search or write memory.
- Letting `MCPClientAdapter` call SQLite or ArcadeDB.
- Retrying write/destructive/external-side-effect tools blindly.
- Executing approval-required tools without an approval boundary.
- Treating tool output text as trusted instructions.
- Exposing MCP credentials or endpoints in capabilities output.
- Making MCP health checks expensive by default.

---

## 42. Future Documents That Depend on This Tooling Layer

| Future Document | Dependency |
|---|---|
| `backend-orchestration-runtime-architecture.md` | Runtime coordinates LLM, memory, and tool calls through provider-neutral gateways. |
| `backend-workflow-strategies-architecture.md` | Strategies can parse tool intents, call tools, and handle tool results without MCP protocol details. |
| `backend-agents-architecture.md` | Agents declare tool needs and call logical tools while remaining MCP-neutral. |
| `backend-policy-architecture.md` | Defines final tool permissions, side-effect policy, approval requirements, trace capture rules, and data exposure rules. |
| `backend-approval-workflow-architecture.md` | Defines human approval flow for write/destructive/external-side-effect tools. |
| `backend-deployment-architecture.md` | Defines MCP endpoint configuration, service-to-service auth, network routing, and environment-specific tool settings. |
| `backend-evaluation-architecture.md` | Evaluates tool selection, argument correctness, error handling, and end-to-end task success. |

---

## 43. Summary

`backend-tooling-mcp-client-architecture.md` defines the backend layer that gives orchestration, strategies, and agents safe, provider-neutral access to external tools through one external MCP server.

It preserves the previously defined API, session, LLM, and memory boundaries: API routes remain thin, `SessionService` remains lifecycle-focused, `LLMGateway` remains the model boundary, and `MemoryGateway` remains the long-term memory boundary.

The most important implementation rule is:

> **The tooling layer owns tool execution, not business workflow logic. Agents and strategies request logical tool calls; `ToolGateway` resolves, validates, checks policy, traces, redacts, calls MCP through `MCPClientAdapter`, normalizes results, and prevents MCP/protocol/credential details from leaking into the rest of the backend.**
