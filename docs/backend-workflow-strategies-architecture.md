# Backend Workflow Strategies Architecture

**Document:** `backend-workflow-strategies-architecture.md`  
**Version:** 1.0  
**Source alignment:** `backend-application-architecture.md`, `backend-foundation-architecture.md`, `backend-core-contracts-architecture.md`, `backend-configuration-architecture.md`, `backend-observability-architecture.md`, `backend-persistence-architecture.md`, `backend-sqlite-workflow-state-architecture.md`, `backend-sqlite-trace-store-architecture.md`, `backend-api-architecture.md`, `backend-session-service-architecture.md`, `backend-llm-gateway-architecture.md`, `backend-memory-store-adapter-architecture.md`, `backend-tooling-mcp-client-architecture.md`, and `backend-orchestration-architecture.md`  
**Scope:** Built-in workflow strategy implementations, strategy contracts, direct-agent flow, retrieval-augmented flow, tool-assisted flow, router flow, bounded planner/executor flow, memory-write flow, fallback behavior, stream-event behavior, workflow-state summaries, policy hooks, trace correlation, testing strategy, and acceptance criteria for the V1 strategy layer.

---

## 1. Purpose

This document defines the next implementation-focused architecture document for the backend application tier.

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
13. `backend-orchestration-architecture.md`
14. `backend-workflow-strategies-architecture.md` ← this document

The previous document established `OrchestrationRuntime` as the only session-facing boundary for running a user turn. It also established that strategies are responsible for workflow shape while the runtime owns turn lifecycle, strategy resolution, context construction, cancellation, and normalized results.

This document deepens the strategy layer.

The goal is to define the concrete V1 strategy catalog and the contracts each strategy must follow so that the backend can support direct agent replies, retrieval-augmented answers, tool-assisted answers, simple routing, bounded planning, and safe memory updates without changing API routes, session service behavior, gateway implementations, or agent plugin contracts.

The core architecture rule is:

> `WorkflowStrategy` implementations own the shape of a turn, but they do not own infrastructure. Strategies may coordinate agents, LLM calls, memory calls, and tool calls only through `OrchestrationContext` and provider-neutral gateways. Strategies must not import concrete LLM providers, `memory_store`, ArcadeDB clients, MCP clients, SQLite clients, API DTOs, frontend models, or provider-specific response objects.

---

## 2. Source Architecture Alignment

This document follows the established backend rules:

- The backend is one deployable application tier in V1.
- Frontend communicates with backend through REST / SSE.
- API routes are thin and delegate chat/reset behavior to `SessionService`.
- `SessionService` owns session lifecycle, workflow-state load/save/reset, and request-to-runtime handoff.
- `SessionService` calls `OrchestrationRuntime`; it does not select strategies, select agents, call LLM providers, search memory, or execute tools directly for normal chat behavior.
- `OrchestrationRuntime` owns per-turn execution flow, strategy resolution, context construction, runtime-level limits, cancellation handling, and normalized runtime results.
- Workflow strategies own step ordering and workflow shape.
- Agents own task-specific behavior and are invoked through narrow agent contracts.
- Agent plugin internals remain a later document.
- LLM calls remain behind `LLMGateway`.
- Long-term memory and document chunks remain behind `MemoryGateway`.
- External tool execution remains behind `ToolGateway`.
- MCP protocol communication remains behind `MCPClientAdapter`.
- SQLite workflow state remains behind `WorkflowStateStore` and is persisted by `SessionService`, not by strategies.
- SQLite traces remain behind `TraceStore` or an observability facade.
- ArcadeDB-backed memory remains behind the memory adapter and must not leak into strategy code.
- Strategies must return safe result summaries and workflow-state deltas to the runtime.
- Strategies must not return, stream, log, or trace raw prompts, raw provider responses, raw MCP payloads, raw memory records, raw workflow state documents, credentials, hidden scratchpads, or stack traces by default.
- Tool, memory, LLM, agent, and strategy decisions must be trace-correlated with the active `trace_id`.

---

## 3. Refined Position in the Backend Implementation Sequence

The prior orchestration document combined the runtime and initial strategy contract in Phase 13. This document refines that phase boundary by splitting strategy implementation into its own focused phase before agent plugins.

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
Phase 16: Hardening and Deployment Readiness
```

This document expands Phase 14.

The output of this phase is a built-in strategy layer that supports:

```text
DirectAgentStrategy.run(...)
DirectAgentStrategy.stream(...)
RetrievalAugmentedStrategy.run(...)
RetrievalAugmentedStrategy.stream(...)
ToolAssistedStrategy.run(...)
ToolAssistedStrategy.stream(...)
RouterStrategy.run(...)
RouterStrategy.stream(...)
BoundedPlannerStrategy.run(...)
MemoryUpdateStrategy.run(...)

StrategyFactory.build(...)
StrategyRegistry.register(...)
StrategyRegistry.resolve(...)
StrategyPolicyGuard.check(...)
StrategyStepRunner.run_step(...)
```

The next document should be:

```text
backend-agents-architecture.md
```

---

## 4. Architecture Goals

The workflow strategy layer should be:

1. **Runtime-compatible**  
   Strategies implement the `OrchestrationStrategy` contract defined by the orchestration runtime.

2. **Gateway-only**  
   Strategies call LLMs, memory, and tools only through `LLMGateway`, `MemoryGateway`, and `ToolGateway` exposed on `OrchestrationContext`.

3. **Agent-ready**  
   Strategies invoke agents through an agent registry/agent handle abstraction, while leaving detailed agent design to the next document.

4. **Configuration-driven**  
   Strategy enablement, use-case mapping, limits, memory behavior, tool behavior, model/profile preferences, fallback behavior, and streaming behavior are configured through YAML.

5. **Composable**  
   Common steps such as memory retrieval, tool execution, LLM answer generation, and memory candidate extraction are reusable across strategies.

6. **Bounded**  
   Strategies enforce max steps, max LLM calls, max memory searches, max tool calls, max tool loop iterations, max context bytes, and total runtime duration.

7. **Safe by default**  
   Strategy outputs are safe summaries suitable for session results, workflow-state deltas, SSE events, and trace events.

8. **Policy-aware**  
   Strategy execution, agent selection, LLM profile use, memory access, memory writes, and tool execution pass through policy checks or gateway-level policy checks.

9. **Fallback-aware**  
   Fallbacks are explicit, configured, bounded, and must not weaken policy restrictions.

10. **Streaming-capable**  
    Strategies can stream normalized `OrchestrationStreamEvent` objects without exposing raw provider chunks or raw tool payloads.

11. **Cancellation-aware**  
    Strategies propagate cancellation to LLM, memory, and tool gateway calls where supported.

12. **Testable**  
    Strategies can be tested with fake agents and fake gateways without SQLite, ArcadeDB, MCP server, or external LLM providers.

---

## 5. Non-Goals

This document should not implement:

- API route behavior.
- Session lifecycle rules.
- Workflow-state SQL persistence.
- Trace-store SQL persistence.
- Concrete LLM provider SDK integrations.
- Concrete ArcadeDB or `memory_store` implementation.
- MCP protocol details.
- MCP server implementation.
- Full agent plugin internals.
- Full production auth/policy system.
- Human approval UI.
- Distributed task queues.
- Multi-process durable workflow engines.
- Unbounded autonomous planning.
- Full prompt-template library.
- Evaluation datasets and scoring dashboards.

Those concerns belong to API, session, persistence, LLM, memory, tooling, MCP, agents, policy, approval, deployment, prompt-context, and evaluation documents.

---

## 6. Strategy Boundary

Strategies sit inside the orchestration layer and below the runtime.

They own:

- Step ordering for a turn.
- Strategy-specific use of agents.
- Strategy-specific LLM/memory/tool sequencing.
- Strategy-specific context assembly decisions.
- Strategy-specific fallback behavior.
- Strategy-specific safe workflow-state delta construction.
- Strategy-specific stream event emission.
- Strategy-specific limits and loop guards.
- Strategy-specific trace event summaries.

They do not own:

- API request parsing.
- Session creation, reset, or persistence.
- SQLite reads/writes.
- ArcadeDB reads/writes.
- MCP protocol communication.
- Provider SDK calls.
- Credential handling.
- Tool policy enforcement internals.
- Memory adapter internals.
- Frontend response formatting.

### 6.1 Boundary Diagram

```text
API
  -> SessionService
      -> WorkflowStateStore.load(...)
      -> OrchestrationRuntime
          -> StrategyRegistry.resolve(...)
          -> WorkflowStrategy
              -> AgentRegistry / Agent handle
              -> LLMGateway
              -> MemoryGateway
              -> ToolGateway
              -> PolicyService / policy hooks
              -> Observability facade
          -> OrchestrationResult / OrchestrationStreamEvent
      -> WorkflowStateStore.save(...)
```

### 6.2 Practical Rule

Strategies should do this:

```python
memory_results = await context.memory.search(
    request=MemorySearchRequest(
        query=request.message,
        scope=MemoryScope(user_id=request.user_id, project_id=request.project_id),
        limit=5,
    ),
    context=request,
)

