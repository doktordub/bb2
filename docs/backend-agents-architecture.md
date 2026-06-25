# Backend Agents Architecture

**Document:** `backend-agents-architecture.md`  
**Version:** 1.0  
**Source alignment:** `backend-application-architecture.md`, `backend-foundation-architecture.md`, `backend-core-contracts-architecture.md`, `backend-configuration-architecture.md`, `backend-observability-architecture.md`, `backend-persistence-architecture.md`, `backend-sqlite-workflow-state-architecture.md`, `backend-sqlite-trace-store-architecture.md`, `backend-api-architecture.md`, `backend-session-service-architecture.md`, `backend-llm-gateway-architecture.md`, `backend-memory-store-adapter-architecture.md`, `backend-tooling-mcp-client-architecture.md`, `backend-orchestration-architecture.md`, and `backend-workflow-strategies-architecture.md`  
**Scope:** Agent plugin interface, agent registry, agent descriptors, agent configuration, agent capability model, prompt-input boundaries, LLM usage, memory usage, tool-intent behavior, memory-candidate behavior, streaming, policy hooks, trace correlation, health/capabilities exposure, testing strategy, and acceptance criteria for the V1 agent layer.

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
14. `backend-workflow-strategies-architecture.md`
15. `backend-agents-architecture.md` ← this document

The previous document established that workflow strategies own the shape of a turn. Strategies decide when to retrieve memory, when to request tools, when to route, when to plan bounded steps, when to fall back, and when to ask an agent for task-specific work.

This document defines the agent layer that strategies invoke.

The goal is to make agents easy to add, configure, test, and constrain without changing API routes, session behavior, orchestration runtime internals, LLM providers, memory adapters, tool adapters, or MCP protocol code.

The core architecture rule is:

> **Agents own task-specific behavior, not infrastructure access. Agents may use controlled capabilities exposed through `OrchestrationContext`, but they must not import concrete LLM providers, MCP clients, SQLite clients, ArcadeDB clients, `memory_store`, external API clients, frontend DTOs, or provider-specific response objects.**

---

## 2. Source Architecture Alignment

This document follows the established backend rules:

- The backend remains one deployable application tier in V1.
- Frontend communicates with backend through REST / SSE.
- API routes remain thin and call `SessionService`.
- `SessionService` owns session lifecycle, workflow-state load/save/reset, and request-to-runtime handoff.
- `OrchestrationRuntime` owns turn lifecycle, context construction, strategy resolution, cancellation, and normalized runtime results.
- Workflow strategies own turn shape and decide which agent to invoke.
- Agents own task-specific work within the constraints provided by a strategy.
- Agent instances are resolved through `AgentRegistry`.
- Agent configuration is YAML-driven.
- LLM access remains behind `LLMGateway`.
- Memory/document access remains behind `MemoryGateway`.
- Tool execution remains behind `ToolGateway`.
- MCP protocol communication remains behind `MCPClientAdapter`.
- SQLite workflow state remains behind `WorkflowStateStore`.
- SQLite traces remain behind `TraceStore` or an observability facade.
- ArcadeDB-backed memory remains hidden behind the `memory_store` wrapper and backend `MemoryGateway`.
- Agents must not persist workflow state directly.
- Agents must not return, stream, log, trace, or persist raw prompts, raw provider responses, raw MCP payloads, raw memory records, raw workflow state documents, credentials, hidden scratchpads, or stack traces by default.
- Agent decisions and calls must be trace-correlated with the active `trace_id`.

---

## 3. Refined Position in the Backend Implementation Sequence

The previous document expanded Phase 14 into concrete workflow strategies. This document expands Phase 15.

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

The output of this phase is an agent layer that supports:

```text
AgentPlugin.run(...)
AgentPlugin.stream(...)
AgentRegistry.register(...)
AgentRegistry.resolve(...)
AgentRegistry.list(...)
AgentFactory.build(...)
AgentPolicyGuard.check(...)
AgentPromptBuilder.build(...)
AgentResultBuilder.build(...)
AgentHealth.check(...)
```

The next document should be:

```text
backend-policy-architecture.md
```

---

## 4. Architecture Goals

The agent layer should be:

1. **Strategy-compatible**  
   Agents are invoked by workflow strategies through a narrow `AgentHandle` / `AgentPlugin` contract.

2. **Gateway-only**  
   Agents use LLMs, memory, and tools only through `OrchestrationContext` and provider-neutral gateway interfaces.

3. **Configuration-driven**  
   Agent enablement, LLM profile, capability grants, allowed tools, memory behavior, prompt settings, and stream behavior are configured through YAML.

4. **Capability-scoped**  
   Each agent declares what it can do. Strategies and policy decide what it may do for a specific turn.

5. **Task-specific**  
   Agents encapsulate domain behavior such as general assistance, document Q&A, tool-using project work, memory curation, and review/critique.

6. **Prompt-safe**  
   Agents build prompts from bounded prompt-input objects and do not expose hidden scratchpads or raw internal instructions.

7. **Tool-safe**  
   V1 agents should produce logical `ToolIntent` objects when tool use is needed unless explicitly configured for controlled self-managed tool calls.

8. **Memory-safe**  
   V1 agents should consume bounded memory context and produce memory candidates when needed. Direct memory writes are allowed only through `MemoryGateway` and policy-controlled settings.

9. **Streaming-capable**  
   Agents can stream normalized `AgentStreamEvent` objects that strategies map to safe `StrategyStreamEvent` objects.

10. **Traceable**  
    Agent selection, start, completion, failures, LLM calls, tool-intent generation, memory-candidate generation, and policy denials are trace-correlated.

11. **Testable**  
    Agents can be tested with fake LLM, fake memory, fake tools, fake policy, and fake observability without SQLite, ArcadeDB, MCP, or external LLM providers.

12. **Replaceable**  
    New agents can be added or swapped through configuration without changing API routes or session service behavior.

---

## 5. Non-Goals

This document does not implement:

- API route behavior.
- Session lifecycle rules.
- Workflow strategy internals.
- SQLite workflow-state persistence.
- SQLite trace-store persistence.
- Concrete LLM provider SDK integrations.
- Concrete ArcadeDB or `memory_store` implementation.
- MCP protocol details.
- MCP server implementation.
- Full production policy engine.
- Human approval UI.
- Full prompt-template library.
- Full prompt-injection defense specification.
- Model evaluation dashboards.
- Distributed agent execution.
- Multi-agent durable workflow engine.
- Autonomous background workers.
- Unbounded planning or recursive agent spawning.

Those concerns belong to API, session, orchestration, strategies, persistence, LLM, memory, tooling, MCP, policy, approval, prompt-context, evaluation, deployment, and hardening documents.

---

## 6. Agent Boundary

Agents sit below workflow strategies and inside the orchestration runtime boundary.

Agents own:

- Task-specific behavior.
- Prompt-input interpretation.
- Agent-specific prompt construction.
- Agent-specific LLM request construction.
- Agent-specific output parsing.
- Agent-specific safe answer generation.
- Tool-intent generation when the strategy delegates tool reasoning to the agent.
- Memory-candidate generation when the strategy delegates memory curation to the agent.
- Safe agent-level stream events.
- Safe agent-level trace summaries.

Agents do not own:

- HTTP request parsing.
- Session creation, reset, or persistence.
- Strategy selection.
- Workflow-state persistence.
- SQLite reads/writes.
- ArcadeDB reads/writes.
- MCP protocol communication.
- Provider SDK calls.
- Credential handling.
- Global policy decisions.
- Raw frontend response formatting.

### 6.1 Boundary Diagram

```text
API
  -> SessionService
      -> OrchestrationRuntime
          -> WorkflowStrategy
              -> AgentRegistry.resolve(...)
              -> AgentHandle.run(...)
                  -> LLMGateway through OrchestrationContext
                  -> optional MemoryGateway through OrchestrationContext
                  -> optional ToolGateway through OrchestrationContext
                  -> PolicyService through OrchestrationContext
                  -> Observability facade through OrchestrationContext
          -> OrchestrationResult / OrchestrationStreamEvent
      -> WorkflowStateStore.save(...)
```

### 6.2 Practical Rule

Agents should do this:

```python
llm_response = await context.llm.complete(
    request=LLMCompletionRequest(
        profile=request.llm_profile,
        messages=prompt_messages,
        metadata={"agent_name": self.name},
    ),
    context=context.request,
)
```

Agents should not do this:

```python
from openai import AsyncOpenAI
from memory_store.service import MemoryService
from fastmcp import Client
import sqlite3

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
mem = MemoryService(...)
conn = sqlite3.connect("workflow_state.db")
```

