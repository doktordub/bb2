# Backend Core Contracts Architecture

**Document:** `backend-core-contracts-architecture.md`  
**Version:** 1.0  
**Source alignment:** `backend-application-architecture.md`, `backend-foundation-architecture.md`, and `pluggable_agentic_ai_overall_architecture.md`  
**Scope:** Shared backend DTOs, protocol interfaces, context objects, result objects, gateway contracts, fake test implementations, dependency rules, and contract acceptance criteria.

---

## 1. Purpose

This document defines the second implementation-focused architecture document for the backend application tier.

It follows `backend-foundation-architecture.md`. The foundation document establishes the backend skeleton, application factory, settings loader, startup flow, logging baseline, health routes, and test layout. This document defines the stable contracts that later backend modules will depend on.

The goal is to make the backend contract-first before implementing concrete LLM providers, memory adapters, MCP tooling, persistence stores, orchestration strategies, session logic, or production agents.

The core contracts should answer these questions:

- What does a backend request look like after API validation?
- What context is passed into orchestration and agents?
- What does an agent return?
- What does an orchestration run return?
- What contracts must LLM, memory, tools, workflow state, trace, policy, and configuration implement?
- How can early tests run without real LLMs, real MCP, real SQLite, real ArcadeDB, or real `memory_store`?

---

## 2. Source Architecture Alignment

This document follows the already-established backend architecture rules:

- The backend is one deployable application tier in V1.
- The backend receives frontend traffic over REST / SSE.
- The backend calls the external MCP tier only through a backend-side MCP client adapter.
- The backend does not implement the MCP server.
- Agents receive controlled capabilities through `OrchestrationContext`.
- Agents do not import LLM provider SDKs, MCP clients, SQLite clients, ArcadeDB clients, or `memory_store.service.MemoryService`.
- LLM access must go through `LLMGateway`.
- Tool access must go through `ToolGateway`.
- Memory access must go through `MemoryGateway`.
- Workflow state access must go through `WorkflowStateStore`.
- Trace persistence must go through `TraceStore`.
- Policy decisions must go through `PolicyService`.
- Concrete provider, storage, and MCP details are intentionally not implemented in this contract phase.

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

This document expands Phase 2.

The output of this phase is not a working agentic runtime yet. The output is a set of small, stable interfaces and data objects that allow later modules to be implemented independently and tested with fakes.

---

## 4. Core Contract Goals

The core contracts should be:

1. **Small**  
   Each contract should describe a narrow capability.

2. **Stable**  
   Later implementation modules should depend on these contracts without needing frequent changes.

3. **Infrastructure-free**  
   Contracts should not import provider SDKs, MCP libraries, SQLite libraries, ArcadeDB libraries, or `memory_store` implementation types.

4. **Async-first**  
   Gateway and runtime contracts should support async execution because LLM, MCP, storage, and streaming operations are I/O heavy.

5. **Testable with fakes**  
   Contract definitions should make it easy to build fake LLM, memory, tools, state, trace, policy, and configuration providers.

6. **Serialization-friendly**  
   Result objects and DTOs should be easy to convert into JSON-safe responses, trace payloads, and logs.

7. **Policy-aware**  
   Contracts should leave clear places for policy decisions, even if the full policy engine comes later.

8. **Provider-neutral**  
   LLM, memory, and tool contracts should hide implementation details behind normalized request and response shapes.

---

## 5. Core Contract Non-Goals

This phase should not implement:

- Real FastAPI chat routes.
- Session lifecycle behavior.
- SQLite persistence.
- `memory_store` integration.
- ArcadeDB access.
- MCP client implementation.
- LLM provider adapters.
- YAML schema validation.
- Agent business behavior.
- Microsoft Agent Framework workflow execution.
- Streaming SSE route behavior.
- Production authentication or authorization.

Those belong in later architecture and implementation phases.

---

## 6. Recommended Contract Package Layout

The foundation phase created the backend shell. This phase adds a small contract layer.

Recommended layout:

```text
backend/
  app/
    contracts/
      __init__.py
      context.py
      results.py
      agents.py
      strategies.py
      llm.py
      memory.py
      tools.py
      state.py
      trace.py
      policy.py
      config.py
      errors.py
      health.py

    testing/
      __init__.py
      fakes/
        __init__.py
        fake_llm.py
        fake_memory.py
        fake_tools.py
        fake_state.py
        fake_trace.py
        fake_policy.py
        fake_config.py
        fake_agent.py
        fake_strategy.py

  tests/
    unit/
      contracts/
        test_context_models.py
        test_result_models.py
        test_fake_gateways.py
        test_fake_agent_strategy.py
```

### 6.1 Why a Central `contracts/` Package

A central `contracts/` package prevents early import cycles.

