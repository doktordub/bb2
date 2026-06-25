# Backend LLM Gateway Architecture

**Document:** `backend-llm-gateway-architecture.md`  
**Version:** 1.0  
**Source alignment:** `backend-application-architecture.md`, `backend-foundation-architecture.md`, `backend-core-contracts-architecture.md`, `backend-configuration-architecture.md`, `backend-observability-architecture.md`, `backend-persistence-architecture.md`, `backend-sqlite-workflow-state-architecture.md`, `backend-sqlite-trace-store-architecture.md`, `backend-api-architecture.md`, and `backend-session-service-architecture.md`  
**Scope:** Provider-neutral LLM access, logical model profiles, provider adapters, local/OpenAI-compatible/custom/cloud model integration, profile resolution, per-agent/per-strategy model selection, streaming normalization, timeout/retry/fallback behavior, policy hooks, trace correlation, redaction, health checks, testing strategy, and acceptance criteria for the V1 `LLMGateway` layer.

---

## 1. Purpose

This document defines the tenth implementation-focused architecture document for the backend application tier.

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
10. `backend-llm-gateway-architecture.md` ← this document

The previous document deepened the `SessionService` layer and established the rule that session lifecycle code must not call LLM providers or `LLMGateway` directly for normal chat behavior. This document defines the LLM boundary that orchestration, strategies, and agents use through provider-neutral logical profiles.

The goal is to support local, custom, OpenAI-compatible, OpenAI, Google, and future model providers without changing API routes, session lifecycle code, orchestration contracts, or agent plugin code.

The core architecture rule is:

> `LLMGateway` is the only backend boundary that resolves logical LLM profiles into concrete provider/model/runtime calls. Agents and strategies request logical profiles and normalized completions; they must not instantiate provider SDKs, hard-code model endpoints, or depend on provider-specific response objects.

---

## 2. Source Architecture Alignment

This document follows the established backend rules:

- The backend is one deployable application tier in V1.
- Frontend communicates with backend through REST / SSE.
- API routes are thin and delegate chat/reset behavior to `SessionService`.
- `SessionService` calls `OrchestrationRuntime` and does not call LLM providers directly.
- `OrchestrationRuntime`, strategies, and agents access models through `LLMGateway` only.
- Each agent can use a different logical LLM profile.
- The orchestrator/router/planner can use a separate logical LLM profile from the final-answer agent.
- LLM provider/model configuration is YAML-driven.
- Local, custom, OpenAI-compatible, OpenAI, Google, and future providers are hidden behind provider adapters.
- Provider SDK responses must not leak into agents, strategies, session results, API DTOs, workflow state, or trace payloads.
- LLM calls must be trace-correlated with the active `trace_id`.
- LLM call trace events must be safe, bounded, and redacted.
- LLM provider credentials, tokens, base URLs if sensitive, raw authorization headers, and provider error payloads must not be returned to the frontend.
- LLM failures map to normalized backend errors.
- LLM policy checks are deny-by-default for unknown providers, unknown profiles, and unauthorized profile use.
- Tool/MCP access remains behind `ToolGateway`; the LLM gateway must not become the tool executor.
- Long-term memory and document chunks remain behind `MemoryGateway`; the LLM gateway must not become the memory store.

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

This document expands Phase 10.

The output of this phase is a provider-neutral model access layer that supports:

```text
LLMGateway.complete(...)
LLMGateway.stream(...)
LLMGateway.health(...)
LLMGateway.list_profiles(...)
ProfileResolver.resolve(...)
ProviderAdapter.complete(...)
ProviderAdapter.stream(...)
```

The next document should be:

```text
backend-memory-store-adapter-architecture.md
```

---

## 4. Architecture Goals

The LLM gateway should be:

1. **Provider-neutral**  
   Agents, strategies, and orchestration code use logical profiles and normalized request/result objects.

2. **Configuration-driven**  
   Provider URLs, model names, profile defaults, timeouts, retries, and fallbacks come from YAML/environment configuration.

3. **Per-agent capable**  
   Different agents can use different LLM profiles without changing agent code.

4. **Orchestrator-capable**  
   Router/planner strategies can use an orchestrator LLM profile separate from agent profiles.

5. **Streaming-capable**  
   Provider-specific stream chunks are normalized into safe backend stream events.

6. **Policy-aware**  
   Profile access is checked before provider calls.

7. **Trace-correlated**  
   Every LLM call records safe lifecycle events with the active `trace_id`.

8. **Redacted by default**  
   Secrets, raw prompts, raw completions, raw provider payloads, and credentials are not stored in traces or logs by default.

9. **Failure-normalizing**  
   Provider errors, timeouts, throttling, and malformed responses map to stable backend error types.

10. **Fallback-capable**  
   Logical profiles can define ordered fallback profiles or fallback providers where policy allows.

11. **Testable**  
   The gateway can be tested with fake provider adapters and deterministic fake responses.

12. **Extensible**  
   New providers can be added by implementing `LLMProviderAdapter` and adding configuration, without changing agents or API routes.

---

## 5. Non-Goals

This document should not implement:

- API route behavior.
- Session lifecycle behavior.
- Full orchestration strategy behavior.
- Agent prompt design.
- Long-term memory search or memory writes.
- Tool/MCP execution.
- MCP server implementation.
- Vector embeddings for memory retrieval.
- Reranking for memory search.
- Fine-tuning workflows.
- Model training.
- Complex model evaluation platform.
- Production billing/cost dashboards.
- Full authentication and authorization model.
- Human approval workflow.
- Prompt marketplace or prompt versioning system.
- Raw prompt/completion archival.
- Multi-tenant secrets vault implementation.

Those concerns belong to memory, tooling/MCP, orchestration, agents, policy, prompt-management, evaluation, and deployment documents.

---

## 6. LLM Gateway Boundary

The LLM gateway sits behind the orchestration runtime.

It owns:

- Logical LLM profile resolution.
- Provider adapter lookup.
- Provider/model/runtime request construction.
- Normalized completion and streaming calls.
- Timeout, retry, fallback, and circuit-breaker behavior.
- Model capability checks.
- LLM policy hooks.
- Safe LLM lifecycle trace events.
- Provider health checks.
- Response normalization.
- Provider error normalization.
- Redaction of sensitive model call metadata.

It does not own:

- API request parsing.
- Session creation/resume/reset.
- Business workflow routing decisions.
- Agent selection.
- Long-term memory search or upsert.
- Tool allowlist decisions.
- MCP client calls.
- MCP server implementation.
- Workflow-state persistence.
- Trace-store SQL implementation.
- User-facing response DTO formatting.

### 6.1 Boundary Diagram

```text
API
  -> SessionService
      -> OrchestrationRuntime
          -> Strategy / Agent
              -> LLMGateway
                  -> ProfileResolver
                  -> PolicyService profile check
                  -> ProviderRegistry
                      -> OpenAICompatibleProviderAdapter
                      -> OpenAIProviderAdapter
                      -> GoogleProviderAdapter
                      -> CustomHttpProviderAdapter
                      -> FutureProviderAdapter
                  -> ObservabilityRecorder / TraceStore
```

### 6.2 Practical Rule

Agents and strategies should do this:

```python
response = await context.llm.complete(
    request=LLMRequest(
        profile="research_reasoning",
        messages=messages,
        temperature=None,
        metadata={"agent_name": self.name},
    ),
    context=context.request,
)
```