llm_result = await context.llm.complete(
    request=LLMCompletionRequest(
        profile="default_reasoning",
        messages=messages,
        metadata={"strategy_name": self.name},
    ),
    context=request,
)
```

Strategies should not do this:

```python
from openai import AsyncOpenAI
from memory_store.service import MemoryService
import sqlite3

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
conn = sqlite3.connect("workflow_state.db")
mem = MemoryService(...)
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
      strategy.py
      strategy_registry.py
      strategy_factory.py
      strategy_config.py
      strategy_policy.py
      strategy_steps.py
      strategy_limits.py
      strategy_result_builder.py
      state_delta.py
      context_budget.py
      prompt_inputs.py
      tool_intents.py
      memory_intents.py
      fallback.py
      stream_mapping.py
      trace_helpers.py
      health.py
      capabilities.py

      strategies/
        __init__.py
        direct_agent.py
        retrieval_augmented.py
        tool_assisted.py
        router.py
        bounded_planner.py
        memory_update.py
        fallback_answer.py
        base.py

    agents/
      base.py
      registry.py
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
      redaction.py
      metrics.py

    testing/
      fakes/
        fake_strategy.py
        fake_agent_registry.py
        fake_agent.py
        fake_llm_gateway.py
        fake_memory_gateway.py
        fake_tool_gateway.py
        fake_policy_service.py