Later concrete modules can still live in their natural places:

```text
app/llm/             concrete LLM gateway and providers
app/persistence/     concrete memory/state/trace adapters
app/tools/           concrete tool gateway and MCP client adapter
app/orchestration/   concrete runtime and strategies
app/agents/          concrete agent plugins
```

Those modules import contracts. Contracts should not import concrete modules.

### 6.2 Alternative Layout

If the team prefers module-local contracts, the same types can be placed under their future modules:

```text
app/orchestration/context.py
app/orchestration/results.py
app/agents/base.py
app/llm/gateway.py
app/tools/base.py
app/persistence/base.py
```

However, for the early implementation phases, the central `app/contracts/` package is simpler because many modules do not exist yet.

---

## 7. Dependency Direction Rules

The contract layer should sit below implementation modules.

```text
Implementation modules
  ↓ import
Core contracts
```

Allowed examples:

```text
app/llm/gateway.py                -> app/contracts/llm.py
app/persistence/memory_adapter.py -> app/contracts/memory.py
app/tools/gateway.py              -> app/contracts/tools.py
app/orchestration/core.py         -> app/contracts/context.py
app/agents/support_agent.py       -> app/contracts/agents.py
```

Avoid:

```text
app/contracts/* -> app/llm/*
app/contracts/* -> app/tools/*
app/contracts/* -> app/persistence/*
app/contracts/* -> app/agents/*
app/contracts/* -> provider SDKs
app/contracts/* -> MCP SDK/client implementation
app/contracts/* -> SQLite or ArcadeDB clients
```

The contracts package may use only standard library types and carefully selected lightweight typing utilities.

---

## 8. Type and Implementation Conventions

Recommended conventions:

| Concern | Recommendation |
|---|---|
| DTOs and result objects | Use `dataclass` for lightweight internal models in V1. |
| Interfaces | Use `typing.Protocol` for dependency inversion and fake implementations. |
| Timestamps | Use timezone-aware `datetime`. |
| IDs | Use strings. Generation is an implementation concern. |
| Metadata | Use `dict[str, Any]` for extensibility, but keep required fields explicit. |
| Async calls | Use `async def` for gateways, strategies, agents, and stores. |
| Serialization | Add optional helper functions later; do not tie contracts to FastAPI/Pydantic yet. |
| Provider-specific payloads | Store only in `metadata` when absolutely necessary. |

### 8.1 Why `dataclass` First

Dataclasses keep the contract layer independent from the web framework and avoid forcing Pydantic models into all internal layers. API DTOs can later be Pydantic models and map into these internal contracts.

### 8.2 When Pydantic Can Be Added

Pydantic is useful at external boundaries:

```text
API request/response validation
YAML config validation
Health response validation
```

The core contracts should remain independent enough to be used by tests and non-HTTP orchestration code.

---

## 9. Shared Context Contracts

### 9.1 `RequestContext`

`RequestContext` is the normalized request object after API/session resolution.

```python
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class RequestContext:
    user_id: str
    session_id: str
    message: str
    usecase: str | None = None
    trace_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

Design notes:

- `user_id` and `session_id` are required because memory scope, workflow state, traces, and policy depend on them.
- `usecase` is optional because early walking-skeleton tests may run without full use-case configuration.
- `trace_id` is optional at contract level, but production requests should set it.
- `metadata` can include `project_id`, `tenant_id`, `channel`, `timezone`, `client`, or attachment references.

### 9.2 `OrchestrationContext`

`OrchestrationContext` is the capability container passed into strategies and agents.

```python
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class OrchestrationContext:
    request: RequestContext
    llm: "LLMGateway"
    memory: "MemoryGateway"
    state: "WorkflowStateStore"
    tools: "ToolGateway"
    trace: "TraceStore"
    policy: "PolicyService"
    config: "ConfigurationView"
    runtime_metadata: dict[str, Any]
```

Design notes:

- Agents should receive this object and nothing lower-level.
- This is where capabilities are controlled.
- Concrete gateways are hidden behind protocols.
- `runtime_metadata` is reserved for non-business runtime details such as selected strategy, test mode, or feature flags.

### 9.3 Context Construction Rule

Only orchestration/session-level code should construct `OrchestrationContext`.

Agents should not construct their own context. They should receive it.

---

## 10. Result Contracts

### 10.1 `AgentResult`

```python
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class AgentResult:
    answer: str
    agent_name: str
    confidence: float | None = None
    llm_profile: str | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    memory_updates: list[dict[str, Any]] = field(default_factory=list)
    handoff_to: str | None = None
    citations: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
