# Backend Memory Store Adapter Architecture

**Document:** `backend-memory-store-adapter-architecture.md`  
**Version:** 1.0  
**Source alignment:** `backend-application-architecture.md`, `backend-foundation-architecture.md`, `backend-core-contracts-architecture.md`, `backend-configuration-architecture.md`, `backend-observability-architecture.md`, `backend-persistence-architecture.md`, `backend-sqlite-workflow-state-architecture.md`, `backend-sqlite-trace-store-architecture.md`, `backend-api-architecture.md`, `backend-session-service-architecture.md`, and `backend-llm-gateway-architecture.md`  
**Scope:** Provider-neutral backend memory access, `MemoryGateway`, `MemoryStoreAdapter`, integration with the existing `memory_store` Python wrapper, long-term agent memory, document chunk retrieval, deterministic document ingestion, hybrid search contracts, memory lifecycle operations, privacy controls, trace correlation, health checks, testing strategy, and acceptance criteria for the V1 memory layer.

---

## 1. Purpose

This document defines the eleventh implementation-focused architecture document for the backend application tier.

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
11. `backend-memory-store-adapter-architecture.md` ← this document

The previous document established `LLMGateway` as the only backend boundary that resolves logical LLM profiles into concrete provider/model/runtime calls. It also explicitly preserved the memory boundary: the LLM gateway must not search or write memory.

This document defines that memory boundary.

The goal is to allow orchestration strategies and agent plugins to search, retrieve, upsert, update, expire, forget, and ingest memory through backend-owned contracts without depending on ArcadeDB, FastEmbed, rerankers, vector indexes, BM25 indexes, or the concrete `memory_store` implementation.

The core architecture rule is:

> `MemoryGateway` is the only orchestration-facing boundary for long-term memory and document chunk access. `MemoryStoreAdapter` is the only backend adapter that calls the existing `memory_store` Python wrapper. Agents and strategies request normalized memory operations; they must not import ArcadeDB clients, vector search libraries, rerankers, or `memory_store.service.MemoryService` directly.

---

## 2. Source Architecture Alignment

This document follows the established backend rules:

- The backend is one deployable application tier in V1.
- Frontend communicates with backend through REST / SSE.
- API routes are thin and delegate chat/reset behavior to `SessionService`.
- `SessionService` calls `OrchestrationRuntime` and does not search or write long-term memory directly for normal chat behavior.
- `OrchestrationRuntime`, strategies, and agents access long-term memory through `MemoryGateway` only.
- `MemoryGateway` exposes provider-neutral memory contracts to the rest of the backend.
- `MemoryStoreAdapter` wraps the existing `memory_store` Python service.
- ArcadeDB remains behind the `memory_store` wrapper and must not leak into agents, strategies, API routes, session results, workflow state, or trace payloads.
- SQLite remains the backend store for workflow state and trace data only.
- ArcadeDB-backed memory is long-term project/user/document memory, not workflow state and not operational trace storage.
- Workflow state remains short-term session/runtime state.
- Traces remain operational diagnostics.
- Session reset clears workflow state only and must not delete memory or document chunks.
- LLM calls remain behind `LLMGateway`; the memory layer must not call concrete LLM providers directly.
- Tool/MCP access remains behind `ToolGateway`; the memory layer must not execute MCP tools.
- Memory operations must be trace-correlated with the active `trace_id`.
- Memory trace events must be safe, bounded, and redacted.
- Raw memory/document content must not be logged or traced by default.
- Memory scope, user scope, project scope, and privacy controls must be enforced before read/write/delete operations.
- Named project allowlists and defaults are configuration-owned at the use-case and agent layers; runtime memory operations resolve one effective `project_id` before adapter access rather than fanning one request across multiple projects.
- Search results returned to agents should be relevant memory records or document chunks, not entire documents by default.

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

This document expands Phase 11.

The output of this phase is a backend memory layer that supports:

```text
MemoryGateway.search(...)
MemoryGateway.get(...)
MemoryGateway.upsert(...)
MemoryGateway.promote(...)
MemoryGateway.supersede(...)
MemoryGateway.contradict(...)
MemoryGateway.expire(...)
MemoryGateway.forget(...)
MemoryGateway.ingest_document(...)
MemoryGateway.delete_by_scope(...)
MemoryGateway.export_by_scope(...)
MemoryGateway.health(...)
MemoryGateway.stats(...)

MemoryStoreAdapter.search(...)
MemoryStoreAdapter.get(...)
MemoryStoreAdapter.upsert(...)
MemoryStoreAdapter.ingest_document(...)
MemoryStoreAdapter.delete_by_scope(...)
MemoryStoreAdapter.export_by_scope(...)
```

The next document should be:

```text
backend-tooling-mcp-client-architecture.md
```

---

## 4. Architecture Goals

The memory layer should be:

1. **Backend-neutral to callers**  
   Agents and strategies use backend memory contracts, not ArcadeDB, FastEmbed, reranker, or `memory_store` implementation details.

2. **Adapter-based**  
   The existing `memory_store` Python wrapper is isolated behind `MemoryStoreAdapter`.

3. **Scope-aware**  
   Every operation carries scope metadata such as user, project, agent, use case, source, and session context where relevant.

4. **Search-focused**  
   Retrieval returns relevant memories and chunks with scores, provenance, and bounded content snippets.

5. **Lifecycle-aware**  
   Agent memory supports upsert, promote, supersede, contradict, expire, and forget behavior.

6. **Document-ingestion-aware**  
   Document chunks use deterministic IDs, source hashes, re-ingest skip/replace behavior, and removed-source handling.

7. **Privacy-aware**  
   Delete/export operations are scope-based and auditable without leaking raw content to logs/traces.

8. **Trace-correlated**  
   Memory operations emit safe trace events with the active `trace_id`.

9. **Configuration-driven**  
   Search defaults, index behavior, chunking defaults, score weights, result limits, and memory lifecycle defaults come from YAML.

10. **RAG-ready**  
    Orchestration and agents can retrieve memory/document chunks and include them in LLM messages through `LLMGateway`, while memory and LLM remain separate boundaries.

11. **Testable**  
    The gateway can run with fake adapters and deterministic fixture results.

12. **Replaceable**  
    If the internal memory implementation changes later, only `MemoryStoreAdapter` and configuration need to change.

---

## 5. Non-Goals

This document should not implement:

- API route behavior.
- Session lifecycle behavior.
- Full orchestration strategy behavior.
- Agent prompt design.
- LLM provider integration.
- Tool/MCP execution.
- MCP server implementation.
- SQLite workflow-state persistence.
- SQLite trace-store SQL behavior.
- Raw ArcadeDB schema internals beyond adapter requirements.
- Complex ontology design.
- Distributed memory sync.
- Multi-writer cluster coordination.
- Advanced access-control policy model.
- Public memory browsing UI.
- Full evaluation platform.
- Embedding model benchmarking.
- Production backup/restore automation.

Those concerns belong to API, session, LLM, tooling/MCP, orchestration, agents, policy, evaluation, and deployment documents.

---

## 6. Memory Boundary

The memory layer sits behind the orchestration runtime.

It owns:

- Long-term memory search contracts.
- Document chunk retrieval contracts.
- Agent memory write/update contracts.
- Memory lifecycle operations.
- Document ingestion coordination through the adapter.
- Scope validation before memory operations.
- Search result normalization.
- Score normalization and safe score metadata.
- Memory health and stats summaries.
- Safe memory trace events.
- Adapter-level error normalization.
- Privacy operations such as export/delete by scope.

It does not own:

- API request parsing.
- Session creation/resume/reset.
- Short-term workflow state storage.
- Operational trace storage.
- LLM provider/model selection.
- LLM calls.
- Tool execution.
- MCP client calls.
- MCP server implementation.
- Agent selection.
- Business workflow branching.
- User-facing response formatting.

### 6.1 Boundary Diagram

```text
API
  -> SessionService
      -> OrchestrationRuntime
          -> Strategy / Agent
              -> MemoryGateway
                  -> MemoryPolicy / ScopeValidator
                  -> MemoryStoreAdapter
                      -> memory_store Python wrapper
                          -> ArcadeDB
                          -> FastEmbed embeddings
                          -> ArcadeDB vector search
                          -> ArcadeDB BM25/full-text search
                          -> optional graph expansion
                          -> optional FastEmbed reranker
                  -> ObservabilityRecorder / TraceStore
```

### 6.2 Practical Rule

Agents and strategies should do this:

```python
results = await context.memory.search(
    request=MemorySearchRequest(
        query="What does the user prefer for backend frameworks?",
        scopes=MemoryScopes(project_id=context.request.project_id),
        top_k=8,
        include_document_chunks=True,
        include_agent_memories=True,
    ),
    context=context.request,
)
```

Agents and strategies should not do this:

```python
from memory_store.service import MemoryService
memory = MemoryService(...)
results = memory.search("query")
```

They should also not do this:

```python
from arcadeDB import ArcadeDB
client = ArcadeDB(...)
client.query("SELECT FROM MemoryRecord ...")
```

Concrete storage, embedding, full-text, graph, and reranker details belong behind `MemoryStoreAdapter` and the existing `memory_store` wrapper.

---

## 7. Memory Gateway vs Memory Store Adapter

The V1 memory layer has two important boundaries:

```text
MemoryGateway
  Public backend contract used by orchestration, strategies, and agents.

MemoryStoreAdapter
  Infrastructure adapter that translates backend memory contracts into calls to the existing memory_store wrapper.
```

### 7.1 `MemoryGateway`

`MemoryGateway` owns backend semantics:

- Scope validation.
- Policy hooks.
- Request normalization.
- Result normalization.
- Trace events.
- Error mapping.
- Safe defaults.
- Result limits.
- Lifecycle operation naming.
- Privacy operation routing.

### 7.2 `MemoryStoreAdapter`

`MemoryStoreAdapter` owns implementation translation:

- Calls into `memory_store.service` or the public wrapper API.
- Maps backend requests to memory-store request objects.
- Maps memory-store responses to backend result models.
- Converts storage-specific errors into normalized backend errors.
- Keeps ArcadeDB, embedding, FTS, vector index, graph, and reranker details isolated.

### 7.3 Why Both Layers Exist

Without both layers, agents would either know too much about memory infrastructure or the adapter would accumulate business policy.

Recommended separation:

```text
Agent/Strategy -> MemoryGateway: "search relevant scoped memory"
MemoryGateway -> MemoryStoreAdapter: "execute normalized memory operation"
MemoryStoreAdapter -> memory_store: "call concrete implementation"
```

---

## 8. Recommended Package Layout

Recommended implementation layout:

```text
backend/
  app/
    memory/
      __init__.py
      gateway.py
      models.py
      errors.py
      scopes.py
      lifecycle.py
      scoring.py
      ingestion.py
      redaction.py
      health.py
      stats.py
      context_builder.py

      adapters/
        __init__.py
        base.py
        memory_store_adapter.py
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
        fake_memory_gateway.py
        fake_memory_store_adapter.py
```

### 8.1 Module Responsibilities

| Module | Responsibility |
|---|---|
| `gateway.py` | Public `MemoryGateway` implementation and orchestration-facing entry point. |
| `models.py` | Memory request/result/config models. |
| `errors.py` | Memory-specific normalized errors. |
| `scopes.py` | Scope model and validation helpers. |
| `lifecycle.py` | Agent memory lifecycle operation helpers. |
| `scoring.py` | Score normalization and result ordering rules. |
| `ingestion.py` | Document ingestion request/result models and coordination helpers. |
| `redaction.py` | Memory-specific redaction helpers. |
| `health.py` | Memory health checks. |
| `stats.py` | Safe memory stats summaries. |
| `context_builder.py` | Helpers for turning search results into bounded prompt context. |
| `adapters/base.py` | `MemoryStoreAdapter` protocol. |
| `adapters/memory_store_adapter.py` | Adapter around the existing `memory_store` Python wrapper. |
| `adapters/fake.py` | Deterministic fake adapter for tests. |

---

## 9. Dependency Direction Rules

Allowed:

```text
app/orchestration/* -> app/memory/gateway.py
app/agents/*        -> app/memory/models.py through OrchestrationContext
app/memory/*        -> app/config/schemas.py
app/memory/*        -> app/policy/service.py through interface
app/memory/*        -> app/observability/events.py through facade
app/memory/adapters/memory_store_adapter.py -> memory_store.service
```

Avoid:

```text
app/api/*           -> app/memory/adapters/*
app/api/*           -> memory_store.service.MemoryService
app/api/*           -> ArcadeDB client
app/session/*       -> MemoryGateway for normal reset behavior
app/agents/*        -> memory_store.service.MemoryService
app/agents/*        -> ArcadeDB client
app/orchestration/* -> memory_store.service.MemoryService
app/orchestration/* -> ArcadeDB client
app/memory/*        -> app/llm/providers/*
app/memory/*        -> app/tools/mcp_adapter.py
app/memory/*        -> sqlite3
```

### 9.1 Route and Session Boundary Rule

Correct path for memory search during chat:

```text
API -> SessionService -> OrchestrationRuntime -> Agent/Strategy -> MemoryGateway -> MemoryStoreAdapter
```

Avoid:

```text
API -> MemoryGateway
SessionService -> MemoryGateway for session reset
SessionService -> memory_store
API -> memory_store
```

### 9.2 LLM Boundary Rule

Correct path for RAG-style answer generation:

```text
Agent/Strategy
  -> MemoryGateway.search
  -> build prompt context from normalized results
  -> LLMGateway.complete or LLMGateway.stream
```

Avoid:

```text
MemoryGateway -> LLMGateway.complete
MemoryStoreAdapter -> LLM provider
memory_store -> LLM provider for answer generation
```

The memory implementation may internally use embedding and reranking models as part of memory search, but those are memory-store implementation details and not conversational LLM calls.

---

## 10. Memory Configuration Integration

Memory behavior should be configured in YAML and resolved by the configuration loader before composition.

Recommended YAML:

```yaml
memory:
  enabled: true
  provider: memory_store

  defaults:
    top_k: 8
    candidate_k: 30
    include_agent_memories: true
    include_document_chunks: true
    include_graph_context: true
    max_result_chars: 1200
    max_total_context_chars: 8000
    trace_queries: false
    trace_result_content: false

  store:
    type: memory_store
    database_path: ${env:MEMORY_ARCADEDB_PATH:./data/memory}
    embedding_model: ${env:MEMORY_EMBEDDING_MODEL:fastembed-default}
    embedding_dimension: ${env:MEMORY_EMBEDDING_DIMENSION:384}
    reranker_model: ${env:MEMORY_RERANKER_MODEL:fastembed-reranker-default}
    schema_version: 1

  chunking:
    strategy: markdown_section
    max_tokens: 350
    overlap_tokens: 50
    deterministic_ids: true

  search:
    vector_top_k: 30
    bm25_top_k: 30
    graph_expansion_hops: 1
    rerank_top_k: 30
    final_top_k: 8
    return_chunks_by_default: true
    return_full_documents_by_default: false

  scoring:
    weights:
      reranker: 0.45
      vector: 0.25
      bm25: 0.15
      temporal: 0.05
      importance: 0.05
      user_rating: 0.05
    normalize_scores: true
    save_raw_component_scores: true

  lifecycle:
    default_ttl_days: null
    memory_type_ttl_days:
      user_preference: null
      project_fact: null
      task_note: 90
      transient_observation: 14
    contradiction_policy: keep_both_mark_conflict
    supersede_policy: mark_previous_superseded

  privacy:
    enable_export_by_scope: true
    enable_delete_by_scope: true
    hard_delete_enabled: false
    tombstone_on_forget: true

  health:
    deep_check_enabled: false
```

### 10.1 Settings Object

Recommended typed settings:

```python
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class MemoryDefaultsSettings:
    top_k: int
    candidate_k: int
    include_agent_memories: bool
    include_document_chunks: bool
    include_graph_context: bool
    max_result_chars: int
    max_total_context_chars: int
    trace_queries: bool = False
    trace_result_content: bool = False


@dataclass(frozen=True, slots=True)
class MemoryStoreSettings:
    type: str
    database_path: str | None
    embedding_model: str
    embedding_dimension: int
    reranker_model: str | None = None
    schema_version: int = 1


@dataclass(frozen=True, slots=True)
class MemoryChunkingSettings:
    strategy: str
    max_tokens: int
    overlap_tokens: int
    deterministic_ids: bool = True


@dataclass(frozen=True, slots=True)
class MemorySearchSettings:
    vector_top_k: int
    bm25_top_k: int
    graph_expansion_hops: int
    rerank_top_k: int
    final_top_k: int
    return_chunks_by_default: bool = True
    return_full_documents_by_default: bool = False


@dataclass(frozen=True, slots=True)
class MemoryScoringSettings:
    weights: dict[str, float] = field(default_factory=dict)
    normalize_scores: bool = True
    save_raw_component_scores: bool = True


@dataclass(frozen=True, slots=True)
class MemoryLifecycleSettings:
    default_ttl_days: int | None = None
    memory_type_ttl_days: dict[str, int | None] = field(default_factory=dict)
    contradiction_policy: str = "keep_both_mark_conflict"
    supersede_policy: str = "mark_previous_superseded"


@dataclass(frozen=True, slots=True)
class MemoryPrivacySettings:
    enable_export_by_scope: bool
    enable_delete_by_scope: bool
    hard_delete_enabled: bool = False
    tombstone_on_forget: bool = True


@dataclass(frozen=True, slots=True)
class MemorySettings:
    enabled: bool
    provider: str
    defaults: MemoryDefaultsSettings
    store: MemoryStoreSettings
    chunking: MemoryChunkingSettings
    search: MemorySearchSettings
    scoring: MemoryScoringSettings
    lifecycle: MemoryLifecycleSettings
    privacy: MemoryPrivacySettings
```