```

### 7.1 Module Responsibilities

| Module | Responsibility |
|---|---|
| `strategy.py` | Public strategy protocol/base interface. |
| `strategy_registry.py` | Register, list, resolve, and validate strategies. |
| `strategy_factory.py` | Build configured strategy instances from settings. |
| `strategy_config.py` | Typed strategy configuration models. |
| `strategy_policy.py` | Strategy-level policy guard helpers. |
| `strategy_steps.py` | Reusable step runner primitives. |
| `strategy_limits.py` | Limit counters and loop guards. |
| `strategy_result_builder.py` | Builds normalized strategy outputs. |
| `state_delta.py` | Builds safe workflow-state deltas for runtime/session persistence. |
| `context_budget.py` | Bounds memory/tool/history context before LLM calls. |
| `prompt_inputs.py` | Strategy-facing prompt input objects, not final prompt templates. |
| `tool_intents.py` | Tool intent parsing/validation helpers. |
| `memory_intents.py` | Memory search/write intent helpers. |
| `fallback.py` | Safe fallback behavior and fallback policy rules. |
| `stream_mapping.py` | Maps strategy step events to orchestration stream events. |
| `trace_helpers.py` | Safe strategy trace event helpers. |
| `strategies/direct_agent.py` | Minimal direct agent/LLM strategy. |
| `strategies/retrieval_augmented.py` | Memory/document retrieval before answer generation. |
| `strategies/tool_assisted.py` | Tool-intent loop through `ToolGateway`. |
| `strategies/router.py` | Selects strategy/agent based on configured routing rules. |
| `strategies/bounded_planner.py` | Bounded plan-then-execute workflow for V1-safe tasks. |
| `strategies/memory_update.py` | Safe candidate extraction and memory write handoff. |
| `strategies/fallback_answer.py` | Last-resort answer strategy when configured and policy allows. |

---

## 8. Dependency Direction Rules

Allowed:

```text
app/orchestration/strategies/* -> app/orchestration/context.py
app/orchestration/strategies/* -> app/orchestration/models.py
app/orchestration/strategies/* -> app/orchestration/events.py
app/orchestration/strategies/* -> app/llm/gateway.py through protocol
app/orchestration/strategies/* -> app/memory/gateway.py through protocol
app/orchestration/strategies/* -> app/tools/gateway.py through protocol
app/orchestration/strategies/* -> app/agents/registry.py through protocol
app/orchestration/strategies/* -> app/policy/service.py through protocol
app/orchestration/strategies/* -> app/observability/* through facade
```

Avoid:

```text
app/orchestration/strategies/* -> app/api/*
app/orchestration/strategies/* -> app/session/*
app/orchestration/strategies/* -> sqlite3
app/orchestration/strategies/* -> memory_store.service.MemoryService
app/orchestration/strategies/* -> ArcadeDB client
app/orchestration/strategies/* -> MCP client libraries
app/orchestration/strategies/* -> provider SDKs
app/orchestration/strategies/* -> FastAPI response models
app/orchestration/strategies/* -> frontend DTOs
```

### 8.1 Strategy-to-Gateway Rule

Correct:

```text
Strategy -> LLMGateway
Strategy -> MemoryGateway
Strategy -> ToolGateway
```

Avoid:

```text
Strategy -> OpenAI SDK
Strategy -> Google SDK
Strategy -> LocalAI HTTP client
Strategy -> memory_store.service.MemoryService
Strategy -> MCPClientAdapter
Strategy -> MCP Server URL
```

### 8.2 Strategy-to-State Rule

Correct:

```text
Strategy -> WorkflowStateDelta
Runtime -> OrchestrationResult
SessionService -> WorkflowStateStore.save(...)
```

Avoid:

```text
Strategy -> WorkflowStateStore.save(...)
Strategy -> sqlite3.connect(...)
Strategy -> direct workflow_state.db update
```

---

## 9. Strategy Configuration Integration

Workflow strategy settings should be resolved by the configuration loader before runtime composition.

Recommended YAML:

```yaml
orchestration:
  enabled: true

  defaults:
    default_usecase: default
    default_strategy: direct_agent
    fallback_strategy: fallback_answer
    max_steps: 8
    max_llm_calls: 3
    max_memory_searches: 2
    max_memory_writes: 1
    max_tool_calls: 3
    max_tool_loop_iterations: 3
    max_context_bytes: 64000
    max_duration_seconds: 120
    stream_strategy_events: true
    expose_strategy_metadata: true

  strategies:
    direct_agent:
      enabled: true
      type: direct_agent
      default_agent: general_assistant_agent
      llm_profile: default_reasoning
      allow_memory_search: false
      allow_tools: false
      allow_memory_write: false
      max_llm_calls: 1
      stream_llm_deltas: true

    retrieval_augmented:
      enabled: true
      type: retrieval_augmented
      default_agent: document_qa_agent
      llm_profile: research_reasoning
      memory:
        enabled: true
        search_limit: 5
        include_document_chunks: true
        include_user_memories: true
        min_score: 0.25
        max_context_items: 8
        max_context_bytes: 32000
      allow_tools: false
      allow_memory_write: false
      stream_llm_deltas: true

    tool_assisted:
      enabled: true
      type: tool_assisted
      default_agent: tool_using_agent
      llm_profile: tool_reasoning
      tool_policy:
        enabled: true
        max_tool_calls: 3
        max_tool_loop_iterations: 3
        allowed_tools:
          - documents.search
          - project.read_file
      memory:
        enabled: false
      stream_tool_events: true
      stream_llm_deltas: true

    router:
      enabled: true
      type: router
      routing_mode: rules_first
      llm_profile: router_lightweight
      candidate_strategies:
        - direct_agent
        - retrieval_augmented
        - tool_assisted
      fallback_strategy: direct_agent
      expose_routing_reason: false

    bounded_planner:
      enabled: false
      type: bounded_planner
      planner_llm_profile: planner_reasoning
      executor_llm_profile: default_reasoning
      max_plan_steps: 5
      max_execute_steps: 5
      allow_tools: true
      allow_memory_search: true
      allow_memory_write: false

    memory_update:
      enabled: true
      type: memory_update
      default_agent: memory_curator_agent
      llm_profile: memory_curator
      candidate_limit: 5
      write_limit: 1
      require_policy_approval: true

    fallback_answer:
      enabled: true
      type: fallback_answer
      llm_profile: default_reasoning
      message: "I could not complete the full workflow, but here is what I can safely answer."

  usecases:
    default:
      strategy: direct_agent
      agent: general_assistant_agent
      allowed_strategies: [direct_agent, router, fallback_answer]

    document_qa:
      strategy: retrieval_augmented
      agent: document_qa_agent
      allowed_strategies: [retrieval_augmented, direct_agent, fallback_answer]

    project_work:
      strategy: tool_assisted
      agent: project_agent
      allowed_strategies: [tool_assisted, retrieval_augmented, direct_agent, fallback_answer]

    auto:
      strategy: router
      allowed_strategies: [router, direct_agent, retrieval_augmented, tool_assisted, fallback_answer]
```

### 9.1 Configuration Safety Rule

Configuration validation should fail fast when:

- A use case points to a missing strategy.
- A strategy is configured but disabled and selected as default.
- A fallback strategy is missing or disabled.
- A strategy references a missing LLM profile.
- A strategy references a missing agent when strict validation is enabled.
- A strategy enables tools while `ToolGateway` is disabled and no fake tool gateway is configured.
- A strategy enables memory while `MemoryGateway` is disabled and no fake memory gateway is configured.
- Max step/tool/LLM/memory limits are less than zero.
- Router candidate strategies include unknown or disabled strategies.
- Tool-assisted strategy includes raw MCP tool names instead of logical tool names.
- Memory update strategy enables writes without policy hooks.
- Bounded planner has no step limit.

---

## 10. Typed Strategy Settings

Recommended dataclasses:

```python
from dataclasses import dataclass, field
from typing import Literal


StrategyType = Literal[
    "direct_agent",
    "retrieval_augmented",
    "tool_assisted",
    "router",
    "bounded_planner",
    "memory_update",
    "fallback_answer",
]


@dataclass(frozen=True, slots=True)
class StrategyLimitSettings:
    max_steps: int = 8
    max_llm_calls: int = 3
    max_memory_searches: int = 2
    max_memory_writes: int = 1
    max_tool_calls: int = 3
    max_tool_loop_iterations: int = 3
    max_context_bytes: int = 64000
    max_duration_seconds: int = 120


@dataclass(frozen=True, slots=True)
class StrategyMemorySettings:
    enabled: bool = False
    search_limit: int = 5
    include_document_chunks: bool = True
    include_user_memories: bool = True
    min_score: float | None = None
    max_context_items: int = 8
    max_context_bytes: int = 32000


@dataclass(frozen=True, slots=True)
class StrategyToolSettings:
    enabled: bool = False
    max_tool_calls: int = 3
    max_tool_loop_iterations: int = 3
    allowed_tools: tuple[str, ...] = ()
    stream_tool_events: bool = True


@dataclass(frozen=True, slots=True)
class StrategySettings:
    name: str
    type: StrategyType
    enabled: bool
    default_agent: str | None = None
    llm_profile: str | None = None
    limits: StrategyLimitSettings = field(default_factory=StrategyLimitSettings)
    memory: StrategyMemorySettings = field(default_factory=StrategyMemorySettings)
    tools: StrategyToolSettings = field(default_factory=StrategyToolSettings)
    fallback_strategy: str | None = None
    expose_reasoning: bool = False
    expose_metadata: bool = True
    extra: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class UsecaseStrategySettings:
    name: str
    strategy: str
    agent: str | None = None
    allowed_strategies: tuple[str, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)
```

### 10.1 `expose_reasoning` Rule

`expose_reasoning` must default to `false` and should not expose hidden chain-of-thought.

Safe exposure examples:

```text
selected strategy name
selected agent name
safe routing category
tool call summary
memory result count
fallback used true/false
```

Unsafe exposure examples:

```text
hidden chain-of-thought
raw planning scratchpad
raw system prompt
raw developer prompt
raw LLM completion metadata that includes sensitive payloads
```

---

## 11. Strategy Contract

The orchestration runtime calls strategies through a narrow contract.

Recommended protocol:

```python
from collections.abc import AsyncIterator
from typing import Protocol


class OrchestrationStrategy(Protocol):
    name: str
    type: str

    async def run(
        self,
        *,
        request: "OrchestrationTurnRequest",
        context: "OrchestrationContext",
    ) -> "StrategyRunResult":
        ...

    async def stream(
        self,
        *,
        request: "OrchestrationTurnRequest",
        context: "OrchestrationContext",
    ) -> AsyncIterator["StrategyStreamEvent"]:
        ...

    async def health(self) -> "StrategyHealthResult":
        ...

    def capabilities(self) -> "StrategyCapabilities":
        ...
```

### 11.1 Strategy Input

Strategies receive the runtime-level turn request:

```python
@dataclass(frozen=True, slots=True)
class OrchestrationTurnRequest:
    trace_id: str
    session_id: str
    user_id: str | None
    project_id: str | None
    usecase: str
    message: str
    workflow_state: "WorkflowStateSnapshot"
    metadata: dict[str, object] = field(default_factory=dict)
```

### 11.2 Strategy Output

Strategies return normalized strategy results:

```python
@dataclass(frozen=True, slots=True)
class StrategyRunResult:
    answer: str
    status: str = "completed"
    agent_name: str | None = None
    strategy_name: str | None = None
    llm_profile: str | None = None
    steps: tuple["WorkflowStepSummary", ...] = ()
    tool_calls: tuple["ToolCallSummary", ...] = ()
    memory_searches: tuple["MemorySearchSummary", ...] = ()
    memory_updates: tuple["MemoryUpdateSummary", ...] = ()
    state_delta: "WorkflowStateDelta | None" = None
    metadata: dict[str, object] = field(default_factory=dict)
```

### 11.3 Strategy Stream Events

Recommended stream event model:

```python
@dataclass(frozen=True, slots=True)
class StrategyStreamEvent:
    type: str
    strategy_name: str
    text: str | None = None
    step: "WorkflowStepSummary | None" = None
    result: StrategyRunResult | None = None
    error: "OrchestrationErrorDetail | None" = None
    metadata: dict[str, object] = field(default_factory=dict)
```

Allowed stream event types:

```text
strategy.started
strategy.step.started
strategy.step.completed
strategy.step.failed
agent.started
agent.completed
memory.search.started
memory.search.completed
tool.started
tool.completed
response.delta
response.metadata
strategy.completed
strategy.failed
strategy.cancelled
```

### 11.4 Stream Safety Rule

Strategy stream events must not include:

- Raw LLM provider chunks.
- Raw prompts.
- Raw system/developer messages.
- Hidden chain-of-thought.
- Raw tool request/response payloads.
- Raw memory records.
- Raw workflow state.
- Credentials.
- Stack traces.

---

## 12. Workflow Step Model

Strategies should report a safe step summary to the runtime.

Recommended model:

```python
from dataclasses import dataclass, field
from typing import Literal


StepType = Literal[
    "route",
    "agent_invoke",
    "llm_call",
    "memory_search",
    "memory_write",
    "tool_call",
    "plan",
    "finalize",
    "fallback",
]

StepStatus = Literal[
    "planned",
    "running",
    "completed",
    "failed",
    "skipped",
    "cancelled",
]


@dataclass(frozen=True, slots=True)
class WorkflowStepSummary:
    step_id: str
    step_type: StepType
    status: StepStatus
    name: str
    started_at: str | None = None
    completed_at: str | None = None
    duration_ms: int | None = None
    summary: str | None = None
    error_code: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)
```

### 12.1 Safe Step Metadata

Allowed metadata examples:

```text
strategy_name
agent_name
llm_profile
memory_result_count
tool_name
tool_status
fallback_used
truncated
```

Disallowed metadata examples:

```text
raw prompt
raw completion
raw memory text
raw tool payload
authorization header
OAuth token
JWT
full workflow state
stack trace
```

---

## 13. Strategy Limit Enforcement

Each strategy receives a limit guard from the runtime or builds one from resolved settings.

Recommended model:

```python
@dataclass(slots=True)
class StrategyLimitGuard:
    max_steps: int
    max_llm_calls: int
    max_memory_searches: int
    max_memory_writes: int
    max_tool_calls: int
    max_tool_loop_iterations: int
    max_context_bytes: int
    max_duration_seconds: int

    steps_used: int = 0
    llm_calls_used: int = 0
    memory_searches_used: int = 0
    memory_writes_used: int = 0
    tool_calls_used: int = 0
    tool_loop_iterations_used: int = 0

    def check_step(self) -> None: ...
    def check_llm_call(self) -> None: ...
    def check_memory_search(self) -> None: ...
    def check_memory_write(self) -> None: ...
    def check_tool_call(self) -> None: ...
    def check_tool_loop_iteration(self) -> None: ...
    def check_context_bytes(self, bytes_used: int) -> None: ...
    def check_duration(self) -> None: ...
```

### 13.1 Limit Error Behavior

When a limit is exceeded:

```text
1. Stop the current strategy path.
2. Record a safe `strategy_limit_exceeded` trace event.
3. Return a normalized strategy error or configured fallback result.
4. Do not continue tool/LLM loops.
5. Do not fall back to a less restrictive strategy after policy denial.
```

---

## 14. Built-In Strategy Catalog

V1 should support a small built-in catalog.

| Strategy | Primary Purpose | Memory | Tools | Planner | V1 Default |
|---|---|---:|---:|---:|---:|
| `direct_agent` | Simple answer through agent/LLM. | optional off | off | no | yes |
| `retrieval_augmented` | Retrieve memory/docs, then answer. | yes | off by default | no | yes |
| `tool_assisted` | Use allowed tools when needed. | optional | yes | limited loop | yes |
| `router` | Choose configured strategy/agent. | optional | off by default | no | optional |
| `bounded_planner` | Plan a small bounded sequence. | optional | optional | yes | disabled by default |
| `memory_update` | Curate memory candidates and write through gateway. | yes/write | off | no | optional |
| `fallback_answer` | Safe fallback response. | off | off | no | yes |

### 14.1 Default V1 Recommendation

Start with:

```text
direct_agent
retrieval_augmented
tool_assisted
fallback_answer
```

Then add:

```text
router
memory_update
bounded_planner
```

Reason: direct, retrieval, and tool-assisted strategies prove the main gateway boundaries. Router and planner behavior add complexity and should be introduced after the basic flows are deterministic and tested.

---

## 15. Direct Agent Strategy

`DirectAgentStrategy` is the smallest useful workflow.

It is appropriate when:

- No tool call is needed.
- No memory search is needed.
- The use case maps directly to one agent.
- The request can be answered from the user message and session history summary.

### 15.1 Flow

```text
1. Start strategy.
2. Resolve configured agent.
3. Build bounded prompt input from message and safe session summary.
4. Call agent or LLM through provider-neutral contract.
5. Build answer.
6. Build safe workflow-state delta.
7. Return StrategyRunResult.
```

### 15.2 Pseudocode

```python
class DirectAgentStrategy:
    name = "direct_agent"
    type = "direct_agent"

    async def run(self, *, request, context) -> StrategyRunResult:
        guard = context.limits.for_strategy(self.name)
        guard.check_step()

        agent = context.agents.resolve(self.settings.default_agent)

        agent_result = await agent.run(
            request=AgentRunRequest(
                message=request.message,
                llm_profile=self.settings.llm_profile,
                context_items=(),
                tools_available=(),
                metadata={"strategy_name": self.name},
            ),
            context=context,
        )

        return StrategyRunResult(
            answer=agent_result.answer,
            agent_name=agent.name,
            strategy_name=self.name,
            llm_profile=self.settings.llm_profile,
            steps=(make_agent_step(agent_result),),
            state_delta=build_turn_state_delta(request, agent_result),
        )
```

### 15.3 Direct Strategy Rules

- It should work with fake LLM and fake agent.
- It should not require memory or tooling.
- It should not execute tool calls even if the LLM suggests one.
- If the agent produces a tool intent, the strategy should either ignore it safely or fail with `UnsupportedToolIntentError`, depending on configuration.
- It should return a clear fallback if the configured agent is missing.

---

## 16. Retrieval-Augmented Strategy

`RetrievalAugmentedStrategy` searches memory/document chunks before answer generation.

It is appropriate when:

- The use case needs project facts, user preferences, prior memories, or indexed document chunks.
- The answer should be grounded in retrieved context.
- The tool layer is not required.

### 16.1 Flow

```text
1. Start strategy.
2. Resolve configured agent.
3. Build memory search request from the user message and scope.
4. Call MemoryGateway.search.
5. Normalize and bound retrieved context.
6. Build prompt input with quoted context blocks.
7. Call agent/LLM.
8. Return answer with safe memory search summary.
9. Return workflow-state delta with memory search summary, not raw memory records.
```

### 16.2 Memory Search Request

```python
memory_result = await context.memory.search(
    request=MemorySearchRequest(
        query=request.message,
        scope=MemoryScope(
            user_id=request.user_id,
            project_id=request.project_id,
            session_id=request.session_id,
            usecase=request.usecase,
        ),
        limit=self.settings.memory.search_limit,
        include_document_chunks=self.settings.memory.include_document_chunks,
        include_user_memories=self.settings.memory.include_user_memories,
        min_score=self.settings.memory.min_score,
    ),
    context=context.request,
)
```

### 16.3 Context Bounding

Retrieved items must be bounded before entering prompt input.

Recommended controls:

```text
max_context_items
max_context_bytes
max_text_chars_per_item
min_score
allowed memory types
allowed document scopes
deduplication by memory_id/source_id/chunk_id
sort by final score then recency where appropriate
```

### 16.4 Safe Context Item

```python
@dataclass(frozen=True, slots=True)
class PromptContextItem:
    source_type: str
    source_id: str | None
    title: str | None
    text: str
    score: float | None = None
    metadata: dict[str, object] = field(default_factory=dict)
```

Allowed metadata:

```text
memory_type
source_title
chunk_index
score
created_at
updated_at
scope_label
```

Disallowed metadata:

```text
raw embedding vectors
ArcadeDB record internals
full source document unless bounded
private connection data
raw memory adapter payload
```

### 16.5 Retrieval Strategy Rules

- Memory/document search must use `MemoryGateway` only.
- Search should happen before answer generation unless configuration explicitly disables retrieval for a turn.
- Raw memory records should not be returned to API/session/frontend.
- Retrieved text should be treated as untrusted data, not instructions.
- If no memory results are found, the strategy can continue with a no-context answer or fallback, depending on use-case config.
- Memory search failures can be degraded to direct answer only if policy allows fallback and the answer clearly avoids unsupported claims.

---

## 17. Tool-Assisted Strategy

`ToolAssistedStrategy` allows a strategy or agent to request logical tool calls through `ToolGateway`.

It is appropriate when:

- The answer requires external capability exposed by MCP through `ToolGateway`.
- The use case has an allowlisted tool set.
- The strategy can bound the tool loop.

### 17.1 Flow

```text
1. Start strategy.
2. Resolve configured agent.
3. Ask agent/LLM for either an answer or a tool intent.
4. Validate tool intent shape.
5. Check strategy-level allowed logical tool names.
6. Call ToolGateway.execute.
7. Add bounded tool result summary/context.
8. Repeat within max_tool_loop_iterations if needed.
9. Ask agent/LLM for final answer using safe tool result context.
10. Return answer with safe tool call summaries.
```

### 17.2 Tool Intent Model

```python
@dataclass(frozen=True, slots=True)
class ToolIntent:
    tool_name: str
    arguments: dict[str, object]
    reason: str | None = None
    confidence: float | None = None
    idempotency_key: str | None = None
```

### 17.3 Tool Intent Validation

Before calling `ToolGateway`, the strategy should validate:

```text
tool_name is a logical backend tool name
tool_name is included in strategy allowed_tools when configured
arguments are JSON-serializable
arguments size is bounded
reason is safe and bounded
no raw auth/token arguments are present
loop and call limits are not exceeded
```

`ToolGateway` still performs registry resolution, policy checks, argument schema validation, timeout handling, MCP execution, result normalization, and safe tracing.

### 17.4 Tool Result Context

Tool results passed to LLM/agent should be reduced to safe context blocks.

```python
@dataclass(frozen=True, slots=True)
class ToolContextItem:
    tool_name: str
    status: str
    summary: str | None
    structured_content: dict[str, object] | None = None
    truncated: bool = False
    metadata: dict[str, object] = field(default_factory=dict)
```

### 17.5 Tool-Assisted Strategy Rules

- Strategies must never call `MCPClientAdapter` directly.
- Strategies must never call raw MCP endpoints.
- LLM tool intents are not execution.
- Every tool call must go through `ToolGateway`.
- Tool outputs are untrusted data and must not override system/developer/agent instructions.
- Tool loops must be bounded.
- External-side-effect and destructive tools must be disabled unless explicit policy/approval exists.
- Provider-native tool call formats should be normalized into `ToolIntent` and executed through `ToolGateway` only.

---

## 18. Router Strategy

`RouterStrategy` selects a configured strategy and optional agent based on use-case rules, lightweight classification, or policy-filtered LLM routing.

It is appropriate when:

- The frontend sends a broad use case such as `auto`.
- Multiple strategies may handle a request.
- The backend needs runtime routing without changing API/session code.

### 18.1 Routing Modes

Recommended V1 modes:

| Mode | Behavior | Default Safety |
|---|---|---|
| `rules_only` | Uses deterministic config rules and request metadata. | safest |
| `rules_first` | Rules first, optional LLM classifier if no rule matches. | recommended |
| `llm_classifier` | LLM chooses among configured candidates. | optional |

### 18.2 Router Flow

```text
1. Start router strategy.
2. Load candidate strategies from use-case config.
3. Policy-filter candidate strategies.
4. Apply deterministic routing rules.
5. If needed and allowed, call LLM classifier through LLMGateway.
6. Normalize selected strategy and confidence.
7. Invoke selected strategy through StrategyRegistry/Runtime helper.
8. Return selected strategy result with safe routing metadata.
```

### 18.3 Routing Decision Model

```python
@dataclass(frozen=True, slots=True)
class StrategyRoutingDecision:
    selected_strategy: str
    selected_agent: str | None = None
    confidence: float | None = None
    routing_mode: str = "rules_only"
    safe_reason: str | None = None
    fallback_used: bool = False
```

### 18.4 Router Safety Rules

- Router may choose only from configured candidate strategies.
- Router must not allow the user to directly select arbitrary strategy names.
- Router must not choose disabled strategies.
- Router must not bypass policy.
- Router must not fall back to a strategy with broader permissions after policy denial.
- Router LLM output must be validated against allowed candidates.
- Router should expose only safe routing metadata, not hidden classifier reasoning.

---

## 19. Bounded Planner Strategy

`BoundedPlannerStrategy` creates a small plan and executes it within strict limits.

It is appropriate when:

- A task requires multiple steps.
- The step count is small.
- All available actions are known and policy-filtered.
- The strategy can fail safely when the plan is invalid or exceeds limits.

V1 should keep this strategy disabled by default until direct, retrieval, and tool-assisted strategies are stable.

### 19.1 Planner Flow

```text
1. Start strategy.
2. Build allowed action set from enabled memory/tool/agent capabilities.
3. Ask planner LLM for a bounded plan or use deterministic planner.
4. Validate plan schema.
5. Reject unknown, disabled, or policy-denied actions.
6. Execute each step through step runner.
7. Stop on failure unless configured to continue safely.
8. Generate final answer.
9. Return safe plan summary and workflow-state delta.
```

### 19.2 Plan Model

```python
@dataclass(frozen=True, slots=True)
class StrategyPlan:
    plan_id: str
    steps: tuple["StrategyPlanStep", ...]
    safe_goal: str | None = None


@dataclass(frozen=True, slots=True)
class StrategyPlanStep:
    step_id: str
    action_type: str
    name: str
    inputs: dict[str, object]
    depends_on: tuple[str, ...] = ()
```

Allowed `action_type` values in V1:

```text
memory_search
tool_call
agent_invoke
llm_call
finalize
```

### 19.3 Planner Safety Rules

- Planner output is untrusted and must be schema-validated.
- Planner cannot invent tools, agents, or LLM profiles.
- Planner cannot call raw MCP tool names.
- Planner cannot exceed configured step limits.
- Planner cannot create background tasks.
- Planner cannot write workflow state directly.
- Planner cannot expose hidden planning scratchpad.
- Planner should return safe plan summaries only.

---

## 20. Memory Update Strategy

`MemoryUpdateStrategy` curates candidate long-term memories and writes approved candidates through `MemoryGateway`.

It is appropriate when:

- The user explicitly asks the assistant to remember something.
- A completed turn produces durable project facts or preferences.
- Policy allows memory writes for the current user/project/use case.

### 20.1 Flow

```text
1. Start memory update strategy or memory update phase.
2. Extract candidate memories through agent/LLM or deterministic rules.
3. Classify memory type and scope.
4. Validate candidate content and sensitivity rules.
5. Call policy hook for memory write.
6. Write approved candidates through MemoryGateway.upsert.
7. Return safe memory update summaries.
```

### 20.2 Candidate Model

```python
@dataclass(frozen=True, slots=True)
class MemoryCandidate:
    text: str
    memory_type: str
    scope: str
    importance: float | None = None
    ttl_policy: str | None = None
    reason: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)
```

### 20.3 Memory Update Rules

- Memory writes must use `MemoryGateway` only.
- Strategies must not import `memory_store.service.MemoryService`.
- Strategies must not write directly to ArcadeDB.
- Memory candidates should be bounded and explicit.
- Sensitive memory handling belongs to policy; strategy should call policy hooks or rely on `MemoryGateway` policy enforcement.
- Memory update summaries returned to API/session should not expose raw internal memory records.

---

## 21. Fallback Answer Strategy

`FallbackAnswerStrategy` provides a safe response when a primary strategy cannot complete and fallback is configured.

It is appropriate when:

- A non-critical memory search fails.
- A non-critical tool is unavailable.
- A selected strategy fails due to a retryable infrastructure issue.
- The backend can still provide a safe partial answer.

### 21.1 Fallback Flow

```text
1. Receive original request and prior failure summary.
2. Verify fallback is allowed for the use case and failure type.
3. Build safe fallback prompt input without raw error payloads.
4. Call LLM/agent if configured, or return static fallback message.
5. Mark result as fallback_used.
6. Return safe answer and failure summary.
```

### 21.2 Fallback Rules

- Do not fallback after policy denial to a less restrictive strategy.
- Do not fallback from a failed write/destructive/external-side-effect tool as if it succeeded.
- Do not hide important uncertainty from the user.
- Do not expose raw exception details.
- Do not retry unboundedly through fallback loops.

---

## 22. Reusable Strategy Steps

Strategies should share step helpers rather than duplicating gateway call patterns.

Recommended helpers:

```text
run_agent_step(...)
run_llm_step(...)
run_memory_search_step(...)
run_memory_write_step(...)
run_tool_step(...)
run_plan_step(...)
build_final_answer_step(...)
```

### 22.1 Step Runner Contract

```python
class StrategyStepRunner:
    async def run_memory_search(
        self,
        *,
        request: MemorySearchRequest,
        context: OrchestrationContext,
        guard: StrategyLimitGuard,
    ) -> "MemorySearchStepResult": ...

    async def run_tool_call(
        self,
        *,
        intent: ToolIntent,
        context: OrchestrationContext,
        guard: StrategyLimitGuard,
    ) -> "ToolStepResult": ...

    async def run_agent(
        self,
        *,
        request: AgentRunRequest,
        context: OrchestrationContext,
        guard: StrategyLimitGuard,
    ) -> "AgentStepResult": ...
```

### 22.2 Step Runner Responsibility

Step runners should handle:

- Limit checks.
- Safe trace events.
- Duration measurement.
- Error normalization.
- Result summary generation.
- Redaction.
- Stream event mapping.

Step runners should not handle:

- Session persistence.
- API response DTO mapping.
- Concrete provider calls.
- Concrete database calls.

---

## 23. Strategy Policy Integration

Strategies should call policy hooks for decisions that happen before gateway-level calls.

Recommended policy checks:

```python
await context.policy.can_run_strategy(
    user_id=request.user_id,
    session_id=request.session_id,
    usecase=request.usecase,
    strategy_name=self.name,
)

await context.policy.can_use_agent(
    user_id=request.user_id,
    usecase=request.usecase,
    strategy_name=self.name,
    agent_name=agent_name,
)

await context.policy.can_use_llm_profile(
    user_id=request.user_id,
    usecase=request.usecase,
    strategy_name=self.name,
    llm_profile=llm_profile,
)
```

Gateway-specific checks remain inside gateways:

```text
ToolGateway checks tool policy before MCP execution.
MemoryGateway checks memory read/write policy before adapter calls.
LLMGateway checks LLM profile/provider policy before provider calls.
```

### 23.1 Policy Denial Rule

When policy denies a strategy, agent, LLM profile, memory operation, or tool call:

```text
1. Stop the denied action.
2. Record safe policy-denied trace event.
3. Return normalized policy error or configured safe refusal.
4. Do not fallback to a less restrictive strategy.
5. Do not execute partial side-effect actions after denial.
```

---

## 24. Agent Integration Boundary

Strategies invoke agents, but agent internals are defined later.

Expected agent registry interface:

```python
class AgentRegistry(Protocol):
    def resolve(self, agent_name: str) -> "AgentHandle": ...
    def list(self) -> list["AgentDescriptor"]: ...
```

Expected agent handle interface:

```python
class AgentHandle(Protocol):
    name: str

    async def run(
        self,
        *,
        request: "AgentRunRequest",
        context: "OrchestrationContext",
    ) -> "AgentRunResult": ...

    async def stream(
        self,
        *,
        request: "AgentRunRequest",
        context: "OrchestrationContext",
    ) -> AsyncIterator["AgentStreamEvent"]: ...
```

### 24.1 Agent Request Shape

```python
@dataclass(frozen=True, slots=True)
class AgentRunRequest:
    message: str
    llm_profile: str | None
    context_items: tuple[PromptContextItem, ...] = ()
    tool_context: tuple[ToolContextItem, ...] = ()
    available_tools: tuple[str, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)
```

### 24.2 Agent Boundary Rules

- Strategies may select configured agents.
- Agents may call gateways only through `OrchestrationContext` if agent design allows it.
- Strategies should pass logical tool names, not MCP names.
- Strategies should pass bounded context items, not raw memory or tool objects.
- Strategies should not inspect provider-specific agent internals.

---

## 25. LLM Integration Boundary

Strategies may call `LLMGateway` directly for routing, planning, or fallback behavior, but answer generation should usually happen through an agent.

Correct:

```text
Strategy -> Agent -> LLMGateway
Strategy -> LLMGateway for router/planner classifier
```

Avoid:

```text
Strategy -> OpenAI SDK
Strategy -> LocalAI URL
Strategy -> provider-specific chat response object
```

### 25.1 LLM Call Summary

Safe summary:

```json
{
  "step_type": "llm_call",
  "llm_profile": "router_lightweight",
  "status": "completed",
  "duration_ms": 180,
  "output_kind": "routing_decision"
}
```

Unsafe summary:

```json
{
  "system_prompt": "...",
  "developer_prompt": "...",
  "raw_completion": {...},
  "api_key": "..."
}
```

---

## 26. Memory Integration Boundary

Strategies may search or write memory only through `MemoryGateway`.

Correct:

```text
RetrievalAugmentedStrategy -> MemoryGateway.search
MemoryUpdateStrategy -> MemoryGateway.upsert
```

Avoid:

```text
Strategy -> ArcadeDB
Strategy -> FastEmbed directly
Strategy -> memory_store.service.MemoryService
```

### 26.1 Memory Search Summary

```python
@dataclass(frozen=True, slots=True)
class MemorySearchSummary:
    status: str
    query_chars: int
    result_count: int
    included_count: int
    truncated: bool = False
    duration_ms: int | None = None
    metadata: dict[str, object] = field(default_factory=dict)
```

### 26.2 Memory Write Summary

```python
@dataclass(frozen=True, slots=True)
class MemoryUpdateSummary:
    status: str
    candidate_count: int
    written_count: int
    skipped_count: int
    duration_ms: int | None = None
    metadata: dict[str, object] = field(default_factory=dict)
```

---

## 27. Tool Integration Boundary

Strategies may execute tools only through `ToolGateway`.

Correct:

```text
ToolAssistedStrategy -> ToolGateway.execute(logical_tool_name)
```

Avoid:

```text
Strategy -> MCPClientAdapter
Strategy -> FastMCP client
Strategy -> raw http://localhost:9001/mcp request
Strategy -> tool credentials
```

### 27.1 Tool Call Summary

```python
@dataclass(frozen=True, slots=True)
class ToolCallSummary:
    tool_name: str
    status: str
    duration_ms: int | None = None
    result_count: int | None = None
    truncated: bool = False
    error_code: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)
```

### 27.2 Tool Failure Behavior

Recommended behavior by failure:

| Failure | Recommended Strategy Behavior |
|---|---|
| Unknown tool | Stop and return normalized strategy/tool error. |
| Disabled tool | Stop; do not ask LLM to find another raw tool. |
| Policy denied | Stop; do not fallback to less restrictive strategy. |
| Validation error | Ask agent for corrected arguments only if loop budget allows. |
| Timeout | Retry only if tool/gateway marks retryable and idempotency is safe. |
| Rate limit | Fallback only if safe partial answer is allowed. |
| Tool unavailable | Fallback if use case allows degraded answer. |
| Result too large | Ask for narrower query only if safe and within loop limits. |

---

## 28. Prompt Input and Context Assembly

This document does not define final prompt templates. It defines prompt input objects that strategies and agents can share.

Recommended prompt input model:

```python
@dataclass(frozen=True, slots=True)
class StrategyPromptInput:
    user_message: str
    session_summary: str | None = None
    context_items: tuple[PromptContextItem, ...] = ()
    tool_context: tuple[ToolContextItem, ...] = ()
    task_instructions: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)
```

### 28.1 Prompt Context Safety

Strategies should:

- Keep context bounded.
- Quote retrieved memory/tool text as data.
- Preserve source labels when helpful.
- Mark truncated context explicitly.
- Avoid including credentials or raw internal payloads.
- Avoid including hidden scratchpads.

A future `backend-prompt-context-architecture.md` can define full prompt assembly standards.

---

## 29. Workflow-State Delta Integration

Strategies return `WorkflowStateDelta` summaries to the runtime. `SessionService` persists state through `WorkflowStateStore`.

Recommended delta shape:

```python
@dataclass(frozen=True, slots=True)
class WorkflowStateDelta:
    append_messages: tuple["ConversationMessage", ...] = ()
    append_steps: tuple[WorkflowStepSummary, ...] = ()
    update_summary: str | None = None
    set_runtime_metadata: dict[str, object] = field(default_factory=dict)
    clear_pending: bool = False
```

### 29.1 Safe State Content

Allowed state content:

```text
user/assistant message text when session policy allows
safe step summaries
selected strategy name
selected agent name
memory search counts
tool call summaries
fallback flag
bounded session summary
```

Avoid state content:

```text
raw tool results
raw memory records
raw provider payloads
raw prompts
hidden scratchpads
credentials
MCP protocol objects
ArcadeDB records
SQLite row internals
```

### 29.2 Pending Approval Placeholder

V1 can represent approval-needed outcomes without implementing full approval workflow.

```python
@dataclass(frozen=True, slots=True)
class PendingApprovalSummary:
    approval_type: str
    tool_name: str | None = None
    safe_description: str | None = None
    expires_at: str | None = None
```

Approval-required strategies should not execute the action. They should return a pending approval summary or a policy-denied error until the approval workflow is implemented.

---

## 30. Streaming Strategy Behavior

Strategies that support streaming should emit normalized `StrategyStreamEvent` objects.

### 30.1 Streaming Direct Strategy

```text
strategy.started
agent.started
response.delta...
agent.completed
strategy.completed
```

### 30.2 Streaming Retrieval Strategy

```text
strategy.started
memory.search.started
memory.search.completed
agent.started
response.delta...
agent.completed
strategy.completed
```

### 30.3 Streaming Tool Strategy

```text
strategy.started
agent.started
tool.started
tool.completed
response.delta...
agent.completed
strategy.completed
```

### 30.4 Streaming Safety Rule

Stream events may include safe operational summaries, but not raw payloads.

Safe:

```json
{
  "type": "tool.completed",
  "tool_name": "documents.search",
  "status": "completed",
  "result_count": 5,
  "duration_ms": 180
}
```

Unsafe:

```json
{
  "raw_mcp_response": {...},
  "authorization": "Bearer ...",
  "full_document_text": "..."
}
```

---

## 31. Cancellation Behavior

Strategies must cooperate with runtime cancellation.

Cancellation flow:

```text
1. API detects client disconnect or runtime receives cancellation.
2. SessionService cancels runtime stream task.
3. Runtime cancels active strategy task.
4. Strategy cancels active gateway/agent call if supported.
5. Strategy emits or records safe cancellation event.
6. Runtime returns cancellation summary.
7. SessionService decides whether to persist cancellation checkpoint.
```

### 31.1 Cancellation Rules

- Do not start new steps after cancellation.
- Do not continue tool loops after cancellation.
- Do not persist state directly from strategy.
- Do not emit further stream events after cancellation is acknowledged.
- Side-effect tool cancellation must respect tool gateway semantics; do not assume downstream side effects were rolled back.

---

## 32. Fallback and Recovery Behavior

Fallback behavior must be explicit and safe.

### 32.1 Fallback Decision Inputs

```python
@dataclass(frozen=True, slots=True)
class FallbackDecisionInput:
    usecase: str
    failed_strategy: str
    error_code: str
    retryable: bool
    side_effect_may_have_started: bool = False
    policy_denied: bool = False
```

### 32.2 Fallback Decision Rules

Allow fallback when:

```text
failure is retryable or degradable
no side-effect action may have partially succeeded
fallback is configured for the use case
fallback does not broaden permissions
policy allows fallback
```

Deny fallback when:

```text
primary failure was policy denied
side effect may have partially executed
fallback requires broader tool/memory/LLM permissions
fallback would hide a data integrity problem
fallback would loop back to the same failed strategy indefinitely
```

---

## 33. Error Model

Recommended strategy errors:

```python
class StrategyError(Exception):
    code: str
    retryable: bool


class StrategyNotFoundError(StrategyError): ...
class StrategyDisabledError(StrategyError): ...
class StrategyPolicyDeniedError(StrategyError): ...
class StrategyLimitExceededError(StrategyError): ...
class StrategyConfigurationError(StrategyError): ...
class AgentResolutionError(StrategyError): ...
class StrategyRoutingError(StrategyError): ...
class StrategyPlanValidationError(StrategyError): ...
class StrategyToolIntentError(StrategyError): ...
class StrategyMemoryError(StrategyError): ...
class StrategyToolError(StrategyError): ...
class StrategyLLMError(StrategyError): ...
class StrategyCancelledError(StrategyError): ...
class StrategyFallbackNotAllowedError(StrategyError): ...
```

### 33.1 Error Mapping

| Error | Retryable | Notes |
|---|---:|---|
| `StrategyNotFoundError` | false | Config or routing bug. |
| `StrategyDisabledError` | false | Strategy not enabled. |
| `StrategyPolicyDeniedError` | false | Must not fallback to weaker policy. |
| `StrategyLimitExceededError` | false | Stop loops. |
| `StrategyConfigurationError` | false | Startup validation should catch most cases. |
| `AgentResolutionError` | false | Missing agent or disabled agent. |
| `StrategyRoutingError` | false/true | Depends on cause. |
| `StrategyPlanValidationError` | false | Planner output invalid. |
| `StrategyToolIntentError` | false | Invalid or unsafe tool intent. |
| `StrategyMemoryError` | true/false | Depends on gateway error. |
| `StrategyToolError` | true/false | Depends on gateway error and side effects. |
| `StrategyLLMError` | true/false | Depends on LLM gateway error. |
| `StrategyCancelledError` | false | Normal cancellation path. |
| `StrategyFallbackNotAllowedError` | false | Return safe error. |

### 33.2 Error Safety Rule

Strategy errors must not expose:

- Raw stack traces.
- Raw provider errors.
- Raw MCP errors.
- Raw memory adapter errors.
- Raw SQL errors.
- Credentials.
- Raw prompt/completion payloads.
- Hidden scratchpads.

---

## 34. Observability and Trace Integration

Strategies emit safe trace events through the observability facade.

Recommended events:

| Event | Emitted By | Notes |
|---|---|---|
| `strategy_started` | Runtime/strategy | Strategy name, use case, trace ID. |
| `strategy_completed` | Strategy | Status, duration, step counts. |
| `strategy_failed` | Strategy | Safe error code/type. |
| `strategy_cancelled` | Strategy/runtime | Cancellation summary. |
| `strategy_step_started` | Step runner | Step type/name only. |
| `strategy_step_completed` | Step runner | Duration/status/summary. |
| `strategy_step_failed` | Step runner | Safe error code. |
| `strategy_routing_decision` | Router | Selected configured strategy, safe confidence. |
| `strategy_fallback_used` | Fallback helper | From/to strategy and safe reason. |
| `strategy_limit_exceeded` | Limit guard | Limit type and configured value. |
| `strategy_plan_created` | Planner | Step count only, no raw scratchpad. |
| `strategy_memory_context_built` | Retrieval helper | Included item count and bytes. |
| `strategy_tool_intent_created` | Tool helper | Logical tool name only. |

### 34.1 Safe Trace Payload Example

```json
{
  "event_name": "strategy_completed",
  "trace_id": "trace_...",
  "payload": {
    "strategy_name": "retrieval_augmented",
    "usecase": "document_qa",
    "status": "completed",
    "duration_ms": 1240,
    "step_count": 3,
    "llm_calls": 1,
    "memory_searches": 1,
    "tool_calls": 0,
    "fallback_used": false
  }
}
```

### 34.2 Unsafe Trace Payload Example

```json
{
  "raw_prompt": "...",
  "raw_llm_response": {...},
  "raw_memory_records": [...],
  "raw_tool_response": {...},
  "authorization": "Bearer ..."
}
```

### 34.3 Metrics

Recommended metrics:

```text
backend.orchestration.strategy.runs.total
backend.orchestration.strategy.duration_ms
backend.orchestration.strategy.failures.total
backend.orchestration.strategy.fallbacks.total
backend.orchestration.strategy.steps.total
backend.orchestration.strategy.limit_exceeded.total
backend.orchestration.strategy.routing.total
backend.orchestration.strategy.streams.total
backend.orchestration.strategy.cancellations.total
```

Allowed metric tags:

```text
strategy_name
strategy_type
usecase
status
error_type
fallback_used
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
provider URL
API keys
```

---

## 35. Health Integration

Strategies should expose safe health and readiness status.

Recommended result:

```python
@dataclass(frozen=True, slots=True)
class StrategyHealthResult:
    strategy_name: str
    strategy_type: str
    status: str
    enabled: bool
    configured_agent: str | None = None
    configured_llm_profile: str | None = None
    memory_required: bool = False
    tools_required: bool = False
    metadata: dict[str, object] = field(default_factory=dict)
```

### 35.1 Health Rules

Health may include:

```text
strategy enabled/disabled status
configured agent name
configured LLM profile name
whether memory/tool gateways are required
last config validation status
```

Health must not include:

```text
raw prompts
provider API keys
MCP endpoints or credentials
memory database paths
raw tool schemas if sensitive
policy internals
```

---

## 36. Capabilities Integration

Capabilities should expose frontend-safe strategy/use-case metadata only.

Recommended capability section:

```json
{
  "orchestration": {
    "enabled": true,
    "default_usecase": "default",
    "usecases": [
      {
        "name": "default",
        "display_name": "Default Assistant",
        "strategy_type": "direct_agent",
        "streaming_supported": true
      },
      {
        "name": "document_qa",
        "display_name": "Document Q&A",
        "strategy_type": "retrieval_augmented",
        "streaming_supported": true
      }
    ]
  }
}
```

### 36.1 Capability Safety Rule

Expose:

```text
safe use-case names
display names
strategy type labels
streaming support
feature flags
```

Do not expose:

```text
internal prompts
policy rules
raw tool allowlists if sensitive
provider URLs
credentials
memory store internals
MCP endpoint
```

---

## 37. Composition Root Integration

The composition root builds configured strategies after gateways and agent registry are available.

Recommended startup sequence:

```text
1. Load settings and YAML configuration.
2. Build observability/redactor/metrics.
3. Build policy service.
4. Build LLMGateway.
5. Build MemoryGateway.
6. Build ToolGateway.
7. Build AgentRegistry with available agent handles or fakes.
8. Validate strategy settings.
9. Build StrategyFactory.
10. Instantiate configured strategies.
11. Register strategies in StrategyRegistry.
12. Build OrchestrationRuntime with StrategyRegistry.
13. Build SessionService with OrchestrationRuntime.
14. Build API app.
15. Log redacted strategy startup summary.
```

### 37.1 Composition Example

```python
def build_strategy_registry(config, gateways, agents, policy, observability) -> StrategyRegistry:
    factory = StrategyFactory(
        config=config.orchestration,
        llm=gateways.llm,
        memory=gateways.memory,
        tools=gateways.tools,
        agents=agents,
        policy=policy,
        observability=observability,
    )

    registry = DefaultStrategyRegistry()
    for strategy_settings in config.orchestration.strategies.values():
        if strategy_settings.enabled:
            registry.register(factory.build(strategy_settings))

    return registry
```

### 37.2 Redacted Startup Summary

Safe:

```json
{
  "event": "strategies_configured",
  "strategies_enabled": 4,
  "strategy_types": ["direct_agent", "retrieval_augmented", "tool_assisted", "fallback_answer"],
  "usecases_configured": 3
}
```

Unsafe:

```json
{
  "raw_prompts": {...},
  "provider_api_key": "...",
  "mcp_endpoint": "...",
  "oauth_token": "..."
}
```

---

## 38. Testing Strategy

### 38.1 Unit Tests

| Test | Purpose |
|---|---|
| Strategy settings validate | Proves config safety. |
| Missing strategy fails config | Prevents runtime surprises. |
| Direct strategy calls agent once | Proves minimal flow. |
| Direct strategy does not call tools | Enforces boundary. |
| Retrieval strategy calls MemoryGateway | Proves memory boundary. |
| Retrieval context is bounded | Prevents prompt bloat. |
| Retrieval no-results path works | Proves graceful degradation. |
| Tool strategy validates logical tool intent | Prevents raw MCP bypass. |
| Tool strategy respects tool loop limit | Prevents unbounded loops. |
| Tool strategy handles validation error | Proves repair/fail behavior. |
| Router chooses only allowed candidates | Prevents arbitrary strategy selection. |
| Router rejects disabled strategy | Enforces config. |
| Planner validates plan schema | Prevents LLM planner injection. |
| Planner rejects unknown action | Prevents arbitrary execution. |
| Memory update calls MemoryGateway only | Enforces adapter boundary. |
| Fallback denied after policy denial | Prevents policy weakening. |
| Strategy limit exceeded normalizes error | Proves limit guard. |
| Strategy stream events are safe | Prevents raw payload streaming. |
| Trace events are redacted | Proves privacy behavior. |
| Cancellation stops further steps | Proves cancellation behavior. |

### 38.2 Integration Tests

| Test | Purpose |
|---|---|
| Runtime resolves direct strategy | Proves registry integration. |
| SessionService runs direct strategy through runtime | Proves API/session unchanged. |
| Retrieval strategy uses fake memory gateway | Proves gateway boundary. |
| Tool strategy uses fake tool gateway | Proves MCP-neutral flow. |
| Router delegates to retrieval strategy | Proves composed strategy execution. |
| Strategy result becomes orchestration result | Proves result mapping. |
| Strategy state delta persists through SessionService | Proves state handoff. |
| Streaming direct strategy reaches SSE via session/API | Proves stream chain. |
| Tool stream summaries are safe | Proves frontend safety. |
| Fallback strategy produces safe answer | Proves recovery path. |
| Policy denial blocks strategy execution | Proves policy integration. |
| No strategy imports infrastructure adapters | Proves dependency boundary. |

### 38.3 Dependency Boundary Tests

Add import-boundary tests to prevent drift:

```text
orchestration/strategies must not import app/api
orchestration/strategies must not import app/session
orchestration/strategies must not import sqlite3
orchestration/strategies must not import memory_store
orchestration/strategies must not import ArcadeDB clients
orchestration/strategies must not import MCP client implementations
orchestration/strategies must not import provider SDKs
```

### 38.4 Fixture Configs

Recommended fixtures:

```text
tests/fixtures/config/strategies_direct_basic.yaml
tests/fixtures/config/strategies_retrieval_basic.yaml
tests/fixtures/config/strategies_tool_basic.yaml
tests/fixtures/config/strategies_router_rules.yaml
tests/fixtures/config/strategies_router_llm.yaml
tests/fixtures/config/strategies_planner_disabled.yaml
tests/fixtures/config/strategies_memory_update.yaml
tests/fixtures/config/strategies_fallback.yaml
tests/fixtures/config/strategies_invalid_missing_agent.yaml
tests/fixtures/config/strategies_invalid_missing_strategy.yaml
tests/fixtures/config/strategies_invalid_unbounded_planner.yaml
tests/fixtures/config/strategies_invalid_raw_mcp_tool.yaml
```

---

## 39. Recommended Implementation Order

### Step 1: Add Strategy Config Models

Deliverables:

- `StrategySettings`
- `StrategyLimitSettings`
- `StrategyMemorySettings`
- `StrategyToolSettings`
- `UsecaseStrategySettings`
- validation for strategy/use-case references

Success criteria:

- Valid strategy fixtures load.
- Missing strategy/use-case references fail fast.
- Unbounded planner config fails fast.

### Step 2: Add Strategy Base Contracts

Deliverables:

- `OrchestrationStrategy` protocol
- `StrategyRunResult`
- `StrategyStreamEvent`
- `WorkflowStepSummary`
- strategy error types

Success criteria:

- Fake strategy implements the protocol.
- Runtime can call fake strategy without real gateways.

### Step 3: Add Strategy Limits and Step Runner

Deliverables:

- `StrategyLimitGuard`
- reusable `StrategyStepRunner`
- safe step summary helpers
- trace helper functions

Success criteria:

- Limit exceeded produces normalized error.
- Step summaries are safe and bounded.

### Step 4: Add Direct Agent Strategy

Deliverables:

- `DirectAgentStrategy`
- agent resolution
- agent/LLM step summary
- non-streaming and streaming support

Success criteria:

- Direct strategy returns answer with fake agent.
- No memory/tool calls occur.

### Step 5: Add Retrieval-Augmented Strategy

Deliverables:

- `RetrievalAugmentedStrategy`
- memory search step
- context bounding
- no-results behavior
- safe memory search summary

Success criteria:

- Fake memory results are included as bounded prompt context.
- Raw memory records are not returned or traced.

### Step 6: Add Tool-Assisted Strategy

Deliverables:

- `ToolIntent`
- tool intent validation
- tool loop guard
- `ToolGateway.execute` step
- safe tool result context

Success criteria:

- Fake tool call runs through `ToolGateway`.
- Raw MCP names are rejected.
- Tool loop limit is enforced.

### Step 7: Add Fallback Answer Strategy

Deliverables:

- `FallbackAnswerStrategy`
- fallback decision helper
- safe fallback metadata

Success criteria:

- Fallback works for configured degradable errors.
- Fallback is denied after policy denial.

### Step 8: Add Router Strategy

Deliverables:

- `RouterStrategy`
- rules-only routing
- optional LLM classifier routing through `LLMGateway`
- candidate validation
- safe routing summaries

Success criteria:

- Router selects only configured candidates.
- LLM classifier output cannot choose unknown strategies.

### Step 9: Add Memory Update Strategy

Deliverables:

- memory candidate model
- memory write step through `MemoryGateway`
- policy hook integration
- safe memory update summaries

Success criteria:

- Candidate writes go through `MemoryGateway` only.
- Policy denial blocks memory writes.

### Step 10: Add Bounded Planner Strategy

Deliverables:

- plan schema
- planner validation
- bounded executor
- safe plan summary

Success criteria:

- Unknown actions are rejected.
- Step limits are enforced.
- Planner remains disabled by default unless explicitly enabled.

### Step 11: Add Health and Capabilities

Deliverables:

- strategy health results
- safe strategy capability summaries
- use-case capability output

Success criteria:

- Health reports configured strategy readiness.
- Capabilities do not expose prompts, credentials, endpoints, or policy internals.

### Step 12: Wire Into Runtime

Deliverables:

- `StrategyFactory`
- `StrategyRegistry` registration
- runtime uses configured strategy instances
- session/API contracts remain unchanged

Success criteria:

- `/chat` can run direct/retrieval/tool strategies through runtime.
- `/chat/stream` can stream safe strategy events.
- API and session layers do not import concrete strategies directly.

---

## 40. Acceptance Criteria

This architecture is complete when:

- `backend-workflow-strategies-architecture.md` deepens the strategy contract established by `backend-orchestration-architecture.md` without changing API or session boundaries.
- Strategy settings are configuration-driven and validated at startup.
- `StrategyRegistry` can register, list, and resolve configured strategies.
- `StrategyFactory` can build enabled strategies from typed settings.
- `DirectAgentStrategy` can run without memory or tools.
- `RetrievalAugmentedStrategy` calls memory only through `MemoryGateway`.
- `ToolAssistedStrategy` calls tools only through `ToolGateway`.
- `RouterStrategy` selects only configured and policy-allowed candidate strategies.
- `BoundedPlannerStrategy` validates plan schema and enforces strict step limits before execution.
- `MemoryUpdateStrategy` writes memory only through `MemoryGateway` and policy hooks.
- `FallbackAnswerStrategy` provides safe fallback only when configured and allowed.
- Strategies do not import API routes, session services, SQLite, ArcadeDB clients, `memory_store`, MCP clients, FastMCP clients, provider SDKs, or frontend DTOs.
- Strategies invoke agents through an agent registry/agent handle abstraction.
- Strategies call LLMs only through `LLMGateway`.
- Strategies search/write memory only through `MemoryGateway`.
- Strategies execute tools only through `ToolGateway`.
- Strategy outputs normalize into `StrategyRunResult` and `StrategyStreamEvent` objects.
- Strategy results contain safe workflow step summaries.
- Strategy results contain safe workflow-state deltas for `SessionService` to persist.
- Strategies do not persist workflow state directly.
- Strategies enforce max steps, max LLM calls, max memory searches, max memory writes, max tool calls, max tool loop iterations, max context bytes, and max duration.
- Strategies support cancellation and stop starting new work after cancellation.
- Strategy stream events are safe for session/API/SSE mapping.
- Raw prompts, raw provider responses, raw tool payloads, raw memory records, raw workflow state documents, credentials, hidden chain-of-thought, planning scratchpads, and stack traces are not returned, streamed, logged, traced, or persisted by default.
- Tool outputs and memory outputs are treated as untrusted data.
- Fallbacks never weaken policy restrictions.
- Policy denial prevents strategy execution or strategy actions.
- Health reports safe strategy readiness.
- Capabilities expose only frontend-safe strategy/use-case metadata.
- Unit tests run with fake strategies, fake agents, fake LLM, fake memory, fake tools, and fake policy.
- Integration tests verify `API -> SessionService -> OrchestrationRuntime -> WorkflowStrategy -> Gateways` without changing API contracts.
- The backend is ready for the next document: `backend-agents-architecture.md`.

---

## 41. Anti-Patterns to Avoid

Avoid these during implementation:

- Calling LLM provider SDKs directly from strategies.
- Calling MCP server directly from strategies.
- Calling `MCPClientAdapter` directly from strategies.
- Searching ArcadeDB directly from strategies.
- Importing `memory_store.service.MemoryService` in strategies.
- Running SQL from strategies.
- Letting strategies persist workflow state directly.
- Letting API routes choose concrete strategies.
- Letting `SessionService` bypass `OrchestrationRuntime` to call strategies directly.
- Letting user metadata directly choose arbitrary strategy, agent, LLM profile, or MCP tool.
- Letting LLM output bypass tool-intent validation.
- Letting provider-native tool calls execute outside `ToolGateway`.
- Returning raw workflow state from strategy results.
- Storing raw tool results in workflow state.
- Storing raw memory records in workflow state.
- Streaming raw provider chunks directly to API.
- Tracing raw prompts or hidden scratchpads by default.
- Exposing hidden chain-of-thought.
- Treating memory/tool text as trusted instructions.
- Creating unbounded LLM-tool loops.
- Retrying external-side-effect tool actions blindly.
- Falling back to a less restricted strategy after policy denial.
- Making router strategy a hidden service locator for infrastructure clients.
- Enabling planner strategy without strict step/action limits.
- Allowing planner to invent tool names, agent names, or LLM profiles.
- Exposing detailed routing/planning scratchpads in capabilities, traces, or API metadata.

---

## 42. Future Documents That Depend on This Strategy Layer

| Future Document | Dependency |
|---|---|
| `backend-agents-architecture.md` | Agents are invoked by strategies through agent handles and `OrchestrationContext`. |
| `backend-policy-architecture.md` | Defines final strategy, agent, LLM, memory, tool, fallback, approval, trace capture, and data exposure policy. |
| `backend-approval-workflow-architecture.md` | Defines pending approval state, resume behavior, and approved tool execution for strategy flows. |
| `backend-prompt-context-architecture.md` | Defines prompt assembly, memory/tool context quoting, and prompt-injection handling. |
| `backend-evaluation-architecture.md` | Evaluates strategy selection, retrieval quality, tool correctness, fallback behavior, and answer quality. |
| `backend-deployment-architecture.md` | Defines environment-specific strategy enablement and gateway availability. |
| `backend-hardening-architecture.md` | Defines production limits, auth, privacy controls, rate limits, and security review gates. |

---

## 43. Summary

`backend-workflow-strategies-architecture.md` defines the concrete strategy layer that sits inside the orchestration runtime and shapes each user turn.

It preserves the previously defined boundaries: API remains thin, `SessionService` owns session lifecycle and state persistence, `OrchestrationRuntime` owns turn lifecycle and strategy resolution, `LLMGateway` owns model access, `MemoryGateway` owns memory/document access, `ToolGateway` owns tool execution, and `MCPClientAdapter` remains the only backend component that speaks MCP protocol.

The most important implementation rule is:

> **Strategies decide workflow shape, not infrastructure access. A strategy may route, retrieve, call agents, request tools, plan bounded steps, and build safe state summaries, but every external capability must go through provider-neutral gateways and every result must be bounded, policy-aware, trace-correlated, and safe for session/API handoff.**