Agents and strategies should not do this:

```python
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
response = client.chat.completions.create(model="hard-coded-model", messages=messages)
```

They should also not do this:

```python
requests.post("http://192.168.1.80:8081/v1/chat/completions", json={...})
```

That concrete endpoint belongs in provider configuration and provider adapter code.

---

## 7. Recommended Package Layout

Recommended implementation layout:

```text
backend/
  app/
    llm/
      __init__.py
      gateway.py
      models.py
      messages.py
      errors.py
      profile_resolver.py
      provider_base.py
      provider_registry.py
      capabilities.py
      token_budget.py
      retry.py
      streaming.py
      redaction.py
      health.py

      providers/
        __init__.py
        openai_compatible.py
        openai.py
        google.py
        custom_http.py
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
        fake_llm_gateway.py
        fake_llm_provider_adapter.py
```

### 7.1 Module Responsibilities

| Module | Responsibility |
|---|---|
| `gateway.py` | Public `LLMGateway` implementation and orchestration-facing entry point. |
| `models.py` | Request/result/config models. |
| `messages.py` | Provider-neutral message and content-part models. |
| `errors.py` | LLM-specific normalized errors. |
| `profile_resolver.py` | Resolve logical profiles to concrete provider/model settings. |
| `provider_base.py` | `LLMProviderAdapter` protocol. |
| `provider_registry.py` | Provider adapter lookup and registration. |
| `capabilities.py` | Model/provider capability declarations and validation. |
| `token_budget.py` | Optional token budget estimation and request limits. |
| `retry.py` | Retry/fallback policy helpers. |
| `streaming.py` | Provider stream chunk normalization. |
| `redaction.py` | LLM-specific redaction helpers. |
| `health.py` | LLM provider/profile health checks. |
| `providers/openai_compatible.py` | Local/custom OpenAI-compatible `/v1/chat/completions` adapter. |
| `providers/openai.py` | Optional OpenAI provider adapter. |
| `providers/google.py` | Optional Google provider adapter. |
| `providers/custom_http.py` | Generic HTTP provider adapter for custom runtimes. |
| `providers/fake.py` | Deterministic fake provider for tests. |

---

## 8. Dependency Direction Rules

Allowed:

```text
app/orchestration/* -> app/llm/gateway.py
app/agents/*        -> app/llm/models.py through OrchestrationContext
app/llm/*           -> app/config/schemas.py
app/llm/*           -> app/policy/service.py through interface
app/llm/*           -> app/observability/events.py through facade
app/llm/providers/* -> provider SDKs or HTTP clients
```

Avoid:

```text
app/api/*           -> app/llm/providers/*
app/session/*       -> app/llm/gateway.py for normal chat behavior
app/agents/*        -> provider SDKs
app/agents/*        -> HTTP clients for LLM endpoints
app/orchestration/* -> provider SDKs
app/llm/*           -> app/tools/mcp_adapter.py
app/llm/*           -> memory_store.service.MemoryService
app/llm/*           -> sqlite3
app/llm/*           -> ArcadeDB client
```

### 8.1 Route and Session Boundary Rule

The API and session layers remain unchanged after LLM integration.

Correct path:

```text
API -> SessionService -> OrchestrationRuntime -> LLMGateway -> ProviderAdapter
```

Avoid:

```text
API -> LLMGateway
SessionService -> LLMGateway
SessionService -> OpenAI-compatible endpoint
SessionService -> OpenAI SDK
SessionService -> Google SDK
```

### 8.2 Agent Boundary Rule

Agents may depend on provider-neutral request/result models exposed through `OrchestrationContext`.

Agents must not know:

```text
provider base URL
provider auth header format
provider SDK object shape
provider retry behavior
provider stream chunk shape
actual model ID unless intentionally exposed as safe metadata
```

---

## 9. LLM Configuration Integration

LLM providers and profiles should be configured in YAML and resolved by the configuration loader before composition.

Recommended YAML:

```yaml
llm:
  defaults:
    profile: default_chat
    timeout_seconds: 120
    stream_timeout_seconds: 300
    max_retries: 1
    trace_prompts: false
    trace_completions: false

  providers:
    local_qwen:
      type: openai_compatible
      enabled: true
      base_url: ${env:LOCAL_LLM_BASE_URL:http://192.168.1.80:8081/v1}
      api_key: ${env:LOCAL_LLM_API_KEY:}
      timeout_seconds: 120
      stream_timeout_seconds: 300
      headers:
        Content-Type: application/json

    openai_main:
      type: openai
      enabled: false
      api_key: ${env:OPENAI_API_KEY}
      timeout_seconds: 120

    google_main:
      type: google
      enabled: false
      api_key: ${env:GOOGLE_API_KEY}
      timeout_seconds: 120

    custom_reasoner:
      type: custom_http
      enabled: false
      endpoint: ${env:CUSTOM_REASONER_URL}
      auth_header: Authorization
      auth_token: ${env:CUSTOM_REASONER_TOKEN}

  profiles:
    default_chat:
      provider: local_qwen
      model: qwen3.5-27b-claude-4.6-opus-reasoning-distilled-i1
      temperature: 0.7
      max_output_tokens: 2048
      supports_streaming: true
      supports_json_schema: false
      allowed_for:
        usecases: [default]
        agents: [support_agent, document_qa_agent]
        strategies: [direct_agent]
      fallback_profiles: []

    orchestration_router:
      provider: local_qwen
      model: qwen3.5-27b-claude-4.6-opus-reasoning-distilled-i1
      temperature: 0.2
      max_output_tokens: 1024
      supports_streaming: false
      allowed_for:
        usecases: [default]
        agents: []
        strategies: [router_strategy]
      fallback_profiles:
        - default_chat

    reviewer_precise:
      provider: openai_main
      model: ${env:OPENAI_REVIEW_MODEL:}
      temperature: 0.1
      max_output_tokens: 2048
      supports_streaming: true
      allowed_for:
        usecases: [review]
        agents: [reviewer_agent]
        strategies: [direct_agent]
      fallback_profiles:
        - default_chat
```

### 9.1 Local OpenAI-Compatible Example

The local model call below is represented as configuration, not hard-coded inside agents:

```bash
curl http://192.168.1.80:8081/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3.5-27b-claude-4.6-opus-reasoning-distilled-i1",
    "messages": [
      {"role": "system", "content": "You are a helpful assistant."},
      {"role": "user", "content": "Hello!"}
    ],
    "temperature": 0.7
  }'
```

The adapter is responsible for converting a provider-neutral `LLMRequest` into this provider's expected wire format.

### 9.2 Profile Resolution Rule

Profile resolution should follow this order:

```text
1. Explicit profile requested by strategy or agent, if policy allows it.
2. Agent-specific profile from YAML.
3. Strategy-specific profile from YAML.
4. Use-case default profile from YAML.
5. Application default profile.
6. Fail with `LLMProfileResolutionError`.
```

### 9.3 Configuration Safety Rule

The capabilities route may expose safe logical profile names only if needed by the frontend.

Do not expose:

```text
api_key
access token
authorization header
provider credentials
connection strings
private base URLs when sensitive
raw deployment internals
```

---

## 10. Typed LLM Settings

Recommended dataclasses:

```python
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class LLMDefaultsSettings:
    profile: str
    timeout_seconds: int
    stream_timeout_seconds: int
    max_retries: int
    trace_prompts: bool = False
    trace_completions: bool = False


@dataclass(frozen=True, slots=True)
class LLMProviderSettings:
    name: str
    type: str
    enabled: bool
    base_url: str | None = None
    endpoint: str | None = None
    api_key: str | None = None
    auth_header: str | None = None
    auth_token: str | None = None
    timeout_seconds: int = 120
    stream_timeout_seconds: int = 300
    headers: dict[str, str] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class LLMProfileSettings:
    name: str
    provider: str
    model: str
    temperature: float | None = None
    top_p: float | None = None
    max_output_tokens: int | None = None
    timeout_seconds: int | None = None
    stream_timeout_seconds: int | None = None
    supports_streaming: bool = True
    supports_json_schema: bool = False
    supports_tool_calling: bool = False
    allowed_for: dict[str, list[str]] = field(default_factory=dict)
    fallback_profiles: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class LLMSettings:
    defaults: LLMDefaultsSettings
    providers: dict[str, LLMProviderSettings]
    profiles: dict[str, LLMProfileSettings]
```

### 10.1 Settings Validation

Configuration validation should fail fast when:

- Default profile is missing.
- A profile references an unknown provider.
- A provider type is unknown.
- A provider is disabled but referenced by an enabled profile without fallback.
- Temperature, top-p, timeout, retry, or token limits are outside allowed ranges.
- Fallback profile cycles exist.
- `supports_streaming: false` is used for a streaming-required route/profile without fallback.
- Required credentials are missing for enabled cloud providers.
- Provider base URL or endpoint is malformed.

---

## 11. Public LLM Gateway Interface

Recommended interface:

```python
from collections.abc import AsyncIterator
from typing import Protocol


class LLMGateway(Protocol):
    async def complete(
        self,
        *,
        request: "LLMRequest",
        context: "RequestContext",
    ) -> "LLMResponse":
        ...

    async def stream(
        self,
        *,
        request: "LLMRequest",
        context: "RequestContext",
    ) -> AsyncIterator["LLMStreamEvent"]:
        ...

    async def health(self) -> "LLMHealthResult":
        ...

    async def list_profiles(self) -> list["LLMProfileSummary"]:
        ...
```

### 11.1 Method Ownership

| Method | Purpose |
|---|---|
| `complete` | Execute a non-streaming model call and return a normalized response. |
| `stream` | Execute a streaming model call and yield normalized stream events. |
| `health` | Check configured provider/profile readiness safely. |
| `list_profiles` | Return safe logical profile metadata for internal services. |

### 11.2 Gateway Call Flow

```text
1. Receive LLMRequest and RequestContext.
2. Resolve requested/default logical profile.
3. Check profile/provider enabled status.
4. Check policy for usecase, strategy, and agent profile access.
5. Validate request against model/profile capabilities.
6. Redact and record `llm_call_started` trace event.
7. Call provider adapter with concrete provider request.
8. Normalize provider response or stream events.
9. Record success/failure/fallback trace events.
10. Return normalized LLMResponse or LLMStreamEvent sequence.
```

---

## 12. LLM Request and Response Models

Recommended provider-neutral request model:

```python
from dataclasses import dataclass, field
from typing import Any, Literal


LLMRole = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True, slots=True)
class LLMContentPart:
    type: Literal["text", "image_url", "json"]
    text: str | None = None
    image_url: str | None = None
    json_value: Any | None = None


@dataclass(frozen=True, slots=True)
class LLMMessage:
    role: LLMRole
    content: str | list[LLMContentPart]
    name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class LLMRequest:
    messages: list[LLMMessage]
    profile: str | None = None
    temperature: float | None = None
    top_p: float | None = None
    max_output_tokens: int | None = None
    response_format: "LLMResponseFormat | None" = None
    stream: bool = False
    timeout_seconds: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

Recommended response model:

```python
@dataclass(frozen=True, slots=True)
class LLMTokenUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class LLMResponse:
    text: str
    profile: str
    provider: str
    model: str
    finish_reason: str | None = None
    usage: LLMTokenUsage | None = None
    raw_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

### 12.1 Response Format Model

Structured output can be expressed without exposing provider-specific syntax to agents:

```python
@dataclass(frozen=True, slots=True)
class LLMResponseFormat:
    type: Literal["text", "json_object", "json_schema"] = "text"
    schema_name: str | None = None
    json_schema: dict[str, Any] | None = None
    strict: bool = False
```

Provider adapters translate this into the provider's supported structured-output format when available.

### 12.2 Request Metadata

Allowed metadata examples:

```text
agent_name
strategy_name
usecase
operation
trace_id
session_id
request_id
```

Metadata must not include:

```text
api keys
authorization headers
raw provider credentials
cookies
JWTs
raw workflow state
full tool payloads
hidden scratchpads
```

---

## 13. Stream Event Contract

The gateway should normalize provider stream chunks into backend events.

Recommended stream events:

```python
from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(frozen=True, slots=True)
class LLMStreamEvent:
    type: Literal[
        "started",
        "delta",
        "metadata",
        "completed",
        "error",
    ]
    text: str | None = None
    profile: str | None = None
    provider: str | None = None
    model: str | None = None
    finish_reason: str | None = None
    usage: LLMTokenUsage | None = None
    error: "LLMErrorDetail | None" = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

### 13.1 Gateway-to-Session Streaming Path

```text
Provider stream chunk
  -> ProviderAdapter normalizes provider chunk
  -> LLMGateway yields LLMStreamEvent
  -> Agent/Strategy maps to OrchestrationStreamEvent
  -> SessionService maps to SessionStreamEvent
  -> API maps to SSE event
```

### 13.2 Streaming Safety Rule

LLM stream events must not expose:

- Provider raw event objects.
- Provider headers.
- Authorization details.
- Raw tool-call payloads.
- Hidden scratchpad or chain-of-thought fields.
- Full provider error payloads.

Only safe deltas, finish reason, usage, and bounded metadata should flow upward.

---

## 14. Provider Adapter Interface

Recommended interface:

```python
from collections.abc import AsyncIterator
from typing import Protocol


class LLMProviderAdapter(Protocol):
    name: str
    provider_type: str

    async def complete(
        self,
        *,
        request: "ResolvedLLMRequest",
    ) -> "ProviderLLMResponse":
        ...

    async def stream(
        self,
        *,
        request: "ResolvedLLMRequest",
    ) -> AsyncIterator["ProviderLLMStreamEvent"]:
        ...

    async def health(self) -> "ProviderHealthResult":
        ...

    def capabilities(self) -> "ProviderCapabilities":
        ...
```

### 14.1 Resolved Request

`ResolvedLLMRequest` contains concrete provider/model configuration and should not be visible to agents:

```python
@dataclass(frozen=True, slots=True)
class ResolvedLLMRequest:
    profile: LLMProfileSettings
    provider: LLMProviderSettings
    model: str
    messages: list[LLMMessage]
    temperature: float | None
    top_p: float | None
    max_output_tokens: int | None
    response_format: LLMResponseFormat | None
    stream: bool
    timeout_seconds: int
    trace_id: str
    session_id: str
    metadata: dict[str, Any] = field(default_factory=dict)