```

Design notes:

- `answer` is the agent's normalized output text.
- `agent_name` makes trace/debug behavior easier.
- `handoff_to` supports future planner/router patterns without requiring them in V1.
- `citations` are generic dictionaries in this phase; a richer citation contract can be added later.

### 10.2 `OrchestrationResult`

```python
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class OrchestrationResult:
    answer: str
    session_id: str
    trace_id: str | None = None
    agent_name: str | None = None
    strategy_name: str | None = None
    llm_profile: str | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    memory_updates: list[dict[str, Any]] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
```

Design notes:

- This is the object returned by orchestration to the session/API layer.
- API routes later map this into HTTP/SSE response DTOs.
- It should not contain provider SDK objects or raw database records.

### 10.3 `StreamEvent`

Streaming is not implemented in this phase, but the contract can define a normalized event shape.

```python
from dataclasses import dataclass, field
from typing import Any, Literal


StreamEventType = Literal[
    "message_started",
    "content_delta",
    "tool_call_summary",
    "agent_summary",
    "trace_summary",
    "message_completed",
    "error",
]


@dataclass(slots=True)
class StreamEvent:
    event_type: StreamEventType
    data: dict[str, Any] = field(default_factory=dict)
```

The API/SSE layer can later convert these to SSE events.

---

## 11. Agent Contracts

### 11.1 `AgentPlugin`

```python
from typing import Protocol


class AgentPlugin(Protocol):
    name: str
    description: str
    capabilities: list[str]

    async def run(self, context: OrchestrationContext) -> AgentResult:
        ...
```

### 11.2 Agent Metadata

```python
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class AgentMetadata:
    name: str
    description: str
    capabilities: list[str]
    enabled: bool = True
    default_llm_profile: str | None = None
    allowed_tools: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
```

### 11.3 Agent Design Rules

Agents may:

- Use `context.llm.complete(...)`.
- Use `context.llm.stream(...)`.
- Use `context.memory.search(...)`.
- Use `context.memory.upsert(...)` when allowed.
- Use `context.tools.call_tool(...)` when allowed.
- Read approved use-case/agent configuration through `context.config`.
- Record trace events through `context.trace` when appropriate.

Agents must not:

- Import provider SDKs.
- Hard-code model names or endpoint URLs.
- Import MCP clients.
- Import SQLite clients.
- Import ArcadeDB clients.
- Import `memory_store.service.MemoryService`.
- Make unrestricted network calls.
- Bypass policy checks.

---

## 12. Strategy Contracts

### 12.1 `OrchestrationStrategy`

```python
from typing import Protocol


class OrchestrationStrategy(Protocol):
    name: str

    async def run(
        self,
        context: OrchestrationContext,
        agents: list[AgentPlugin],
    ) -> OrchestrationResult:
        ...
```

### 12.2 Strategy Metadata

```python
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class StrategyMetadata:
    name: str
    description: str
    supports_streaming: bool = False
    default_llm_profile: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

### 12.3 Strategy Design Rules

Strategies may:

- Select one or more agents.
- Use `context.llm` for router/planner calls.
- Use `context.memory` to load context before agent execution.
- Use `context.trace` to record strategy and routing events.
- Return a normalized `OrchestrationResult`.

Strategies must not:

- Instantiate provider clients.
- Call MCP directly.
- Run SQL.
- Import ArcadeDB or `memory_store`.
- Hard-code business-specific infrastructure details.

---

## 13. LLM Contracts

### 13.1 LLM Message and Request Models

```python
from dataclasses import dataclass, field
from typing import Any, Literal


LLMRole = Literal["system", "user", "assistant", "tool"]


@dataclass(slots=True)
class LLMMessage:
    role: LLMRole
    content: str
    name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class LLMRequest:
    component: str
    messages: list[LLMMessage]
    profile: str | None = None
    response_format: dict[str, Any] | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

### 13.2 LLM Response Models

```python
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class LLMUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class LLMResponse:
    text: str
    profile: str
    provider: str
    model: str
    usage: LLMUsage | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

### 13.3 Streaming Delta

```python
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class LLMStreamDelta:
    text_delta: str
    profile: str | None = None
    provider: str | None = None
    model: str | None = None
    is_final: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
```

### 13.4 `LLMGateway` Protocol

```python
from collections.abc import AsyncIterator
from typing import Protocol


class LLMGateway(Protocol):
    async def complete(
        self,
        request: LLMRequest,
        context: OrchestrationContext,
    ) -> LLMResponse:
        ...

    async def stream(
        self,
        request: LLMRequest,
        context: OrchestrationContext,
    ) -> AsyncIterator[LLMStreamDelta]:
        ...
```

### 13.5 LLM Contract Rules