---

## 7. Agent Execution Modes

V1 should support two agent execution modes, but default to the safer strategy-managed mode.

### 7.1 Strategy-Managed Agents

In this mode, the strategy owns memory search, tool execution, loop control, fallback, and state delta construction.

The agent receives:

```text
user message
safe session summary
bounded memory/document context
bounded tool result context
available logical tool names
strategy constraints
agent configuration
```

The agent returns:

```text
answer
optional tool intents
optional memory candidates
optional review findings
safe metadata
safe stream events
```

Recommended V1 default:

```text
direct_agent strategy -> general_assistant_agent -> LLM answer
retrieval_augmented strategy -> document_qa_agent -> LLM answer using bounded context
tool_assisted strategy -> tool_using_agent -> ToolIntent, then final answer
memory_update strategy -> memory_curator_agent -> MemoryCandidate objects
```

### 7.2 Controlled Self-Managed Agents

In this mode, an agent may directly call `context.memory`, `context.tools`, or multiple `context.llm` calls when all of the following are true:

```text
agent capability allows it
strategy permits delegation for this turn
policy allows it
limits are enforced
calls still go through gateways
trace events are emitted
results are normalized and redacted
```

Controlled self-managed agents are useful later for specialized agents, but V1 should avoid them unless there is a clear need.

### 7.3 Execution Mode Rule

Default to:

```text
Strategy manages workflow shape.
Agent manages task-specific language and structured outputs.
Gateway manages infrastructure access.
Policy manages permission.
Runtime manages lifecycle.
SessionService manages persistence handoff.
```

---

## 8. Recommended Package Layout

Recommended implementation layout:

```text
backend/
  app/
    agents/
      __init__.py
      base.py
      registry.py
      factory.py
      config.py
      models.py
      capabilities.py
      errors.py
      health.py
      prompts.py
      result_builder.py
      stream_mapping.py
      policy.py
      trace_helpers.py

      plugins/
        __init__.py
        general_assistant.py
        document_qa.py
        tool_using.py
        project_agent.py
        memory_curator.py
        reviewer.py
        base_llm_agent.py

    orchestration/
      context.py
      prompt_inputs.py
      tool_intents.py
      memory_intents.py
      strategy.py
      strategies/
        direct_agent.py
        retrieval_augmented.py
        tool_assisted.py
        memory_update.py
        router.py
        bounded_planner.py

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
        fake_agent.py
        fake_agent_registry.py
        fake_llm_gateway.py
        fake_memory_gateway.py
        fake_tool_gateway.py
        fake_policy_service.py
```

### 8.1 Module Responsibilities

| Module | Responsibility |
|---|---|
| `agents/base.py` | Public agent protocol/base interface. |
| `agents/registry.py` | Register, list, resolve, and validate agent handles. |
| `agents/factory.py` | Build configured agent instances from typed settings. |
| `agents/config.py` | Typed YAML-backed agent configuration models. |
| `agents/models.py` | Agent request/result/descriptor/stream models. |
| `agents/capabilities.py` | Capability declarations and capability validation. |
| `agents/errors.py` | Agent-specific normalized error taxonomy. |
| `agents/health.py` | Safe health reporting for configured agents. |
| `agents/prompts.py` | Agent-local prompt builders that consume safe prompt inputs. |
| `agents/result_builder.py` | Output normalization and structured result parsing. |
| `agents/stream_mapping.py` | Maps LLM/gateway stream chunks into safe agent events. |
| `agents/policy.py` | Agent-level policy guard helpers. |
| `agents/trace_helpers.py` | Safe agent trace event helpers. |
| `agents/plugins/general_assistant.py` | General assistant behavior. |
| `agents/plugins/document_qa.py` | Answers using bounded retrieved context. |
| `agents/plugins/tool_using.py` | Produces logical tool intents and final answers. |
| `agents/plugins/project_agent.py` | Project-focused agent using allowed project/document tools. |
| `agents/plugins/memory_curator.py` | Extracts and validates memory candidates. |
| `agents/plugins/reviewer.py` | Reviews answers, plans, or outputs against criteria. |
| `agents/plugins/base_llm_agent.py` | Shared LLM-agent helper for prompt construction and output parsing. |

---

## 9. Dependency Direction Rules

Allowed:

```text
app/agents/* -> app/agents/models.py
app/agents/* -> app/agents/capabilities.py
app/agents/* -> app/orchestration/context.py through protocol
app/agents/* -> app/orchestration/prompt_inputs.py
app/agents/* -> app/orchestration/tool_intents.py
app/agents/* -> app/orchestration/memory_intents.py
app/agents/* -> app/llm/gateway.py through protocol
app/agents/* -> app/memory/gateway.py through protocol, only when allowed
app/agents/* -> app/tools/gateway.py through protocol, only when allowed
app/agents/* -> app/policy/service.py through protocol
app/agents/* -> app/observability/* through facade
```

Avoid:

```text
app/agents/* -> app/api/*
app/agents/* -> app/session/*
app/agents/* -> sqlite3
app/agents/* -> memory_store.service.MemoryService
app/agents/* -> ArcadeDB client
app/agents/* -> MCP client libraries
app/agents/* -> FastMCP client
app/agents/* -> provider SDKs
app/agents/* -> external HTTP clients for tool APIs
app/agents/* -> FastAPI response models
app/agents/* -> frontend DTOs
```

### 9.1 Agent-to-Gateway Rule

Correct:

```text
Agent -> LLMGateway
Agent -> MemoryGateway only when allowed
Agent -> ToolGateway only when allowed
```

Avoid:

```text
Agent -> OpenAI SDK
Agent -> Google SDK
Agent -> LocalAI HTTP URL
Agent -> memory_store.service.MemoryService
Agent -> ArcadeDB
Agent -> MCPClientAdapter
Agent -> MCP server URL
Agent -> raw external API endpoint
```

### 9.2 Agent-to-State Rule

Correct:

```text
Agent -> AgentRunResult
Strategy -> WorkflowStateDelta
Runtime -> OrchestrationResult
SessionService -> WorkflowStateStore.save(...)
```

Avoid:

```text
Agent -> WorkflowStateStore.save(...)
Agent -> sqlite3.connect(...)
Agent -> direct workflow_state.db update
Agent -> direct trace.db update
```

---

## 10. Agent Configuration Integration

Agent settings should be resolved by the configuration loader before runtime composition.

Recommended YAML:

```yaml
agents:
  defaults:
    enabled: true
    stream_llm_deltas: true
    expose_agent_metadata: true
    max_prompt_context_bytes: 32000
    max_output_chars: 12000
    max_tool_intents: 3
    max_memory_candidates: 5
    allow_self_managed_tools: false
    allow_self_managed_memory: false
    allow_memory_write: false

  plugins:
    general_assistant_agent:
      enabled: true
      type: general_assistant
      display_name: General Assistant
      description: General purpose assistant for direct answers.
      llm_profile: default_reasoning
      capabilities:
        answer: true
        stream: true
        memory_read: false
        memory_write: false
        tool_intents: false
        tool_execute: false
      prompt_profile: general_assistant_v1

    document_qa_agent:
      enabled: true
      type: document_qa
      display_name: Document Q&A Agent
      description: Answers questions using bounded retrieved memory and document chunks.
      llm_profile: research_reasoning
      capabilities:
        answer: true
        stream: true
        memory_read: true
        memory_write: false
        tool_intents: false
        tool_execute: false
      prompt_profile: document_qa_v1
      context_policy:
        require_context_for_grounded_claims: true
        max_context_items: 8
        cite_context_labels: true

    tool_using_agent:
      enabled: true
      type: tool_using
      display_name: Tool Using Agent
      description: Produces logical tool intents and final answers from safe tool results.
      llm_profile: tool_reasoning
      capabilities:
        answer: true
        stream: true
        tool_intents: true
        tool_execute: false
        memory_read: false
        memory_write: false
      prompt_profile: tool_using_v1
      allowed_tool_intents:
        - documents.search
        - project.read_file
      max_tool_intents: 3

    project_agent:
      enabled: true
      type: project_agent
      display_name: Project Agent
      description: Helps with project files and project-scoped context through strategy-managed tools.
      llm_profile: project_reasoning
      capabilities:
        answer: true
        stream: true
        tool_intents: true
        tool_execute: false
        memory_read: true
        memory_write: false
      prompt_profile: project_agent_v1
      allowed_tool_intents:
        - project.read_file
        - project.search_files
        - documents.search

    memory_curator_agent:
      enabled: true
      type: memory_curator
      display_name: Memory Curator Agent
      description: Extracts safe memory candidates for strategy/policy-controlled writes.
      llm_profile: memory_curator
      capabilities:
        answer: false
        stream: false
        memory_candidate_extract: true
        memory_write: false
        tool_intents: false
        tool_execute: false
      prompt_profile: memory_curator_v1
      max_memory_candidates: 5

    reviewer_agent:
      enabled: true
      type: reviewer
      display_name: Reviewer Agent
      description: Reviews generated answers or plan summaries against configured criteria.
      llm_profile: reviewer_lightweight
      capabilities:
        review: true
        answer: false
        stream: false
      prompt_profile: reviewer_v1
```