```

### 14.2 Adapter Responsibility

Provider adapters own:

- Provider-specific request body mapping.
- Provider-specific auth header construction.
- Provider-specific timeout handling.
- Provider-specific streaming chunk parsing.
- Provider-specific response normalization into gateway-internal models.
- Provider-specific error mapping into normalized errors.

Provider adapters must not own:

- Agent selection.
- Strategy selection.
- Tool execution.
- Memory search.
- Workflow state persistence.
- API response formatting.

---

## 15. Provider Types

Recommended V1 provider types:

| Provider Type | Purpose |
|---|---|
| `openai_compatible` | Local/custom runtimes that implement `/v1/chat/completions`. |
| `openai` | Native OpenAI adapter, optional. |
| `google` | Native Google adapter, optional. |
| `custom_http` | Custom provider-specific HTTP contract. |
| `fake` | Deterministic provider for tests. |

### 15.1 OpenAI-Compatible Adapter

The OpenAI-compatible adapter should support local runtimes and custom HTTP servers that expose an OpenAI-style chat-completions endpoint.

Default endpoint construction:

```text
{base_url}/chat/completions
```

Example resolved provider config:

```yaml
providers:
  local_qwen:
    type: openai_compatible
    base_url: http://192.168.1.80:8081/v1
```

The adapter should generate a request shaped like:

```json
{
  "model": "qwen3.5-27b-claude-4.6-opus-reasoning-distilled-i1",
  "messages": [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "Hello!"}
  ],
  "temperature": 0.7,
  "stream": false
}
```

### 15.2 Native OpenAI Adapter

The native OpenAI adapter may use the official SDK or direct HTTP internally, but that implementation detail must stay inside `providers/openai.py`.

Agents, strategies, API routes, and session code must never import or instantiate the OpenAI SDK.

### 15.3 Native Google Adapter

The native Google adapter may use the official SDK or direct HTTP internally, but that implementation detail must stay inside `providers/google.py`.

Agents, strategies, API routes, and session code must never import or instantiate the Google SDK.

### 15.4 Custom HTTP Adapter

The custom HTTP adapter is for provider-specific runtimes that are not OpenAI-compatible.

It should require explicit mapping configuration rather than guessing provider behavior.

Recommended rule:

```text
If a custom runtime can implement OpenAI-compatible chat completions, prefer `openai_compatible` over `custom_http`.
```

### 15.5 Fake Adapter

The fake adapter should be deterministic and should support both `complete` and `stream`.

Example behavior:

```text
Input: "hello"
Output: "fake response: hello"
```

Use fake adapters for API/session/orchestration tests that do not need real provider calls.

---

## 16. Profile Resolver

The profile resolver maps a logical profile name to provider/model/runtime settings.

Recommended interface:

```python
class LLMProfileResolver:
    def resolve(
        self,
        *,
        requested_profile: str | None,
        usecase: str | None,
        agent_name: str | None,
        strategy_name: str | None,
        streaming_required: bool,
    ) -> LLMProfileResolution:
        ...
```

Recommended result:

```python
@dataclass(frozen=True, slots=True)
class LLMProfileResolution:
    profile: LLMProfileSettings
    provider: LLMProviderSettings
    fallback_chain: list[str]
    reason: str
```

### 16.1 Resolution Inputs

| Input | Source |
|---|---|
| `requested_profile` | Agent/strategy request or use-case configuration. |
| `usecase` | `RequestContext.usecase`. |
| `agent_name` | Current agent metadata. |
| `strategy_name` | Current strategy metadata. |
| `streaming_required` | Gateway method or orchestration request. |

### 16.2 Resolution Validation

The resolver should validate:

- Profile exists.
- Provider exists.
- Provider is enabled.
- Profile is allowed for current use case, agent, and strategy.
- Profile supports streaming if streaming is required.
- Profile has a valid fallback chain if primary provider is unavailable.

### 16.3 Fallback Cycle Prevention

Fallback profile chains must be acyclic.

Invalid example:

```text
profile_a -> profile_b -> profile_a
```

The configuration loader should reject this at startup.

---

## 17. Policy Integration

The LLM gateway should call policy before provider execution.

Recommended policy check:

```python
allowed = await policy.can_use_llm_profile(
    user_id=context.user_id,
    session_id=context.session_id,
    usecase=context.usecase,
    agent_name=request.metadata.get("agent_name"),
    strategy_name=request.metadata.get("strategy_name"),
    profile=resolved.profile.name,
    provider=resolved.provider.name,
    model=resolved.profile.model,
)
```

### 17.1 V1 Policy Defaults

Recommended V1 defaults:

```text
Deny unknown profiles.
Deny disabled providers.
Deny disabled profiles.
Allow only configured profile/usecase/agent/strategy combinations.
Deny direct provider/model override from user metadata.
Deny raw provider parameters not listed in the profile schema.
Trace all LLM calls with safe metadata.
Do not trace raw prompts/completions by default.
```

### 17.2 User-Supplied Model Override Rule

User input must not be allowed to directly select arbitrary provider/model values.

Allowed:

```text
Agent requests logical profile `research_reasoning`.
Configuration maps profile to provider/model.
Policy approves use.
```

Avoid:

```text
User sends metadata.model = "expensive-or-unauthorized-model".
Gateway calls that model directly.
```

---

## 18. Orchestration Integration

The orchestration runtime injects `LLMGateway` into `OrchestrationContext`.

Recommended context shape:

```python
@dataclass
class OrchestrationContext:
    request: RequestContext
    llm: LLMGateway
    memory: "MemoryGateway"
    state: "WorkflowStateStore"
    tools: "ToolGateway"
    trace: "TraceStore"
    policy: "PolicyService"
    config: dict[str, Any]
```

### 18.1 Strategy Usage

A router strategy may use a profile configured for orchestration:

```python
router_result = await context.llm.complete(
    request=LLMRequest(
        profile="orchestration_router",
        messages=router_messages,
        temperature=0.2,
        metadata={"strategy_name": "router_strategy", "operation": "route"},
    ),
    context=context.request,
)
```

### 18.2 Agent Usage

An agent may use its configured profile:

```python
answer = await context.llm.complete(
    request=LLMRequest(
        profile=None,  # resolver can use agent/use-case default
        messages=agent_messages,
        metadata={"agent_name": self.name, "operation": "answer"},
    ),
    context=context.request,
)
```

### 18.3 Session Service Boundary Reminder

`SessionService` does not call `LLMGateway` directly.

Correct:

```text
SessionService -> OrchestrationRuntime -> LLMGateway
```

Avoid:

```text
SessionService -> LLMGateway.complete
```

If future history compression needs an LLM, implement it through orchestration or a dedicated summarization service that uses `LLMGateway` behind a clear boundary.

---

## 19. Message Construction Boundary

The LLM gateway should not own business prompt construction.

Prompt construction belongs to:

```text
Strategy
Agent
Future PromptBuilder / PromptTemplateService
```

The gateway may own:

- Message validation.
- Provider-specific message conversion.
- Capability checks.
- Request redaction before tracing/logging.
- Token budget estimation.

The gateway must not silently inject hidden business instructions except for infrastructure-required provider formatting.

### 19.1 System Message Rule

System messages should be composed by strategy/agent/prompt service according to use-case configuration.

The gateway should treat messages as input, not author the business behavior.

### 19.2 Hidden Chain-of-Thought Rule

The gateway must not request or expose hidden chain-of-thought. If a provider returns internal reasoning fields, provider adapters must discard or redact them unless a future policy explicitly defines safe handling.

---

## 20. Response Normalization

Provider adapters normalize provider responses into `LLMResponse`.

Normalized fields:

| Field | Meaning |
|---|---|
| `text` | User-visible assistant text or structured-output text. |
| `profile` | Logical profile used. |
| `provider` | Logical provider name. |
| `model` | Configured model identifier; safe internal metadata. |
| `finish_reason` | Normalized finish reason such as `stop`, `length`, `error`, `cancelled`. |
| `usage` | Token usage if provider returns it. |
| `raw_id` | Provider response ID if safe and useful. |
| `metadata` | Bounded safe diagnostics. |

### 20.1 Finish Reason Normalization

Recommended normalized finish reasons:

```text
stop
length
content_filter
tool_call
error
timeout
cancelled
unknown
```

### 20.2 Usage Normalization

If provider usage is unavailable, leave usage fields as `None`.

Do not invent token counts unless using a clearly labeled local estimator.

---

## 21. Tool Calling Boundary

The LLM gateway may support provider tool-call response parsing as a model capability, but it must not execute tools.

Correct path for executing tools:

```text
Agent/Strategy receives model-intended tool request
  -> OrchestrationRuntime validates flow
  -> ToolGateway enforces policy
  -> MCPClientAdapter calls Single MCP Server