### 10.2 Configuration Validation

Configuration validation should fail fast when:

- Memory is enabled but provider type is unknown.
- Embedding dimension is missing or invalid.
- Embedding dimension does not match the configured memory store schema, if schema already exists.
- Chunk size or overlap is invalid.
- Overlap is greater than or equal to chunk size.
- Search top-k values are less than 1.
- `graph_expansion_hops` is greater than the V1 limit of 1.
- Scoring weights are negative.
- Required score components are missing when normalization is enabled.
- Full-document return is enabled by default without an explicit safety decision.
- Privacy delete/export operations are disabled but required by environment policy.
- Store path or connection configuration is malformed.

---

## 11. Memory Scopes

Every memory operation must carry scope.

Recommended scope model:

```python
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class MemoryScopes:
    user_id: str | None = None
    project_id: str | None = None
    tenant_id: str | None = None
    session_id: str | None = None
    agent_name: str | None = None
    usecase: str | None = None
    source_id: str | None = None
    document_id: str | None = None
    tags: tuple[str, ...] = ()
    metadata: dict[str, str] = field(default_factory=dict)
```

### 11.1 Scope Rules

Recommended V1 rules:

```text
At least one durable scope must be present for writes.
Durable scopes include user_id, project_id, tenant_id, source_id, or document_id.
Session_id alone is not enough for long-term memory writes unless explicitly allowed.
Search may combine user, project, usecase, agent, and document scopes.
Delete/export operations must require explicit durable scope.
```

### 11.2 Scope Examples

Project memory:

```python
MemoryScopes(
    user_id="local_user",
    project_id="bb1_poc",
    usecase="architecture_generation",
)
```

Document chunk memory:

```python
MemoryScopes(
    project_id="bb1_poc",
    source_id="backend-application-architecture.md",
    document_id="doc_backend_application_architecture",
)
```

Agent-specific memory:

```python
MemoryScopes(
    user_id="local_user",
    project_id="bb1_poc",
    agent_name="architecture_writer_agent",
)
```

### 11.3 Scope Safety Rule

Do not allow user-provided request metadata to override durable memory scope without policy approval.

Allowed:

```text
RequestContext contains authenticated or configured user/project scope.
Agent passes that scope into MemoryGateway.
Policy approves operation.
```

Avoid:

```text
User sends metadata.project_id = "other_project".
Gateway searches that project without ownership validation.
```

---

## 12. Public Memory Gateway Interface

Recommended interface:

```python
from typing import Protocol


class MemoryGateway(Protocol):
    async def search(
        self,
        *,
        request: "MemorySearchRequest",
        context: "RequestContext",
    ) -> "MemorySearchResult":
        ...

    async def get(
        self,
        *,
        request: "MemoryGetRequest",
        context: "RequestContext",
    ) -> "MemoryRecord | None":
        ...

    async def upsert(
        self,
        *,
        request: "MemoryUpsertRequest",
        context: "RequestContext",
    ) -> "MemoryWriteResult":
        ...

    async def promote(
        self,
        *,
        request: "MemoryLifecycleRequest",
        context: "RequestContext",
    ) -> "MemoryWriteResult":
        ...

    async def supersede(
        self,
        *,
        request: "MemorySupersedeRequest",
        context: "RequestContext",
    ) -> "MemoryWriteResult":
        ...

    async def contradict(
        self,
        *,
        request: "MemoryContradictRequest",
        context: "RequestContext",
    ) -> "MemoryWriteResult":
        ...

    async def expire(
        self,
        *,
        request: "MemoryLifecycleRequest",
        context: "RequestContext",
    ) -> "MemoryWriteResult":
        ...

    async def forget(
        self,
        *,
        request: "MemoryForgetRequest",
        context: "RequestContext",
    ) -> "MemoryWriteResult":
        ...

    async def ingest_document(
        self,
        *,
        request: "DocumentIngestRequest",
        context: "RequestContext",
    ) -> "DocumentIngestResult":
        ...

    async def delete_by_scope(
        self,
        *,
        request: "MemoryDeleteByScopeRequest",
        context: "RequestContext",
    ) -> "MemoryDeleteResult":
        ...

    async def export_by_scope(
        self,
        *,
        request: "MemoryExportByScopeRequest",
        context: "RequestContext",
    ) -> "MemoryExportResult":
        ...

    async def health(self) -> "MemoryHealthResult":
        ...

    async def stats(
        self,
        *,
        scopes: "MemoryScopes | None" = None,
    ) -> "MemoryStatsResult":
        ...
```

### 12.1 Method Ownership

| Method | Purpose |
|---|---|
| `search` | Retrieve relevant memories and document chunks for agent/orchestration use. |
| `get` | Fetch a single memory or chunk by normalized ID. |
| `upsert` | Create or update an agent memory. |
| `promote` | Increase durability/importance of a memory. |
| `supersede` | Mark an older memory replaced by a newer memory. |
| `contradict` | Link conflicting memories and mark conflict state. |
| `expire` | Mark a memory expired based on lifecycle rules. |
| `forget` | Tombstone or delete a memory by ID/scope. |
| `ingest_document` | Chunk and index a document through the adapter. |
| `delete_by_scope` | Delete/tombstone memories matching scope for privacy/project cleanup. |
| `export_by_scope` | Export memories matching scope for privacy/data portability. |
| `health` | Return safe memory readiness. |
| `stats` | Return safe counts and index status summaries. |

### 12.2 Gateway Call Flow

```text
1. Receive memory request and RequestContext.
2. Validate request shape and limits.
3. Resolve/validate memory scopes.
4. Check policy for read/write/delete/export operation.
5. Redact and record memory operation started trace event.
6. Call MemoryStoreAdapter.
7. Normalize adapter result.
8. Apply gateway-level result bounds and content limits.
9. Record success/failure trace event.
10. Return normalized memory result or normalized memory error.
```

---

## 13. Memory Record Model

Recommended provider-neutral memory record:

```python
from dataclasses import dataclass, field
from typing import Any, Literal


MemoryKind = Literal[
    "agent_memory",
    "document_chunk",
    "document_summary",
    "project_fact",
    "user_preference",
    "task_note",
    "system_note",
]

MemoryStatus = Literal[
    "active",
    "superseded",
    "contradicted",
    "expired",
    "forgotten",
    "removed",
]


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    memory_id: str
    kind: MemoryKind
    status: MemoryStatus
    content: str
    scopes: MemoryScopes
    source: "MemorySource | None" = None
    importance: float | None = None
    confidence: float | None = None
    created_at: str | None = None
    updated_at: str | None = None
    expires_at: str | None = None
    tags: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
```

### 13.1 Source Model

```python
@dataclass(frozen=True, slots=True)
class MemorySource:
    source_id: str | None = None
    document_id: str | None = None
    chunk_id: str | None = None
    source_uri: str | None = None
    source_hash: str | None = None
    chunk_index: int | None = None
    section_path: tuple[str, ...] = ()
    title: str | None = None
```

### 13.2 Content Rules

Memory record content may be returned to agents when policy allows it, but must not be logged or traced by default.

Safe trace payload:

```json
{
  "memory_id": "mem_...",
  "kind": "document_chunk",
  "content_chars": 842,
  "source_id": "backend-application-architecture.md",
  "chunk_index": 12
}
```

Unsafe trace payload:

```json
{
  "content": "full private document chunk text..."
}
```

---

## 14. Search Request and Result Models

Recommended search request:

```python
@dataclass(frozen=True, slots=True)
class MemorySearchRequest:
    query: str
    scopes: MemoryScopes
    top_k: int | None = None
    candidate_k: int | None = None
    include_agent_memories: bool = True
    include_document_chunks: bool = True
    include_graph_context: bool = True
    filters: "MemorySearchFilters | None" = None
    max_result_chars: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

Recommended filters:

```python
@dataclass(frozen=True, slots=True)
class MemorySearchFilters:
    kinds: tuple[MemoryKind, ...] = ()
    tags: tuple[str, ...] = ()
    status: tuple[MemoryStatus, ...] = ("active",)
    source_ids: tuple[str, ...] = ()
    document_ids: tuple[str, ...] = ()
    created_after: str | None = None
    created_before: str | None = None
```

Recommended result:

```python
@dataclass(frozen=True, slots=True)
class MemorySearchResult:
    query_id: str
    results: list["MemorySearchHit"]
    total_candidates: int | None = None
    search_strategy: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

Search hit:

```python
@dataclass(frozen=True, slots=True)
class MemorySearchHit:
    record: MemoryRecord
    score: "MemoryScore"
    match_reason: str | None = None
    highlights: list[str] = field(default_factory=list)
    related_records: list[MemoryRecord] = field(default_factory=list)
```

Score model:

```python
@dataclass(frozen=True, slots=True)
class MemoryScore:
    final_score: float
    vector_score: float | None = None
    bm25_score: float | None = None
    reranker_score: float | None = None
    temporal_score: float | None = None
    importance_score: float | None = None
    user_rating_score: float | None = None
    graph_score: float | None = None
```

### 14.1 Search Result Shape Rule

Search should return relevant chunks and memory records, not entire documents by default.

Recommended behavior:

```text
Document ingestion stores chunks.
Search retrieves chunks.
Agents use the top relevant chunks as prompt context.
Full document retrieval requires explicit get/export/read behavior and policy approval.
```

Avoid:

```text
Search query returns the entire source document when only one section matched.
Search result includes unbounded document text.
Search result includes unrelated chunks because they share a source file.
```

### 14.2 Result Content Bounds

Recommended default:

```text
max_result_chars: 1200
max_total_context_chars: 8000
```

The gateway may trim or reject oversized results before they reach an agent.

If content is trimmed, the result should say so in metadata:

```json
{
  "trimmed": true,
  "original_chars": 4200,
  "returned_chars": 1200
}
```

---

## 15. Memory Lifecycle Operations

Agent memories are not static notes. They need lifecycle state.

V1 lifecycle operations:

```text
upsert
promote
supersede
contradict
expire
forget
```

### 15.1 Upsert

Use `upsert` when an agent creates or updates a durable memory.

Recommended request:

```python
@dataclass(frozen=True, slots=True)
class MemoryUpsertRequest:
    content: str
    kind: MemoryKind
    scopes: MemoryScopes
    memory_id: str | None = None
    importance: float | None = None
    confidence: float | None = None
    ttl_days: int | None = None
    tags: tuple[str, ...] = ()
    source: MemorySource | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

Use cases:

```text
Remember user preference.
Save project fact.
Save durable agent note.
Save resolved instruction from a project workflow.
```

### 15.2 Promote

Use `promote` when a memory becomes more important or durable.

Examples:

```text
A repeated user preference is confirmed.
A project fact is referenced by several successful tasks.
A task note becomes a durable project rule.
```

### 15.3 Supersede

Use `supersede` when a newer memory replaces an older memory.

Example:

```text
Old: "Project uses two MCP endpoints."
New: "Project uses one MCP endpoint."
```

The old memory should remain auditable but should not be returned by default search unless requested.

### 15.4 Contradict

Use `contradict` when two memories conflict but the correct answer is not yet resolved.

Example:

```text
Memory A says model profile is `default_chat`.
Memory B says model profile is `research_reasoning`.
```

Both may remain visible to a debugging or resolution workflow, but normal search should prefer active, non-contradicted records unless policy says otherwise.

### 15.5 Expire

Use `expire` when a memory is no longer valid due to TTL or time-sensitive status.

Examples:

```text
Temporary task note expired after 90 days.
Transient observation expired after 14 days.
```

### 15.6 Forget

Use `forget` for explicit deletion/tombstone behavior.

Recommended default:

```text
Tombstone first.
Hard delete only when privacy configuration and policy allow it.
```

Forget must not be triggered by session reset.

---

## 16. Document Ingestion Model

Document ingestion turns source documents into searchable chunks.

Recommended request:

```python
@dataclass(frozen=True, slots=True)
class DocumentIngestRequest:
    source_id: str
    document_id: str | None
    content: str
    scopes: MemoryScopes
    source_uri: str | None = None
    source_hash: str | None = None
    title: str | None = None
    content_type: str = "text/markdown"
    chunking: "DocumentChunkingOverride | None" = None
    replace_existing: bool = True
    mark_missing_chunks_removed: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)
```

Recommended result:

```python
@dataclass(frozen=True, slots=True)
class DocumentIngestResult:
    document_id: str
    source_id: str
    source_hash: str
    status: str
    chunks_created: int
    chunks_updated: int
    chunks_unchanged: int
    chunks_removed: int
    skipped_unchanged_document: bool
    metadata: dict[str, Any] = field(default_factory=dict)
```

### 16.1 Deterministic Chunk IDs

Document chunks should have deterministic IDs so re-ingestion is stable.

Recommended ID inputs:

```text
project_id or tenant_id
source_id
document_id
source_hash or section hash
section path
chunk index
chunk text hash
```

Example shape:

```text
chunk_<hash(project_id|source_id|section_path|chunk_index|chunk_text_hash)>
```

### 16.2 Re-Ingestion Rules

Recommended behavior:

```text
If source_hash is unchanged, skip re-ingestion.
If source_hash changed, re-chunk deterministically.
Unchanged chunk IDs remain unchanged.
Changed chunks are replaced.
Missing chunks are marked removed or deleted according to config.
Search excludes removed chunks by default.
```

### 16.3 Document Chunking Rule

For markdown documents, recommended V1 chunking:

```yaml
chunking:
  strategy: markdown_section
  max_tokens: 350
  overlap_tokens: 50
```

This means search results should usually be focused section chunks, not entire markdown files.

### 16.4 Full Document Retrieval Rule

Full document retrieval should be an explicit operation, not the default search behavior.

Allowed future operations:

```text
MemoryGateway.get_document(document_id)
MemoryGateway.export_by_scope(...)
DocumentService.read_source(...)
```

Avoid using `MemoryGateway.search` to return full documents.

---

## 17. Search Pipeline Contract

The concrete search pipeline lives inside `memory_store`, but the backend contract should expect this V1 behavior:

```text
1. Embed query with FastEmbed or configured embedding model.
2. Run ArcadeDB vector search, top N.
3. Run ArcadeDB BM25/full-text search, top N.
4. Merge and deduplicate candidates.
5. Optionally expand graph context by one hop.
6. Optionally rerank candidates.
7. Normalize component scores.
8. Compute final weighted score.
9. Return top K memory records/chunks.
```

### 17.1 V1 Graph Limit

V1 graph expansion should be limited to one hop.

Recommended rule:

```text
Graph expansion may add directly related context, but it must not flood search results with broad neighborhoods.
```

### 17.2 Score Formula

Recommended default:

```text
final_score =
  reranker_score      * 0.45 +
  vector_score        * 0.25 +
  bm25_score          * 0.15 +
  temporal_score      * 0.05 +
  importance_score    * 0.05 +
  user_rating_score   * 0.05
```

If a component is unavailable, the adapter should either normalize over available components or return the missing component as `None`, according to configuration.

### 17.3 Score Debugging

Raw component scores are useful for evaluation and debugging.

They may be returned in `MemoryScore`, but trace/log payloads should include only bounded score summaries unless debug capture is enabled.

---

## 18. Prompt Context Builder

Memory search results are not automatically prompt text.

Recommended helper:

```python
class MemoryContextBuilder:
    def build_context(
        self,
        *,
        search_result: MemorySearchResult,
        max_chars: int,
        include_sources: bool = True,
    ) -> "MemoryPromptContext":
        ...
```

Recommended result:

```python
@dataclass(frozen=True, slots=True)
class MemoryPromptContext:
    text: str
    included_memory_ids: list[str]
    omitted_memory_ids: list[str]
    total_chars: int
    truncated: bool