### 10.1 Configuration Safety Rule

Configuration validation should fail fast when:

- An enabled agent has an unknown `type`.
- An enabled agent references a missing LLM profile.
- An enabled agent references a missing prompt profile when strict prompt validation is enabled.
- A strategy references a missing or disabled agent.
- A use case references a missing or disabled agent.
- An agent allows tool execution without `ToolGateway` enabled.
- An agent allows memory read/write without `MemoryGateway` enabled.
- An agent enables memory writes without policy hooks.
- An agent declares raw MCP tool names instead of logical backend tool names.
- An agent declares all tools as allowed by wildcard in V1.
- Agent output limits are negative or unbounded.
- A self-managed agent lacks explicit limits.
- Two agents register the same name.

---

## 11. Typed Agent Settings

Recommended dataclasses:

```python
from dataclasses import dataclass, field
from typing import Literal


AgentType = Literal[
    "general_assistant",
    "document_qa",
    "tool_using",
    "project_agent",
    "memory_curator",
    "reviewer",
    "custom",
]


@dataclass(frozen=True, slots=True)
class AgentCapabilitySettings:
    answer: bool = True
    review: bool = False
    stream: bool = True
    memory_read: bool = False
    memory_write: bool = False
    memory_candidate_extract: bool = False
    tool_intents: bool = False
    tool_execute: bool = False
    self_managed_memory: bool = False
    self_managed_tools: bool = False


@dataclass(frozen=True, slots=True)
class AgentLimitSettings:
    max_prompt_context_bytes: int = 32000
    max_output_chars: int = 12000
    max_tool_intents: int = 3
    max_memory_candidates: int = 5
    max_llm_calls: int = 1
    max_self_managed_tool_calls: int = 0
    max_self_managed_memory_searches: int = 0


@dataclass(frozen=True, slots=True)
class AgentContextPolicySettings:
    require_context_for_grounded_claims: bool = False
    cite_context_labels: bool = True
    max_context_items: int = 8
    max_context_bytes: int = 32000
    allow_untrusted_context_instructions: bool = False


@dataclass(frozen=True, slots=True)
class AgentSettings:
    name: str
    type: AgentType
    enabled: bool
    display_name: str | None = None
    description: str | None = None
    llm_profile: str | None = None
    prompt_profile: str | None = None
    capabilities: AgentCapabilitySettings = field(default_factory=AgentCapabilitySettings)
    limits: AgentLimitSettings = field(default_factory=AgentLimitSettings)
    context_policy: AgentContextPolicySettings = field(default_factory=AgentContextPolicySettings)
    allowed_tool_intents: tuple[str, ...] = ()
    allowed_memory_scopes: tuple[str, ...] = ()
    expose_metadata: bool = True
    extra: dict[str, object] = field(default_factory=dict)
```

### 11.1 Agent Settings Rule

Agent settings are declarative capability grants. They are not permission by themselves.

Effective permission should be computed from:

```text
agent settings
strategy settings
use-case settings
request identity/scope
policy decision
gateway policy checks
runtime limits
```

---

## 12. Agent Descriptor and Capability Model

Agents should publish descriptors that are safe for runtime resolution and optional capabilities responses.

Recommended descriptor:

```python
@dataclass(frozen=True, slots=True)
class AgentDescriptor:
    name: str
    type: str
    display_name: str
    description: str
    enabled: bool
    llm_profile: str | None
    capabilities: "AgentCapabilities"
    supported_usecases: tuple[str, ...] = ()
    supported_strategies: tuple[str, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)
```

Recommended capabilities:

```python
@dataclass(frozen=True, slots=True)
class AgentCapabilities:
    answer: bool = True
    review: bool = False
    stream: bool = True
    memory_read: bool = False
    memory_write: bool = False
    memory_candidate_extract: bool = False
    tool_intents: bool = False
    tool_execute: bool = False
    self_managed_memory: bool = False
    self_managed_tools: bool = False
```

### 12.1 Safe Descriptor Metadata

Allowed metadata:

```text
agent type
safe display name
description
capability flags
configured logical tool names when safe to expose
supported use cases
streaming support
```

Disallowed metadata:

```text
raw prompts
hidden instructions
provider URLs
API keys
MCP endpoint
memory database paths
policy internals
raw tool schemas if sensitive
```

---

## 13. Agent Registry

`AgentRegistry` is the only normal way for strategies to resolve agents.

Recommended protocol:

```python
from typing import Protocol


class AgentRegistry(Protocol):
    def register(self, agent: "AgentHandle") -> None: ...
    def resolve(self, agent_name: str) -> "AgentHandle": ...
    def list(self) -> tuple["AgentDescriptor", ...]: ...
    def contains(self, agent_name: str) -> bool: ...
```

Recommended implementation:

```python
class DefaultAgentRegistry:
    def __init__(self) -> None:
        self._agents: dict[str, AgentHandle] = {}

    def register(self, agent: AgentHandle) -> None:
        if agent.name in self._agents:
            raise AgentConfigurationError(
                code="duplicate_agent",
                message=f"Agent already registered: {agent.name}",
            )
        self._agents[agent.name] = agent

    def resolve(self, agent_name: str) -> AgentHandle:
        try:
            return self._agents[agent_name]
        except KeyError as exc:
            raise AgentNotFoundError(
                code="agent_not_found",
                message=f"Unknown agent: {agent_name}",
            ) from exc

    def list(self) -> tuple[AgentDescriptor, ...]:
        return tuple(agent.descriptor() for agent in self._agents.values())
```

### 13.1 Registry Rules

- The registry should contain enabled agents only.
- Disabled agents should fail startup validation if referenced by an enabled use case or strategy.
- The registry should not instantiate provider SDKs.
- The registry should not resolve tools, memory stores, or LLM providers.
- The registry should expose safe descriptors only.
- Strategies should never instantiate agents directly.

---

## 14. Agent Factory and Composition Root

The composition root builds configured agents after settings, gateways, policy, and observability are available.

Recommended startup sequence:

```text
1. Load settings and YAML configuration.
2. Build observability/redactor/metrics.
3. Build policy service.
4. Build LLMGateway.
5. Build MemoryGateway.
6. Build ToolGateway.
7. Validate agent settings.
8. Build AgentFactory.
9. Instantiate enabled agents.
10. Register agents in AgentRegistry.
11. Validate strategy references against AgentRegistry.
12. Build StrategyFactory and StrategyRegistry.
13. Build OrchestrationRuntime.
14. Build SessionService.
15. Build API app.
16. Log redacted agent startup summary.
```

Recommended factory shape:

```python
class AgentFactory:
    def __init__(
        self,
        *,
        settings: "AgentsSettings",
        policy: "PolicyService",
        observability: "ObservabilityFacade",
    ) -> None:
        self.settings = settings
        self.policy = policy
        self.observability = observability

    def build(self, agent_settings: AgentSettings) -> "AgentHandle":
        match agent_settings.type:
            case "general_assistant":
                return GeneralAssistantAgent(agent_settings)
            case "document_qa":
                return DocumentQaAgent(agent_settings)
            case "tool_using":
                return ToolUsingAgent(agent_settings)
            case "project_agent":
                return ProjectAgent(agent_settings)
            case "memory_curator":
                return MemoryCuratorAgent(agent_settings)
            case "reviewer":
                return ReviewerAgent(agent_settings)
            case _:
                raise AgentConfigurationError(
                    code="unknown_agent_type",
                    message=f"Unknown agent type: {agent_settings.type}",
                )
```

### 14.1 Redacted Startup Summary

Safe:

```json
{
  "event": "agents_configured",
  "agents_enabled": 5,
  "agent_types": ["general_assistant", "document_qa", "tool_using", "memory_curator", "reviewer"],
  "streaming_agents": 3
}
```

Unsafe:

```json
{
  "raw_prompts": {...},
  "provider_api_key": "...",
  "mcp_endpoint": "...",
  "oauth_token": "...",
  "memory_db_path": "..."
}
```

---

## 15. Agent Contract

Strategies call agents through a narrow contract.

Recommended protocol:

```python
from collections.abc import AsyncIterator
from typing import Protocol


class AgentHandle(Protocol):
    name: str
    type: str

    async def run(
        self,
        *,
        request: "AgentRunRequest",
        context: "OrchestrationContext",
    ) -> "AgentRunResult":
        ...

    async def stream(
        self,
        *,
        request: "AgentRunRequest",
        context: "OrchestrationContext",
    ) -> AsyncIterator["AgentStreamEvent"]:
        ...

    async def health(self) -> "AgentHealthResult":
        ...

    def descriptor(self) -> "AgentDescriptor":
        ...
```

### 15.1 Contract Rules

- `run` returns a normalized `AgentRunResult`.
- `stream` emits normalized `AgentStreamEvent` objects.
- `health` returns safe readiness metadata only.
- `descriptor` returns safe capability metadata only.
- Agents must be async-compatible.
- Agents must accept fake gateways in tests.
- Agents must not require API/session objects.

---

## 16. Agent Input Model

Strategies pass an `AgentRunRequest` that contains only bounded, safe context.

Recommended model:

```python
@dataclass(frozen=True, slots=True)
class AgentRunRequest:
    trace_id: str
    session_id: str
    user_id: str | None
    project_id: str | None
    usecase: str
    message: str
    llm_profile: str | None = None
    strategy_name: str | None = None
    session_summary: str | None = None
    context_items: tuple["PromptContextItem", ...] = ()
    tool_context: tuple["ToolContextItem", ...] = ()
    available_tools: tuple[str, ...] = ()
    task: "AgentTask | None" = None
    constraints: tuple[str, ...] = ()
    output_format: "AgentOutputFormat | None" = None
    metadata: dict[str, object] = field(default_factory=dict)
```

Recommended task model:

```python
@dataclass(frozen=True, slots=True)
class AgentTask:
    type: str
    instruction: str
    expected_outputs: tuple[str, ...] = ()
    safe_goal: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)
```

Recommended output format model:

```python
@dataclass(frozen=True, slots=True)
class AgentOutputFormat:
    kind: str = "answer"
    schema_name: str | None = None
    require_json: bool = False
    max_items: int | None = None
```

### 16.1 Agent Input Safety Rule

Agents may receive:

```text
user message
safe session summary
bounded retrieved context
bounded tool context
logical tool names
strategy constraints
safe metadata
```

Agents must not receive by default:

```text
raw workflow state document
raw SQLite rows
raw memory adapter records
raw embedding vectors
raw MCP payloads
provider SDK responses
credentials
hidden chain-of-thought
raw API request objects
```

---

## 17. Agent Output Model

Agents return normalized results.

Recommended model:

```python
@dataclass(frozen=True, slots=True)
class AgentRunResult:
    status: str
    answer: str | None = None
    agent_name: str | None = None
    llm_profile: str | None = None
    tool_intents: tuple["ToolIntent", ...] = ()
    memory_candidates: tuple["MemoryCandidate", ...] = ()
    review: "AgentReviewResult | None" = None
    usage: "AgentUsageSummary | None" = None
    output_items: tuple["AgentOutputItem", ...] = ()
    warnings: tuple["AgentWarning", ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)
```

Recommended output item:

```python
@dataclass(frozen=True, slots=True)
class AgentOutputItem:
    type: str
    text: str | None = None
    data: dict[str, object] | None = None
    source_label: str | None = None
    confidence: float | None = None
    metadata: dict[str, object] = field(default_factory=dict)
```

Recommended usage summary:

```python
@dataclass(frozen=True, slots=True)
class AgentUsageSummary:
    llm_calls: int = 0
    memory_searches: int = 0
    memory_writes: int = 0
    tool_calls: int = 0
    input_chars: int | None = None
    output_chars: int | None = None
```

### 17.1 Output Safety Rule

Agent outputs may include:

```text
final answer text
logical tool intents
memory candidates
review findings
safe warnings
safe usage counts
safe metadata
```

Agent outputs must not include:

```text
raw prompts
raw LLM completions
hidden chain-of-thought
raw provider responses
raw memory records
raw tool payloads
credentials
stack traces
```

---

## 18. Agent Stream Events

Agents that support streaming emit normalized `AgentStreamEvent` objects.

Recommended model:

```python
@dataclass(frozen=True, slots=True)
class AgentStreamEvent:
    type: str
    agent_name: str
    text: str | None = None
    result: AgentRunResult | None = None
    tool_intent: "ToolIntent | None" = None
    memory_candidate: "MemoryCandidate | None" = None
    warning: "AgentWarning | None" = None
    error: "AgentErrorDetail | None" = None
    metadata: dict[str, object] = field(default_factory=dict)
```

Allowed event types:

```text
agent.started
agent.prompt_built
agent.llm.started
agent.llm.delta
agent.llm.completed
agent.tool_intent.created
agent.memory_candidate.created
agent.review.completed
agent.completed
agent.failed
agent.cancelled
```

### 18.1 Stream Safety Rule

Agent stream events must not include:

- Raw provider chunks.
- Raw prompts.
- Raw system/developer messages.
- Hidden chain-of-thought.
- Raw tool request/response payloads.
- Raw memory records.
- Raw workflow state.
- Credentials.
- Stack traces.

---

## 19. Agent Lifecycle

Agent lifecycle per turn:

```text
1. Strategy resolves agent from AgentRegistry.
2. Strategy builds AgentRunRequest from bounded context.
3. Strategy and/or agent policy guard checks whether the agent may run.
4. Agent validates request against its capabilities and limits.
5. Agent builds prompt input.
6. Agent calls LLMGateway if needed.
7. Agent parses/normalizes output.
8. Agent returns answer, tool intents, memory candidates, review result, or warnings.
9. Strategy decides next workflow step.
10. Runtime normalizes final result.
11. SessionService persists safe workflow-state delta.
```

### 19.1 Lifecycle Rules

- Agents should be stateless between turns unless explicitly configured with safe in-memory caches.
- Agent-level caches must not store raw secrets, prompts, tool payloads, or memory records.
- Agents must not mutate global configuration at runtime.
- Agents must not spawn other agents directly in V1.
- Agents must not create background tasks.
- Agents must stop when cancellation is requested.

---

## 20. General Assistant Agent

`GeneralAssistantAgent` is the smallest useful LLM-backed agent.

It is appropriate when:

- The strategy is `direct_agent`.
- No tool execution is needed.
- No memory retrieval is needed.
- The answer can be generated from the user message and safe session summary.

### 20.1 Flow

```text
1. Validate answer capability.
2. Build direct-answer prompt input from message and safe session summary.
3. Call LLMGateway using configured logical LLM profile.
4. Normalize answer.
5. Return AgentRunResult.
```

### 20.2 Pseudocode

```python
class GeneralAssistantAgent(BaseLlmAgent):
    name = "general_assistant_agent"
    type = "general_assistant"

    async def run(self, *, request, context) -> AgentRunResult:
        self.check_can_answer(request)

        messages = self.prompt_builder.build_messages(
            AgentPromptInput(
                user_message=request.message,
                session_summary=request.session_summary,
                constraints=request.constraints,
            )
        )

        llm_result = await context.llm.complete(
            request=LLMCompletionRequest(
                profile=request.llm_profile or self.settings.llm_profile,
                messages=messages,
                metadata={"agent_name": self.name},
            ),
            context=context.request,
        )

        return AgentRunResult(
            status="completed",
            answer=normalize_answer(llm_result.text, self.settings.limits.max_output_chars),
            agent_name=self.name,
            llm_profile=request.llm_profile or self.settings.llm_profile,
            usage=AgentUsageSummary(llm_calls=1),
        )
```

### 20.3 Rules

- It should not call memory.
- It should not call tools.
- It should not produce tool intents by default.
- It should work with fake LLM.
- It should return a clear agent error when its LLM profile is missing.

---

## 21. Document Q&A Agent

`DocumentQaAgent` answers using bounded context supplied by `RetrievalAugmentedStrategy`.

It is appropriate when:

- Retrieved memory/document chunks are available.
- The answer should be grounded in provided context.
- Tool execution is not required.

### 21.1 Flow