```

Avoid:

```text
LLMGateway -> MCPClientAdapter
LLMGateway -> external tool API
LLMGateway -> memory_store
```

### 21.1 V1 Recommendation

For V1, prefer explicit agent/strategy-controlled tool planning rather than provider-native auto-tool execution.

If provider-native tool-call structures are used later, normalize them into safe intent objects and route execution through `ToolGateway`.

---

## 22. Memory Boundary

The LLM gateway must not search or write memory.

Correct memory path:

```text
OrchestrationRuntime / Agent -> MemoryGateway -> MemoryStoreAdapter -> memory_store -> ArcadeDB
```

Avoid:

```text
LLMGateway -> MemoryGateway.search
LLMGateway -> memory_store.service.MemoryService
LLMGateway -> ArcadeDB
```

### 22.1 Prompt Context Rule

Agents or strategies may include memory results in messages sent to the LLM gateway.

The gateway treats those messages as input and may validate/redact trace metadata, but it does not decide which memories to retrieve.

---

## 23. Timeout, Retry, and Fallback Behavior

LLM calls should be bounded.

Recommended timeout order:

```text
request.timeout_seconds
profile.timeout_seconds
provider.timeout_seconds
llm.defaults.timeout_seconds
```

Streaming timeout order:

```text
request.timeout_seconds
profile.stream_timeout_seconds
provider.stream_timeout_seconds
llm.defaults.stream_timeout_seconds
```

### 23.1 Retry Policy

Retries should be conservative by default.

Recommended retryable conditions:

```text
transient network failure
provider timeout before response started
HTTP 429 / rate limit if provider indicates retryable
HTTP 502 / 503 / 504
connection reset before response started
```

Recommended non-retryable conditions:

```text
invalid profile
policy denied
bad request generated by gateway
unsupported capability
invalid credentials
context length exceeded unless fallback compression exists
provider returns content policy rejection
```

### 23.2 Fallback Policy

Fallback should be explicit and configured per profile.

Recommended behavior:

```text
1. Try primary profile.
2. If retryable failure occurs, apply retry policy for primary profile.
3. If still failing and fallback_profiles exist, resolve next fallback profile.
4. Re-check policy for fallback profile.
5. Record `llm_fallback_selected` trace event.
6. Execute fallback.
7. Return response with metadata indicating fallback was used.
```

### 23.3 Fallback Safety Rule

Do not fallback to a profile that violates:

- Use-case restrictions.
- Agent restrictions.
- Strategy restrictions.
- Data locality requirements.
- Privacy policy.
- Streaming requirement.
- Structured-output requirement.

---

## 24. Token Budgets and Context Limits

The gateway should enforce configured request-size and output-size limits.

Recommended profile fields:

```yaml
profiles:
  default_chat:
    max_input_tokens: 24000
    max_output_tokens: 2048
    max_total_tokens: 32000
```

### 24.1 Gateway Responsibilities

The gateway may:

- Estimate message size.
- Reject obviously oversized requests.
- Enforce `max_output_tokens`.
- Include safe size metadata in trace events.
- Return a normalized `LLMContextLengthError`.

The gateway should not:

- Decide which memories to remove.
- Compress conversation history by itself.
- Rewrite agent prompts silently.
- Truncate user input without explicit strategy/session policy.

### 24.2 Context Compression Boundary

Context compression belongs to:

```text
Session history policy
Orchestration strategy
Agent prompt builder
Future summarization service
```

The gateway may report that input is too large and expose safe token/character estimates to the caller.

---

## 25. Observability and Trace Integration

The LLM gateway should emit safe trace events through the observability facade or `TraceStore` interface.

Recommended trace events:

| Event | Emitted By | Notes |
|---|---|---|
| `llm_profile_resolved` | `ProfileResolver` / gateway | Logical profile/provider/model metadata only. |
| `llm_policy_checked` | Gateway/policy facade | Allowed/denied summary only. |
| `llm_call_started` | Gateway | No raw prompt by default. |
| `llm_call_completed` | Gateway | Duration, finish reason, usage if available. |
| `llm_call_failed` | Gateway | Safe error type/code only. |
| `llm_stream_started` | Gateway | Streaming metadata only. |
| `llm_stream_completed` | Gateway | Duration, finish reason, usage if available. |
| `llm_stream_cancelled` | Gateway | Cancellation summary. |
| `llm_retry_scheduled` | Gateway | Attempt number and retry reason. |
| `llm_fallback_selected` | Gateway | Source/target logical profile names. |
| `llm_provider_health_checked` | Health service/gateway | Safe status summary. |

### 25.1 Safe Trace Payload Example

```json
{
  "event_name": "llm_call_completed",
  "trace_id": "trace_...",
  "payload": {
    "profile": "default_chat",
    "provider": "local_qwen",
    "model": "qwen3.5-27b-claude-4.6-opus-reasoning-distilled-i1",
    "duration_ms": 1420,
    "input_message_count": 4,
    "input_chars": 3200,
    "output_chars": 980,
    "finish_reason": "stop",
    "input_tokens": null,
    "output_tokens": null,
    "fallback_used": false
  }
}
```

### 25.2 Unsafe Trace Payload Example

```json
{
  "messages": [
    {"role": "user", "content": "full private user prompt..."}
  ],
  "api_key": "...",
  "authorization": "Bearer ...",
  "raw_provider_response": {...}
}
```

### 25.3 Metrics

Recommended metrics:

```text
backend.llm.calls.total
backend.llm.calls.duration_ms
backend.llm.calls.in_flight
backend.llm.calls.failed_total
backend.llm.streams.total
backend.llm.streams.duration_ms
backend.llm.streams.cancelled_total
backend.llm.retries.total
backend.llm.fallbacks.total
backend.llm.tokens.input_total
backend.llm.tokens.output_total
```

Allowed metric tags:

```text
profile
provider
model_family or safe model label
status
error_type
streaming
fallback_used
```

Avoid metric tags:

```text
session_id
trace_id
raw_user_id
full model endpoint
prompt text
completion text
API key
```

---

## 26. Privacy and Redaction

The LLM gateway must assume prompts and completions can contain user-sensitive data.

Default behavior:

```text
Do not log raw prompts.
Do not log raw completions.
Do not store raw prompts in trace events.
Do not store raw completions in trace events.
Do not return provider error bodies verbatim.
Do not expose provider credentials or headers.
```

### 26.1 Redaction Targets

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

### 26.2 Debug Capture

Optional prompt/completion capture must be disabled by default.

If enabled in a local development profile, it should require explicit configuration:

```yaml
llm:
  defaults:
    trace_prompts: false
    trace_completions: false