- `LLMRequest.profile` is a logical profile name, not a provider/model hard-code.
- Provider, model, endpoint, timeout, fallback, and credential details are resolved later by the LLM gateway implementation.
- The contract should support local OpenAI-compatible endpoints, cloud providers, and custom providers without changing agents.
- `component` should be set to values such as `orchestrator.router_strategy` or `agent.document_qa_agent` for tracing and policy.

---

## 14. Memory Contracts

### 14.1 Memory Scope

```python
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class MemoryScope:
    user_id: str | None = None
    project_id: str | None = None
    tenant_id: str | None = None
    usecase: str | None = None
    session_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

### 14.2 Memory Search and Result Models

```python
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class MemorySearchRequest:
    text: str
    scope: MemoryScope
    memory_types: list[str] | None = None
    limit: int = 10
    include_document_chunks: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class MemoryResult:
    memory_id: str
    text: str
    score: float | None = None
    memory_type: str | None = None
    source_id: str | None = None
    chunk_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

### 14.3 Memory Write Models

```python
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class MemoryWrite:
    text: str
    scope: MemoryScope
    memory_type: str
    stable_key: str | None = None
    importance: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class MemoryRecord:
    memory_id: str
    text: str
    memory_type: str
    scope: MemoryScope
    metadata: dict[str, Any] = field(default_factory=dict)
```

### 14.4 `MemoryGateway` Protocol

```python
from typing import Protocol


class MemoryGateway(Protocol):
    async def search(
        self,
        request: MemorySearchRequest,
        context: OrchestrationContext,
    ) -> list[MemoryResult]:
        ...

    async def upsert(
        self,
        memory: MemoryWrite,
        context: OrchestrationContext,
    ) -> MemoryRecord:
        ...

    async def forget(
        self,
        memory_id: str,
        context: OrchestrationContext,
    ) -> None:
        ...

    async def health(self) -> dict[str, Any]:
        ...
```

### 14.5 Memory Contract Rules

- The contract mentions memory, not ArcadeDB.
- The contract mentions the memory gateway, not `memory_store.service.MemoryService`.
- Document chunks can be represented as `MemoryResult` records with `source_id` and `chunk_id`.
- Scope is required for search and write operations.
- Long-term memory should remain separate from workflow state and traces.

---

## 15. Tool Contracts

### 15.1 Tool Specification and Result Models

```python
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    source: str
    permissions: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ToolCallRequest:
    tool_name: str
    arguments: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ToolResult:
    tool_name: str
    success: bool
    data: Any | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

### 15.2 `ToolGateway` Protocol

```python
from typing import Protocol


class ToolGateway(Protocol):
    async def list_tools(
        self,
        context: OrchestrationContext,
    ) -> list[ToolSpec]:
        ...

    async def call_tool(
        self,
        request: ToolCallRequest,
        context: OrchestrationContext,
    ) -> ToolResult:
        ...
```

### 15.3 Tool Contract Rules

- Tool names should be logical names such as `documents.search` or `support.create_ticket`.
- The tool contract does not expose MCP implementation details.
- Later MCP client adapters normalize MCP tools into `ToolSpec` and MCP responses into `ToolResult`.
- Tool authorization is enforced by `ToolGateway` and `PolicyService`, not by agents directly.

---

## 16. Workflow State Contracts

### 16.1 State Models

```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class WorkflowStateRecord:
    session_id: str
    state: dict[str, Any]
    version: int = 1
    created_at: datetime | None = None
    updated_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

### 16.2 `WorkflowStateStore` Protocol

```python
from typing import Any, Protocol


class WorkflowStateStore(Protocol):
    async def load(self, session_id: str) -> dict[str, Any]:
        ...

    async def save(self, session_id: str, state: dict[str, Any]) -> None:
        ...

    async def reset(self, session_id: str) -> None:
        ...

    async def health(self) -> dict[str, Any]:
        ...
```

### 16.3 Workflow State Contract Rules

- Workflow state is short-term runtime/session state.
- Workflow state is not long-term memory.
- Session reset should call `WorkflowStateStore.reset(session_id)`.
- Session reset must not call memory deletion unless a separate explicit memory deletion request is made.
- SQLite is a later implementation detail.

---

## 17. Trace Contracts

### 17.1 Trace Event Model

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

### 17.2 `TraceStore` Protocol

```python
from typing import Any, Protocol


class TraceStore(Protocol):
    async def record_event(self, event: TraceEvent) -> None:
        ...

    async def health(self) -> dict[str, Any]:
        ...
```

### 17.3 Minimum Event Type Constants