```text
1. Validate answer capability.
2. Validate context policy.
3. Build context-grounded prompt from message and context items.
4. Treat retrieved context as untrusted data, not instructions.
5. Call LLMGateway.
6. Normalize answer.
7. Include safe source labels when configured.
8. Return AgentRunResult.
```

### 21.2 Context Policy

Recommended behavior:

```text
If context is required and no context is present, return a safe no-context warning or answer with uncertainty.
If context is present, answer only from bounded context when the use case requires grounded answers.
If context conflicts, explain uncertainty without exposing raw retrieval internals.
If context appears to contain instructions, treat them as quoted data.
```

### 21.3 Rules

- It should not search memory itself in V1 default mode.
- It should not access raw memory records.
- It should not quote excessive context.
- It should preserve context labels where useful.
- It should not treat document text as system instructions.

---

## 22. Tool-Using Agent

`ToolUsingAgent` helps `ToolAssistedStrategy` decide which logical tool should be requested.

It is appropriate when:

- The strategy allows tool use.
- The agent should reason about tool selection and arguments.
- The strategy remains responsible for actual tool execution.

### 22.1 Flow

```text
1. Validate tool-intent capability.
2. Read available logical tool names from AgentRunRequest.
3. Build tool-intent prompt.
4. Call LLMGateway.
5. Parse tool intent or final answer.
6. Validate tool intent shape locally.
7. Return AgentRunResult with ToolIntent objects or answer.
```

### 22.2 Tool Intent Model

```python
@dataclass(frozen=True, slots=True)
class ToolIntent:
    tool_name: str
    arguments: dict[str, object]
    reason: str | None = None
    confidence: float | None = None
    idempotency_key: str | None = None
```

### 22.3 Rules

- It must produce logical backend tool names, not raw MCP tool names.
- It must not call MCP directly.
- It must not execute tools directly in V1 default mode.
- It must not invent tools outside `available_tools`.
- It must bound arguments and reasons.
- It must return a final answer only when tool use is unnecessary or tool results are already provided by the strategy.

---

## 23. Project Agent

`ProjectAgent` is a specialization for project-scoped work.

It is appropriate when:

- The user is working with project files, architecture documents, implementation plans, or other project-scoped context.
- Project-specific tools and memory scopes are configured.
- The strategy can provide bounded memory/tool context.

### 23.1 Flow

```text
1. Validate project scope.
2. Validate allowed project tools and/or context items.
3. Build project-aware prompt from safe context.
4. Produce answer, tool intent, or structured project output.
5. Return safe result.
```

### 23.2 Rules

- It should operate on `project_id` or configured project scope.
- It should not read files directly from disk unless exposed through `ToolGateway` or strategy-provided context.
- It should not bypass `MemoryGateway` for project memory.
- It should not bypass `ToolGateway` for project tools.
- It should not persist project decisions directly into workflow state or long-term memory.

---

## 24. Memory Curator Agent

`MemoryCuratorAgent` extracts safe memory candidates.

It is appropriate when:

- The user explicitly asks the assistant to remember something.
- A strategy decides that a completed turn may contain durable memory candidates.
- Policy allows memory candidate extraction for the current scope.

### 24.1 Flow

```text
1. Validate memory-candidate capability.
2. Build memory-curation prompt from the current turn and safe context.
3. Extract candidate memories.
4. Classify memory type and scope.
5. Bound and normalize candidate text.
6. Return MemoryCandidate objects to strategy.
7. Strategy/policy/gateway decide whether to write.
```

### 24.2 Candidate Model

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

### 24.3 Rules

- It should not write memory directly in V1 default mode.
- It should not import `memory_store` or ArcadeDB.
- It should not retain sensitive memory candidates without policy approval.
- It should not produce unbounded memory candidates.
- It should return skipped/rejected candidates as safe warnings when useful.

---

## 25. Reviewer Agent

`ReviewerAgent` reviews an answer, plan, tool summary, or memory candidate against configured criteria.

It is appropriate when:

- A strategy wants a second pass on quality, safety, or completeness.
- The output should be checked before finalization.
- Evaluation-style review is needed inside a bounded workflow.

### 25.1 Flow

```text
1. Validate review capability.
2. Build review prompt from candidate output and criteria.
3. Call LLMGateway.
4. Parse review result.
5. Return safe review findings.
```

### 25.2 Review Result Model

```python
@dataclass(frozen=True, slots=True)
class AgentReviewResult:
    status: str
    passed: bool
    score: float | None = None
    findings: tuple[str, ...] = ()
    suggested_revision: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)
```

### 25.3 Rules

- It should not replace the workflow strategy.
- It should not call tools by default.
- It should not persist results directly.
- It should not expose hidden review scratchpads.
- It should return safe findings and optional suggested revision only.

---

## 26. Base LLM Agent Pattern

Most V1 agents can share a `BaseLlmAgent` helper.

Recommended responsibilities:

```text
resolve configured LLM profile
validate request against capabilities
build prompt messages from safe prompt inputs
call LLMGateway
parse structured output when required
normalize answer text
emit safe trace events
emit safe stream events
map LLM errors to AgentError
```

Recommended skeleton:

```python
class BaseLlmAgent:
    def __init__(self, settings: AgentSettings) -> None:
        self.settings = settings
        self.name = settings.name
        self.type = settings.type

    def descriptor(self) -> AgentDescriptor:
        return build_agent_descriptor(self.settings)

    def resolve_llm_profile(self, request: AgentRunRequest) -> str:
        profile = request.llm_profile or self.settings.llm_profile
        if not profile:
            raise AgentConfigurationError(
                code="missing_llm_profile",
                message=f"Agent {self.name} has no LLM profile",
            )
        return profile

    async def call_llm(self, *, messages, request, context):
        profile = self.resolve_llm_profile(request)
        await context.policy.can_use_agent_llm_profile(
            user_id=request.user_id,
            usecase=request.usecase,
            agent_name=self.name,
            llm_profile=profile,
        )
        return await context.llm.complete(
            request=LLMCompletionRequest(
                profile=profile,
                messages=messages,
                metadata={"agent_name": self.name},
            ),
            context=context.request,
        )
```

### 26.1 Base Agent Rule

Base helpers should reduce duplication, but they should not become a hidden orchestrator.

Avoid putting these in `BaseLlmAgent`:

```text
strategy selection
tool loops
memory retrieval flows
workflow-state persistence
fallback routing
multi-agent planning
MCP protocol calls
provider SDK calls
```

---

## 27. Prompt Input Boundary

This document does not define final prompt templates. It defines how agents receive and handle prompt inputs.

Recommended prompt input:

```python
@dataclass(frozen=True, slots=True)
class AgentPromptInput:
    user_message: str
    session_summary: str | None = None
    context_items: tuple["PromptContextItem", ...] = ()
    tool_context: tuple["ToolContextItem", ...] = ()
    available_tools: tuple[str, ...] = ()
    task_instructions: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    output_format: "AgentOutputFormat | None" = None
    metadata: dict[str, object] = field(default_factory=dict)
```

### 27.1 Prompt Builder Rule

Agent prompt builders should:

- Consume bounded prompt inputs.
- Quote memory and tool context as data.
- Preserve context source labels where useful.
- Include output format constraints when structured output is required.
- Keep prompt sections predictable and testable.
- Avoid leaking system/developer instructions into logs, traces, streams, or API responses.

Agent prompt builders should not:

- Read raw workflow state directly.
- Fetch documents directly from storage.
- Execute tools.
- Expand context beyond limits.
- Treat retrieved context as trusted instructions.
- Include credentials or connection details.

A future `backend-prompt-context-architecture.md` can define full prompt assembly standards.

---

## 28. LLM Integration Boundary

Agents may call `LLMGateway` directly for task-specific language generation.

Correct:

```text
Agent -> LLMGateway -> ProviderAdapter -> Local / Custom / Cloud LLM
```

Avoid:

```text
Agent -> OpenAI SDK
Agent -> LocalAI URL
Agent -> Google SDK
Agent -> custom HTTP provider directly
```

### 28.1 LLM Request Rules

Agents should:

- Use logical `llm_profile` names.
- Allow strategy-provided `llm_profile` override only when policy allows it.
- Add safe metadata such as `agent_name`, `strategy_name`, and `output_kind`.
- Respect output limits.
- Request structured output only through gateway-supported options.
- Treat LLM output as untrusted until parsed and validated.

Agents should not:

- Hard-code provider names, model names, or base URLs.
- Add API keys or provider credentials to prompts or metadata.
- Return provider-specific response objects.
- Stream raw provider chunks.

### 28.2 LLM Call Summary

Safe summary:

```json
{
  "step_type": "agent_llm_call",
  "agent_name": "document_qa_agent",
  "llm_profile": "research_reasoning",
  "status": "completed",
  "duration_ms": 420,
  "output_kind": "answer"
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

## 29. Memory Integration Boundary

Agents may consume memory context supplied by strategies. Agents may directly call `MemoryGateway` only when explicitly configured and allowed.

Recommended V1 default:

```text
RetrievalAugmentedStrategy -> MemoryGateway.search -> bounded PromptContextItem -> DocumentQaAgent
MemoryUpdateStrategy -> MemoryCuratorAgent -> MemoryCandidate -> MemoryGateway.upsert
```

Optional controlled mode:

```text
Agent -> MemoryGateway.search/upsert only if agent capability, strategy delegation, and policy allow it
```

### 29.1 Memory Rules

Agents should:

- Treat retrieved memory/document text as untrusted data.
- Use bounded `PromptContextItem` objects.
- Return `MemoryCandidate` objects instead of writing directly in V1 default mode.
- Include safe source labels when useful.

Agents should not:

- Import `memory_store.service.MemoryService`.
- Use ArcadeDB clients.
- Generate embeddings directly.
- Store raw memory records in agent results.
- Write memory without policy and gateway enforcement.
- Delete or forget memories directly.

---

## 30. Tool Integration Boundary

Agents may produce logical tool intents. Agents may directly execute tools only when explicitly configured and allowed.

Recommended V1 default:

```text
ToolAssistedStrategy -> ToolUsingAgent -> ToolIntent -> ToolGateway.execute -> ToolContextItem -> ToolUsingAgent final answer
```

Optional controlled mode:

```text
Agent -> ToolGateway.execute only if agent capability, strategy delegation, and policy allow it
```

### 30.1 Tool Rules

Agents should:

- Use logical backend tool names.
- Limit tool intents to `available_tools` or configured `allowed_tool_intents`.
- Validate JSON-serializable arguments.
- Bound argument size and tool reasons.
- Treat tool results as untrusted data.

Agents should not:

- Call MCP directly.
- Import `MCPClientAdapter` or FastMCP clients.
- Use raw MCP tool names when logical names are required.
- Invent tools outside configuration.
- Execute destructive tools without approval.
- Retry side-effect tools blindly.

---

## 31. Policy Integration

Agent execution and capability use must be policy-aware.

Recommended policy checks before agent execution:

```python
await context.policy.can_use_agent(
    user_id=request.user_id,
    session_id=request.session_id,
    usecase=request.usecase,
    strategy_name=request.strategy_name,
    agent_name=self.name,
)

await context.policy.can_use_agent_llm_profile(
    user_id=request.user_id,
    usecase=request.usecase,
    agent_name=self.name,
    llm_profile=resolved_profile,
)
```

Policy checks for direct memory/tool calls remain mandatory when self-managed mode is enabled:

```python
await context.policy.can_agent_search_memory(...)
await context.policy.can_agent_write_memory(...)
await context.policy.can_agent_execute_tool(...)
```

Gateway-level checks still remain inside gateways:

```text
LLMGateway checks profile/provider policy.
MemoryGateway checks memory read/write policy.
ToolGateway checks tool policy before MCP execution.
```

### 31.1 Policy Denial Rule

When policy denies an agent, LLM profile, memory operation, tool intent, or tool execution:

```text
1. Stop the denied action.
2. Record a safe policy-denied trace event.
3. Return normalized agent error or safe refusal.
4. Do not fall back to a less restrictive agent.
5. Do not execute partial side-effect actions after denial.
```

---

## 32. Workflow-State Integration

Agents do not persist workflow state.

Agents return safe outputs to strategies. Strategies convert those outputs into `WorkflowStateDelta` objects where appropriate.

Correct:

```text
AgentRunResult -> StrategyRunResult -> WorkflowStateDelta -> SessionService save
```

Avoid:

```text
Agent -> WorkflowStateStore.save
Agent -> SQLite
Agent -> direct workflow state mutation
```

### 32.1 Safe State Content From Agents

Allowed agent-derived state summaries:

```text
assistant answer
selected agent name
safe warnings
safe review result
safe tool intent summary
safe memory candidate count
safe usage counts
```

Avoid state content:

```text
raw prompt
raw LLM response
raw tool payload
raw memory record
hidden scratchpad
credentials
provider metadata with sensitive payloads
```

---

## 33. Observability and Trace Integration

Agents emit safe trace events through the observability facade or trace helper.

Recommended events:

| Event | Emitted By | Notes |
|---|---|---|
| `agent_selected` | Strategy/runtime | Agent name, type, use case. |
| `agent_started` | Agent/step runner | Agent name and strategy name. |
| `agent_prompt_built` | Agent | Prompt profile and bounded context counts only. |
| `agent_llm_started` | Agent/LLMGateway | Agent name and LLM profile. |
| `agent_llm_completed` | Agent/LLMGateway | Duration and safe usage summary. |
| `agent_tool_intent_created` | Tool-using agent | Logical tool name only. |
| `agent_memory_candidate_created` | Memory curator | Candidate count/type summary only. |
| `agent_review_completed` | Reviewer | Pass/fail/score only. |
| `agent_completed` | Agent | Status, duration, output kind. |
| `agent_failed` | Agent | Safe error code/type. |
| `agent_cancelled` | Agent/runtime | Cancellation summary. |
| `agent_policy_denied` | Agent/policy guard | Safe denial reason code. |

### 33.1 Safe Trace Payload Example

```json
{
  "event_name": "agent_completed",
  "trace_id": "trace_...",
  "payload": {
    "agent_name": "document_qa_agent",
    "agent_type": "document_qa",
    "strategy_name": "retrieval_augmented",
    "status": "completed",
    "duration_ms": 940,
    "llm_calls": 1,
    "context_items": 5,
    "tool_intents": 0,
    "memory_candidates": 0
  }
}
```

### 33.2 Unsafe Trace Payload Example

```json
{
  "raw_prompt": "...",
  "raw_llm_response": {...},
  "raw_memory_records": [...],
  "raw_tool_response": {...},
  "authorization": "Bearer ..."
}
```

### 33.3 Metrics

Recommended metrics:

```text
backend.agents.runs.total
backend.agents.duration_ms
backend.agents.failures.total
backend.agents.streams.total
backend.agents.llm_calls.total
backend.agents.tool_intents.total
backend.agents.memory_candidates.total
backend.agents.policy_denials.total
backend.agents.cancellations.total
```

Allowed metric tags:

```text
agent_name
agent_type
usecase
strategy_name
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
provider URL
API keys
```

---

## 34. Agent Error Model

Recommended agent errors:

```python
class AgentError(Exception):
    code: str
    retryable: bool


