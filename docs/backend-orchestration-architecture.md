# Backend Orchestration Architecture

**Document:** `backend-orchestration-architecture.md`  
**Version:** 1.0  
**Source alignment:** `backend-application-architecture.md`, `backend-foundation-architecture.md`, `backend-core-contracts-architecture.md`, `backend-configuration-architecture.md`, `backend-observability-architecture.md`, `backend-persistence-architecture.md`, `backend-sqlite-workflow-state-architecture.md`, `backend-sqlite-trace-store-architecture.md`, `backend-api-architecture.md`, `backend-session-service-architecture.md`, `backend-llm-gateway-architecture.md`, `backend-memory-store-adapter-architecture.md`, and `backend-tooling-mcp-client-architecture.md`  
**Scope:** Backend orchestration runtime, strategy execution, turn lifecycle, orchestration context, gateway coordination, strategy registry, use-case routing, planning boundaries, LLM/memory/tool integration, streaming orchestration events, workflow-state handoff, trace correlation, error normalization, testing strategy, and acceptance criteria for the V1 orchestration layer.

---

## 1. Purpose

This document defines the thirteenth implementation-focused architecture document for the backend application tier.

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
12. `backend-tooling-mcp-client-architecture.md`
13. `backend-orchestration-architecture.md` ← this document

The previous document established `ToolGateway` as the only orchestration-facing boundary for tool execution and `MCPClientAdapter` as the only backend adapter that speaks MCP protocol to the single external MCP server.

This document defines the orchestration layer that sits above the LLM, memory, and tool gateways.

The goal is to provide a small but extensible runtime that can coordinate a user turn, choose a strategy, call an agent, use LLM/memory/tools through provider-neutral gateways, emit safe stream events, update workflow state summaries, and return normalized session results without leaking infrastructure details across module boundaries.

The core architecture rule is:

> `OrchestrationRuntime` is the only session-facing boundary for running a user turn. Strategies and agents coordinate work through `OrchestrationContext` and provider-neutral gateways. The runtime must not import concrete LLM providers, `memory_store`, ArcadeDB clients, MCP clients, SQLite clients, API DTOs, or frontend-specific response models.

---

## 2. Source Architecture Alignment

This document follows the established backend rules:

- The backend is one deployable application tier in V1.
- Frontend communicates with backend through REST / SSE.
- API routes are thin and delegate chat/reset behavior to `SessionService`.
- `SessionService` owns session lifecycle, workflow-state load/save/reset, and request-to-runtime handoff.
- `SessionService` calls `OrchestrationRuntime`; it does not select agents, call LLM providers, execute tools, or search memory directly for normal chat behavior.
- `OrchestrationRuntime` owns per-turn execution flow, strategy selection, context creation, cancellation handling, and normalized runtime results.
- Strategies own workflow shape, such as direct agent, retrieval-augmented answer, tool-assisted answer, or router behavior.
- Agents own task-specific reasoning and domain-specific behavior, but agent plugin details are defined in the next document.
- LLM calls remain behind `LLMGateway`.
- Long-term memory and document chunks remain behind `MemoryGateway`.
- External tool execution remains behind `ToolGateway`.
- MCP protocol communication remains behind `MCPClientAdapter`.
- SQLite workflow state remains behind `WorkflowStateStore`.
- SQLite traces remain behind `TraceStore` or the observability facade.
- ArcadeDB-backed memory remains behind the memory adapter and must not leak into orchestration code.
- Orchestration stream events must be safe, bounded, and suitable for `SessionService` to map to session stream events and API SSE events.
- Raw LLM provider payloads, raw MCP payloads, raw memory records, raw workflow state documents, raw trace payloads, credentials, and hidden scratchpads must not be returned to the API/frontend.
- Tool, LLM, memory, and strategy decisions must be trace-correlated with the active `trace_id`.

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
Phase 13: Orchestration Runtime and Strategy Contract
Phase 14: Workflow Strategy Implementations
Phase 15: Agent Plugins
Phase 16: Policy Hardening
Phase 17: Deployment Readiness
```

This document expands Phase 13.

The output of this phase is a backend orchestration layer that supports:

```text
OrchestrationRuntime.run_turn(...)
OrchestrationRuntime.stream_turn(...)
OrchestrationRuntime.health(...)
OrchestrationRuntime.capabilities(...)

StrategyRegistry.resolve(...)
StrategyRegistry.list(...)
StrategyRegistry.register(...)

OrchestrationStrategy.run(...)
OrchestrationStrategy.stream(...)
```

The next document should be:

```text
backend-workflow-strategies-architecture.md
```


---

## 4. Architecture Goals

The orchestration layer should be:

1. **Session-facing but session-neutral**  
   `SessionService` calls the runtime, but the runtime does not create, reset, or persist sessions directly.

2. **Gateway-oriented**  
   Runtime, strategies, and agents call LLMs, memory, and tools only through `LLMGateway`, `MemoryGateway`, and `ToolGateway`.

3. **Strategy-driven**  
   Different use cases can select different orchestration strategies without changing API routes or session service internals.

4. **Agent-ready**  
   The runtime should invoke agent plugins through a narrow provider-neutral contract while leaving detailed agent plugin design to the next document.

5. **Streaming-capable**  
   Runtime and strategies should emit normalized orchestration stream events that can be mapped to session stream events and API SSE events.

6. **Trace-correlated**  
   Every turn, strategy decision, agent invocation, gateway call summary, failure, and cancellation should be correlated with `trace_id`.

7. **State-summary oriented**  
   Runtime returns safe workflow-state patches or summaries to `SessionService`; it does not write directly to SQLite.

8. **Policy-aware**  
   Strategy selection, model/profile usage, memory access, and tool execution should pass through policy hooks or gateway-level policy checks.

9. **Configurable**  
   Use cases, default strategy, fallback strategy, strategy limits, max steps, max tool calls, memory behavior, and streaming behavior should be configured through YAML.

10. **Failure-bounded**  
   Runtime should normalize strategy, agent, LLM, memory, and tool errors into stable orchestration errors.

11. **Cancellation-aware**  
   Streaming and long-running turns must propagate cancellation to strategies and gateway calls where supported.

12. **Testable**  
   Runtime tests should run with fake LLM, fake memory, fake tools, fake strategies, and fake agents.

---

## 5. Non-Goals

This document should not implement:

- API route behavior.
- Session creation, resume, reset, or ownership rules.
- Concrete SQLite workflow-state SQL.
- Concrete SQLite trace SQL.
- Concrete LLM provider integrations.
- Concrete ArcadeDB or `memory_store` implementation.
- MCP client protocol details.
- MCP server implementation.
- Full agent plugin catalog.
- Full prompt templates for every agent.
- Human approval workflow.
- Production authentication and authorization.
- Multi-tenant policy model.
- Frontend rendering behavior.
- Distributed workflow engines.
- Long-running background jobs.
- Durable task queues.
- Multi-process orchestration coordination.
- Full evaluation harness.

Those concerns belong to API, session, persistence, LLM, memory, tooling, MCP, agents, policy, approval, deployment, and evaluation documents.

---

## 6. Orchestration Boundary

The orchestration layer sits between `SessionService` and the provider-neutral gateways.

It owns:

- Per-turn runtime lifecycle.
- Strategy resolution.
- Strategy registry.
- Orchestration context construction.
- Gateway dependency injection into strategies/agents.
- Agent invocation boundary.
- Safe turn result assembly.
- Runtime stream event normalization.
- Runtime-level timeout and cancellation handling.
- Safe workflow-state delta generation.
- Safe trace events for orchestration decisions.
- Runtime health and capability summaries.

It does not own:

- API request parsing or response DTOs.
- Session ID creation or reset behavior.
- Workflow-state persistence implementation.
- Trace persistence implementation.
- LLM provider SDK calls.
- MCP protocol calls.
- Memory store implementation.
- Tool registry internals.
- Concrete agent plugin loading details beyond invoking registered agents.
- Frontend SSE wire formatting.

### 6.1 Boundary Diagram

```text
Frontend
  -> API
      -> SessionService
          -> WorkflowStateStore.load(...)
          -> OrchestrationRuntime
              -> StrategyRegistry
              -> OrchestrationStrategy
                  -> AgentRegistry / AgentPlugin
                  -> LLMGateway
                  -> MemoryGateway
                  -> ToolGateway
                  -> PolicyService
                  -> ObservabilityRecorder
          -> WorkflowStateStore.save(...)
      -> API response / SSE mapping