```python
REQUEST_RECEIVED = "request_received"
CONTEXT_CREATED = "context_created"
WORKFLOW_STATE_LOADED = "workflow_state_loaded"
MEMORY_SEARCH_STARTED = "memory_search_started"
MEMORY_SEARCH_COMPLETED = "memory_search_completed"
LLM_CALL_STARTED = "llm_call_started"
LLM_CALL_COMPLETED = "llm_call_completed"
LLM_CALL_FAILED = "llm_call_failed"
LLM_FALLBACK_SELECTED = "llm_fallback_selected"
STRATEGY_SELECTED = "strategy_selected"
AGENT_SELECTED = "agent_selected"
AGENT_STARTED = "agent_started"
AGENT_COMPLETED = "agent_completed"
TOOL_CALL_STARTED = "tool_call_started"
TOOL_CALL_COMPLETED = "tool_call_completed"
TOOL_CALL_FAILED = "tool_call_failed"
WORKFLOW_STATE_SAVED = "workflow_state_saved"
RESPONSE_RETURNED = "response_returned"
ERROR_OCCURRED = "error_occurred"
```

### 17.4 Trace Contract Rules

- Trace events are operational records, not memories.
- The contract should not assume SQLite.
- Payloads should be JSON-safe.
- Do not store secrets, tokens, API keys, raw credentials, or sensitive payloads in trace data.

---

## 18. Policy Contracts

### 18.1 Policy Decision Models

```python
from dataclasses import dataclass, field
from typing import Any, Literal


PolicyAction = Literal[
    "llm.complete",
    "llm.stream",
    "memory.search",
    "memory.upsert",
    "memory.forget",
    "tool.list",
    "tool.call",
    "state.load",
    "state.save",
    "state.reset",
]


@dataclass(slots=True)
class PolicyRequest:
    action: PolicyAction
    component: str
    resource: str | None = None
    scope: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PolicyDecision:
    allowed: bool
    reason: str | None = None
    requires_approval: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
```

### 18.2 `PolicyService` Protocol

```python
from typing import Protocol


class PolicyService(Protocol):
    async def evaluate(
        self,
        request: PolicyRequest,
        context: OrchestrationContext,
    ) -> PolicyDecision:
        ...

    async def require_allowed(
        self,
        request: PolicyRequest,
        context: OrchestrationContext,
    ) -> None:
        ...
```

### 18.3 Policy Contract Rules

- Policy should be deny-by-default in real implementations.
- Fake policy may allow everything by default for early unit tests.
- Tool, LLM, memory, and state operations should have clear policy action names.
- Detailed policy rules are implemented later in `policy-architecture.md`.

---

## 19. Configuration Contracts

### 19.1 Configuration View

The contract layer should not implement full YAML validation yet. It should define the read-only interface that runtime code can depend on.

```python
from typing import Any, Protocol


class ConfigurationView(Protocol):
    def get(self, path: str, default: Any = None) -> Any:
        ...

    def require(self, path: str) -> Any:
        ...

    def section(self, path: str) -> dict[str, Any]:
        ...
```

### 19.2 Configuration Loader Protocol

```python
from typing import Protocol


class ConfigurationLoader(Protocol):
    async def load(self) -> ConfigurationView:
        ...
```

### 19.3 Configuration Contract Rules

- Full YAML schema validation comes in the next architecture document.
- Runtime code should ask for configuration through `ConfigurationView`, not raw environment variables.
- Provider/model/tool details should remain outside agents and API routes.

---

## 20. Error Contracts

### 20.1 Base Error Types

```python
class BackendError(Exception):
    """Base exception for known backend errors."""


class ConfigurationError(BackendError):
    """Configuration is missing, invalid, or inconsistent."""


class PolicyDeniedError(BackendError):
    """A policy check denied the requested action."""


class GatewayError(BackendError):
    """Base error for gateway failures."""


class LLMGatewayError(GatewayError):
    """LLM gateway failed or returned invalid output."""


class ToolGatewayError(GatewayError):
    """Tool gateway or downstream MCP call failed."""


class MemoryGatewayError(GatewayError):
    """Memory gateway failed."""


class WorkflowStateError(GatewayError):
    """Workflow state load/save/reset failed."""


class TraceStoreError(GatewayError):
    """Trace store write failed."""
```

### 20.2 Error Contract Rules

- Contracts define error categories, not HTTP mappings.
- API error-to-response mapping belongs in `backend-api-architecture.md`.
- Implementations should raise known errors where useful and include trace-safe metadata.
- Do not include secrets in exception messages.

---

## 21. Health Contract

The foundation already introduced health routes. This phase defines a small component health contract that future modules can implement.

```python
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol


HealthStatus = Literal["ok", "degraded", "error", "unknown"]


@dataclass(slots=True)
class ComponentHealth:
    name: str
    status: HealthStatus
    configured: bool = True
    details: dict[str, Any] = field(default_factory=dict)


class HealthCheck(Protocol):
    async def health(self) -> ComponentHealth | dict[str, Any]:
        ...
```