```

### 18.1 Context Builder Responsibilities

The context builder may:

- Sort by final score.
- Deduplicate near-identical chunks.
- Include source labels.
- Trim to a character/token budget.
- Emit safe metadata about included/omitted memory IDs.

It must not:

- Call LLM providers.
- Search memory again implicitly.
- Execute tools.
- Persist workflow state.
- Trace raw memory content by default.

### 18.2 Example Prompt Context

```text
Relevant memory:
[1] Project fact, source=backend-llm-gateway-architecture.md, section="Memory Boundary"
The LLM gateway must not search or write memory. Memory access is through MemoryGateway.

[2] Document chunk, source=backend-api-architecture.md, section="LLM, Memory, Tool, and MCP Boundaries"
API routes must not directly call MemoryGateway. The normal path is API -> SessionService -> OrchestrationRuntime -> Gateways.
```

The agent can include this context in an `LLMRequest` sent to `LLMGateway`.

---

## 19. Memory Store Adapter Interface

Recommended adapter protocol:

```python
from typing import Protocol


class MemoryStoreAdapter(Protocol):
    async def search(
        self,
        *,
        request: "AdapterMemorySearchRequest",
    ) -> "AdapterMemorySearchResult":
        ...

    async def get(
        self,
        *,
        memory_id: str,
        scopes: MemoryScopes,
    ) -> "MemoryRecord | None":
        ...

    async def upsert(
        self,
        *,
        request: "AdapterMemoryUpsertRequest",
    ) -> "MemoryWriteResult":
        ...

    async def update_lifecycle(
        self,
        *,
        request: "AdapterMemoryLifecycleUpdateRequest",
    ) -> "MemoryWriteResult":
        ...

    async def ingest_document(
        self,
        *,
        request: "AdapterDocumentIngestRequest",
    ) -> "DocumentIngestResult":
        ...

    async def delete_by_scope(
        self,
        *,
        request: "AdapterDeleteByScopeRequest",
    ) -> "MemoryDeleteResult":
        ...

    async def export_by_scope(
        self,
        *,
        request: "AdapterExportByScopeRequest",
    ) -> "MemoryExportResult":
        ...

    async def health(self) -> "MemoryStoreHealthResult":
        ...

    async def stats(
        self,
        *,
        scopes: MemoryScopes | None = None,
    ) -> "MemoryStatsResult":
        ...
```

### 19.1 Adapter Responsibility

The adapter owns:

- Concrete `memory_store` wrapper construction.
- Request translation.
- Response translation.
- Error translation.
- Implementation-specific metadata cleanup.
- Store health checks.

The adapter must not own:

- Agent selection.
- Strategy selection.
- API response formatting.
- LLM prompt construction.
- Tool execution.
- Workflow state persistence.
- Trace-store SQL.
- Policy decisions beyond enforcing gateway-approved operation parameters.

### 19.2 Adapter Initialization

Recommended composition:

```python
def build_memory_gateway(config, policy, observability) -> MemoryGateway:
    adapter = MemoryStoreMemoryAdapter(
        settings=config.memory.store,
        chunking=config.memory.chunking,
        search=config.memory.search,
        scoring=config.memory.scoring,
    )

    return DefaultMemoryGateway(
        settings=config.memory,
        adapter=adapter,
        policy=policy,
        observability=observability,
        redactor=observability.redactor,
    )