```

### 6.2 Practical Rule

`SessionService` should do this:

```python
result = await orchestration.run_turn(
    request=runtime_request,
    context=runtime_context,
)
```

`SessionService` should not do this:

```python
llm_result = await llm_gateway.complete(...)
tool_result = await tool_gateway.execute(...)
memory_result = await memory_gateway.search(...)
```

Strategies and agents should do this:

```python
llm_result = await context.llm.complete(request=llm_request, context=context.request)
tool_result = await context.tools.execute(request=tool_request, context=context.request)
memory_result = await context.memory.search(request=memory_request, context=context.request)
```

Strategies and agents should not do this:

```python
openai_client.chat.completions.create(...)
requests.post("http://localhost:9001/mcp", json={...})
memory_store.service.MemoryService(...)
sqlite3.connect("workflow_state.db")
```

---

## 7. Recommended Package Layout

Recommended implementation layout:

```text
backend/
  app/
    orchestration/
      __init__.py
      runtime.py
      context.py
      models.py
      events.py
      errors.py
      registry.py
      strategy.py
      strategy_registry.py
      usecase_router.py
      result_builder.py
      state_delta.py
      cancellation.py
      limits.py
      capabilities.py
      health.py

      strategies/
        __init__.py
        direct_agent.py
        retrieval_augmented.py
        tool_assisted.py
        router.py
        echo.py

    agents/
      base.py
      registry.py
      models.py

    session/
      service.py
      models.py

    llm/
      gateway.py
      models.py

    memory/
      gateway.py
      models.py

    tools/
      gateway.py
      models.py

    policy/
      service.py
      models.py

    observability/
      events.py
      trace_context.py
      metrics.py
      redaction.py

    persistence/
      workflow_state.py
      trace_store.py

    config/
      schemas.py
      settings.py
      loader.py

    testing/
      fakes/
        fake_orchestration_runtime.py
        fake_strategy.py
        fake_agent.py
        fake_llm_gateway.py
        fake_memory_gateway.py
        fake_tool_gateway.py
        fake_policy_service.py