Health outputs must not include secrets, tokens, full connection strings, credentials, raw prompts, raw completions, or sensitive memory content.

---

## 22. Fake Implementations for Tests

The contract phase should include fake implementations so tests can run before real adapters exist.

### 22.1 Fake LLM Gateway

```python
from collections.abc import AsyncIterator


class FakeLLMGateway:
    def __init__(self, response_text: str = "fake response") -> None:
        self.response_text = response_text
        self.requests: list[LLMRequest] = []

    async def complete(
        self,
        request: LLMRequest,
        context: OrchestrationContext,
    ) -> LLMResponse:
        self.requests.append(request)
        return LLMResponse(
            text=self.response_text,
            profile=request.profile or "fake_profile",
            provider="fake_provider",
            model="fake_model",
        )

    async def stream(
        self,
        request: LLMRequest,
        context: OrchestrationContext,
    ) -> AsyncIterator[LLMStreamDelta]:
        self.requests.append(request)
        yield LLMStreamDelta(
            text_delta=self.response_text,
            profile=request.profile or "fake_profile",
            provider="fake_provider",
            model="fake_model",
            is_final=True,
        )
```

### 22.2 Fake Memory Gateway

```python
class FakeMemoryGateway:
    def __init__(self, results: list[MemoryResult] | None = None) -> None:
        self.results = results or []
        self.search_requests: list[MemorySearchRequest] = []
        self.writes: list[MemoryWrite] = []

    async def search(
        self,
        request: MemorySearchRequest,
        context: OrchestrationContext,
    ) -> list[MemoryResult]:
        self.search_requests.append(request)
        return self.results

    async def upsert(
        self,
        memory: MemoryWrite,
        context: OrchestrationContext,
    ) -> MemoryRecord:
        self.writes.append(memory)
        return MemoryRecord(
            memory_id=memory.stable_key or "fake_memory_id",
            text=memory.text,
            memory_type=memory.memory_type,
            scope=memory.scope,
            metadata=memory.metadata,
        )

    async def forget(self, memory_id: str, context: OrchestrationContext) -> None:
        return None

    async def health(self) -> dict[str, Any]:
        return {"status": "ok", "provider": "fake"}
```

### 22.3 Fake Tool Gateway

```python
class FakeToolGateway:
    def __init__(self, tools: list[ToolSpec] | None = None) -> None:
        self.tools = tools or []
        self.calls: list[ToolCallRequest] = []

    async def list_tools(self, context: OrchestrationContext) -> list[ToolSpec]:
        return self.tools

    async def call_tool(
        self,
        request: ToolCallRequest,
        context: OrchestrationContext,
    ) -> ToolResult:
        self.calls.append(request)
        return ToolResult(
            tool_name=request.tool_name,
            success=True,
            data={"fake": True, "arguments": request.arguments},
        )
```

### 22.4 Fake Workflow State Store

```python
class FakeWorkflowStateStore:
    def __init__(self) -> None:
        self.states: dict[str, dict[str, Any]] = {}

    async def load(self, session_id: str) -> dict[str, Any]:
        return self.states.get(session_id, {})

    async def save(self, session_id: str, state: dict[str, Any]) -> None:
        self.states[session_id] = state

    async def reset(self, session_id: str) -> None:
        self.states.pop(session_id, None)

    async def health(self) -> dict[str, Any]:
        return {"status": "ok", "provider": "fake"}
```

### 22.5 Fake Trace Store

```python
class FakeTraceStore:
    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    async def record_event(self, event: TraceEvent) -> None:
        self.events.append(event)

    async def health(self) -> dict[str, Any]:
        return {"status": "ok", "provider": "fake"}
```

### 22.6 Fake Policy Service

```python
class FakePolicyService:
    def __init__(self, allow: bool = True) -> None:
        self.allow = allow
        self.requests: list[PolicyRequest] = []

    async def evaluate(
        self,
        request: PolicyRequest,
        context: OrchestrationContext,
    ) -> PolicyDecision:
        self.requests.append(request)
        return PolicyDecision(
            allowed=self.allow,
            reason=None if self.allow else "Denied by fake policy",
        )

    async def require_allowed(
        self,
        request: PolicyRequest,
        context: OrchestrationContext,
    ) -> None:
        decision = await self.evaluate(request, context)
        if not decision.allowed:
            raise PolicyDeniedError(decision.reason or "Policy denied")
```

### 22.7 Fake Configuration View

```python
class FakeConfigurationView:
    def __init__(self, values: dict[str, Any] | None = None) -> None:
        self.values = values or {}

    def get(self, path: str, default: Any = None) -> Any:
        current: Any = self.values
        for part in path.split("."):
            if not isinstance(current, dict) or part not in current:
                return default
            current = current[part]
        return current

    def require(self, path: str) -> Any:
        value = self.get(path, None)
        if value is None:
            raise ConfigurationError(f"Missing required config path: {path}")
        return value

    def section(self, path: str) -> dict[str, Any]:
        value = self.get(path, {})
        if not isinstance(value, dict):
            raise ConfigurationError(f"Config path is not a section: {path}")
        return value
```