```

A future policy document should define whether prompt/completion capture can ever be enabled outside local development.

---

## 27. Error Model

Recommended LLM errors:

```python
class LLMError(Exception):
    code: str
    retryable: bool


class LLMProfileResolutionError(LLMError): ...
class LLMPolicyDeniedError(LLMError): ...
class LLMProviderUnavailableError(LLMError): ...
class LLMProviderTimeoutError(LLMError): ...
class LLMRateLimitError(LLMError): ...
class LLMAuthenticationError(LLMError): ...
class LLMBadRequestError(LLMError): ...
class LLMUnsupportedCapabilityError(LLMError): ...
class LLMContextLengthError(LLMError): ...
class LLMMalformedResponseError(LLMError): ...
class LLMStreamingError(LLMError): ...
class LLMCancelledError(LLMError): ...
```

### 27.1 Error Mapping

| Gateway Error | Retryable | API Mapping Later |
|---|---:|---|
| `LLMProfileResolutionError` | false | `400 unknown_llm_profile` or config error |
| `LLMPolicyDeniedError` | false | `403 policy_denied` |
| `LLMProviderUnavailableError` | true | `503 llm_unavailable` |
| `LLMProviderTimeoutError` | true | `504 llm_timeout` |
| `LLMRateLimitError` | true | `503 llm_rate_limited` |
| `LLMAuthenticationError` | false | `503 llm_authentication_failed` internally; do not expose credentials |
| `LLMBadRequestError` | false | `500 llm_bad_request` if generated internally |
| `LLMUnsupportedCapabilityError` | false | `400 unsupported_llm_capability` or config error |
| `LLMContextLengthError` | false unless compression fallback exists | `400 context_too_large` |
| `LLMMalformedResponseError` | true/false by provider | `502 llm_malformed_response` |
| `LLMStreamingError` | true/false by stage | SSE `response.error` through session/API |
| `LLMCancelledError` | false | cancellation path, normally no user-visible error |

### 27.2 Error Safety Rule

Normalized LLM errors must not expose:

- Raw provider response body.
- Raw provider request body.
- Authorization headers.
- API keys.
- Stack traces.
- Raw prompt text.
- Raw completion text.

---

## 28. Health Integration

The LLM gateway should expose safe health status for providers and profiles.

Recommended result:

```python
@dataclass(frozen=True, slots=True)
class LLMHealthResult:
    status: str
    providers_configured: bool
    profiles_configured: bool
    default_profile: str | None
    providers: dict[str, "ProviderHealthSummary"]
    profiles: dict[str, "ProfileHealthSummary"]
```

Recommended health response section:

```json
{
  "llm": {
    "status": "ok",
    "providers_configured": true,
    "profiles_configured": true,
    "default_profile": "default_chat",
    "providers": {
      "local_qwen": {
        "status": "ok",
        "type": "openai_compatible",
        "enabled": true
      }
    },
    "profiles": {
      "default_chat": {
        "status": "ok",
        "provider": "local_qwen",
        "enabled": true,
        "supports_streaming": true
      }
    }
  }
}
```

### 28.1 Health Safety Rule

Health output must not include:

```text
api_key
authorization header
provider tokens
private credentials
full base URL if classified sensitive
raw provider health response
raw exception stack trace
```

### 28.2 Health Check Depth

Recommended V1 behavior:

```text
Startup validation checks configuration shape.
Health route reports provider/profile configured status.
Optional deep provider ping is configurable and disabled by default if it causes model load or cost.
```

---

## 29. Capabilities Integration

The capabilities service may include safe LLM feature flags.

Recommended capability section:

```json
{
  "llm": {
    "enabled": true,
    "default_profile": "default_chat",
    "streaming_supported": true,
    "structured_output_supported": false,
    "available_logical_profiles": [
      "default_chat",
      "orchestration_router"
    ]
  }
}
```

### 29.1 Capability Safety Rule

Expose only frontend-safe logical names and feature flags.

Do not expose:

```text
provider URLs
API keys
provider account names
raw model credentials
private deployment details
```

If logical profile names reveal sensitive information, expose display labels instead.

---

## 30. Composition Root Integration

The composition root builds provider adapters and injects `LLMGateway` into orchestration.

Recommended startup sequence:

```text
1. Load settings and YAML configuration.
2. Validate LLM provider and profile config.
3. Build redactor and observability recorder.
4. Build policy service.
5. Build provider adapters from `llm.providers`.
6. Register provider adapters in `ProviderRegistry`.
7. Build `LLMProfileResolver`.
8. Build `LLMGateway`.
9. Build orchestration runtime with `llm=llm_gateway`.
10. Build session service with orchestration runtime.
11. Build API app.
12. Log redacted LLM startup summary.
```

### 30.1 Composition Example

```python
def build_llm_gateway(config, policy, observability) -> LLMGateway:
    provider_registry = ProviderRegistry()

    for provider_name, provider_config in config.llm.providers.items():
        if not provider_config.enabled:
            continue

        adapter = build_provider_adapter(provider_config)
        provider_registry.register(provider_name, adapter)

    resolver = LLMProfileResolver(
        defaults=config.llm.defaults,
        providers=config.llm.providers,
        profiles=config.llm.profiles,
    )

    return DefaultLLMGateway(
        settings=config.llm,
        resolver=resolver,
        providers=provider_registry,
        policy=policy,
        observability=observability,
        redactor=observability.redactor,
    )
```

### 30.2 Redacted Startup Summary

Safe startup log:

```json
{
  "event": "llm_gateway_configured",
  "providers": ["local_qwen"],
  "profiles": ["default_chat", "orchestration_router"],
  "default_profile": "default_chat"
}
```

Unsafe startup log:

```json
{
  "api_key": "...",
  "headers": {"Authorization": "Bearer ..."},
  "connection_string": "..."
}
```

---

## 31. Provider Registry

The provider registry maps configured provider names to concrete adapters.

Recommended behavior:

```python
class ProviderRegistry:
    def register(self, name: str, adapter: LLMProviderAdapter) -> None: ...
    def get(self, name: str) -> LLMProviderAdapter: ...
    def list_names(self) -> list[str]: ...