```

### 7.1 Module Responsibilities

| Module | Responsibility |
|---|---|
| `runtime.py` | Public `OrchestrationRuntime` implementation and session-facing entry point. |
| `context.py` | `OrchestrationContext` and dependency bundle passed to strategies/agents. |
| `models.py` | Runtime request/result, step summaries, strategy metadata, and turn metadata. |
| `events.py` | Runtime stream events and safe event mapping helpers. |
| `errors.py` | Normalized orchestration errors. |
| `strategy.py` | `OrchestrationStrategy` protocol/base class. |
| `strategy_registry.py` | Strategy registration, lookup, fallback, and policy filtering. |
| `usecase_router.py` | Resolve use case to strategy and agent candidates. |
| `result_builder.py` | Builds `OrchestrationResult` from strategy outputs and summaries. |
| `state_delta.py` | Produces safe workflow-state patches for `SessionService` to persist. |
| `cancellation.py` | Runtime cancellation helpers. |
| `limits.py` | Max steps, tool calls, memory searches, context size, and duration guards. |
| `capabilities.py` | Safe orchestration capability summaries. |
| `health.py` | Runtime and strategy readiness checks. |
| `strategies/*` | Built-in V1 strategy implementations. |

---

## 8. Dependency Direction Rules

Allowed:

```text
app/session/*       -> app/orchestration/runtime.py
app/orchestration/* -> app/llm/gateway.py
app/orchestration/* -> app/memory/gateway.py
app/orchestration/* -> app/tools/gateway.py
app/orchestration/* -> app/agents/base.py through interfaces
app/orchestration/* -> app/policy/service.py through interface
app/orchestration/* -> app/observability/events.py through facade
app/orchestration/* -> app/config/schemas.py
app/orchestration/* -> app/contracts/*
```

Avoid:

```text
app/orchestration/* -> app/api/*
app/orchestration/* -> sqlite3
app/orchestration/* -> app/persistence/sqlite/*
app/orchestration/* -> memory_store.service.MemoryService
app/orchestration/* -> ArcadeDB client
app/orchestration/* -> MCP client implementation
app/orchestration/* -> app/tools/mcp/*
app/orchestration/* -> provider SDKs
app/orchestration/* -> frontend DTOs
app/orchestration/* -> concrete FastAPI/Flask response types
```

### 8.1 Gateway Dependency Rule

The runtime can depend on gateway interfaces:

```text
LLMGateway
MemoryGateway
ToolGateway
PolicyService
AgentRegistry
ObservabilityRecorder
```

It must not depend on concrete adapters:

```text
OpenAI client
Google client
LocalAI HTTP client
memory_store service
ArcadeDB connection
MCPClientAdapter
SqliteWorkflowStateStore
SqliteTraceStore
```

### 8.2 Session Boundary Rule

Correct path:

```text
API -> SessionService -> OrchestrationRuntime -> Strategy -> Gateways
```

Avoid:

```text
API -> OrchestrationRuntime
API -> Strategy
SessionService -> Strategy directly
SessionService -> LLMGateway directly for normal chat
SessionService -> ToolGateway directly for normal chat
```

---

## 9. Orchestration Configuration Integration

Orchestration settings should be configured in YAML and resolved by the configuration loader before composition.

Recommended YAML:

```yaml
orchestration:
  enabled: true

  defaults:
    strategy: direct_agent
    fallback_strategy: direct_agent
    max_steps: 8
    max_tool_calls: 4
    max_memory_searches: 3
    max_llm_calls: 6
    max_turn_duration_seconds: 120
    max_stream_duration_seconds: 300
    emit_step_events: true
    emit_tool_events: true
    emit_memory_events: true
    expose_chain_of_thought: false
    save_runtime_snapshots: false

  strategies:
    direct_agent:
      enabled: true
      type: direct_agent
      default_agent: assistant_agent
      allowed_usecases: [default]
      llm_profile: default_chat
      memory_enabled: false
      tools_enabled: false

    retrieval_augmented:
      enabled: true
      type: retrieval_augmented
      default_agent: document_qa_agent
      allowed_usecases: [document_qa, architecture_writer]
      llm_profile: research_reasoning
      memory_enabled: true
      tools_enabled: false
      memory:
        default_limit: 8
        include_document_chunks: true
        include_user_memory: true

    tool_assisted:
      enabled: true
      type: tool_assisted
      default_agent: tool_using_agent
      allowed_usecases: [tooling, support]
      llm_profile: tool_reasoning
      memory_enabled: true
      tools_enabled: true
      tools:
        max_calls: 4
        allowed_safety_levels: [read_only, write]

    router:
      enabled: false
      type: router
      allowed_usecases: [default, document_qa, tooling]
      llm_profile: router_small
      candidate_strategies:
        - direct_agent
        - retrieval_augmented
        - tool_assisted

  usecases:
    default:
      strategy: direct_agent
      agent: assistant_agent
      llm_profile: default_chat

    document_qa:
      strategy: retrieval_augmented
      agent: document_qa_agent
      llm_profile: research_reasoning

    architecture_writer:
      strategy: retrieval_augmented
      agent: architecture_writer_agent
      llm_profile: research_reasoning

    support:
      strategy: tool_assisted
      agent: support_agent
      llm_profile: tool_reasoning
```

### 9.1 Configuration Rules

Configuration validation should fail fast when:

- Orchestration is enabled but no default strategy is configured.
- Default strategy is missing or disabled.
- Fallback strategy is missing or disabled.
- A use case points to a missing or disabled strategy.
- A strategy points to a missing agent when strict agent validation is enabled.
- A strategy points to a missing LLM profile.
- A strategy enables tools while `ToolGateway` is disabled and no fake tool gateway is configured.
- A strategy enables memory while `MemoryGateway` is disabled and no fake memory gateway is configured.
- Max step/tool/LLM/memory limits are invalid.
- `expose_chain_of_thought` is true outside a local debugging profile.
- A strategy declares destructive/external-side-effect tool use without policy support.
- Unknown strategy type is configured.

### 9.2 Safe Config Exposure

Capabilities may expose safe strategy/use-case metadata:

```json
{
  "orchestration": {
    "enabled": true,
    "default_strategy": "direct_agent",
    "usecases": ["default", "document_qa"]
  }
}
```

Capabilities must not expose:

```text
hidden prompts
developer instructions
raw routing rules if sensitive
provider credentials
MCP endpoints
database paths
internal policy expressions
```

---

## 10. Typed Orchestration Settings

Recommended dataclasses:

```python
from dataclasses import dataclass, field
from typing import Any, Literal


StrategyType = Literal[
    "direct_agent",
    "retrieval_augmented",
    "tool_assisted",
    "router",
    "echo",
]


@dataclass(frozen=True, slots=True)
class OrchestrationDefaultsSettings:
    strategy: str
    fallback_strategy: str
    max_steps: int
    max_tool_calls: int
    max_memory_searches: int
    max_llm_calls: int
    max_turn_duration_seconds: int
    max_stream_duration_seconds: int
    emit_step_events: bool = True
    emit_tool_events: bool = True
    emit_memory_events: bool = True
    expose_chain_of_thought: bool = False
    save_runtime_snapshots: bool = False


@dataclass(frozen=True, slots=True)
class StrategySettings:
    name: str
    enabled: bool
    type: StrategyType
    default_agent: str | None = None
    allowed_usecases: tuple[str, ...] = ()
    llm_profile: str | None = None
    memory_enabled: bool = False
    tools_enabled: bool = False
    max_steps: int | None = None
    max_tool_calls: int | None = None
    max_memory_searches: int | None = None
    max_llm_calls: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class UseCaseSettings:
    name: str
    strategy: str
    agent: str | None = None
    llm_profile: str | None = None
    display_name: str | None = None
    description: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class OrchestrationSettings:
    enabled: bool
    defaults: OrchestrationDefaultsSettings
    strategies: dict[str, StrategySettings]
    usecases: dict[str, UseCaseSettings]
```

### 10.1 Settings Validation

Validation should verify:

```text
default strategy exists
fallback strategy exists
all usecase strategies exist
all configured limits are positive
strategy names are unique
usecase names are unique
strategy type is known
disabled strategies are not selected by active usecases
agent names are valid when strict registry validation is enabled
LLM profile names are valid when strict LLM validation is enabled
local-only debug settings are not enabled in production profile
```

---

## 11. Public Orchestration Runtime Interface

Recommended interface:

```python
from collections.abc import AsyncIterator
from typing import Protocol


class OrchestrationRuntime(Protocol):
    async def run_turn(
        self,
        *,
        request: "OrchestrationRequest",
        context: "OrchestrationRuntimeContext",
    ) -> "OrchestrationResult":
        ...

    async def stream_turn(
        self,
        *,
        request: "OrchestrationRequest",
        context: "OrchestrationRuntimeContext",
    ) -> AsyncIterator["OrchestrationStreamEvent"]:
        ...

    async def health(self) -> "OrchestrationHealthResult":
        ...

    async def capabilities(self) -> "OrchestrationCapabilitiesResult":
        ...
```

### 11.1 Method Ownership

| Method | Purpose |
|---|---|
| `run_turn` | Execute one non-streaming user turn and return a normalized result. |
| `stream_turn` | Execute one streaming user turn and yield normalized orchestration events. |
| `health` | Return safe runtime/strategy readiness. |
| `capabilities` | Return safe use-case/strategy features for health/capability aggregation. |

### 11.2 Runtime Call Flow

```text
1. Receive OrchestrationRequest and OrchestrationRuntimeContext from SessionService.
2. Validate request and runtime limits.
3. Resolve use case.
4. Resolve strategy.
5. Build OrchestrationContext.
6. Emit `orchestration_started`.
7. Run strategy.
8. Strategy may call agent, LLM, memory, and tools through context gateways.
9. Collect safe step summaries.
10. Build OrchestrationResult or stream events.
11. Build safe WorkflowStateDelta for SessionService.
12. Emit `orchestration_completed` or `orchestration_failed`.
13. Return normalized result or normalized error.
```

---

## 12. Orchestration Request and Result Models

Recommended request model:

```python
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class OrchestrationRequest:
    session_id: str
    trace_id: str
    user_id: str
    message: str
    usecase: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    workflow_state: "WorkflowStateSnapshot | None" = None
```

Recommended runtime context:

```python
@dataclass(frozen=True, slots=True)
class OrchestrationRuntimeContext:
    request_id: str
    trace_id: str
    session_id: str
    user_id: str
    project_id: str | None = None
    tenant_id: str | None = None
    timezone: str | None = None
    client: str | None = None
    cancellation_token: "CancellationToken | None" = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

Recommended result model:

```python
@dataclass(frozen=True, slots=True)
class OrchestrationResult:
    answer: str
    session_id: str
    trace_id: str
    usecase: str
    strategy_name: str
    agent_name: str | None = None
    llm_profile: str | None = None
    steps: list["OrchestrationStepSummary"] = field(default_factory=list)
    tool_calls: list["ToolCallSummary"] = field(default_factory=list)
    memory_searches: list["MemorySearchSummary"] = field(default_factory=list)
    memory_updates: list["MemoryUpdateSummary"] = field(default_factory=list)
    state_delta: "WorkflowStateDelta | None" = None
    finish_reason: str = "stop"
    duration_ms: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

### 12.1 Step Summary Model

```python
@dataclass(frozen=True, slots=True)
class OrchestrationStepSummary:
    step_id: str
    step_type: str
    status: str
    started_at: str | None = None
    completed_at: str | None = None
    duration_ms: int | None = None
    safe_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

### 12.2 Result Safety Rule

`OrchestrationResult` is returned to `SessionService`, and parts of it may become API-visible. It must not include:

```text
raw provider request
raw provider response
raw tool payload
raw MCP envelope
raw memory record body unless policy allows
raw workflow state document
credentials
authorization headers
hidden chain-of-thought
debug stack traces
```

---

## 13. Orchestration Stream Event Contract

Recommended stream events:

```python
from dataclasses import dataclass, field
from typing import Any, Literal


OrchestrationEventType = Literal[
    "orchestration.started",
    "strategy.selected",
    "agent.started",
    "agent.completed",
    "memory.search.started",
    "memory.search.completed",
    "tool.started",
    "tool.completed",
    "llm.started",
    "llm.delta",
    "llm.completed",
    "response.delta",
    "response.metadata",
    "response.completed",
    "orchestration.completed",
    "orchestration.error",
    "orchestration.cancelled",
]


@dataclass(frozen=True, slots=True)
class OrchestrationStreamEvent:
    type: OrchestrationEventType
    trace_id: str
    session_id: str
    text: str | None = None
    result: OrchestrationResult | None = None
    error: "OrchestrationErrorDetail | None" = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

### 13.1 Session/API Mapping

`SessionService` maps orchestration stream events to session stream events.

API then maps session stream events to SSE.

```text
OrchestrationStreamEvent
  -> SessionStreamEvent
      -> API SSE event
```

This avoids leaking runtime internals directly to the HTTP/SSE boundary.

### 13.2 Stream Event Safety Rule

Runtime stream events may become client-visible. Every stream event must be safe and bounded.

Do not emit:

```text
raw LLM provider chunk objects
raw MCP protocol objects
raw tool results
raw memory records
raw workflow state
hidden scratchpads
credentials
stack traces
```

### 13.3 Minimal V1 Event Set

A minimal V1 implementation can start with:

```text
orchestration.started
strategy.selected
response.delta
response.completed
orchestration.completed
orchestration.error
orchestration.cancelled
```

More detailed memory/tool/agent events can be added after the core runtime is stable.

---

## 14. Orchestration Context

`OrchestrationContext` is the dependency bundle passed to strategies and agents.

Recommended shape:

```python
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class OrchestrationContext:
    request: OrchestrationRequest
    runtime: OrchestrationRuntimeContext
    settings: OrchestrationSettings
    strategy_settings: StrategySettings
    llm: "LLMGateway"
    memory: "MemoryGateway"
    tools: "ToolGateway"
    agents: "AgentRegistry"
    policy: "PolicyService"
    observability: "ObservabilityRecorder"
    limits: "OrchestrationLimits"
    state: "WorkflowStateSnapshot | None" = None
    metadata: dict[str, Any] | None = None
```

### 14.1 Context Rules

The context may include gateway interfaces and safe runtime metadata.

It must not include:

```text
API request object
FastAPI Request
Flask request
raw HTTP headers
raw auth tokens
SQLite connection
ArcadeDB connection
MCP client adapter
provider SDK client
mutable global config
```

### 14.2 Context Construction

The runtime constructs the context once per turn after strategy resolution.

```text
SessionService passes request + loaded workflow state.
Runtime resolves usecase/strategy.
Runtime builds context with gateways and safe metadata.
Strategy receives context and runs.
```

---

## 15. Orchestration Strategy Contract

Strategies are workflow-shaping components. They decide how to answer a turn.

Recommended interface:

```python
from collections.abc import AsyncIterator
from typing import Protocol


class OrchestrationStrategy(Protocol):
    @property
    def name(self) -> str:
        ...

    async def run(
        self,
        *,
        context: OrchestrationContext,
    ) -> OrchestrationResult:
        ...

    async def stream(
        self,
        *,
        context: OrchestrationContext,
    ) -> AsyncIterator[OrchestrationStreamEvent]:
        ...
```

### 15.1 Strategy Responsibilities

A strategy may:

- Select an agent.
- Prepare safe prompt/context input for an agent.
- Search memory through `MemoryGateway`.
- Ask an LLM through `LLMGateway`.
- Parse an LLM tool intent into a provider-neutral `ToolIntent`.
- Execute allowed tools through `ToolGateway`.
- Summarize gateway results for an answer.
- Produce safe step summaries.
- Produce a workflow-state delta.

A strategy must not:

- Call provider SDKs directly.
- Call MCP server directly.
- Import `memory_store` or ArcadeDB clients.
- Persist workflow state directly.
- Persist traces directly except through observability facade.
- Return raw tool/memory/LLM payloads.
- Expose hidden chain-of-thought.

### 15.2 Built-In V1 Strategies

Recommended initial strategies:

| Strategy | Purpose | Dependencies |
|---|---|---|
| `echo` | Local development walking skeleton. | None or fake LLM. |
| `direct_agent` | Single agent answers with LLM, no memory/tools by default. | Agent registry, LLM gateway. |
| `retrieval_augmented` | Search memory/docs then answer with agent/LLM. | Memory gateway, LLM gateway. |
| `tool_assisted` | Allow bounded tool use for approved tools. | Tool gateway, LLM gateway, optional memory gateway. |
| `router` | Route to another strategy based on use case or LLM classification. | Policy, config, optional LLM gateway. |

### 15.3 Strategy Fallback Rule

Fallback should be conservative.

Recommended order:

```text
configured usecase strategy
configured default strategy
configured fallback strategy
safe error response
```

If the configured strategy fails due to policy denial or unsafe tool request, do not automatically fall back to a strategy that bypasses the policy decision.

---

## 16. Strategy Registry

The strategy registry provides stable strategy lookup.

Recommended interface:

```python
class StrategyRegistry:
    def register(self, strategy: OrchestrationStrategy, settings: StrategySettings) -> None:
        ...

    def resolve(
        self,
        *,
        strategy_name: str,
        usecase: str | None,
        context: OrchestrationRuntimeContext,
    ) -> "ResolvedStrategy":
        ...

    def list(
        self,
        *,
        enabled_only: bool = True,
    ) -> list["StrategyDescriptor"]:
        ...
```

Recommended resolved model:

```python
@dataclass(frozen=True, slots=True)
class ResolvedStrategy:
    strategy: OrchestrationStrategy
    settings: StrategySettings
    source: str
```

### 16.1 Registry Rules

The registry should:

- Only return enabled strategies.
- Enforce configured use-case allowlists.
- Support deterministic fallback.
- Produce safe descriptors for capabilities.
- Avoid instantiating provider SDKs inside strategy lookup.
- Avoid hidden runtime mutation during lookup.

### 16.2 Strategy Descriptor

```python
@dataclass(frozen=True, slots=True)
class StrategyDescriptor:
    name: str
    type: str
    enabled: bool
    allowed_usecases: tuple[str, ...]
    supports_streaming: bool
    memory_enabled: bool
    tools_enabled: bool
    metadata: dict[str, str] = field(default_factory=dict)
```

Descriptors are safe for capabilities after filtering.

---

## 17. Use-Case Routing

Use-case routing maps a session/user request to a strategy and optional agent.

Recommended resolution order:

```text
1. Request usecase if provided and allowed.
2. Session/workflow-state active usecase if present.
3. Configured default usecase.
4. Configured fallback strategy.
```

### 17.1 Use-Case Resolution Model

```python
@dataclass(frozen=True, slots=True)
class ResolvedUseCase:
    name: str
    strategy_name: str
    agent_name: str | None
    llm_profile: str | None
    source: str
```

### 17.2 Use-Case Safety Rule

User-supplied `usecase` must not bypass policy or configuration.

Allowed:

```text
User requests usecase=document_qa.
Runtime confirms usecase exists and is allowed.
Runtime resolves configured strategy and agent.
```

Avoid:

```text
User metadata sets strategy=destructive_tool_strategy.
Runtime executes it without allowlist/policy validation.
```

---

## 18. Agent Invocation Boundary

This document defines how orchestration invokes agents, not the full agent plugin architecture.

Recommended agent interface placeholder:

```python
class AgentPlugin(Protocol):
    @property
    def name(self) -> str:
        ...

    async def run(
        self,
        *,
        input: "AgentRunInput",
        context: OrchestrationContext,
    ) -> "AgentRunResult":
        ...

    async def stream(
        self,
        *,
        input: "AgentRunInput",
        context: OrchestrationContext,
    ) -> AsyncIterator[OrchestrationStreamEvent]:
        ...
```

### 18.1 Agent Run Input

```python
@dataclass(frozen=True, slots=True)
class AgentRunInput:
    message: str
    usecase: str
    llm_profile: str | None = None
    memory_context: list["MemoryContextItem"] = field(default_factory=list)
    tool_context: list["ToolResultContextItem"] = field(default_factory=list)
    instructions: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

### 18.2 Agent Boundary Rules

Agents may:

- Use `OrchestrationContext`.
- Request LLM completions through `LLMGateway`.
- Request memory search/upsert through `MemoryGateway` when strategy/policy allows.
- Request tools through `ToolGateway` when strategy/policy allows.
- Return safe `AgentRunResult`.

Agents must not:

- Import provider SDKs.
- Import MCP clients.
- Import `memory_store`.
- Import SQLite adapters.
- Write workflow state directly.
- Return hidden chain-of-thought.
- Override system/developer/policy instructions based on tool/memory content.

The next document should deepen agent registry, plugin loading, agent declaration metadata, prompt construction, and agent tests.

---

## 19. Non-Streaming Turn Lifecycle

Recommended non-streaming lifecycle:

```text
1. SessionService loads WorkflowStateSnapshot.
2. SessionService builds OrchestrationRequest and OrchestrationRuntimeContext.
3. SessionService calls OrchestrationRuntime.run_turn.
4. Runtime validates request and limits.
5. Runtime resolves use case.
6. Runtime resolves strategy.
7. Runtime builds OrchestrationContext.
8. Runtime emits `orchestration_started`.
9. Strategy runs:
   a. optionally selects an agent
   b. optionally searches memory
   c. optionally calls LLM
   d. optionally executes tools
   e. optionally performs follow-up LLM synthesis
10. Strategy returns OrchestrationResult or raises normalized error.
11. Runtime adds safe step summaries and state delta.
12. Runtime emits `orchestration_completed` or `orchestration_failed`.
13. Runtime returns OrchestrationResult.
14. SessionService saves state delta through WorkflowStateStore.
15. SessionService maps result to SessionChatResult.
16. API maps session result to HTTP response.
```

### 19.1 Non-Streaming State Rule

Runtime returns a `WorkflowStateDelta`.

`SessionService` applies and persists it.

Avoid:

```text
Runtime writes WorkflowStateStore.save(...)
Strategy writes WorkflowStateStore.save(...)
Agent writes WorkflowStateStore.save(...)
```

### 19.2 Non-Streaming Trace Rule

Runtime may emit safe trace events through observability facade.

Avoid:

```text
Runtime calls SqliteTraceStore SQL directly.
Strategy constructs raw trace rows directly.
```

---

## 20. Streaming Turn Lifecycle

Recommended streaming lifecycle:

```text
1. SessionService loads WorkflowStateSnapshot.
2. SessionService calls OrchestrationRuntime.stream_turn.
3. Runtime emits `orchestration.started`.
4. Runtime resolves usecase and strategy.
5. Runtime emits `strategy.selected`.
6. Strategy streams safe events.
7. LLM token/delta events are normalized into `response.delta` or strategy-specific events.
8. Memory/tool events are summarized only if enabled and safe.
9. Runtime emits `orchestration.completed`.
10. Runtime yields final event containing safe result summary/state delta.
11. SessionService saves final state once.
12. API maps session stream events to SSE.
```

### 20.1 Streaming Save Rule

For streaming chat:

```text
Load workflow state once near start.
Save final workflow state once at completion.
Save failure/cancellation checkpoint only if safe and useful.
Do not save workflow state on every token.
```

### 20.2 Streaming Cancellation Rule

When cancellation is requested:

```text
1. API detects disconnect or upstream cancellation.
2. SessionService propagates cancellation to runtime.
3. Runtime cancels strategy task.
4. Strategy cancels gateway calls where possible.
5. Runtime emits/records `orchestration.cancelled`.
6. SessionService optionally persists safe cancellation summary.
```

---

## 21. Workflow State Integration

Workflow state remains a session/service concern, but orchestration can read a snapshot and return a delta.

Recommended snapshot model:

```python
@dataclass(frozen=True, slots=True)
class WorkflowStateSnapshot:
    session_id: str
    version: int
    messages: list["ConversationMessage"] = field(default_factory=list)
    active_usecase: str | None = None
    active_agent: str | None = None
    step_summaries: list[OrchestrationStepSummary] = field(default_factory=list)
    pending_approvals: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
```

Recommended delta model:

```python
@dataclass(frozen=True, slots=True)
class WorkflowStateDelta:
    append_messages: list["ConversationMessage"] = field(default_factory=list)
    set_active_usecase: str | None = None
    set_active_agent: str | None = None
    append_step_summaries: list[OrchestrationStepSummary] = field(default_factory=list)
    append_pending_approvals: list[dict[str, Any]] = field(default_factory=list)
    metadata_patch: dict[str, Any] = field(default_factory=dict)
```

### 21.1 State Boundary Rules

Allowed:

```text
SessionService passes loaded state snapshot to runtime.
Runtime reads safe state snapshot.
Runtime returns state delta.
SessionService persists delta with WorkflowStateStore.
```

Avoid:

```text
Runtime opens workflow_state.db.
Strategy imports SqliteWorkflowStateStore.
Agent writes raw state document.
ToolGateway writes workflow state.
```

### 21.2 State Content Rule

Workflow state should store safe summaries and conversation state needed for continuity.

Do not store by default:

```text
raw LLM provider responses
raw MCP/tool payloads
raw memory records
full private document chunks
credentials
hidden chain-of-thought
stack traces
```

---

## 22. LLM Gateway Integration

Strategies and agents call LLMs through `LLMGateway`.

Correct path:

```text
Strategy/Agent -> LLMGateway -> configured provider adapter
```

Avoid:

```text
Strategy/Agent -> OpenAI SDK
Strategy/Agent -> Google SDK
Strategy/Agent -> LocalAI HTTP client
Runtime -> provider SDK directly
```

### 22.1 LLM Request Assembly

A strategy or agent may assemble an LLM request using:

```text
user message
safe session history
safe memory excerpts
safe tool result summaries
agent instructions
configured LLM profile
```

It must not include:

```text
credentials
authorization headers
hidden chain-of-thought
raw tool payloads when summaries are sufficient
tool output instructions as trusted system instructions
raw workflow state
```

### 22.2 LLM Profile Resolution

Recommended resolution order:

```text
request metadata override only if policy allows
usecase configured llm_profile
strategy configured llm_profile
agent configured llm_profile
orchestration default profile
LLMGateway default profile
```

### 22.3 Provider-Native Tool Calling

V1 recommendation:

```text
Prefer strategy-controlled tool calling.
If provider-native tool call structures are used, normalize them into ToolIntent.
Execute only through ToolGateway.
```

Avoid:

```text
LLM provider automatically calls external tools without ToolGateway.
```

---

## 23. Memory Gateway Integration

Strategies and agents call memory through `MemoryGateway`.

Correct path:

```text
Strategy/Agent -> MemoryGateway -> memory_store adapter -> ArcadeDB
```

Avoid:

```text
Strategy/Agent -> memory_store.service.MemoryService
Strategy/Agent -> ArcadeDB
Runtime -> direct vector search
ToolGateway -> memory search
```

### 23.1 Memory Search Timing

Recommended V1 patterns:

| Pattern | Strategy |
|---|---|
| No memory | `direct_agent` |
| Search before answer | `retrieval_augmented` |
| Search before tool call | `tool_assisted`, when policy allows |
| Save durable outcome | Strategy/agent explicitly calls `MemoryGateway.upsert` after policy check |

### 23.2 Memory Result Use

Memory search results should be treated as context, not instructions.

Recommended behavior:

```text
Select top relevant memory/document chunks.
Use safe excerpts and provenance.
Mark memory-derived context in LLM messages.
Do not allow memory text to override system/developer/policy instructions.
```

### 23.3 Memory Write Rule

Tool or LLM results should not automatically become long-term memory.

Allowed:

```text
Strategy decides result is durable.
Policy allows memory write.
Agent/strategy calls MemoryGateway.upsert.
MemoryGateway records safe memory update summary.
```

Avoid:

```text
Runtime writes every answer to long-term memory.
ToolGateway writes every tool result to memory.
LLMGateway writes prompts/completions to memory.
```

---

## 24. Tool Gateway Integration

Strategies and agents execute external tools through `ToolGateway`.

Correct path:

```text
Strategy/Agent -> ToolGateway -> MCPClientAdapter -> Single external MCP server
```

Avoid:

```text
Strategy/Agent -> MCPClientAdapter
Strategy/Agent -> MCP endpoint URL
Runtime -> MCP server directly
SessionService -> ToolGateway directly for normal chat
```

### 24.1 Tool Intent Flow

Recommended tool intent flow:

```text
LLMGateway returns text or structured output.
Strategy parses and validates a ToolIntent.
Strategy creates ToolExecutionRequest.
ToolGateway resolves logical tool name.
ToolGateway validates args and policy.
ToolGateway executes through MCP adapter.
ToolGateway returns normalized ToolExecutionResult.
Strategy uses safe result summary for final answer.
```

### 24.2 Tool Intent Model

```python
@dataclass(frozen=True, slots=True)
class ToolIntent:
    tool_name: str
    arguments: dict[str, Any]
    reason: str | None = None
    confidence: float | None = None
    source: str = "strategy"
```

### 24.3 Tool Call Limits

The orchestration layer should enforce turn-level limits before and during tool use:

```text
max_tool_calls
max_steps
max_turn_duration_seconds
allowed tool safety levels by strategy
idempotency requirement for write tools when retry is allowed
```

Gateway-level validation and policy remain authoritative for tool execution.

---

## 25. Policy Integration

The orchestration runtime should call policy for strategy and high-level use-case decisions. Gateways should still enforce their own policy checks for LLM, memory, and tool operations.

Recommended checks:

```python
allowed = await policy.can_run_strategy(
    user_id=context.user_id,
    session_id=context.session_id,
    usecase=resolved_usecase.name,
    strategy_name=resolved_strategy.settings.name,
    agent_name=resolved_usecase.agent_name,
)
```

Additional gateway-level checks:

```text
LLMGateway checks profile/provider permissions.
MemoryGateway checks memory scope/access.
ToolGateway checks tool allowlist, scope, and argument policy.
```

### 25.1 Policy Defaults

Recommended V1 defaults:

```text
Deny disabled strategies.
Deny unknown usecases.
Deny unknown agents.
Deny unknown LLM profiles.
Deny destructive/external-side-effect tools unless explicitly enabled.
Deny hidden chain-of-thought exposure.
Deny direct raw provider/tool/memory payload exposure.
Allow default local usecase in local profile.
```

### 25.2 Policy Safety Rule

Strategy selection must not become an escalation path.

Avoid:

```text
User sets metadata.strategy=admin_tool_strategy.
Runtime executes it.
```

Allowed:

```text
User requests usecase.
Runtime resolves configured strategy.
Policy confirms strategy/usecase/agent combination.
```

---

## 26. Runtime Limits

The runtime should enforce turn-level limits to prevent runaway loops.

Recommended limits:

```python
@dataclass(frozen=True, slots=True)
class OrchestrationLimits:
    max_steps: int
    max_tool_calls: int
    max_memory_searches: int
    max_llm_calls: int
    max_turn_duration_seconds: int
    max_stream_duration_seconds: int
    max_context_chars: int | None = None
```

### 26.1 Limit Enforcement

Runtime should track:

```text
step count
LLM call count
tool call count
memory search count
elapsed turn duration
stream duration
context size if measurable
```

If a limit is exceeded:

```text
stop strategy execution
return or stream a safe error
record `orchestration_limit_exceeded`
produce safe state delta if useful
```

### 26.2 Loop Guard

Tool-assisted strategies should include loop guards:

```text
No more than max_tool_calls.
No repeated identical tool call unless explicitly allowed.
No unbounded LLM-tool-LLM loops.
No retry loops beyond gateway policy.
No escalation to disabled/destructive tools.
```

---

## 27. Planning and Reasoning Boundary

Strategies may implement planning, but hidden chain-of-thought must not be exposed.

Recommended V1 approach:

```text
Use concise, structured plan objects when needed.
Keep private reasoning internal to strategy/agent implementation.
Return safe step summaries.
Use final answer and safe metadata for API/session.
```

### 27.1 Safe Plan Model

```python
@dataclass(frozen=True, slots=True)
class RuntimePlan:
    objective: str
    steps: list[str]
    required_tools: list[str] = field(default_factory=list)
    requires_memory: bool = False
    requires_approval: bool = False
```

### 27.2 Plan Safety Rule

Safe to expose:

```text
"Searching project memory"
"Calling documents.search"
"Drafting final answer"
```

Do not expose:

```text
hidden chain-of-thought
private scratchpad
raw prompts
raw model deliberation
policy internals
credentials
```

---

## 28. Context Construction and Prompt Input

The runtime and strategies must construct bounded context.

Recommended sources:

```text
current user message
safe recent conversation history
safe workflow state summaries
safe memory snippets
safe tool result summaries
agent instructions
use-case constraints
```

### 28.1 Context Ordering

Recommended ordering for RAG-style strategies:

```text
system/developer/agent instructions
policy-safe task framing
recent conversation summary
selected memory/document context
selected tool result context
current user message
```

### 28.2 Prompt Injection Safety

Memory and tool outputs are untrusted data.

Recommended rule:

```text
Memory/tool result text must be quoted or labeled as external context and must not override system, developer, policy, or agent instructions.
```

A future prompt/security document may define exact formatting templates.

---

## 29. Error Model

Recommended orchestration errors:

```python
class OrchestrationError(Exception):
    code: str
    retryable: bool


class OrchestrationDisabledError(OrchestrationError): ...
class UnknownUseCaseError(OrchestrationError): ...
class StrategyNotFoundError(OrchestrationError): ...
class StrategyDisabledError(OrchestrationError): ...
class StrategyPolicyDeniedError(OrchestrationError): ...
class AgentNotFoundError(OrchestrationError): ...
class AgentExecutionError(OrchestrationError): ...
class OrchestrationLimitExceededError(OrchestrationError): ...
class OrchestrationTimeoutError(OrchestrationError): ...
class OrchestrationCancelledError(OrchestrationError): ...
class OrchestrationDependencyUnavailableError(OrchestrationError): ...
class OrchestrationMalformedOutputError(OrchestrationError): ...
```

### 29.1 Error Mapping

| Orchestration Error | Retryable | Session/API Mapping Later |
|---|---:|---|
| `OrchestrationDisabledError` | false | `503 orchestration_disabled` |
| `UnknownUseCaseError` | false | `400 unknown_usecase` |
| `StrategyNotFoundError` | false | `500 strategy_not_configured` or `400 unknown_strategy` |
| `StrategyDisabledError` | false | `403 strategy_disabled` |
| `StrategyPolicyDeniedError` | false | `403 policy_denied` |
| `AgentNotFoundError` | false | `500 agent_not_configured` |
| `AgentExecutionError` | true/false by cause | `500 agent_execution_failed` |
| `OrchestrationLimitExceededError` | false | `429 orchestration_limit_exceeded` or `400` by policy |
| `OrchestrationTimeoutError` | true | `504 orchestration_timeout` |
| `OrchestrationCancelledError` | false | cancellation path |
| `OrchestrationDependencyUnavailableError` | true | `503 dependency_unavailable` |
| `OrchestrationMalformedOutputError` | true/false by cause | `502 malformed_orchestration_output` |

### 29.2 Error Safety Rule

Errors must not expose:

```text
raw provider response
raw tool response
raw memory payload
raw workflow state
credentials
authorization headers
stack traces
hidden scratchpads
```

---

## 30. Observability and Trace Integration

The runtime should emit safe trace events through the observability facade.

Recommended trace events:

| Event | Emitted By | Notes |
|---|---|---|
| `orchestration_started` | Runtime | trace/session/usecase only. |
| `usecase_resolved` | Runtime/router | resolved usecase and source. |
| `strategy_selected` | Runtime/registry | safe strategy metadata. |
| `strategy_started` | Runtime/strategy | no raw prompt/context. |
| `strategy_completed` | Runtime/strategy | duration/status/step count. |
| `agent_started` | Strategy | safe agent name/usecase. |
| `agent_completed` | Strategy | duration/status. |
| `memory_context_selected` | Strategy | count/scope only. |
| `tool_intent_created` | Strategy | logical tool name only, no raw args by default. |
| `orchestration_limit_exceeded` | Runtime | limit name and safe count. |
| `orchestration_completed` | Runtime | duration/finish reason. |
| `orchestration_failed` | Runtime | safe error code/type. |
| `orchestration_cancelled` | Runtime | cancellation summary. |

Gateway-specific trace events remain owned by each gateway.

### 30.1 Safe Trace Payload Example

```json
{
  "event_name": "strategy_completed",
  "trace_id": "trace_...",
  "payload": {
    "strategy_name": "retrieval_augmented",
    "usecase": "document_qa",
    "agent_name": "document_qa_agent",
    "duration_ms": 1430,
    "llm_calls": 1,
    "memory_searches": 1,
    "tool_calls": 0,
    "status": "completed"
  }
}
```

### 30.2 Unsafe Trace Payload Example

```json
{
  "prompt": "full prompt...",
  "raw_llm_response": {...},
  "raw_tool_result": {...},
  "raw_memory_record": {...},
  "authorization": "Bearer ..."
}
```

### 30.3 Metrics

Recommended metrics:

```text
backend.orchestration.turns.total
backend.orchestration.turns.duration_ms
backend.orchestration.turns.failed_total
backend.orchestration.turns.cancelled_total
backend.orchestration.streams.total
backend.orchestration.streams.duration_ms
backend.orchestration.strategy.selected_total
backend.orchestration.steps.total
backend.orchestration.limit_exceeded_total
```

Allowed metric tags:

```text
usecase
strategy_name
agent_name
status
error_type
streaming
```

Avoid metric tags:

```text
session_id
trace_id
raw_user_id
message text
prompt text
tool arguments
memory text
credentials
```

---

## 31. Health Integration

The runtime should expose safe health.

Recommended health result:

```python
@dataclass(frozen=True, slots=True)
class OrchestrationHealthResult:
    status: str
    enabled: bool
    strategies_configured: int
    strategies_enabled: int
    default_strategy: str | None
    fallback_strategy: str | None
    agent_registry_status: str
    llm_gateway_status: str | None = None
    memory_gateway_status: str | None = None
    tool_gateway_status: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

Recommended health response section:

```json
{
  "orchestration": {
    "status": "ok",
    "enabled": true,
    "strategies_configured": 4,
    "strategies_enabled": 3,
    "default_strategy": "direct_agent",
    "fallback_strategy": "direct_agent",
    "agent_registry_status": "ok"
  }
}
```

### 31.1 Health Safety Rule

Health output must not include:

```text
raw prompts
agent private instructions
provider credentials
MCP endpoints
database paths
memory connection details
tool auth details
stack traces
```

---

## 32. Capabilities Integration

The runtime should expose safe orchestration capabilities for the capabilities aggregator.

Recommended capability section:

```json
{
  "orchestration": {
    "enabled": true,
    "streaming_supported": true,
    "available_usecases": [
      {
        "name": "default",
        "display_name": "Default Assistant",
        "strategy": "direct_agent"
      },
      {
        "name": "document_qa",
        "display_name": "Document Q&A",
        "strategy": "retrieval_augmented"
      }
    ],
    "strategies": [
      {
        "name": "direct_agent",
        "supports_streaming": true,
        "memory_enabled": false,
        "tools_enabled": false
      }
    ]
  }
}
```

### 32.1 Capability Safety Rule

Capabilities may expose:

```text
safe usecase names
display names
strategy names if not sensitive
streaming support
memory/tools enabled flags
max message/context limits if frontend-relevant
```

Do not expose:

```text
prompt templates
routing rules if sensitive
provider URLs
MCP endpoints
credentials
private policy details
internal debug settings
```

---

## 33. Composition Root Integration

The composition root builds gateways, registries, strategies, and runtime, then injects runtime into `SessionService`.

Recommended startup sequence:

```text
1. Load settings and YAML configuration.
2. Validate orchestration settings.
3. Build observability/redactor/metrics.
4. Build policy service.
5. Build WorkflowStateStore and TraceStore.
6. Build LLMGateway.
7. Build MemoryGateway.
8. Build ToolGateway.
9. Build AgentRegistry with available agent plugins or fakes.
10. Build built-in strategies.
11. Register strategies with StrategyRegistry.
12. Build OrchestrationRuntime.
13. Build SessionService with runtime and workflow-state store.
14. Build API app with SessionService.
15. Log redacted orchestration startup summary.
```

### 33.1 Composition Example

```python
def build_orchestration_runtime(container, config) -> OrchestrationRuntime:
    strategy_registry = StrategyRegistry()

    strategy_registry.register(
        DirectAgentStrategy(),
        settings=config.orchestration.strategies["direct_agent"],
    )
    strategy_registry.register(
        RetrievalAugmentedStrategy(),
        settings=config.orchestration.strategies["retrieval_augmented"],
    )
    strategy_registry.register(
        ToolAssistedStrategy(),
        settings=config.orchestration.strategies["tool_assisted"],
    )

    return DefaultOrchestrationRuntime(
        settings=config.orchestration,
        strategies=strategy_registry,
        agents=container.agents,
        llm=container.llm_gateway,
        memory=container.memory_gateway,
        tools=container.tool_gateway,
        policy=container.policy,
        observability=container.observability,
    )
```

### 33.2 Redacted Startup Summary

Safe startup log:

```json
{
  "event": "orchestration_configured",
  "enabled": true,
  "strategies_configured": 4,
  "strategies_enabled": 3,
  "default_strategy": "direct_agent",
  "fallback_strategy": "direct_agent"
}
```

Unsafe startup log:

```json
{
  "prompt_template": "...",
  "provider_api_key": "...",
  "mcp_endpoint": "...",
  "database_path": "..."
}
```

---

## 34. Direct Agent Strategy

The direct agent strategy is the simplest useful V1 strategy.

Recommended flow:

```text
1. Resolve configured agent.
2. Build AgentRunInput from user message and safe history.
3. Call agent.
4. Agent calls LLMGateway.
5. Strategy returns agent result.
```

### 34.1 Direct Agent Use Cases

Recommended for:

```text
default chat
simple assistant responses
local walking skeleton
non-tool non-memory workflows
```

### 34.2 Direct Agent Boundaries

The direct strategy should not:

```text
search memory unless explicitly configured
execute tools unless explicitly configured
select arbitrary LLM profiles from user metadata
persist state directly
```

---

## 35. Retrieval-Augmented Strategy

The retrieval-augmented strategy coordinates memory/document search with answer synthesis.

Recommended flow:

```text
1. Resolve agent and LLM profile.
2. Build MemorySearchRequest with trusted scope.
3. Call MemoryGateway.search.
4. Select bounded memory/document context.
5. Build AgentRunInput with memory context.
6. Agent calls LLMGateway for synthesis.
7. Strategy returns answer and memory search summaries.
```

### 35.1 Memory Search Request Example

```python
memory_result = await context.memory.search(
    request=MemorySearchRequest(
        query=context.request.message,
        limit=8,
        scopes=MemoryScopes(
            user_id=context.runtime.user_id,
            project_id=context.runtime.project_id,
            session_id=context.runtime.session_id,
            usecase=context.request.usecase,
        ),
        include_document_chunks=True,
        include_user_memory=True,
        metadata={"strategy_name": "retrieval_augmented"},
    ),
    context=context.request,
)
```

### 35.2 Retrieval Safety Rule

Retrieved memory/document context must be:

```text
bounded
policy-scoped
clearly labeled as external context
provenance-preserving when possible
not treated as instruction hierarchy
```

---

## 36. Tool-Assisted Strategy

The tool-assisted strategy coordinates LLM/tool use through safe tool intents.

Recommended flow:

```text
1. Resolve agent and LLM profile.
2. Optionally search memory.
3. Ask LLM/agent whether a tool is needed.
4. Normalize desired tool use into ToolIntent.
5. Check strategy-level limits and allowed safety levels.
6. Execute through ToolGateway.
7. Optionally synthesize final answer with LLM using safe tool result summary.
8. Return answer, tool summaries, and state delta.
```

### 36.1 Tool-Assisted Loop Guard

Recommended loop guard:

```text
no more than max_tool_calls
no repeated identical calls by default
no destructive/external-side-effect calls without policy and approval support
no retry loops beyond ToolGateway retry policy
tool errors must be summarized safely
```

### 36.2 Tool Result Prompting Rule

When using tool results in LLM prompts:

```text
include selected fields or summaries
label tool output as untrusted external data
do not paste credentials or raw payloads
respect result truncation markers
```

---

## 37. Router Strategy

The router strategy selects another strategy based on configured rules or a bounded LLM classification step.

Recommended V1 behavior:

```text
Prefer config/rule-based routing first.
Use LLM router only when configured.
Router returns a strategy selection, not a final answer, unless configured as a direct router.
Policy validates selected strategy.
Runtime executes selected strategy.
```

### 37.1 Router Input

Router may use:

```text
usecase
message summary
safe session metadata
configured candidate strategies
```

Router must not use:

```text
raw credentials
full workflow state when unnecessary
raw trace payloads
private hidden prompts
```

### 37.2 Router Output

```python
@dataclass(frozen=True, slots=True)
class StrategyRouteDecision:
    strategy_name: str
    agent_name: str | None = None
    llm_profile: str | None = None
    confidence: float | None = None
    reason_summary: str | None = None
```

Do not expose hidden deliberation; expose only safe reason summaries when needed.

---

## 38. Approval Boundary

V1 may detect that an action requires approval without implementing the full approval workflow.

Recommended behavior:

```text
If a tool or strategy step requires approval and no approval service exists, return a safe approval-required result or normalized policy error.
Do not silently execute approval-required actions.
Do not ask ToolGateway to bypass approval.
```

### 38.1 Future Approval Flow

A future approval document may introduce:

```text
Strategy creates approval request.
Runtime returns WorkflowStateDelta with pending approval.
SessionService saves pending approval.
Frontend asks user to approve.
SessionService resumes workflow.
Runtime executes approved tool through ToolGateway after approval token validation.
```

Until then, approval-required actions should not execute autonomously.

---

## 39. Security and Privacy

### 39.1 Credential Handling

Orchestration code must not receive or pass raw credentials.

Credentials must not be:

```text
included in OrchestrationRequest metadata
included in OrchestrationContext
passed to LLM prompts
passed as tool arguments
stored in WorkflowStateDelta
emitted in stream events
recorded in traces
returned in capabilities
```

### 39.2 Untrusted Content

These are untrusted data:

```text
user messages
memory text
document chunks
tool results
MCP downstream responses
LLM-generated tool arguments
```

They must not override:

```text
system instructions
developer instructions
policy decisions
tool allowlists
gateway validation
strategy limits
```

### 39.3 Hidden Reasoning

The runtime may use internal reasoning/planning, but it must not expose hidden chain-of-thought.

Safe output:

```text
step summaries
decision summaries
tool summaries
memory summaries
final answer
```

Unsafe output:

```text
private scratchpad
hidden chain-of-thought
raw deliberation trace
full prompt internals
```

---

## 40. Testing Strategy

### 40.1 Unit Tests

| Test | Purpose |
|---|---|
| Orchestration settings validate | Proves config safety. |
| Disabled default strategy fails fast | Prevents broken startup. |
| Usecase resolves to configured strategy | Proves routing. |
| Unknown usecase returns normalized error | Prevents arbitrary routing. |
| Strategy registry denies disabled strategy | Enforces config boundary. |
| Runtime builds context with gateway interfaces | Proves dependency wiring. |
| Runtime does not persist state directly | Preserves session boundary. |
| Direct strategy calls agent | Proves basic runtime path. |
| Retrieval strategy calls MemoryGateway only | Preserves memory boundary. |
| Tool strategy calls ToolGateway only | Preserves MCP boundary. |
| LLM calls go through LLMGateway | Preserves provider boundary. |
| Strategy limit stops runaway loop | Proves guardrails. |
| Streaming emits safe events | Proves stream contract. |
| Cancellation records safe event | Proves cancellation behavior. |
| Raw prompts/results not traced by default | Proves privacy behavior. |
| Errors map to orchestration errors | Proves stable error model. |

### 40.2 Integration Tests

| Test | Purpose |
|---|---|
| SessionService calls runtime | Proves session-runtime boundary. |
| Runtime executes direct strategy with fake agent/LLM | Proves non-streaming vertical slice. |
| Runtime streams direct strategy events | Proves streaming vertical slice. |
| Retrieval strategy uses fake memory gateway | Proves memory gateway integration. |
| Tool-assisted strategy uses fake tool gateway | Proves tool gateway integration. |
| Runtime produces state delta | Proves workflow-state handoff. |
| SessionService persists runtime state delta | Proves end-to-end state integration. |
| Trace events recorded for turn | Proves observability. |
| Capabilities include safe usecases | Proves capability integration. |
| Health reports strategy registry readiness | Proves health integration. |
| Policy denial blocks strategy | Proves policy integration. |

### 40.3 Optional Local Integration Tests

With configured local gateways:

```text
LLMGateway -> local/OpenAI/Google provider profile
MemoryGateway -> memory_store adapter
ToolGateway -> local MCP server at configured single endpoint
```

These tests should be isolated from CI unless the services are available through deterministic fixtures.

---

## 41. Fixture Configs

Recommended fixtures:

```text
tests/fixtures/config/orchestration_basic_direct.yaml
tests/fixtures/config/orchestration_streaming_direct.yaml
tests/fixtures/config/orchestration_retrieval_augmented.yaml
tests/fixtures/config/orchestration_tool_assisted.yaml
tests/fixtures/config/orchestration_router.yaml
tests/fixtures/config/orchestration_unknown_usecase.yaml
tests/fixtures/config/orchestration_disabled_strategy.yaml
tests/fixtures/config/orchestration_policy_denied.yaml
tests/fixtures/config/orchestration_limits.yaml
tests/fixtures/config/orchestration_debug_unsafe_invalid.yaml
```

Recommended fake components:

```text
FakeOrchestrationRuntime
FakeStrategy
FakeAgent
FakeLLMGateway
FakeMemoryGateway
FakeToolGateway
FakePolicyService
FakeObservabilityRecorder
```

---

## 42. Recommended Implementation Order

### Step 1: Add Orchestration Config Schemas

Deliverables:

- `OrchestrationSettings`
- `OrchestrationDefaultsSettings`
- `StrategySettings`
- `UseCaseSettings`
- validation for strategies, use cases, limits, and unsafe debug settings

Success criteria:

- Valid direct/retrieval/tool configs load.
- Invalid default strategy fails fast.
- Unsafe chain-of-thought exposure setting fails outside local debug profile.

### Step 2: Add Runtime Models and Errors

Deliverables:

- `OrchestrationRequest`
- `OrchestrationRuntimeContext`
- `OrchestrationResult`
- `OrchestrationStreamEvent`
- `OrchestrationStepSummary`
- `WorkflowStateDelta`
- normalized orchestration errors

Success criteria:

- Models serialize/validate cleanly.
- Errors expose stable code/retryable values.
- No API DTOs are imported.

### Step 3: Add Strategy Protocol and Registry

Deliverables:

- `OrchestrationStrategy`
- `StrategyRegistry`
- `ResolvedStrategy`
- safe strategy descriptors

Success criteria:

- Enabled strategy resolves.
- Disabled/unknown strategy fails clearly.
- Use-case allowlist is enforced.

### Step 4: Add Default Runtime

Deliverables:

- `DefaultOrchestrationRuntime.run_turn`
- `DefaultOrchestrationRuntime.stream_turn`
- use-case resolution
- strategy resolution
- context construction
- safe trace events

Success criteria:

- Runtime can execute fake strategy.
- Runtime emits safe started/completed/error events.
- Runtime returns state delta without writing persistence.

### Step 5: Add Direct Agent Strategy

Deliverables:

- `DirectAgentStrategy`
- fake/default agent integration
- LLM gateway call through agent or strategy
- safe result summaries

Success criteria:

- Non-streaming direct response works with fake LLM.
- Streaming direct response emits safe deltas.
- No provider SDK imports exist in strategy code.

### Step 6: Add Retrieval-Augmented Strategy

Deliverables:

- `RetrievalAugmentedStrategy`
- `MemoryGateway.search` integration
- context selection and safe summaries
- final LLM synthesis through agent/LLM gateway

Success criteria:

- Fake memory results are included as bounded context.
- Memory search summary appears in result.
- Raw memory records are not returned or traced.

### Step 7: Add Tool-Assisted Strategy

Deliverables:

- `ToolIntent`
- `ToolAssistedStrategy`
- tool call loop guard
- `ToolGateway.execute` integration
- safe tool summaries

Success criteria:

- Fake tool call runs through ToolGateway.
- Tool limits are enforced.
- Raw tool payloads are not streamed/traced/returned.

### Step 8: Add Runtime Limits and Cancellation

Deliverables:

- `OrchestrationLimits`
- step/tool/memory/LLM counters
- timeout handling
- cancellation propagation

Success criteria:

- Limit exceeded produces normalized error.
- Streaming cancellation records safe event.
- Gateway calls receive cancellation where supported.

### Step 9: Add Health and Capabilities

Deliverables:

- `OrchestrationHealthResult`
- `OrchestrationCapabilitiesResult`
- safe usecase and strategy descriptors

Success criteria:

- Health includes strategy registry readiness.
- Capabilities list safe usecases.
- No prompts, credentials, endpoints, or internal policy details are exposed.

### Step 10: Wire Runtime into SessionService

Deliverables:

- SessionService uses `OrchestrationRuntime.run_turn`.
- SessionService uses `OrchestrationRuntime.stream_turn`.
- SessionService persists `WorkflowStateDelta`.
- API remains unchanged.

Success criteria:

- `/chat` path reaches runtime through SessionService.
- `/chat/stream` path streams through runtime.
- API routes still do not import strategies, agents, gateways, SQLite, ArcadeDB, or MCP clients.

---

## 43. Acceptance Criteria

This architecture is complete when:

- `OrchestrationRuntime` exposes `run_turn`, `stream_turn`, `health`, and `capabilities`.
- `SessionService` calls `OrchestrationRuntime` for normal chat and streaming behavior.
- API routes do not call `OrchestrationRuntime` directly.
- API routes do not import strategies, agents, LLM providers, memory adapters, tool adapters, MCP clients, SQLite, or ArcadeDB.
- Runtime resolves use cases through configuration.
- Runtime resolves strategies through `StrategyRegistry`.
- Runtime builds `OrchestrationContext` with provider-neutral gateways.
- Strategies call LLMs only through `LLMGateway`.
- Strategies search/write memory only through `MemoryGateway`.
- Strategies execute tools only through `ToolGateway`.
- Runtime and strategies do not import provider SDKs, `memory_store`, ArcadeDB clients, MCP clients, or SQLite adapters.
- Runtime returns `OrchestrationResult` for non-streaming turns.
- Runtime yields `OrchestrationStreamEvent` objects for streaming turns.
- Runtime returns `WorkflowStateDelta` or safe state summaries to `SessionService`.
- Runtime does not persist workflow state directly.
- Runtime emits safe trace events through the observability facade.
- Raw prompts, raw provider responses, raw tool payloads, raw memory records, credentials, hidden chain-of-thought, and stack traces are not returned, streamed, logged, or traced by default.
- Strategy and gateway calls are trace-correlated with `trace_id`.
- Runtime enforces step, LLM call, memory search, tool call, and duration limits.
- Runtime supports cancellation for streaming and long-running turns.
- Unknown use cases fail clearly.
- Disabled strategies fail clearly.
- Policy denial prevents strategy execution or gateway actions.
- Tool-assisted strategies execute only logical tool names through `ToolGateway`.
- Retrieval strategies use bounded memory/document context.
- Direct strategy can run without memory or tools.
- Health reports safe orchestration readiness.
- Capabilities expose only frontend-safe usecase/strategy metadata.
- Unit tests run with fake strategies, agents, LLM, memory, tools, and policy.
- Integration tests verify `API -> SessionService -> OrchestrationRuntime -> Gateways` without changing API contracts.
- The backend is ready for the next document: `backend-agents-architecture.md`.

---

## 44. Anti-Patterns to Avoid

Avoid these during implementation:

- Calling LLM providers directly from runtime, strategies, or agents.
- Calling MCP server directly from runtime, strategies, or agents.
- Searching ArcadeDB directly from runtime, strategies, or agents.
- Importing `memory_store.service.MemoryService` in orchestration code.
- Running SQL from orchestration code.
- Letting API routes select strategies or agents.
- Letting `SessionService` execute tools for normal chat behavior.
- Letting user metadata directly choose arbitrary strategy, agent, LLM profile, or MCP tool.
- Letting LLM output bypass tool validation.
- Letting provider-native tool calls execute outside `ToolGateway`.
- Returning raw workflow state from orchestration results.
- Storing raw tool results in workflow state.
- Storing raw memory records in workflow state.
- Streaming raw provider chunks directly to API.
- Tracing raw prompts or hidden scratchpads by default.
- Exposing hidden chain-of-thought.
- Treating memory/tool text as trusted instructions.
- Creating unbounded LLM-tool loops.
- Retrying external-side-effect tool actions blindly.
- Falling back to a less restricted strategy after policy denial.
- Making orchestration depend on frontend-specific response models.
- Using strategy registry as a hidden service locator for concrete infrastructure clients.

---

## 45. Future Documents That Depend on This Orchestration Layer

| Future Document | Dependency |
|---|---|
| `backend-agents-architecture.md` | Agents are invoked by strategies through the orchestration context and gateway interfaces. |
| `backend-workflow-strategies-architecture.md` | Deepens direct, retrieval, tool-assisted, router, planner, and approval-aware strategies. |
| `backend-policy-architecture.md` | Defines final strategy, agent, LLM, memory, tool, approval, trace capture, and data exposure policy. |
| `backend-approval-workflow-architecture.md` | Defines pending approval state, resume behavior, and approved tool execution. |
| `backend-prompt-context-architecture.md` | Defines prompt assembly, context quoting, memory/tool result formatting, and injection protections. |
| `backend-evaluation-architecture.md` | Evaluates strategy selection, tool correctness, memory use, answer quality, and failure recovery. |
| `backend-deployment-architecture.md` | Defines runtime config, environment profiles, process model, and gateway availability. |
| `backend-hardening-architecture.md` | Defines production limits, auth, privacy controls, rate limits, and security review gates. |

---

## 46. Summary

`backend-orchestration-architecture.md` defines the backend runtime layer that coordinates a user turn after `SessionService` has loaded session workflow state and before `SessionService` persists the updated state.

It preserves the previously defined boundaries: API remains thin, `SessionService` owns session lifecycle and state persistence, `LLMGateway` owns model access, `MemoryGateway` owns memory/document access, `ToolGateway` owns tool execution, and `MCPClientAdapter` remains the only backend component that speaks MCP protocol.

The most important implementation rule is:

> **The orchestration layer coordinates workflow, but it does not own infrastructure. Runtime and strategies choose the flow, invoke agents, call provider-neutral gateways, enforce limits, emit safe events, and return normalized results/state deltas. Concrete providers, databases, MCP protocol details, API DTOs, and frontend behavior remain outside the orchestration boundary.**