---

## 23. Contract Test Patterns

### 23.1 Context Construction Test

```python
async def test_orchestration_context_can_be_constructed() -> None:
    request = RequestContext(
        user_id="user_1",
        session_id="session_1",
        message="hello",
        usecase="test",
        trace_id="trace_1",
    )

    context = OrchestrationContext(
        request=request,
        llm=FakeLLMGateway(),
        memory=FakeMemoryGateway(),
        state=FakeWorkflowStateStore(),
        tools=FakeToolGateway(),
        trace=FakeTraceStore(),
        policy=FakePolicyService(),
        config=FakeConfigurationView(),
        runtime_metadata={},
    )

    assert context.request.session_id == "session_1"
```

### 23.2 Fake Agent Test

```python
class FakeAgent:
    name = "fake_agent"
    description = "A fake test agent."
    capabilities = ["test"]

    async def run(self, context: OrchestrationContext) -> AgentResult:
        response = await context.llm.complete(
            LLMRequest(
                component="agent.fake_agent",
                messages=[LLMMessage(role="user", content=context.request.message)],
            ),
            context,
        )
        return AgentResult(
            answer=response.text,
            agent_name=self.name,
            llm_profile=response.profile,
        )
```

### 23.3 Fake Strategy Test

```python
class FakeDirectStrategy:
    name = "fake_direct_strategy"

    async def run(
        self,
        context: OrchestrationContext,
        agents: list[AgentPlugin],
    ) -> OrchestrationResult:
        agent = agents[0]
        result = await agent.run(context)
        return OrchestrationResult(
            answer=result.answer,
            session_id=context.request.session_id,
            trace_id=context.request.trace_id,
            agent_name=result.agent_name,
            strategy_name=self.name,
            llm_profile=result.llm_profile,
        )
```

---

## 24. Contract Validation Checklist

Before moving to the configuration architecture phase, validate that:

- Contract modules import without importing concrete LLM, MCP, SQLite, ArcadeDB, or `memory_store` packages.
- `RequestContext` can represent a normalized frontend/API request.
- `OrchestrationContext` can hold fake gateway implementations.
- `AgentPlugin` can be implemented by a fake agent.
- `OrchestrationStrategy` can be implemented by a fake direct strategy.
- `LLMGateway` fake can return a deterministic completion.
- `MemoryGateway` fake can return deterministic memory results.
- `ToolGateway` fake can record tool calls.
- `WorkflowStateStore` fake can load, save, and reset in memory.
- `TraceStore` fake can record events in memory.
- `PolicyService` fake can allow or deny actions.
- Unit tests can run without real external services.

---

## 25. Walking Skeleton Enabled by Contracts

After this phase, the backend should be ready to build a walking skeleton like this:

```text
POST /chat
  -> SessionService
  -> OrchestrationRuntime
  -> DirectStrategy
  -> FakeAgent
  -> FakeLLMGateway
  -> FakeWorkflowStateStore or future SQLite store
  -> FakeTraceStore or future SQLite trace store
  -> Response
```

The important outcome is not intelligence yet. The important outcome is that the dependency direction is correct and the route can be tested end-to-end without concrete infrastructure.

---

## 26. Recommended Implementation Order Inside This Phase

### Step 1: Create Contract Package

Deliverables:

- `app/contracts/__init__.py`
- `app/contracts/context.py`
- `app/contracts/results.py`
- `app/contracts/errors.py`

Success criteria:

- Context and result models import successfully.
- Basic model construction tests pass.

### Step 2: Define Agent and Strategy Protocols

Deliverables:

- `app/contracts/agents.py`
- `app/contracts/strategies.py`

Success criteria:

- Fake agent can implement `AgentPlugin`.
- Fake strategy can implement `OrchestrationStrategy`.

### Step 3: Define Gateway Protocols

Deliverables:

- `app/contracts/llm.py`
- `app/contracts/memory.py`
- `app/contracts/tools.py`
- `app/contracts/state.py`
- `app/contracts/trace.py`
- `app/contracts/policy.py`
- `app/contracts/config.py`

Success criteria:

- Fakes can implement all gateway contracts.
- Contract tests do not require real providers.

### Step 4: Add Fake Implementations

Deliverables:

- `app/testing/fakes/fake_llm.py`
- `app/testing/fakes/fake_memory.py`
- `app/testing/fakes/fake_tools.py`
- `app/testing/fakes/fake_state.py`
- `app/testing/fakes/fake_trace.py`
- `app/testing/fakes/fake_policy.py`
- `app/testing/fakes/fake_config.py`
- `app/testing/fakes/fake_agent.py`
- `app/testing/fakes/fake_strategy.py`

Success criteria:

- Tests can build a complete fake `OrchestrationContext`.
- Fake direct strategy can execute fake agent.

### Step 5: Add Contract Tests

Deliverables:

- Unit tests for model construction.
- Unit tests for fake gateways.
- Unit tests for fake agent and strategy.
- Unit tests proving no concrete infrastructure is required.

Success criteria:

- `pytest` passes.
- No test needs a live LLM, MCP server, SQLite database, ArcadeDB database, or memory store.

---

## 27. Acceptance Criteria

This architecture is complete when:

- The backend has a stable core contract layer.
- Contracts compile/import without concrete infrastructure dependencies.
- Agents can be written against `OrchestrationContext`.
- Strategies can be written against `OrchestrationContext` and `AgentPlugin`.
- LLM access is represented only by `LLMGateway`.
- Memory access is represented only by `MemoryGateway`.
- Tool access is represented only by `ToolGateway`.
- Workflow state is represented only by `WorkflowStateStore`.
- Traces are represented only by `TraceStore`.
- Policy is represented only by `PolicyService`.
- Configuration is represented by `ConfigurationView` and `ConfigurationLoader`.
- Fake implementations exist for all gateways and stores.
- Unit tests can exercise agent and strategy behavior using fakes.
- No agent, strategy, or contract imports provider SDKs, MCP clients, SQLite clients, ArcadeDB clients, or `memory_store` concrete types.
- The backend is ready for the next document: `configuration-architecture.md`.

---

## 28. Anti-Patterns to Avoid

Avoid these during the core contracts phase:

- Adding real LLM provider clients into contract modules.
- Adding MCP client libraries into contract modules.
- Adding SQLAlchemy or SQLite logic into contract modules.
- Adding ArcadeDB or `memory_store` imports into contract modules.
- Making `OrchestrationContext` too large or business-specific.
- Letting agents receive concrete implementations instead of protocols.
- Creating one large `BackendServices` object that hides unclear dependencies.
- Returning provider-specific raw responses from gateway contracts.
- Returning MCP-specific raw responses from tool contracts.
- Storing request traces as memory results.
- Treating workflow state as memory.
- Skipping fake implementations and jumping directly to real adapters.

---

## 29. Future Documents That Depend on These Contracts

The following documents should build directly on this one:

| Future Document | Depends on These Contracts |
|---|---|
| `configuration-architecture.md` | `ConfigurationView`, `ConfigurationLoader`, profile/config access patterns |
| `observability-architecture.md` | `TraceEvent`, `TraceStore`, health contracts, error contracts |
| `persistence-architecture.md` | `MemoryGateway`, `WorkflowStateStore`, `TraceStore` |
| `sqlite-workflow-state-architecture.md` | `WorkflowStateStore`, `WorkflowStateRecord` |
| `sqlite-trace-store-architecture.md` | `TraceStore`, `TraceEvent` |
| `backend-api-architecture.md` | `RequestContext`, `OrchestrationResult`, error contracts |
| `session-service-architecture.md` | `RequestContext`, `WorkflowStateStore`, `OrchestrationResult` |
| `llm-gateway-architecture.md` | `LLMGateway`, `LLMRequest`, `LLMResponse`, `LLMStreamDelta` |
| `memory-store-adapter-architecture.md` | `MemoryGateway`, `MemorySearchRequest`, `MemoryResult`, `MemoryWrite` |
| `tooling-mcp-client-architecture.md` | `ToolGateway`, `ToolSpec`, `ToolCallRequest`, `ToolResult` |
| `orchestration-architecture.md` | `OrchestrationContext`, `OrchestrationStrategy`, `AgentPlugin` |
| `workflow-strategies-architecture.md` | `OrchestrationStrategy`, `AgentPlugin`, `OrchestrationResult` |
| `agents-architecture.md` | `AgentPlugin`, `AgentResult`, gateway protocols |
| `policy-architecture.md` | `PolicyRequest`, `PolicyDecision`, `PolicyService` |

---

## 30. Summary

The core contracts layer is the dependency anchor for the backend application.

It should be implemented immediately after the backend foundation because every later module needs stable shared types and protocols. These contracts allow the backend to grow from a simple walking skeleton into a full agentic runtime without coupling agents to LLM SDKs, MCP clients, SQLite, ArcadeDB, or other concrete infrastructure.

The most important implementation rule is:

> **Contracts define capability boundaries. Concrete modules provide implementations. Agents and strategies depend on the capabilities, not the infrastructure.**