```

### 31.1 Registration Rules

- Provider names must be unique.
- Disabled providers should not be registered unless health needs to report disabled state separately.
- Unknown provider type should fail startup validation.
- Provider adapter construction should not perform expensive model calls by default.

---

## 32. OpenAI-Compatible Provider Adapter Design

The OpenAI-compatible adapter is the most important V1 adapter because it supports local/custom runtimes.

Recommended responsibilities:

- Build endpoint URL from `base_url`.
- Convert `LLMMessage` into OpenAI-compatible message objects.
- Map profile fields to request body.
- Add configured headers and auth header if present.
- Support non-streaming calls.
- Support streaming calls when provider supports streaming.
- Normalize response text and finish reason.
- Normalize token usage if returned.
- Normalize errors.

### 32.1 Non-Streaming Request Mapping

Provider-neutral:

```python
LLMRequest(
    profile="default_chat",
    messages=[
        LLMMessage(role="system", content="You are a helpful assistant."),
        LLMMessage(role="user", content="Hello!"),
    ],
    temperature=0.7,
)
```

OpenAI-compatible body:

```json
{
  "model": "qwen3.5-27b-claude-4.6-opus-reasoning-distilled-i1",
  "messages": [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "Hello!"}
  ],
  "temperature": 0.7,
  "stream": false
}
```

### 32.2 Streaming Request Mapping

```json
{
  "model": "qwen3.5-27b-claude-4.6-opus-reasoning-distilled-i1",
  "messages": [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "Hello!"}
  ],
  "temperature": 0.7,
  "stream": true
}
```

### 32.3 Adapter Output

The adapter should not return provider JSON to callers.

It returns normalized gateway-internal response models, which the gateway converts into public `LLMResponse` or `LLMStreamEvent` objects.

---

## 33. Structured Output

Structured output should be expressed as `LLMResponseFormat`, not provider-specific parameters in agent code.

Example:

```python
LLMRequest(
    profile="orchestration_router",
    messages=messages,
    response_format=LLMResponseFormat(
        type="json_schema",
        schema_name="route_decision",
        json_schema={
            "type": "object",
            "properties": {
                "agent_name": {"type": "string"},
                "reason": {"type": "string"}
            },
            "required": ["agent_name"]
        },
        strict=True,
    ),
)
```

### 33.1 Capability Handling

If the selected profile/provider does not support JSON schema:

```text
1. Use provider-native JSON schema if supported.
2. Use profile fallback if configured and policy allows.
3. Otherwise fail with `LLMUnsupportedCapabilityError`.
```

Avoid silently downgrading strict structured output to plain text.

---

## 34. Streaming Lifecycle and Cancellation

Streaming requires explicit cancellation handling across layers.

Recommended lifecycle:

```text
1. Gateway emits `LLMStreamEvent(type="started")`.
2. Provider adapter opens stream.
3. Provider chunks are normalized into `delta` events.
4. Cancellation is detected from caller or HTTP disconnect upstream.
5. Gateway closes provider stream where possible.
6. Gateway records `llm_stream_cancelled` or `llm_stream_completed`.
7. Gateway yields final `completed` or `error` event when safe.
```

### 34.1 Save Boundary Reminder

Workflow state is not saved by the LLM gateway.

For streaming chat:

```text
API detects client disconnect.
SessionService handles stream finalization.
OrchestrationRuntime/Agent handles model cancellation.
LLMGateway cancels provider call.
SessionService decides whether/how to save workflow state.
```

### 34.2 Streaming Delta Rule

Do not trace or log every token/delta by default.

Trace lifecycle milestones instead:

```text
llm_stream_started
llm_stream_first_delta
llm_stream_completed
llm_stream_cancelled
llm_stream_failed
```

---

## 35. Concurrency and Resource Control

The gateway should support concurrent calls but enforce configured resource limits.

Recommended future settings:

```yaml
llm:
  concurrency:
    max_in_flight_total: 8
    max_in_flight_per_provider: 4
    max_in_flight_per_session: 2