class AgentNotFoundError(AgentError): ...
class AgentDisabledError(AgentError): ...
class AgentConfigurationError(AgentError): ...
class AgentPolicyDeniedError(AgentError): ...
class AgentCapabilityError(AgentError): ...
class AgentInputValidationError(AgentError): ...
class AgentPromptBuildError(AgentError): ...
class AgentLLMError(AgentError): ...
class AgentOutputParseError(AgentError): ...
class AgentToolIntentError(AgentError): ...
class AgentMemoryCandidateError(AgentError): ...
class AgentReviewError(AgentError): ...
class AgentLimitExceededError(AgentError): ...
class AgentCancelledError(AgentError): ...
```

### 34.1 Error Mapping

| Error | Retryable | Notes |
|---|---:|---|
| `AgentNotFoundError` | false | Config or strategy reference bug. |
| `AgentDisabledError` | false | Disabled agent referenced by config. |
| `AgentConfigurationError` | false | Startup validation should catch most cases. |
| `AgentPolicyDeniedError` | false | Must not fallback to weaker agent. |
| `AgentCapabilityError` | false | Strategy requested unsupported capability. |
| `AgentInputValidationError` | false | Bad or unsafe request shape. |
| `AgentPromptBuildError` | false/true | Depends on cause. |
| `AgentLLMError` | true/false | Depends on LLM gateway error. |
| `AgentOutputParseError` | false/true | Retry only when repair is configured and bounded. |
| `AgentToolIntentError` | false | Invalid or unsafe tool intent. |
| `AgentMemoryCandidateError` | false | Invalid candidate shape. |
| `AgentReviewError` | false/true | Depends on cause. |
| `AgentLimitExceededError` | false | Stop additional work. |
| `AgentCancelledError` | false | Normal cancellation path. |

### 34.2 Error Safety Rule

Agent errors must not expose:

- Raw stack traces.
- Raw provider errors.
- Raw MCP errors.
- Raw memory adapter errors.
- Raw SQL errors.
- Credentials.
- Raw prompt/completion payloads.
- Hidden scratchpads.

---

## 35. Streaming Behavior

Agent streaming should be normalized before it reaches strategies and API/SSE mapping.

### 35.1 Streaming Direct Answer

```text
agent.started
agent.llm.started
agent.llm.delta...
agent.llm.completed
agent.completed
```

### 35.2 Streaming Tool Intent

```text
agent.started
agent.llm.started
agent.llm.completed
agent.tool_intent.created
agent.completed
```

### 35.3 Streaming Final Answer After Tool Results

```text
agent.started
agent.llm.started
agent.llm.delta...
agent.llm.completed
agent.completed
```

### 35.4 Streaming Rules

- Stream only normalized agent events.
- Do not stream raw provider chunks.
- Do not stream raw prompts.
- Do not stream raw tool payloads.
- Do not stream raw memory records.
- Do not stream hidden chain-of-thought.
- Strategy remains responsible for mapping agent stream events to strategy stream events.

---

## 36. Cancellation Behavior

Agents must cooperate with runtime cancellation.

Cancellation flow:

```text
1. API detects client disconnect or runtime receives cancellation.
2. Runtime cancels active strategy task.
3. Strategy cancels active agent task.
4. Agent cancels active LLM/memory/tool gateway call if supported.
5. Agent emits or records safe cancellation event.
6. Strategy returns cancellation summary.
7. Runtime returns cancellation summary.
8. SessionService decides whether to persist cancellation checkpoint.
```

### 36.1 Cancellation Rules

- Agents must not start new LLM/memory/tool work after cancellation.
- Agents must not continue streaming after cancellation is acknowledged.
- Agents must not persist state directly.
- Agents must not assume side-effect tool cancellation rolled back downstream actions.
- Agents should return a normalized `AgentCancelledError` or cancellation event.

---

## 37. Health Integration

Agents should expose safe health and readiness status.

Recommended result:

```python
@dataclass(frozen=True, slots=True)
class AgentHealthResult:
    agent_name: str
    agent_type: str
    status: str
    enabled: bool
    configured_llm_profile: str | None = None
    prompt_profile: str | None = None
    memory_required: bool = False
    tools_required: bool = False
    streaming_supported: bool = False
    metadata: dict[str, object] = field(default_factory=dict)
```

### 37.1 Health Rules

Health may include:

```text
agent enabled/disabled status
agent type
configured logical LLM profile
prompt profile name
whether memory/tool gateways are required
streaming support
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

## 38. Capabilities Integration

Capabilities should expose frontend-safe agent/use-case metadata only.

Recommended capability section:

```json
{
  "agents": [
    {
      "name": "general_assistant_agent",
      "display_name": "General Assistant",
      "type": "general_assistant",
      "streaming_supported": true,
      "capabilities": ["answer"]
    },
    {
      "name": "document_qa_agent",
      "display_name": "Document Q&A Agent",
      "type": "document_qa",
      "streaming_supported": true,
      "capabilities": ["answer", "memory_context"]
    }
  ]
}
```

### 38.1 Capability Safety Rule

Expose:

```text
safe agent names
display names
agent type labels
safe capability labels
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

## 39. Composition Root Integration

The composition root builds agents before strategies because strategies reference agents.

Recommended composition:

```python
def build_agent_registry(config, policy, observability) -> AgentRegistry:
    factory = AgentFactory(
        settings=config.agents,
        policy=policy,
        observability=observability,
    )

    registry = DefaultAgentRegistry()
    for agent_settings in config.agents.plugins.values():
        if agent_settings.enabled:
            registry.register(factory.build(agent_settings))

    return registry