```

---

## 20. Existing `memory_store` Wrapper Integration

The project already has a Python wrapper called `memory_store` that encapsulates memory capabilities.

The backend should treat it as an infrastructure dependency.

Recommended adapter file:

```text
backend/app/memory/adapters/memory_store_adapter.py
```

Recommended import boundary:

```python
# Allowed only inside memory_store_adapter.py or very narrow adapter package.
from memory_store.service import MemoryService
```

Avoid importing `MemoryService` from:

```text
app/api/*
app/session/*
app/orchestration/*
app/agents/*
app/llm/*
app/tools/*
```

### 20.1 Adapter Construction Pattern

```python
class MemoryStoreMemoryAdapter:
    def __init__(self, *, settings, chunking, search, scoring):
        self._settings = settings
        self._chunking = chunking
        self._search = search
        self._scoring = scoring
        self._service = MemoryService(
            database_path=settings.database_path,
            embedding_model=settings.embedding_model,
            embedding_dimension=settings.embedding_dimension,
            reranker_model=settings.reranker_model,
        )
```

The exact constructor should match the actual wrapper API. The important architecture rule is that the constructor is hidden inside the adapter.

### 20.2 Wrapper API Stability

If the wrapper API changes, update:

```text
MemoryStoreMemoryAdapter
adapter tests
fixture config
```

Do not update:

```text
API routes
SessionService
Agents
Strategies
LLMGateway
ToolGateway
```

---

## 21. Policy Integration

The memory gateway should call policy before memory execution.

Recommended policy checks:

```python
allowed = await policy.can_access_memory(
    user_id=context.user_id,
    session_id=context.session_id,
    usecase=context.usecase,
    operation="search",
    scopes=request.scopes,
    agent_name=request.scopes.agent_name,
    memory_kinds=request.filters.kinds if request.filters else (),
)
```

For writes:

```python
allowed = await policy.can_write_memory(
    user_id=context.user_id,
    session_id=context.session_id,
    usecase=context.usecase,
    operation="upsert",
    scopes=request.scopes,
    memory_kind=request.kind,
)
```

For delete/export:

```python
allowed = await policy.can_admin_memory_scope(
    user_id=context.user_id,
    operation="delete_by_scope",
    scopes=request.scopes,
)
```

### 21.1 V1 Policy Defaults

Recommended V1 defaults:

```text
Deny memory operations when memory is disabled.
Deny writes without durable scope.
Deny delete/export without explicit durable scope.
Deny cross-user or cross-project scope overrides.
Allow search within current user/project scope.
Allow agent memories only for configured agents.
Allow document chunks only for configured project/document scope.
Do not return forgotten/removed records by default.
Do not return superseded/contradicted records by default unless requested.
Trace all memory operations with safe metadata.
Do not trace raw query text by default.
Do not trace raw memory result content by default.
```

### 21.2 User-Supplied Scope Override Rule

User input must not directly select arbitrary memory scopes.

Allowed:

```text
Authenticated/configured request context establishes user/project scope.
Agent asks for search inside that scope.
Policy approves.
```

Avoid:

```text
User sends {"project_id":"other_project"} and receives memory from that project.
```

---

## 22. Orchestration Integration

The orchestration runtime injects `MemoryGateway` into `OrchestrationContext`.

Recommended context shape:

```python
@dataclass
class OrchestrationContext:
    request: RequestContext
    llm: LLMGateway
    memory: MemoryGateway
    state: WorkflowStateStore
    tools: ToolGateway
    trace: TraceStore
    policy: PolicyService
    config: dict[str, Any]
```

### 22.1 Strategy Usage

A RAG strategy may search memory before selecting an agent or before building the final prompt:

```python
memory_result = await context.memory.search(
    request=MemorySearchRequest(
        query=context.request.message,
        scopes=MemoryScopes(
            user_id=context.request.user_id,
            project_id=context.request.metadata.get("project_id"),
            usecase=context.request.usecase,
        ),
        top_k=8,
        include_document_chunks=True,
        include_agent_memories=True,
    ),
    context=context.request,
)
```

### 22.2 Agent Usage

An agent may retrieve relevant project facts:

```python
memories = await context.memory.search(
    request=MemorySearchRequest(
        query="backend architecture memory boundaries",
        scopes=MemoryScopes(
            user_id=context.request.user_id,
            project_id="bb1_poc",
            agent_name=self.name,
        ),
        filters=MemorySearchFilters(kinds=("project_fact", "document_chunk")),
    ),
    context=context.request,
)
```

### 22.3 Combining Memory With LLM

Correct:

```text
Agent -> MemoryGateway.search
Agent -> MemoryContextBuilder.build_context
Agent -> LLMGateway.complete
```

Avoid:

```text
MemoryGateway -> LLMGateway
LLMGateway -> MemoryGateway
```

This prevents circular dependencies and keeps retrieval separate from generation.

---

## 23. Session Service Boundary

`SessionService` does not delete or mutate long-term memory during reset.

Correct reset behavior:

```text
SessionService.reset_session
  -> WorkflowStateStore.reset
  -> return reset confirmation
```

Avoid:

```text
SessionService.reset_session
  -> MemoryGateway.delete_by_scope
  -> TraceStore.delete
```

### 23.1 Session History vs Memory

Session history belongs to workflow state.

Long-term durable facts/preferences/project knowledge belong to memory.

Promotion from session history into memory should be an explicit orchestration/agent decision with policy approval.

### 23.2 Future Summarization

If future session summarization writes durable memory, use this path:

```text
OrchestrationRuntime / SummarizationAgent
  -> LLMGateway if needed
  -> MemoryGateway.upsert
```

Do not hide durable memory writes inside `SessionService` without explicit architecture and policy.

---

## 24. API Integration

The API layer should remain unchanged after memory integration.

Normal chat path:

```text
POST /chat
  -> API validates request
  -> SessionService.handle_chat
  -> OrchestrationRuntime
  -> Agent/Strategy
  -> MemoryGateway.search/upsert if needed
```

The API must not expose general-purpose memory admin routes in V1 unless a future policy document defines them.

### 24.1 Health Integration

`GET /health` may include safe memory health via `HealthService`:

```json
{
  "memory": {
    "status": "ok",
    "provider": "memory_store",
    "configured": true,
    "schema_initialized": true,
    "embedding_model_configured": true
  }
}
```

### 24.2 Capabilities Integration

`GET /capabilities` may include safe memory feature flags:

```json
{
  "memory": {
    "enabled": true,
    "search_enabled": true,
    "document_ingestion_enabled": false,
    "agent_memory_enabled": true
  }
}
```

Do not expose:

```text
ArcadeDB paths
embedding model internals if sensitive
raw index names
memory_store connection settings
full document contents
private source URIs
```

---

## 25. Observability and Trace Integration

The memory gateway should emit safe trace events through the observability facade or `TraceStore` interface.

Recommended trace events:

| Event | Emitted By | Notes |
|---|---|---|
| `memory_search_started` | Gateway | Query length/hash, scopes summary, no raw query by default. |
| `memory_search_completed` | Gateway | Result count, duration, score summary, no raw content by default. |
| `memory_search_failed` | Gateway | Safe error type/code. |
| `memory_get_started` | Gateway | Memory ID and scope summary. |
| `memory_get_completed` | Gateway | Found/not found and content length only. |
| `memory_write_started` | Gateway | Operation, kind, scope summary, content length only. |
| `memory_write_completed` | Gateway | Memory ID, status, duration. |
| `memory_lifecycle_updated` | Gateway | Operation and affected IDs. |
| `document_ingest_started` | Gateway | Source ID, source hash, content length. |
| `document_ingest_completed` | Gateway | Created/updated/unchanged/removed counts. |
| `memory_delete_by_scope_started` | Gateway | Scope summary, no raw content. |
| `memory_delete_by_scope_completed` | Gateway | Count summary. |
| `memory_export_by_scope_completed` | Gateway | Count/size summary only. |
| `memory_health_checked` | Health service/gateway | Safe status summary. |

### 25.1 Safe Search Trace Payload

```json
{
  "event_name": "memory_search_completed",
  "trace_id": "trace_...",
  "payload": {
    "query_chars": 84,
    "query_hash": "sha256:...",
    "project_id": "bb1_poc",
    "kinds": ["project_fact", "document_chunk"],
    "top_k": 8,
    "result_count": 6,
    "duration_ms": 74,
    "max_score": 0.91,
    "min_score": 0.42
  }
}
```

### 25.2 Unsafe Search Trace Payload

```json
{
  "query": "full user question with private data...",
  "results": [
    {"content": "full memory result text..."}
  ]
}
```

### 25.3 Metrics

Recommended metrics:

```text
backend.memory.searches.total
backend.memory.searches.duration_ms
backend.memory.searches.results_count
backend.memory.writes.total
backend.memory.writes.duration_ms
backend.memory.ingests.total
backend.memory.ingests.duration_ms
backend.memory.ingests.chunks_created
backend.memory.ingests.chunks_updated
backend.memory.ingests.chunks_unchanged
backend.memory.ingests.chunks_removed
backend.memory.deletes.total
backend.memory.errors.total
```

Allowed metric tags:

```text
operation
kind
status
error_type
provider
search_strategy
```

Avoid metric tags:

```text
session_id
trace_id
raw_user_id
query text
memory content
source URI if sensitive
full database path
```

---

## 26. Privacy and Redaction

Memory content can contain user preferences, project facts, document text, and sensitive operational context.

Default behavior:

```text
Do not log raw memory query text.
Do not log raw memory result content.
Do not store raw memory content in trace events.
Do not store raw documents in trace events.
Do not return forgotten/removed records by default.
Do not expose memory storage paths or connection details in API responses.
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

Also treat these as content-sensitive:

```text
raw_document
raw_chunk
prompt
completion
embedding
vector
provider_response
```

### 26.2 Privacy Controls

V1 should support these backend operations even if public API routes are not yet exposed:

```text
export_by_scope
delete_by_scope
forget memory by ID
mark source removed
```

These operations are needed for future privacy and project-cleanup workflows.

### 26.3 Tombstone vs Hard Delete

Recommended default:

```text
forget -> tombstone
explicit privacy hard delete -> hard delete only when enabled and policy-approved
```

Tombstones help prevent accidental re-creation of forgotten records during re-ingestion or retries.

---

## 27. Error Model

Recommended memory errors:

```python
class MemoryError(Exception):
    code: str
    retryable: bool


class MemoryDisabledError(MemoryError): ...
class MemoryScopeError(MemoryError): ...
class MemoryPolicyDeniedError(MemoryError): ...
class MemoryStoreUnavailableError(MemoryError): ...
class MemoryStoreTimeoutError(MemoryError): ...
class MemoryValidationError(MemoryError): ...
class MemoryNotFoundError(MemoryError): ...
class MemoryConflictError(MemoryError): ...
class MemoryIngestionError(MemoryError): ...
class MemoryEmbeddingDimensionError(MemoryError): ...
class MemorySearchError(MemoryError): ...
class MemoryExportError(MemoryError): ...
class MemoryDeleteError(MemoryError): ...
class MemoryMalformedResultError(MemoryError): ...
```

### 27.1 Error Mapping

| Gateway Error | Retryable | API Mapping Later |
|---|---:|---|
| `MemoryDisabledError` | false | `503 memory_disabled` or capability disabled |
| `MemoryScopeError` | false | `400 invalid_memory_scope` |
| `MemoryPolicyDeniedError` | false | `403 policy_denied` |
| `MemoryStoreUnavailableError` | true | `503 memory_unavailable` |
| `MemoryStoreTimeoutError` | true | `504 memory_timeout` |
| `MemoryValidationError` | false | `400 invalid_memory_request` |
| `MemoryNotFoundError` | false | `404 memory_not_found` |
| `MemoryConflictError` | true/false by details | `409 memory_conflict` |
| `MemoryIngestionError` | true/false by cause | `500 memory_ingestion_failed` |
| `MemoryEmbeddingDimensionError` | false | `500 memory_schema_mismatch` |
| `MemorySearchError` | true/false by cause | `502 memory_search_failed` |
| `MemoryExportError` | false/true by cause | `500 memory_export_failed` |
| `MemoryDeleteError` | false/true by cause | `500 memory_delete_failed` |
| `MemoryMalformedResultError` | true/false by cause | `502 memory_malformed_result` |

### 27.2 Error Safety Rule

Normalized memory errors must not expose:

- Raw memory content.
- Raw document text.
- Embedding vectors.
- Full ArcadeDB query text if sensitive.
- Internal database paths if sensitive.
- Stack traces.
- Raw adapter responses.
- Credentials.

---

## 28. Health Integration

The memory gateway should expose safe health status.

Recommended result:

```python
@dataclass(frozen=True, slots=True)
class MemoryHealthResult:
    status: str
    enabled: bool
    provider: str
    configured: bool
    schema_initialized: bool | None = None
    embedding_model_configured: bool | None = None
    embedding_dimension: int | None = None
    search_available: bool | None = None
    ingest_available: bool | None = None
    error: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)
```

Recommended health response section:

```json
{
  "memory": {
    "status": "ok",
    "enabled": true,
    "provider": "memory_store",
    "configured": true,
    "schema_initialized": true,
    "embedding_model_configured": true,
    "embedding_dimension": 384,
    "search_available": true,
    "ingest_available": true
  }
}
```

### 28.1 Health Safety Rule

Health output must not include:

```text
raw database path if sensitive
connection strings
credentials
raw index definitions
raw document counts by private scope unless allowed
raw exception stack trace
```

### 28.2 Health Check Depth

Recommended V1 behavior:

```text
Startup validation checks configuration shape.
Health route reports configured status and lightweight store readiness.
Deep checks are optional and disabled by default.
```

A deep check may validate index availability or execute a tiny search, but it must not be expensive or expose content.

---

## 29. Capabilities Integration

The capabilities service may include safe memory flags.

Recommended capability section:

```json
{
  "memory": {
    "enabled": true,
    "search_enabled": true,
    "agent_memory_enabled": true,
    "document_chunk_search_enabled": true,
    "document_ingestion_enabled": false,
    "max_search_results": 8
  }
}
```

### 29.1 Capability Safety Rule

Expose only frontend-safe flags and limits.

Do not expose:

```text
ArcadeDB file path
embedding provider internals if sensitive
reranker model if sensitive
private source IDs
memory records
raw chunks
privacy delete route availability unless route exists and policy allows it
```

---

## 30. Composition Root Integration

The composition root builds the memory adapter and injects `MemoryGateway` into orchestration.

Recommended startup sequence:

```text
1. Load settings and YAML configuration.
2. Validate memory config.
3. Build redactor and observability recorder.
4. Build policy service.
5. Build MemoryStoreAdapter from memory.store settings.
6. Build MemoryGateway with adapter, policy, observability, and redactor.
7. Build LLMGateway.
8. Build ToolGateway placeholder/fake until tooling phase.
9. Build orchestration runtime with memory=memory_gateway.
10. Build session service with orchestration runtime.
11. Build API app.
12. Log redacted memory startup summary.
```

### 30.1 Composition Example

```python
def build_memory_gateway(config, policy, observability) -> MemoryGateway:
    if not config.memory.enabled:
        return DisabledMemoryGateway(settings=config.memory)

    if config.memory.provider != "memory_store":
        raise ConfigurationError(f"Unknown memory provider: {config.memory.provider}")

    adapter = MemoryStoreMemoryAdapter(
        store_settings=config.memory.store,
        chunking_settings=config.memory.chunking,
        search_settings=config.memory.search,
        scoring_settings=config.memory.scoring,
    )

    return DefaultMemoryGateway(
        settings=config.memory,
        adapter=adapter,
        policy=policy,
        observability=observability,
        redactor=observability.redactor,
    )
```

### 30.2 Redacted Startup Summary

Safe startup log:

```json
{
  "event": "memory_gateway_configured",
  "enabled": true,
  "provider": "memory_store",
  "chunking_strategy": "markdown_section",
  "max_tokens": 350,
  "overlap_tokens": 50,
  "search_final_top_k": 8
}
```

Unsafe startup log:

```json
{
  "database_path": "/private/path/to/memory",
  "raw_config": {...},
  "connection_string": "..."
}
```

---

## 31. Disabled Memory Mode

The backend should support disabled memory mode for early tests and local fallback.

Recommended behavior:

```text
MemoryGateway.search returns empty results or raises MemoryDisabledError by config.
MemoryGateway.upsert/write operations fail with MemoryDisabledError.
Health reports memory disabled.
Capabilities reports memory enabled=false.
```

### 31.1 Disabled Search Policy

Recommended V1 default:

```text
Search returns an empty MemorySearchResult when memory is disabled and the operation is optional.
Writes fail clearly when memory is disabled.
```

This allows simple chat to work without memory while preventing silent loss of intended durable writes.

---

## 32. Fake Memory Adapter

A fake adapter is required for tests.

Recommended behavior:

```text
In-memory list of records.
Deterministic search based on simple keyword overlap.
Deterministic IDs.
No external dependencies.
Supports search, get, upsert, lifecycle update, ingest_document, health, stats.
```

### 32.1 Fake Adapter Use Cases

Use fake memory for:

```text
API/session tests that should not depend on ArcadeDB.
Orchestration tests that need predictable retrieval.
Agent tests that verify prompt context construction.
Policy tests that verify search/write blocking.
```

Avoid using fake memory to validate:

```text
ArcadeDB vector search behavior.
BM25 ranking behavior.
FastEmbed embeddings.
Reranker quality.
Graph expansion behavior.
```

Those require adapter or integration-local tests.

---

## 33. Concurrency and Consistency

Memory operations should be safe under concurrent chat requests.

Recommended V1 rules:

```text
Use adapter-level locking only if the underlying memory_store requires it.
Do not share mutable request objects between calls.
Document re-ingestion should be idempotent by source hash and deterministic chunk IDs.
Lifecycle updates should be conditional where possible.
Delete/export by scope should be explicit and not run as part of normal chat.
```

### 33.1 Cross-Store Rule

Do not attempt one transaction spanning:

```text
workflow_state SQLite database
trace SQLite database
ArcadeDB memory store
LLM provider call
MCP tool call
```

Instead:

```text
Use operation-level idempotency.
Record trace events best-effort.
Keep memory writes explicit and retry-safe where possible.
```

### 33.2 Workflow State and Memory Consistency

Workflow state may reference memory IDs, but it should not embed full memory records by default.

Recommended state reference:

```json
{
  "used_memory_ids": ["mem_123", "chunk_456"]
}
```

Avoid:

```json
{
  "memory_records": [
    {"content": "full chunk text..."}
  ]
}
```

---

## 34. Security

### 34.1 Storage Access

Only the memory adapter should access the concrete memory store.

Avoid:

```text
ArcadeDB credentials in agents.
Memory database path in API route code.
Direct memory_store construction outside adapter.
```

### 34.2 Embedding and Vector Safety

Embedding vectors should not be exposed to API responses, trace payloads, or agent-facing metadata unless a future debugging route explicitly allows it.

### 34.3 Request Parameter Allowlist

The gateway should accept only known request parameters.

Allowed search parameters:

```text
query
scopes
top_k
candidate_k
include_agent_memories
include_document_chunks
include_graph_context
filters
max_result_chars
metadata
```

Provider-specific search internals should come from trusted config, not user metadata.

### 34.4 Content Exposure

Memory content is allowed to reach agents when policy permits retrieval. That is the purpose of memory search.

Memory content should not automatically reach:

```text
API responses
health output
capabilities output
trace events
metrics
logs
workflow state
```

---

## 35. Testing Strategy

### 35.1 Unit Tests

| Test | Purpose |
|---|---|
| Memory config validates | Proves settings load and fail fast. |
| Invalid chunking rejected | Prevents bad ingestion behavior. |
| Invalid score weights rejected | Prevents broken ranking. |
| Scope required for writes | Prevents unscoped durable memory. |
| Search calls policy | Enforces access control. |
| Policy denial blocks adapter call | Prevents unauthorized reads/writes. |
| Search returns bounded results | Prevents oversized prompt context. |
| Search excludes removed/forgotten by default | Enforces lifecycle status. |
| Upsert maps to adapter | Proves write boundary. |
| Supersede maps lifecycle update | Proves lifecycle behavior. |
| Contradict links records | Proves conflict handling. |
| Expire hides expired by default | Proves lifecycle filtering. |
| Forget tombstones by default | Proves privacy behavior. |
| Ingest unchanged source skips | Proves deterministic re-ingest. |
| Changed document replaces chunks | Proves update behavior. |
| Removed chunks marked removed | Proves source cleanup. |
| Raw query not traced by default | Proves privacy behavior. |
| Raw result content not traced by default | Proves privacy behavior. |
| Health hides store path | Proves safe health response. |
| Fake adapter deterministic search | Proves stable tests. |

### 35.2 Integration Tests

| Test | Purpose |
|---|---|
| Gateway starts with fake adapter | Proves composition wiring. |
| Gateway starts with memory_store adapter | Proves wrapper integration. |
| Search with fake adapter returns expected records | Proves gateway result shape. |
| Document ingestion creates chunks | Proves ingestion path. |
| Re-ingestion skips unchanged document | Proves source hash behavior. |
| Search returns chunks not full document | Proves retrieval granularity. |
| Hybrid search returns golden memories | Proves configured retrieval quality. |
| Component scores are available when configured | Proves scoring diagnostics. |
| Orchestration uses MemoryGateway | Proves orchestration integration. |
| Agent builds prompt context from memory | Proves RAG handoff. |
| Trace events recorded for memory search | Proves observability. |
| Delete by scope removes or tombstones expected records | Proves privacy operation. |
| Export by scope returns bounded export | Proves data portability path. |

### 35.3 Optional Local Memory Store Test

For environments with the real `memory_store` and ArcadeDB available:

```text
Provider: memory_store
Chunking: markdown_section, max_tokens=350, overlap_tokens=50
Search: vector top 30 + BM25 top 30 + merge/dedup + one-hop graph + rerank
```

These tests should be marked optional or integration-local so CI does not depend on a private local memory database.

---

## 36. Fixture Configs

Recommended fixtures:

```text
tests/fixtures/config/memory_disabled.yaml
tests/fixtures/config/memory_fake_basic.yaml
tests/fixtures/config/memory_fake_search.yaml
tests/fixtures/config/memory_fake_ingestion.yaml
tests/fixtures/config/memory_store_basic.yaml
tests/fixtures/config/memory_store_markdown_chunking.yaml
tests/fixtures/config/memory_invalid_chunking.yaml
tests/fixtures/config/memory_invalid_embedding_dimension.yaml
tests/fixtures/config/memory_trace_capture_disabled.yaml
tests/fixtures/config/memory_trace_capture_enabled_local_only.yaml
tests/fixtures/memory/documents/backend_sample.md
tests/fixtures/memory/golden_memories.jsonl
tests/fixtures/memory/golden_search_cases.yaml
```

---

## 37. Recommended Implementation Order

### Step 1: Add Memory Config Schemas

Deliverables:

- `MemorySettings`
- `MemoryStoreSettings`
- `MemoryChunkingSettings`
- `MemorySearchSettings`
- `MemoryScoringSettings`
- `MemoryLifecycleSettings`
- `MemoryPrivacySettings`
- validation for chunking, scoring, embedding dimension, and provider type

Success criteria:

- Valid fake/store configs load.
- Invalid config fails fast.
- Store paths and sensitive config are not logged.

### Step 2: Add Memory Models and Errors

Deliverables:

- `MemoryScopes`
- `MemoryRecord`
- `MemorySource`
- `MemorySearchRequest`
- `MemorySearchResult`
- `MemorySearchHit`
- `MemoryScore`
- `MemoryUpsertRequest`
- document ingest models
- lifecycle request models
- normalized memory errors

Success criteria:

- Models serialize/validate cleanly.
- Errors expose safe code/retryable values.

### Step 3: Add Adapter Protocol and Fake Adapter

Deliverables:

- `MemoryStoreAdapter` protocol
- fake adapter
- fake health/stats behavior

Success criteria:

- Gateway can search/upsert/ingest with fake adapter without external dependencies.

### Step 4: Add Default MemoryGateway

Deliverables:

- `search`
- `get`
- `upsert`
- lifecycle operations
- document ingestion call
- delete/export by scope call
- health/stats
- policy hook integration
- observability hook integration
- result bounding and redaction

Success criteria:

- Fake search and write operations work.
- Policy denial blocks adapter execution.
- Trace events are emitted safely.

### Step 5: Add `memory_store` Adapter

Deliverables:

- concrete adapter around `memory_store.service.MemoryService`
- search request mapping
- memory write mapping
- document ingestion mapping
- lifecycle update mapping
- delete/export mapping if wrapper supports it
- error normalization

Success criteria:

- Backend memory models map to wrapper calls.
- Wrapper-specific objects do not leak upward.
- ArcadeDB details do not leak upward.

### Step 6: Add Document Ingestion Behavior

Deliverables:

- deterministic document/chunk IDs
- source hash skip behavior
- replace changed chunks
- mark removed chunks
- ingest trace events

Success criteria:

- Re-ingesting unchanged document skips work.
- Changed sections update expected chunks.
- Search excludes removed chunks by default.

### Step 7: Add Search Result and Context Builder

Deliverables:

- normalized score mapping
- bounded result content
- optional highlights
- prompt context builder

Success criteria:

- Search returns chunks/records, not full documents by default.
- Context builder produces bounded prompt text.

### Step 8: Add Orchestration Wiring

Deliverables:

- inject `MemoryGateway` into `OrchestrationContext`
- update stub/direct strategy to optionally search memory
- update agent examples to use memory search and upsert through context

Success criteria:

- `POST /chat` path can retrieve memory through orchestration without changing API/session code.

### Step 9: Add Health and Capabilities Integration

Deliverables:

- memory health section
- safe memory capability flags
- fake/store health tests

Success criteria:

- `/health` includes safe memory readiness.
- `/capabilities` does not expose storage details.

### Step 10: Add Privacy Operations

Deliverables:

- `delete_by_scope`
- `export_by_scope`
- `forget`
- tombstone/hard-delete config
- policy checks

Success criteria:

- Scope delete/export requires durable scope and policy approval.
- Forget does not run during session reset.

---

## 38. Acceptance Criteria

This architecture is complete when:

- `MemoryGateway` provides provider-neutral search, get, upsert, lifecycle, document ingestion, delete/export, health, and stats methods.
- `MemoryStoreAdapter` is the only backend component that calls the existing `memory_store` Python wrapper.
- Agents and strategies use `MemoryGateway` through `OrchestrationContext` only.
- API routes do not call `MemoryGateway`, `memory_store`, ArcadeDB, embeddings, rerankers, or vector search directly.
- `SessionService` does not delete or mutate long-term memory during session reset.
- Session reset clears workflow state only.
- SQLite remains used for workflow state and trace stores only.
- ArcadeDB-backed memory remains behind `memory_store` and `MemoryStoreAdapter`.
- Memory search returns relevant chunks and records, not entire documents by default.
- Document chunks use deterministic IDs.
- Re-ingestion skips unchanged sources by source hash.
- Changed document sections update or replace affected chunks.
- Missing chunks are marked removed or deleted according to config.
- Agent memory supports upsert, promote, supersede, contradict, expire, and forget operations.
- Scope validation is required for all read/write/delete/export operations.
- Policy denial prevents memory adapter calls.
- Search result content is bounded before reaching agents.
- Raw memory queries are not logged or traced by default.
- Raw memory result content is not logged or traced by default.
- Memory operation trace events are trace-correlated with `trace_id` and `session_id` when available.
- Memory health output is safe and does not expose private store details.
- Capabilities output exposes only safe memory feature flags.
- Fake adapter tests can run without external services.
- Optional real `memory_store` tests are isolated from CI.
- The backend is ready for the next document: `backend-tooling-mcp-client-architecture.md`.

---

## 39. Anti-Patterns to Avoid

Avoid these during implementation:

- Importing `memory_store.service.MemoryService` in agents.
- Importing `memory_store.service.MemoryService` in strategies.
- Importing `memory_store.service.MemoryService` in API routes.
- Importing ArcadeDB clients outside the memory-store wrapper or adapter.
- Returning entire documents from normal search.
- Returning unbounded chunks to agents.
- Storing full memory results in workflow state.
- Logging raw memory content.
- Tracing raw memory content.
- Treating traces as memory.
- Treating workflow state as long-term memory.
- Deleting memory during session reset.
- Letting user metadata override memory scope.
- Allowing unscoped memory writes.
- Allowing delete/export without durable scope and policy approval.
- Letting `LLMGateway` search or write memory.
- Letting `MemoryGateway` call LLM providers for answer generation.
- Letting `MemoryGateway` execute MCP tools.
- Making document ingestion non-deterministic.
- Re-ingesting unchanged documents every run.
- Losing source provenance for chunks.
- Hiding score/debug fields needed for retrieval evaluation.
- Exposing embedding vectors in API responses or traces.
- Depending on real local ArcadeDB memory files in unit tests.

---

## 40. Future Documents That Depend on This Memory Layer

| Future Document | Dependency |
|---|---|
| `backend-tooling-mcp-client-architecture.md` | Tool execution remains separate from memory retrieval; tools may receive memory-derived context only through orchestration decisions. |
| `backend-orchestration-architecture.md` | Runtime uses `MemoryGateway` for retrieval and memory writes without depending on store details. |
| `backend-workflow-strategies-architecture.md` | Strategies can define RAG and memory-write behavior using gateway contracts. |
| `backend-agents-architecture.md` | Agents can search/upsert memory while remaining storage-neutral. |
| `backend-policy-architecture.md` | Defines final memory scope permissions, privacy rules, delete/export access, and content exposure policy. |
| `backend-evaluation-architecture.md` | Uses golden memories/search cases and score diagnostics to evaluate retrieval quality. |
| `backend-deployment-architecture.md` | Defines memory store paths, backups, environment-specific settings, and operational readiness checks. |

---

## 41. Summary

`backend-memory-store-adapter-architecture.md` defines the backend memory layer for long-term agent memory and document chunk retrieval.

It preserves all previously established boundaries: API routes remain thin, `SessionService` remains lifecycle-focused, `LLMGateway` remains provider/model-focused, SQLite remains for workflow state and traces, and ArcadeDB-backed memory remains isolated behind the existing `memory_store` wrapper.

The most important implementation rule is:

> **The memory gateway owns backend memory semantics, and the memory store adapter owns concrete `memory_store` integration. Agents and strategies ask for scoped memory operations; they must never know or care whether the backing implementation uses ArcadeDB, vector search, BM25, graph expansion, or reranking.**