```

### 35.1 V1 Recommendation

For V1, implement simple concurrency guards only if needed.

At minimum:

- Use per-call timeouts.
- Respect cancellation.
- Do not share mutable request state between calls.
- Keep provider clients thread-safe or create scoped clients safely.

### 35.2 Session-Level Concurrency

Session-level conflict handling remains in `SessionService` and `WorkflowStateStore`, not the LLM gateway.

---

## 36. Security

### 36.1 Credential Handling

Provider credentials should come from environment-resolved configuration.

Provider adapters may receive resolved secrets, but secrets must not be:

- Logged.
- Stored in trace events.
- Returned in health/capabilities.
- Passed to agents.
- Persisted in workflow state.

### 36.2 Header Handling

Provider adapters construct provider auth headers internally.

Agents must not pass provider headers.

### 36.3 Request Parameter Allowlist

The gateway should accept only known request parameters:

```text
messages
profile
temperature
top_p
max_output_tokens
response_format
stream
timeout_seconds
metadata
```

Provider-specific `extra` settings should come from trusted profile/provider config, not user request metadata.

---

## 37. Testing Strategy

### 37.1 Unit Tests

| Test | Purpose |
|---|---|
| Default profile resolves | Proves basic profile resolution. |
| Agent-specific profile resolves | Proves per-agent model selection. |
| Strategy-specific profile resolves | Proves orchestrator/router profile selection. |
| Unknown profile fails | Prevents accidental provider calls. |
| Disabled provider fails | Enforces config safety. |
| Fallback chain resolves | Proves fallback behavior. |
| Fallback cycle rejected | Prevents infinite resolution loops. |
| Policy denied blocks call | Enforces profile policy. |
| OpenAI-compatible request maps correctly | Proves local runtime compatibility. |
| Provider response normalizes | Prevents provider object leakage. |
| Streaming chunks normalize | Proves stream contract. |
| Timeout maps to normalized error | Proves error handling. |
| Rate limit maps to normalized error | Proves retry/fallback behavior. |
| Raw prompt not logged by default | Proves privacy behavior. |
| Secrets are redacted | Proves redaction behavior. |
| Health output hides credentials | Proves safe health response. |

### 37.2 Integration Tests

| Test | Purpose |
|---|---|
| Gateway starts with fake provider | Proves composition wiring. |
| Gateway completes with fake provider | Proves end-to-end non-streaming call. |
| Gateway streams with fake provider | Proves end-to-end stream call. |
| Orchestration uses gateway profile | Proves orchestration integration. |
| Agent uses configured profile | Proves agent profile routing. |
| Router strategy uses router profile | Proves strategy profile routing. |
| Fallback provider is used on fake failure | Proves fallback chain. |
| Trace events recorded for call | Proves observability. |
| API/session remain unchanged | Proves boundary stability. |

### 37.3 Optional Local Runtime Test

For environments with the local model server running:

```text
LLM provider: openai_compatible
Base URL: http://192.168.1.80:8081/v1
Model: qwen3.5-27b-claude-4.6-opus-reasoning-distilled-i1
```

This test should be marked optional or integration-local so CI does not depend on a private local runtime.

---

## 38. Fixture Configs

Recommended fixtures:

```text
tests/fixtures/config/llm_fake_basic.yaml
tests/fixtures/config/llm_fake_streaming.yaml
tests/fixtures/config/llm_fake_fallback.yaml
tests/fixtures/config/llm_openai_compatible_local.yaml
tests/fixtures/config/llm_disabled_provider.yaml
tests/fixtures/config/llm_unknown_profile.yaml
tests/fixtures/config/llm_policy_denied.yaml
tests/fixtures/config/llm_structured_output.yaml
tests/fixtures/config/llm_trace_capture_disabled.yaml
tests/fixtures/config/llm_trace_capture_enabled_local_only.yaml
```

---

## 39. Recommended Implementation Order

### Step 1: Add LLM Config Schemas

Deliverables:

- `LLMSettings`
- `LLMProviderSettings`
- `LLMProfileSettings`
- validation for providers/profiles/fallback chains

Success criteria:

- Valid fake/local config loads.
- Invalid profile/provider references fail fast.
- Secrets are environment-resolved but not logged.

### Step 2: Add LLM Models and Errors

Deliverables:

- `LLMMessage`
- `LLMContentPart`
- `LLMRequest`
- `LLMResponse`
- `LLMStreamEvent`
- `LLMResponseFormat`
- normalized LLM errors

Success criteria:

- Models serialize/validate cleanly.
- Errors expose safe code/retryable values.

### Step 3: Add Provider Adapter Protocol

Deliverables:

- `LLMProviderAdapter`
- `ProviderRegistry`
- provider health result model
- fake provider adapter

Success criteria:

- Gateway can call fake adapter without external dependencies.

### Step 4: Add Profile Resolver

Deliverables:

- profile resolution logic
- fallback chain validation
- streaming capability validation
- allowed usecase/agent/strategy validation hook

Success criteria:

- Default, agent, strategy, and explicit profiles resolve correctly.

### Step 5: Add Default LLMGateway

Deliverables:

- `complete`
- `stream`
- `health`
- `list_profiles`
- policy hook integration
- observability hook integration

Success criteria:

- Fake non-streaming and streaming calls work.
- Trace events are emitted safely.
- Policy denial blocks provider execution.

### Step 6: Add OpenAI-Compatible Adapter

Deliverables:

- request mapping for `/v1/chat/completions`
- non-streaming response parsing
- streaming event parsing
- timeout/error normalization

Success criteria:

- Adapter maps local runtime config into expected request body.
- Provider raw JSON does not leak upward.

### Step 7: Add Optional Provider Adapters

Deliverables:

- `OpenAIProviderAdapter` optional
- `GoogleProviderAdapter` optional
- `CustomHttpProviderAdapter` optional

Success criteria:

- Optional adapters are isolated.
- Missing optional dependencies do not break fake/local adapter tests.

### Step 8: Add Retry and Fallback

Deliverables:

- retry helper
- retryable error classification
- fallback profile execution
- fallback trace events

Success criteria:

- Retryable fake provider failure can fallback to configured profile.
- Policy is rechecked for fallback profile.

### Step 9: Add Orchestration Wiring

Deliverables:

- inject `LLMGateway` into `OrchestrationContext`
- update stub orchestrator or direct strategy to call gateway
- update agent examples to use logical profiles

Success criteria:

- `POST /chat` path can use fake or local LLM through orchestration without changing API/session code.

### Step 10: Add Health and Capabilities Integration

Deliverables:

- LLM health section
- safe profile/provider summaries
- optional capability flags

Success criteria:

- `/health` includes safe LLM readiness.
- `/capabilities` does not expose secrets.

---

## 40. Acceptance Criteria

This architecture is complete when:

- `LLMGateway` provides provider-neutral `complete`, `stream`, `health`, and `list_profiles` methods.
- Agents and strategies use `LLMGateway` through `OrchestrationContext` only.
- API routes do not call LLM providers or `LLMGateway` directly.
- `SessionService` does not call LLM providers or `LLMGateway` directly for normal chat behavior.
- Provider/model selection is driven by logical profiles in YAML.
- Each agent can be configured with a different LLM profile.
- Orchestrator/router strategies can use a separate LLM profile.
- Local OpenAI-compatible runtimes are supported through configuration.
- Custom/cloud providers are isolated behind provider adapters.
- Provider SDK response objects do not leak into agents, orchestration results, session results, API responses, workflow state, or traces.
- LLM calls are trace-correlated with `trace_id` and `session_id`.
- Trace events contain safe metadata only by default.
- Raw prompts and completions are not logged or traced by default.
- Provider credentials are never exposed in logs, traces, health, capabilities, API responses, or workflow state.
- Unknown profiles fail clearly.
- Unknown providers fail clearly.
- Disabled providers are not called.
- Policy denial prevents provider calls.
- Streaming provider chunks normalize into `LLMStreamEvent` objects.
- Provider failures normalize into stable backend errors.
- Retry and fallback behavior is explicit, bounded, and traceable.
- Fallback profiles are rechecked through policy.
- Health checks report safe provider/profile readiness.
- Fake provider tests can run without external services.
- Optional local runtime tests are isolated from CI.
- The backend is ready for the next document: `backend-memory-store-adapter-architecture.md`.

---

## 41. Anti-Patterns to Avoid

Avoid these during implementation:

- Hard-coding model names in agents.
- Hard-coding provider URLs in agents.
- Hard-coding local LLM endpoints in route handlers.
- Letting users directly choose arbitrary provider/model IDs through request metadata.
- Calling OpenAI, Google, local model endpoints, or custom provider endpoints from API routes.
- Calling LLM providers from `SessionService`.
- Importing provider SDKs in agents or strategies.
- Returning provider SDK responses from gateway methods.
- Storing raw provider responses in workflow state.
- Logging raw prompts by default.
- Logging raw completions by default.
- Tracing raw provider request bodies by default.
- Exposing provider credentials in health output.
- Exposing provider base URLs in capabilities if sensitive.
- Retrying non-idempotent or already-started streaming calls blindly.
- Falling back to unauthorized profiles.
- Silently downgrading strict structured output to plain text.
- Letting the LLM gateway execute MCP tools.
- Letting the LLM gateway search or write memory.
- Treating traces as long-term memory.
- Making provider health checks expensive by default.

---

## 42. Future Documents That Depend on This LLM Gateway

| Future Document | Dependency |
|---|---|
| `backend-memory-store-adapter-architecture.md` | Agents can use LLM output and memory results together, while memory remains behind `MemoryGateway`. |
| `backend-tooling-mcp-client-architecture.md` | LLM-generated tool intents must execute only through `ToolGateway` and MCP client adapter. |
| `backend-orchestration-architecture.md` | Runtime uses `LLMGateway` for router/planner/final-answer calls. |
| `backend-workflow-strategies-architecture.md` | Strategies can select configured logical LLM profiles without provider-specific code. |
| `backend-agents-architecture.md` | Agents define profile needs and prompt behavior while remaining provider-neutral. |
| `backend-policy-architecture.md` | Defines final LLM profile permissions, data locality constraints, prompt capture rules, and provider access control. |
| `backend-deployment-architecture.md` | Defines runtime process settings, provider credentials, local model endpoints, timeouts, and environment-specific LLM config. |

---

## 43. Summary

`backend-llm-gateway-architecture.md` defines the backend layer that gives orchestration, strategies, and agents provider-neutral access to local, custom, OpenAI-compatible, OpenAI, Google, and future LLM providers.

It preserves the previously defined API and session boundaries: API routes remain thin, `SessionService` remains lifecycle-focused, and LLM access happens only behind orchestration through `LLMGateway`.

The most important implementation rule is:

> **The LLM gateway owns provider access, not business workflow logic. Agents and strategies ask for logical profiles; the gateway resolves, validates, calls, traces, redacts, normalizes, retries, and falls back without leaking provider details into the rest of the backend.**