```

Recommended full order:

```text
settings/config
observability
policy
LLMGateway
MemoryGateway
ToolGateway
AgentRegistry
StrategyRegistry
OrchestrationRuntime
SessionService
API app
```

### 39.1 Composition Rule

The composition root may know concrete agent classes. Strategies, API routes, session services, and gateways should not.

---

## 40. Testing Strategy

### 40.1 Unit Tests

| Test | Purpose |
|---|---|
| Agent settings validate | Proves config safety. |
| Missing LLM profile fails config | Prevents runtime surprises. |
| Duplicate agent name fails registry | Prevents ambiguous resolution. |
| Disabled agent cannot be resolved | Enforces config. |
| Strategy references existing agent | Proves config integration. |
| General assistant calls LLM once | Proves minimal flow. |
| General assistant does not call memory/tools | Enforces boundary. |
| Document Q&A uses provided context only | Preserves strategy-managed retrieval. |
| Document Q&A treats context as data | Prevents prompt injection by retrieved text. |
| Tool agent emits logical ToolIntent | Proves tool-intent pattern. |
| Tool agent rejects unknown tools | Prevents arbitrary tool execution. |
| Tool agent does not execute tools by default | Enforces V1 boundary. |
| Project agent requires project scope | Prevents cross-scope behavior. |
| Memory curator emits bounded candidates | Prevents memory bloat. |
| Memory curator does not write memory by default | Enforces gateway/policy boundary. |
| Reviewer returns safe findings | Prevents scratchpad exposure. |
| Agent stream events are safe | Prevents raw provider streaming. |
| Agent trace events are redacted | Proves privacy behavior. |
| Policy denial blocks agent execution | Proves policy integration. |
| Cancellation stops further work | Proves cancellation behavior. |

### 40.2 Integration Tests

| Test | Purpose |
|---|---|
| Runtime resolves configured agent | Proves registry integration. |
| Direct strategy invokes general assistant | Proves strategy-agent handoff. |
| Retrieval strategy invokes document Q&A agent | Proves bounded context handoff. |
| Tool strategy invokes tool agent then ToolGateway | Proves intent/execution split. |
| Memory update strategy invokes memory curator | Proves candidate/write split. |
| Reviewer can be invoked by bounded planner | Proves optional review step. |
| Agent result becomes strategy result | Proves result mapping. |
| Agent stream reaches SSE safely | Proves stream chain. |
| Agent error normalizes into runtime error | Proves error mapping. |
| Agent health appears in backend health | Proves safe readiness exposure. |
| Capabilities include safe agent descriptors | Proves frontend-safe metadata. |

### 40.3 Dependency Boundary Tests

Add import-boundary tests to prevent drift:

```text
agents must not import app/api
agents must not import app/session
agents must not import sqlite3
agents must not import memory_store
agents must not import ArcadeDB clients
agents must not import MCP client implementations
agents must not import FastMCP clients
agents must not import provider SDKs
agents must not import frontend DTOs
```

### 40.4 Fixture Configs

Recommended fixtures:

```text
tests/fixtures/config/agents_general_basic.yaml
tests/fixtures/config/agents_document_qa_basic.yaml
tests/fixtures/config/agents_tool_using_basic.yaml
tests/fixtures/config/agents_project_basic.yaml
tests/fixtures/config/agents_memory_curator_basic.yaml
tests/fixtures/config/agents_reviewer_basic.yaml
tests/fixtures/config/agents_invalid_missing_llm_profile.yaml
tests/fixtures/config/agents_invalid_duplicate_name.yaml
tests/fixtures/config/agents_invalid_raw_mcp_tool.yaml
tests/fixtures/config/agents_invalid_unbounded_self_managed.yaml
tests/fixtures/config/agents_invalid_memory_write_without_policy.yaml
```

---

## 41. Recommended Implementation Order

### Step 1: Add Agent Config Models

Deliverables:

- `AgentSettings`
- `AgentCapabilitySettings`
- `AgentLimitSettings`
- `AgentContextPolicySettings`
- agent config validation

Success criteria:

- Valid agent fixtures load.
- Missing LLM profile references fail fast.
- Unsafe self-managed configuration fails fast.

### Step 2: Add Agent Base Contracts

Deliverables:

- `AgentHandle` protocol
- `AgentRunRequest`
- `AgentRunResult`
- `AgentStreamEvent`
- `AgentDescriptor`
- `AgentCapabilities`
- agent error types

Success criteria:

- Fake agent implements the protocol.
- Strategies can call fake agents without real gateways.

### Step 3: Add Agent Registry and Factory

Deliverables:

- `DefaultAgentRegistry`
- `AgentFactory`
- startup validation for agent references
- redacted startup summary

Success criteria:

- Enabled agents register successfully.
- Duplicate and missing agents fail clearly.
- Strategy config validates against agent registry.

### Step 4: Add Base LLM Agent

Deliverables:

- `BaseLlmAgent`
- LLM profile resolution
- prompt builder hooks
- output normalization
- trace helper integration

Success criteria:

- Fake LLM can be used.
- Raw provider responses do not leave the LLM gateway boundary.

### Step 5: Add General Assistant Agent

Deliverables:

- `GeneralAssistantAgent`
- direct answer prompt profile
- non-streaming and streaming support

Success criteria:

- Direct strategy can produce an answer through the general assistant.
- No memory/tool calls occur.

### Step 6: Add Document Q&A Agent

Deliverables:

- `DocumentQaAgent`
- bounded context handling
- context labels
- no-context warning behavior

Success criteria:

- Retrieval strategy can pass memory/document context to the agent.
- The agent does not search memory directly in default mode.

### Step 7: Add Tool-Using Agent

Deliverables:

- `ToolUsingAgent`
- tool-intent prompt profile
- tool intent parser/validator
- final-answer-after-tool-context behavior

Success criteria:

- Tool strategy receives logical tool intents.
- Unknown tool names are rejected.
- The agent does not execute tools directly in default mode.

### Step 8: Add Project Agent

Deliverables:

- `ProjectAgent`
- project-scope validation
- project-oriented prompt profile
- project tool-intent restrictions

Success criteria:

- Project use case can request project-scoped tool intents safely.
- The agent does not read files or storage directly.

### Step 9: Add Memory Curator Agent

Deliverables:

- `MemoryCuratorAgent`
- memory candidate extraction
- candidate classification
- candidate bounding

Success criteria:

- Memory update strategy receives bounded candidates.
- Candidate writes still go through strategy/policy/MemoryGateway.

### Step 10: Add Reviewer Agent

Deliverables:

- `ReviewerAgent`
- review result model
- review prompt profile
- safe findings output

Success criteria:

- Reviewer returns pass/fail/findings without hidden scratchpad.
- Reviewer can run with fake LLM.

### Step 11: Add Health and Capabilities

Deliverables:

- agent health results
- agent capability summaries
- safe capability output mapping

Success criteria:

- Health reports configured agent readiness.
- Capabilities do not expose prompts, credentials, endpoints, raw tools, or policy internals.

### Step 12: Wire Into Runtime and Strategies

Deliverables:

- composition root builds `AgentRegistry`
- `StrategyFactory` receives `AgentRegistry`
- direct/retrieval/tool/memory strategies invoke configured agents
- API/session contracts remain unchanged

Success criteria:

- `/chat` can run direct/retrieval/tool-assisted flows through real or fake agents.
- `/chat/stream` can stream safe agent-derived events through strategy/runtime/API mapping.
- API and session layers do not import concrete agents.

---

## 42. Acceptance Criteria

This architecture is complete when:

- `backend-agents-architecture.md` deepens the agent plugin layer established by `backend-application-architecture.md` and `backend-workflow-strategies-architecture.md` without changing API or session boundaries.
- Agent settings are configuration-driven and validated at startup.
- `AgentRegistry` can register, list, and resolve configured agents.
- `AgentFactory` can build enabled agents from typed settings.
- Strategies invoke agents only through an agent registry/agent handle abstraction.
- `GeneralAssistantAgent` can answer through `LLMGateway` without memory or tools.
- `DocumentQaAgent` can answer using bounded context supplied by retrieval strategies.
- `ToolUsingAgent` can produce logical tool intents without executing tools directly in V1 default mode.
- `ProjectAgent` can operate within project-scoped context and logical project tool intents.
- `MemoryCuratorAgent` can produce bounded memory candidates without writing memory directly in V1 default mode.
- `ReviewerAgent` can return safe review findings without hidden scratchpads.
- Agents do not import API routes, session services, SQLite, ArcadeDB clients, `memory_store`, MCP clients, FastMCP clients, provider SDKs, or frontend DTOs.
- Agents call LLMs only through `LLMGateway`.
- Agents search/write memory only through `MemoryGateway` when explicitly allowed by agent capability, strategy delegation, and policy.
- Agents execute tools only through `ToolGateway` when explicitly allowed by agent capability, strategy delegation, and policy.
- Agents produce logical tool intents rather than raw MCP calls in V1 default mode.
- Agents return normalized `AgentRunResult` and `AgentStreamEvent` objects.
- Agent results contain safe answers, tool intents, memory candidates, review findings, warnings, and metadata.
- Agents do not persist workflow state directly.
- Agents support cancellation and stop starting new work after cancellation.
- Agent stream events are safe for strategy/runtime/API/SSE mapping.
- Raw prompts, raw provider responses, raw tool payloads, raw memory records, raw workflow state documents, credentials, hidden chain-of-thought, planning scratchpads, and stack traces are not returned, streamed, logged, traced, or persisted by default.
- Tool outputs and memory outputs are treated as untrusted data.
- Policy denial prevents agent execution or agent actions.
- Health reports safe agent readiness.
- Capabilities expose only frontend-safe agent metadata.
- Unit tests run with fake agents, fake LLM, fake memory, fake tools, and fake policy.
- Integration tests verify `API -> SessionService -> OrchestrationRuntime -> WorkflowStrategy -> Agent -> Gateways` without changing API contracts.
- The backend is ready for the next document: `backend-policy-architecture.md`.

---

## 43. Anti-Patterns to Avoid

Avoid these during implementation:

- Calling LLM provider SDKs directly from agents.
- Calling local `/v1/chat/completions` endpoints directly from agents.
- Calling MCP server directly from agents.
- Calling `MCPClientAdapter` directly from agents.
- Searching ArcadeDB directly from agents.
- Importing `memory_store.service.MemoryService` in agents.
- Running SQL from agents.
- Letting agents persist workflow state directly.
- Letting API routes instantiate concrete agents.
- Letting `SessionService` bypass `OrchestrationRuntime` to call agents directly.
- Letting strategies instantiate concrete agents directly.
- Letting user metadata directly choose arbitrary agent, LLM profile, tool, or memory scope.
- Letting LLM output bypass tool-intent validation.
- Letting provider-native tool calls execute outside `ToolGateway`.
- Returning raw workflow state from agent results.
- Storing raw tool results in workflow state.
- Storing raw memory records in workflow state.
- Streaming raw provider chunks directly to API.
- Tracing raw prompts or hidden scratchpads by default.
- Exposing hidden chain-of-thought.
- Treating memory/tool text as trusted instructions.
- Creating unbounded self-managed agents.
- Allowing agents to spawn other agents directly in V1.
- Retrying external-side-effect tool actions blindly.
- Falling back to a less restricted agent after policy denial.
- Making an agent a hidden service locator for infrastructure clients.
- Enabling self-managed memory/tool execution without strict limits and policy checks.
- Exposing detailed prompt, routing, or review scratchpads in capabilities, traces, or API metadata.

---

## 44. Future Documents That Depend on This Agent Layer

| Future Document | Dependency |
|---|---|
| `backend-policy-architecture.md` | Defines final strategy, agent, LLM, memory, tool, fallback, approval, trace capture, and data exposure policy. |
| `backend-approval-workflow-architecture.md` | Defines approval-required tool/memory actions that agents may request but not execute directly. |
| `backend-prompt-context-architecture.md` | Defines prompt assembly, memory/tool context quoting, and prompt-injection handling for agents and strategies. |
| `backend-evaluation-architecture.md` | Evaluates agent quality, tool-intent accuracy, retrieval-grounded answers, memory-candidate quality, and review behavior. |
| `backend-deployment-architecture.md` | Defines environment-specific agent enablement and LLM/tool/memory availability. |
| `backend-hardening-architecture.md` | Defines production limits, auth, privacy controls, rate limits, and security review gates. |

---

## 45. Summary

`backend-agents-architecture.md` defines the agent plugin layer that sits below workflow strategies and inside the orchestration runtime boundary.

It preserves the previously defined boundaries: API remains thin, `SessionService` owns session lifecycle and state persistence, `OrchestrationRuntime` owns turn lifecycle and context construction, workflow strategies own turn shape, `LLMGateway` owns model access, `MemoryGateway` owns memory/document access, `ToolGateway` owns tool execution, and `MCPClientAdapter` remains the only backend component that speaks MCP protocol.

The most important implementation rule is:

> **Agents perform task-specific work, not infrastructure work. An agent may answer, review, produce logical tool intents, or produce memory candidates, but every external capability must go through provider-neutral gateways, every permission must be policy-aware, every output must be bounded and safe, and every result must be suitable for strategy/runtime/session handoff.**
