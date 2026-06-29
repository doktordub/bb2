# Backend Memory Store Adapter Implementation Plan

**Document:** `backend-memory-store-adapter-plan.md`  
**Version:** 1.0  
**Source alignment:** `backend-memory-store-adapter-architecture.md`, `backend-persistence-plan.md`, the current backend implementation baseline under `backend/`, and the installed local dependency surface under `backend/.venv/Lib/site-packages/memory_store` plus `backend/.venv/Lib/site-packages/agent_framework`  
**Repository rule:** all backend application code lives under `backend/`

---

## 1. Purpose

This plan converts the memory-store-adapter architecture into a phased implementation sequence that matches the current repository, the actual `memory_store` package that is installed in the backend virtual environment, and the repo rule that all backend runtime code belongs under `backend/`.

The plan is intentionally strict about repository boundaries:

- Backend application code belongs in `backend/`.
- Backend source modules belong in `backend/app/`.
- Backend tests belong in `backend/tests/`.
- Backend configuration files belong in `backend/config/`.
- Backend local data files belong in `backend/data/`.
- Documentation updates belong in `docs/`.
- No backend runtime, adapter, policy, orchestration, or agent integration code should be placed in the repository root, `frontend/`, `mcp/`, or `backend/.venv/Lib/site-packages/`.

For clarity, this document uses filesystem paths such as `backend/app/memory/gateway.py`. Python imports may still use the `app.*` package path because `backend/` is the Python project root.

---

## 2. Review Outcomes

The architecture document is strong on the boundary that matters most for this phase: orchestration-facing memory access must stay behind one backend-owned `MemoryGateway`, and concrete `memory_store` access must stay behind one backend-owned adapter.

The review also confirms that this phase is not greenfield work. The repository already contains a shallow memory boundary that should be deepened rather than replaced wholesale:

- `backend/app/contracts/memory.py` already defines a provider-neutral `MemoryGateway` protocol plus minimal scope, search, result, write, and record DTOs.
- `backend/app/persistence/memory_store_adapter.py` already acts as a lazy-import adapter around the installed `memory_store` package.
- `backend/app/persistence/factory.py` already wires memory startup through backend composition.
- `backend/app/testing/fakes/fake_memory.py` already provides a deterministic fake gateway for higher-level tests.
- `backend/app/orchestration/core.py` already injects `memory` into `OrchestrationContext`.
- `backend/app/foundation/health.py` and `backend/app/foundation/capabilities.py` already reserve memory-related health and capability sections.
- `backend/config/app.yaml` already contains a shallow `persistence.memory` section plus disabled-by-default `features.memory_enabled` and write-protected `allow_writes: false` defaults.
- `backend/tests/unit/contracts/test_fake_gateways.py` already enforces an import boundary that treats `memory_store` as forbidden outside backend-owned boundaries.

The review identifies the following implementation concerns that should shape the plan:

1. **The current public memory contract is thinner than the target architecture.**  
   `backend/app/contracts/memory.py` currently exposes only `search`, `upsert`, `forget`, and `health`, with minimal request and result shapes. The target architecture requires `get`, lifecycle operations, document ingestion, delete/export, stats, richer search hits, bounded context shaping, and safe health/stat result models.

2. **The current configuration shape is still persistence-era and too shallow.**  
   The repo currently exposes only `persistence.memory.memory_store.{config_path,database_path,default_scope,search_limit_default,search_limit_max,allow_writes}`. The architecture requires typed memory defaults, retrieval, scoring, chunking, lifecycle, privacy, and health settings that align with the actual `memory_store` wrapper configuration surface.

3. **The current implementation already has a memory boundary, but it is intentionally shallow.**  
   The persistence phase correctly deferred document ingestion, chunk lifecycle, ranking behavior, privacy export/delete flows, and policy-rich lifecycle semantics. The memory phase should extend that boundary instead of re-solving the earlier persistence problem.

4. **The installed `memory_store` package already provides most of the V1 capability set.**  
   The wrapper surface under `backend/.venv/Lib/site-packages/memory_store` already includes `get_memory`, `search`, `search_document_chunks`, `get_chunk`, `get_chunk_context`, `ingest_document`, `ingest_folder`, `promote`, `supersede`, `contradict`, `expire`, `forget`, `delete_by_scope`, `export_scope`, `stats`, and `health`, plus wrapper-owned retrieval, scoring, chunking, and privacy helpers. The plan should expose and normalize those capabilities rather than reimplement them in backend code.

5. **The wrapper scope model does not exactly match the target backend scope model.**  
   `memory_store.models.Scope` currently supports `user_id`, `project_id`, and `agent_id`. The architecture and current backend contracts also care about `session_id`, `usecase`, `tenant_id`, source/document identifiers, tags, and metadata. The backend gateway must therefore own the richer scope model and project only the compatible subset into `memory_store`, while preserving the richer fields for policy, tracing, and backend-side filtering.

6. **The backend should not duplicate wrapper retrieval, scoring, or ingestion logic.**  
   The installed wrapper already owns hybrid search, reciprocal-rank fusion, optional one-hop graph expansion, reranking, normalized component scores, deterministic chunk IDs, source hashing, unchanged-source skipping, and removed-chunk handling. Backend `app/memory/` code should normalize, bound, redact, and trace those results; it should not build a second ranking or chunking engine.

7. **Health, capabilities, policy, and trace surfaces are still too coarse.**  
   The current backend only exposes shallow memory health and a boolean memory capability. The current policy surface only has explicit memory coverage for `memory.upsert`, scope checks, and a generic `memory.*` prefix rule. The memory phase needs precise action names, safe health metadata, bounded stats, and trace-safe event payloads for the broader memory surface.

8. **One package-layout recommendation from the architecture should be adapted to existing repo conventions.**  
   The architecture recommends a dedicated `backend/app/memory/` runtime package. The repo should follow that for runtime implementation, factories, mappers, and adapter internals. However, provider-neutral public contracts should remain under `backend/app/contracts/memory.py` because the repo already treats `backend/app/contracts/` as the stable public boundary for orchestration capabilities.

9. **The memory phase should decouple memory runtime ownership from the persistence package.**  
   `backend/app/persistence/` should continue to own SQLite workflow-state and trace stores. The long-term memory runtime should move to `backend/app/memory/`, even if a temporary compatibility shim remains in `backend/app/persistence/memory_store_adapter.py` during the transition.

10. **`agent_framework` is a downstream consumer concern, not a dependency of the memory layer.**  
    The environment already has `backend/.venv/Lib/site-packages/agent_framework`, but the memory layer should not import `agent_framework` directly. Future agent plugins or adapters that use `agent_framework` must consume memory only through `OrchestrationContext.memory`.

---

## 3. `memory_store` Capability Alignment

The plan should align backend work to the installed wrapper surface exactly.

| Backend concern | Installed `memory_store` surface | Planning decision |
|---|---|---|
| Provider construction | `memory_store.service.MemoryService.from_config(...)` and `memory_store.store.MemoryStore.from_config(...)` | Keep the construction choice private to the backend adapter. Do not let callers depend on either class directly. |
| Store configuration | `memory_store.config.MemoryStoreSettings` with `database`, `embeddings`, `reranker`, `retrieval`, `scoring`, `chunking`, `privacy`, `api`, `logging` | Add backend typed memory settings that map cleanly onto this wrapper config shape instead of inventing a divergent schema. |
| Search | `search(MemorySearchQuery)` returning `MemorySearchResult` with `component_scores` and `normalized_scores` | Treat wrapper retrieval and ranking as authoritative. The backend should map, bound, and redact results, not re-rank them. |
| Chunk-only retrieval | `search_document_chunks(...)`, `get_chunk(...)`, `get_chunk_context(...)` | Use these methods internally for document-chunk workflows and prompt-context building where needed. |
| Single-record fetch | `get_memory(memory_id)` and `get_chunk(chunk_id)` | Backend `get(...)` should normalize the lookup shape and support memory/chunk retrieval without leaking wrapper-specific types. |
| Writes | `add_memory(...)`, `upsert_memory(...)`, `update_memory(...)` | Use `upsert_memory` for the core V1 write path. Keep `update_memory` internal unless the public contract needs partial updates later. |
| Lifecycle | `promote`, `supersede`, `contradict`, `expire`, `forget` | Expose these through provider-neutral backend lifecycle requests and normalized results. |
| Ingestion | `ingest_document(path, scope)` and `ingest_folder(path, scope)` | Expose `ingest_document` as the V1 public operation. Keep `ingest_folder` as an internal helper or local-only admin/test utility unless a later doc requires it publicly. |
| Privacy operations | `delete_by_scope`, `export_scope`, `forget_by_user`, `disable_memory`, `redact`, `import_memories` | Publicly expose only the architecture-required `forget`, `delete_by_scope`, and `export_by_scope` in V1. Leave the rest internal or explicitly deferred. |
| Stats and health | `stats()` and `health()` | Return safe backend-normalized results. Never expose raw `database_path` or wrapper-private dependency detail in API-facing payloads. |
| Scope model | `Scope(user_id, project_id, agent_id)` | Backend must retain richer scope metadata and map only the compatible subset into the wrapper. Map backend `agent_name` to wrapper `agent_id` when needed. |

Two additional alignment rules matter:

- The backend should keep using the installed wrapper that lives under `backend/.venv/Lib/site-packages/memory_store`; it should not copy wrapper code into `backend/app/`.
- The backend should not expose every wrapper feature just because it exists. `import_memories`, `redact`, `disable_memory`, and `add_feedback` are useful local capabilities, but they are not required by the current architecture document and should remain out of scope unless later documents require them.

---

## 4. Non-Negotiable Boundary Rules

- Treat `backend/` as the Python project root for all memory-layer work.
- Keep provider-neutral public contracts under `backend/app/contracts/`.
- Create concrete memory runtime implementation modules only under `backend/app/memory/`.
- Keep backend tests under `backend/tests/`.
- Keep backend configuration parsing and typed runtime views under `backend/app/config/` and canonical YAML under `backend/config/`.
- Do not place backend code in `backend/.venv/Lib/site-packages/`, the repository root, `frontend/`, or `mcp/`.
- Do not let `backend/app/api/` call `memory_store`, `ArcadeDB`, embeddings, rerankers, or vector-search libraries directly.
- Do not let `backend/app/session/` call `MemoryGateway` for normal reset behavior.
- Do not let `backend/app/orchestration/`, `backend/app/agents/`, or future `agent_framework`-based agents import `memory_store` directly.
- Do not let `backend/app/memory/` call LLM providers directly, execute MCP tools, or persist workflow state directly.
- Keep `backend/app/persistence/` focused on SQLite workflow-state and trace stores once memory bootstrap is moved into `backend/app/memory/`.
- Preserve the path `API -> SessionService -> OrchestrationRuntime -> Agent/Strategy -> MemoryGateway -> MemoryStoreAdapter`.
- Keep session reset semantics unchanged: workflow state only, never long-term memory deletion.
- Do not log or trace raw memory text, raw chunk text, embeddings, full documents, database paths, credentials, connection strings, or wrapper-internal payloads by default.
- Use the wrapper retrieval and ingestion engine rather than rebuilding hybrid search, graph expansion, scoring, or deterministic chunking in backend code.

---

## 5. Phase Overview

| Phase | Name | Primary Outcome |
|---|---|---|
| 0 | [DONE] Current Memory Baseline and Architecture Fit | The plan starts from the repo's real shallow memory boundary and the installed wrapper capabilities instead of describing Phase 11 as greenfield work. |
| 1 | [DONE] Memory Configuration and Typed Settings Alignment | Memory behavior becomes a typed, validated backend config surface that maps cleanly to `memory_store` settings and backend-only policy/trace constraints. |
| 2 | [DONE] Public Contract Deepening and Error Model | The stable provider-neutral memory contract under `backend/app/contracts/` grows to cover search, get, lifecycle, ingestion, privacy, health, and stats. |
| 3 | [DONE] Dedicated Memory Runtime Package, Factory, and Fake Adapter | Runtime implementation moves under `backend/app/memory/`, with a real adapter protocol, a deterministic fake adapter, and a dedicated memory factory. |
| 4 | [DONE] Default MemoryGateway Core | A backend-owned gateway can resolve scopes, enforce policy, apply disabled-mode behavior, emit safe traces, and bound results before calling any concrete adapter. |
| 5 | [DONE] Concrete `memory_store` Adapter Expansion | The backend adapter exposes the wrapper's real search, chunk, lifecycle, privacy, stats, and health capabilities without leaking wrapper types upward. |
| 6 | [DONE] Document Ingestion, Chunk Retrieval, and Context Builder | Deterministic markdown ingestion, chunk retrieval, and bounded prompt-context construction become first-class backend memory flows. |
| 7 | [DONE] Lifecycle, Privacy, and Admin Operations | Lifecycle updates, delete/export flows, bounded stats, and safe admin-oriented memory operations become complete and policy-gated. |
| 8 | [DONE] Composition Root, Orchestration Adoption, Health, Capabilities, and Agent Readiness | Startup wires the dedicated memory runtime cleanly, orchestration uses it without API/session drift, and health/capabilities report safe memory readiness. |
| 9 | [DONE] Fixtures, Quality Gates, Freeze, and Handoff | The memory slice is covered by focused tests, optional local wrapper suites, repo-accurate docs, and a full backend quality gate. |

---

## 6. Detailed Implementation Phases

### [DONE] Phase 0. Current Memory Baseline and Architecture Fit

**Goal**

Record the current backend and wrapper baseline so implementation extends the existing repo instead of describing a second memory boundary.

**Files already present**

- [DONE] `backend/app/contracts/memory.py`
- [DONE] `backend/app/contracts/context.py`
- [DONE] `backend/app/contracts/errors.py`
- [DONE] `backend/app/contracts/policy.py`
- [DONE] `backend/app/contracts/trace.py`
- [DONE] `backend/app/persistence/memory_store_adapter.py`
- [DONE] `backend/app/persistence/factory.py`
- [DONE] `backend/app/persistence/settings.py`
- [DONE] `backend/app/testing/fakes/fake_memory.py`
- [DONE] `backend/app/orchestration/core.py`
- [DONE] `backend/app/foundation/health.py`
- [DONE] `backend/app/foundation/capabilities.py`
- [DONE] `backend/app/policy/service.py`
- [DONE] `backend/config/app.yaml`

**Implementation outcomes already in place**

- [DONE] The backend already has a provider-neutral memory contract.
- [DONE] The orchestration context already reserves a `memory` capability slot.
- [DONE] Startup already builds a memory component through backend composition.
- [DONE] The current adapter already uses lazy import and lazy initialization for the external wrapper.
- [DONE] Health already reserves a memory section and degrades cleanly when memory is optional.
- [DONE] The repo already has a deterministic fake memory gateway for higher-level tests.
- [DONE] Default config already keeps memory effectively disabled for normal behavior through `features.memory_enabled: false` and `allow_writes: false`.

**Current limitations that later phases must fix**

- The public contract is too thin.
- Memory configuration is too shallow and still persistence-oriented.
- Runtime ownership still sits under `backend/app/persistence/` instead of `backend/app/memory/`.
- Policy actions, trace events, and health/capabilities are too coarse for the target memory surface.
- The current adapter exposes only a small subset of the wrapper's installed capabilities.
- No current strategy or example agent uses the memory gateway for real retrieval or write flows.

**Exit criteria**

- [DONE] The plan starts from the current `backend/` baseline and extends it rather than replacing it.

### [DONE] Phase 1. Memory Configuration and Typed Settings Alignment

**Goal**

Expand the current shallow memory configuration into a typed backend runtime view that maps cleanly onto the installed `memory_store` settings model while also carrying backend-only rules for scope, result limits, privacy, and tracing.

**Files to create or update**

- [DONE] `backend/app/config/schemas.py`
- [DONE] `backend/app/config/validation.py`
- [DONE] `backend/app/config/view.py`
- [DONE] `backend/app/persistence/settings.py`
- [DONE] `backend/config/app.yaml`
- [DONE] `backend/tests/unit/config/test_config_view.py`
- [DONE] `backend/tests/unit/config/test_validation.py`
- [DONE] `backend/tests/fixtures/config/memory_disabled.yaml`
- [DONE] `backend/tests/fixtures/config/memory_fake_basic.yaml`
- [DONE] `backend/tests/fixtures/config/memory_store_basic.yaml`
- [DONE] `backend/tests/fixtures/config/memory_store_markdown_chunking.yaml`
- [DONE] `backend/tests/fixtures/config/memory_invalid_chunking.yaml`
- [DONE] `backend/tests/fixtures/config/memory_invalid_scoring.yaml`
- [DONE] `backend/tests/fixtures/config/memory_invalid_scope_rules.yaml`

**Implementation tasks**

- [DONE] Add a canonical top-level `memory:` config section in `backend/config/app.yaml` for runtime semantics. The implemented end state now carries `memory.enabled`, `memory.provider`, `memory.required`, `memory.defaults`, `memory.store`, `memory.chunking`, `memory.search`, `memory.scoring`, `memory.lifecycle`, `memory.privacy`, and `memory.health`.
- [DONE] Map the backend config shape to the wrapper's actual settings surface instead of a generic placeholder shape, including database/schema settings, embedding and reranker settings, retrieval settings, chunking settings, scoring weights, and privacy defaults.
- [DONE] Add backend-only gateway settings for bounded context shaping, trace capture policy, durable-scope rules, and delete/export enablement controls.
- [DONE] Expose a typed `MemorySettings` runtime view from `backend/app/config/view.py` via `get_memory_settings(config)`.
- [DONE] Choose the canonical provider bootstrap source as top-level `memory.provider` and `memory.required`, while keeping the legacy `persistence.memory` shape as a compatibility alias instead of a second runtime source of truth.
- [DONE] Keep transition compatibility parser-only and view-level for legacy `persistence.memory` fixtures while new runtime code and new fixtures consume the canonical typed `MemorySettings` view.
- [DONE] Validate at config-load time that provider types are known, graph expansion hops stay within `0..1`, chunk overlap stays below chunk size, search limits remain ordered, scoring weights remain non-zero in aggregate, durable-scope rules remain coherent with policy defaults, and delete/export controls remain policy-safe.
- [DONE] Keep memory disabled and writes disallowed by default until a later phase or environment explicitly enables them.
- [DONE] Keep secrets and memory-store filesystem paths redacted in config summaries, health, and startup logs.

**Validation**

- [DONE] Add and pass focused config-view and validation tests for the expanded memory section.
- [DONE] Run `.venv\Scripts\python.exe -m pytest tests/unit/config/test_config_view.py tests/unit/config/test_validation.py` from `backend/`.
- [DONE] Run `.venv\Scripts\python.exe -m ruff check app/config tests/unit/config/test_config_view.py tests/unit/config/test_validation.py` from `backend/`.
- [DONE] Run `.venv\Scripts\python.exe -m mypy app/config` from `backend/`.

**Exit criteria**

- Memory runtime code can consume one typed `MemorySettings` object instead of raw nested config sections.
- The backend config shape maps directly to the installed wrapper's capabilities and constraints.
- Invalid memory config fails fast during backend startup.

### [DONE] Phase 2. Public Contract Deepening and Error Model

**Goal**

Deepen the stable provider-neutral memory contract under `backend/app/contracts/` so orchestration, policies, and future agent plugins have one complete backend-owned memory surface.

**Files to create or update**

- [DONE] `backend/app/contracts/memory.py`
- [DONE] `backend/app/contracts/errors.py`
- [DONE] `backend/app/contracts/policy.py`
- [DONE] `backend/app/contracts/trace.py`
- [DONE] `backend/app/contracts/__init__.py`
- [DONE] `backend/app/testing/fakes/fake_memory.py`
- [DONE] `backend/tests/unit/contracts/test_memory_contracts.py`
- [DONE] `backend/tests/unit/contracts/test_fake_gateways.py`

**Implementation tasks**

- [DONE] Expand `backend/app/contracts/memory.py` to include provider-neutral DTOs and protocol methods for:
  - [DONE] search
  - [DONE] get
  - [DONE] upsert
  - [DONE] promote
  - [DONE] supersede
  - [DONE] contradict
  - [DONE] expire
  - [DONE] forget
  - [DONE] ingest_document
  - [DONE] delete_by_scope
  - [DONE] export_by_scope
  - [DONE] health
  - [DONE] stats
- [DONE] Deepen the scope model so the backend can carry richer memory scope than the wrapper supports directly, including `user_id`, `project_id`, `tenant_id`, `session_id`, `agent_name`, `usecase`, `source_id`, `document_id`, tags, and metadata.
- [DONE] Introduce richer request and result models such as `MemoryGetRequest`, `MemoryUpsertRequest`, `MemoryLifecycleRequest`, `MemorySupersedeRequest`, `MemoryContradictRequest`, `MemoryForgetRequest`, `DocumentIngestRequest`, `MemoryDeleteByScopeRequest`, `MemoryExportByScopeRequest`, `MemorySearchFilters`, `MemorySearchResult`, `MemorySearchHit`, `MemoryScore`, `MemoryHealthResult`, and `MemoryStatsResult`.
- [DONE] Make `get(...)` flexible enough to normalize either memory-record or document-chunk lookup without leaking wrapper-specific method names by adding a `lookup_kind` hint.
- [DONE] Extend `backend/app/contracts/policy.py` action names to cover the full memory surface, including `memory.get`, `memory.ingest_document`, `memory.promote`, `memory.supersede`, `memory.contradict`, `memory.expire`, `memory.delete_by_scope`, `memory.export_by_scope`, and `memory.stats`.
- [DONE] Add normalized memory error subclasses in `backend/app/contracts/errors.py` for disabled memory, invalid scope, not-found, policy denial, adapter failure, ingestion failure, and privacy-operation failure.
- [DONE] Extend `backend/app/contracts/trace.py` with the memory lifecycle, ingestion, delete/export, health, and stats event names required by the gateway.
- [DONE] Update the contract-level fake gateway so higher-level tests can still use a simple deterministic implementation without needing the new adapter layer.

**Validation**

- [DONE] Add and pass focused contract tests for the expanded memory DTO and protocol surface.
- [DONE] Run `.venv\Scripts\python.exe -m pytest tests/unit/contracts/test_memory_contracts.py tests/unit/contracts/test_fake_gateways.py` from `backend/`.
- [DONE] Run `.venv\Scripts\python.exe -m ruff check app/contracts app/testing/fakes/fake_memory.py tests/unit/contracts/test_memory_contracts.py tests/unit/contracts/test_fake_gateways.py` from `backend/`.
- [DONE] Run `.venv\Scripts\python.exe -m mypy app/contracts app/testing/fakes/fake_memory.py` from `backend/`.

**Exit criteria**

- [DONE] The stable public memory contract covers the Phase 11 surface without importing wrapper types.
- [DONE] Policy and trace vocabularies can express the full memory action set.

### [DONE] Phase 3. Dedicated Memory Runtime Package, Factory, and Fake Adapter

**Goal**

Create a dedicated `backend/app/memory/` runtime package so long-term memory behavior is no longer owned by `backend/app/persistence/`.

**Files to create or update**

- [DONE] `backend/app/memory/__init__.py`
- [DONE] `backend/app/memory/gateway.py`
- [DONE] `backend/app/memory/scopes.py`
- [DONE] `backend/app/memory/errors.py`
- [DONE] `backend/app/memory/redaction.py`
- [DONE] `backend/app/memory/context_builder.py`
- [DONE] `backend/app/memory/health.py`
- [DONE] `backend/app/memory/stats.py`
- [DONE] `backend/app/memory/factory.py`
- [DONE] `backend/app/memory/adapters/__init__.py`
- [DONE] `backend/app/memory/adapters/base.py`
- [DONE] `backend/app/memory/adapters/fake.py`
- [DONE] `backend/app/persistence/memory_store_adapter.py`
- [DONE] `backend/tests/unit/memory/test_fake_adapter.py`
- [DONE] `backend/tests/unit/memory/test_factory.py`

**Implementation tasks**

- [DONE] Create `backend/app/memory/` as the runtime home for:
  - [DONE] gateway implementation
  - [DONE] scope resolution
  - [DONE] request/result normalization
  - [DONE] redaction helpers
  - [DONE] health and stats shaping
  - [DONE] adapter protocols and concrete adapters
  - [DONE] prompt-context building
- [DONE] Keep provider-neutral public DTOs under `backend/app/contracts/memory.py`; do not create a second competing public memory-contract tree.
- [DONE] Add a narrow adapter protocol in `backend/app/memory/adapters/base.py` that expresses the gateway's internal needs without exposing wrapper types.
- [DONE] Add a deterministic fake adapter in `backend/app/memory/adapters/fake.py` for memory-specific unit tests. This is separate from the higher-level fake gateway in `backend/app/testing/fakes/fake_memory.py`.
- [DONE] Add `backend/app/memory/factory.py` so memory construction is owned by the memory package, not by the persistence package.
- [DONE] Decide the transition strategy for `backend/app/persistence/memory_store_adapter.py`:
  - [DONE] move the implementation under `backend/app/memory/` and update construction imports atomically
  - [DONE] keep a very small compatibility shim that re-exports the new adapter for one phase only
- [DONE] Avoid moving SQLite workflow-state or trace code into `backend/app/memory/`; only long-term memory behavior should move.

**Validation**

- [DONE] Add and pass unit tests for fake-adapter determinism and memory-factory construction behavior.
- [DONE] Run `.venv\Scripts\python.exe -m pytest tests/unit/memory/test_fake_adapter.py tests/unit/memory/test_factory.py` from `backend/`.
- [DONE] Run `.venv\Scripts\python.exe -m ruff check app/memory tests/unit/memory/test_fake_adapter.py tests/unit/memory/test_factory.py` from `backend/`.
- [DONE] Run `.venv\Scripts\python.exe -m mypy app/memory` from `backend/`.

**Exit criteria**

- [DONE] Runtime ownership of long-term memory lives under `backend/app/memory/`.
- [DONE] A dedicated fake adapter exists for memory-unit testing without external services.

### [DONE] Phase 4. Default MemoryGateway Core

**Goal**

Implement a backend-owned default gateway that resolves scopes, enforces policy, applies disabled-mode behavior, records safe traces, and bounds results before any adapter call.

**Files to create or update**

- [DONE] `backend/app/memory/gateway.py`
- [DONE] `backend/app/memory/scopes.py`
- [DONE] `backend/app/memory/redaction.py`
- [DONE] `backend/app/policy/service.py`
- [DONE] `backend/app/contracts/policy.py`
- [DONE] `backend/app/contracts/trace.py`
- [DONE] `backend/app/observability/events.py`
- [DONE] `backend/tests/unit/memory/test_gateway.py`
- [DONE] `backend/tests/unit/memory/test_scope_resolution.py`
- [DONE] `backend/tests/unit/memory/test_policy_integration.py`
- [DONE] `backend/tests/unit/memory/test_disabled_mode.py`

**Implementation tasks**

- [DONE] Implement `DefaultMemoryGateway` in `backend/app/memory/gateway.py`.
- [DONE] Resolve effective scope from the combination of:
  - [DONE] explicit request scope
  - [DONE] authenticated request context
  - [DONE] `OrchestrationContext.runtime_metadata`
  - [DONE] configured default-scope rules
- [DONE] Enforce durable-scope rules at the gateway boundary before any adapter call.
- [DONE] Project the richer backend scope model down to wrapper-compatible `user_id`, `project_id`, and `agent_id` only at adapter time.
- [DONE] Route every memory operation through the policy service using the expanded `PolicyAction` vocabulary.
- [DONE] Implement disabled-memory semantics explicitly:
  - [DONE] optional search returns empty results or an empty result object according to the final contract
  - [DONE] writes and admin operations fail clearly with a normalized memory-disabled error
- [DONE] Emit memory trace events with safe payloads only. Trace payloads may include:
  - [DONE] operation name
  - [DONE] trace/session correlation IDs
  - [DONE] bounded counts
  - [DONE] scope-presence flags
  - [DONE] score summaries
  - [DONE] latency and success/failure metadata
- [DONE] Do not trace raw query text or raw result text by default.
- [DONE] Apply gateway-level result bounding and truncation after adapter calls but before records reach agents.
- [DONE] Keep wrapper-specific scoring and debug metadata optional and safe.

**Validation**

- [DONE] Add and pass focused gateway tests for scope resolution, policy denial, disabled mode, trace payload shaping, and bounded results.
- [DONE] Run `.venv\Scripts\python.exe -m pytest tests/unit/memory/test_gateway.py tests/unit/memory/test_scope_resolution.py tests/unit/memory/test_policy_integration.py tests/unit/memory/test_disabled_mode.py` from `backend/`.
- [DONE] Run `.venv\Scripts\python.exe -m ruff check app/memory app/policy app/observability/events.py tests/unit/memory/test_gateway.py tests/unit/memory/test_scope_resolution.py tests/unit/memory/test_policy_integration.py tests/unit/memory/test_disabled_mode.py` from `backend/`.
- [DONE] Run `.venv\Scripts\python.exe -m mypy app/memory app/policy` from `backend/`.

**Exit criteria**

- [DONE] The backend has one complete `DefaultMemoryGateway` implementation.
- [DONE] Memory policy and trace behavior are enforced before concrete adapter execution.

### [DONE] Phase 5. Concrete `memory_store` Adapter Expansion

**Goal**

Expand the concrete adapter so it exposes the installed wrapper's real capability set without leaking wrapper models, exceptions, or internal semantics upward.

**Files to create or update**

- [DONE] `backend/app/memory/adapters/memory_store.py`
- [DONE] `backend/app/persistence/memory_store_adapter.py`
- [DONE] `backend/app/memory/factory.py`
- [DONE] `backend/tests/unit/memory/test_memory_store_adapter.py`
- [DONE] `backend/tests/unit/memory/test_memory_store_adapter_health.py`
- [DONE] `backend/tests/unit/memory/test_memory_store_scope_mapping.py`
- [DONE] `backend/tests/fixtures/config/memory_store_basic.yaml`
- [DONE] `backend/tests/fixtures/config/memory_store_local_optional.yaml`

**Implementation tasks**

- [DONE] Expand the current lazy runtime loader to cover all wrapper types needed for V1 behavior, including search, lifecycle, ingestion, export, stats, and health.
- [DONE] Keep the choice of `MemoryService` versus the public `MemoryStore` facade private to the adapter. The implementation keeps the direct-service path internal.
- [DONE] Map backend operations to wrapper methods carefully:
  - [DONE] `search` -> `search(...)`
  - [DONE] chunk-only search or context lookup -> `get_chunk(...)` for lookup-kind routing, with chunk-context helpers deferred to phase 6 where they are first consumed
  - [DONE] `get` -> `get_memory(...)` or `get_chunk(...)` based on lookup kind
  - [DONE] `upsert` -> `upsert_memory(...)`
  - [DONE] lifecycle operations -> `promote`, `supersede`, `contradict`, `expire`, `forget`
  - [DONE] `ingest_document` -> `ingest_document(...)`
  - [DONE] `delete_by_scope` -> `delete_by_scope(...)`, with safe per-record fallback when backend-only scope filters are present
  - [DONE] `export_by_scope` -> `export_scope(...)`
  - [DONE] `stats` -> `stats()`
  - [DONE] `health` -> `health()`
- [DONE] Map backend `agent_name` to wrapper `agent_id` consistently.
- [DONE] Preserve richer backend-only scope fields in backend-owned metadata so they survive round-trips even though the wrapper cannot store them directly in `Scope`.
- [DONE] Normalize wrapper errors into backend errors. No wrapper exception classes leak above the adapter.
- [DONE] Normalize wrapper scores, record status, type names, and chunk metadata into backend DTOs.
- [DONE] Redact wrapper health output aggressively. The installed wrapper returns a raw `database_path`; backend health does not expose it.
- [DONE] Keep non-architecture wrapper features such as `import_memories`, `disable_memory`, `redact`, and `add_feedback` internal or deferred.

**Validation**

- [DONE] Add and pass unit tests for adapter request mapping, scope translation, stats/health mapping, and error normalization.
- [DONE] Run `.venv\Scripts\python.exe -m pytest tests/unit/memory/test_memory_store_adapter.py tests/unit/memory/test_memory_store_adapter_health.py tests/unit/memory/test_memory_store_scope_mapping.py` from `backend/`.
- [DONE] Run `.venv\Scripts\python.exe -m ruff check app/memory/adapters tests/unit/memory/test_memory_store_adapter.py tests/unit/memory/test_memory_store_adapter_health.py tests/unit/memory/test_memory_store_scope_mapping.py` from `backend/`.
- [DONE] Run `.venv\Scripts\python.exe -m mypy app/memory/adapters` from `backend/`.

**Exit criteria**

- [DONE] The concrete backend adapter covers the installed wrapper's V1-relevant capabilities.
- [DONE] No wrapper types or exceptions leak above the adapter boundary.

### [DONE] Phase 6. Document Ingestion, Chunk Retrieval, and Context Builder

**Goal**

Expose deterministic document-chunk ingestion and bounded prompt-context building as first-class backend memory behavior.

**Files to create or update**

- [DONE] `backend/app/contracts/memory.py`
- [DONE] `backend/app/memory/gateway.py`
- [DONE] `backend/app/memory/context_builder.py`
- [DONE] `backend/app/memory/__init__.py`
- [DONE] `backend/app/memory/adapters/base.py`
- [DONE] `backend/app/memory/adapters/fake.py`
- [DONE] `backend/app/memory/adapters/memory_store.py`
- [DONE] `backend/app/testing/fakes/fake_memory.py`
- [DONE] `backend/tests/unit/memory/test_ingestion.py`
- [DONE] `backend/tests/unit/memory/test_chunk_retrieval.py`
- [DONE] `backend/tests/unit/memory/test_context_builder.py`
- [DONE] `backend/tests/integration/memory/support.py`
- [DONE] `backend/tests/integration/memory/test_document_ingestion.py`
- [DONE] `backend/tests/integration/memory/test_chunk_search.py`
- [DONE] `backend/tests/fixtures/memory/documents/backend_sample.md`
- [DONE] `backend/tests/fixtures/memory/golden_search_cases.yaml`

**Implementation tasks**

- [DONE] Add public request/result DTOs and gateway paths for `ingest_document`, `get_chunk_context(...)`, and structured prompt-context payloads.
- [DONE] Lean on the wrapper's installed ingestion behavior for:
  - [DONE] markdown-section chunking
  - [DONE] deterministic source-hash and chunk-ID generation
  - [DONE] unchanged-source skipping
  - [DONE] changed-chunk replacement
  - [DONE] removed-chunk handling
- [DONE] Keep `ingest_folder` internal or local-only unless a later architecture document explicitly requires a public backend surface for it.
- [DONE] Add chunk retrieval helpers that can build bounded prompt context from:
  - [DONE] top search hits
  - [DONE] chunk windows from `get_chunk_context(...)`
  - [DONE] source/title/heading metadata
  - [DONE] safe score summaries
- [DONE] Ensure search returns relevant chunks and memory records, not entire documents, by default. The gateway now resolves read scopes without over-constraining long-term results with context-derived session and use-case fields.
- [DONE] Ensure the context builder enforces hard limits on per-result text, total assembled context text, and metadata verbosity.

**Validation**

- [DONE] Add and pass unit tests for ingestion mapping, unchanged-source skip behavior, removed-chunk filtering, and context-size bounding.
- [DONE] Add integration tests that exercise deterministic chunk ingestion and chunk-only search through the gateway.
- [DONE] Run `.venv\Scripts\python.exe -m pytest tests/unit/memory/test_ingestion.py tests/unit/memory/test_chunk_retrieval.py tests/unit/memory/test_context_builder.py tests/integration/memory/test_document_ingestion.py tests/integration/memory/test_chunk_search.py` from `backend/`.
- [DONE] Run `.venv\Scripts\python.exe -m ruff check app/memory app/contracts/memory.py app/testing/fakes/fake_memory.py tests/unit/memory/test_ingestion.py tests/unit/memory/test_chunk_retrieval.py tests/unit/memory/test_context_builder.py tests/integration/memory` from `backend/`.
- [DONE] Run `.venv\Scripts\python.exe -m mypy app/memory app/contracts/memory.py app/testing/fakes/fake_memory.py` from `backend/`.

**Exit criteria**

- [DONE] The backend can ingest markdown documents deterministically through the wrapper, including inline-content ingestion via a backend-owned temporary document path.
- [DONE] Prompt-context assembly is bounded, trace-safe, and chunk-oriented by default.

### [DONE] Phase 7. Lifecycle, Privacy, and Admin Operations

**Goal**

Complete the lifecycle and privacy/admin surface so long-term memory can be updated, superseded, contradicted, expired, forgotten, deleted by scope, and exported by scope under policy control.

**Files to create or update**

- [DONE] `backend/app/memory/gateway.py`
- [DONE] `backend/app/memory/health.py`
- [DONE] `backend/app/memory/stats.py`
- [DONE] `backend/app/memory/adapters/memory_store.py`
- [DONE] `backend/app/policy/service.py`
- [DONE] `backend/tests/unit/memory/test_lifecycle.py`
- [DONE] `backend/tests/unit/memory/test_privacy_operations.py`
- [DONE] `backend/tests/unit/memory/test_stats.py`
- [DONE] `backend/tests/integration/memory/test_scope_export.py`
- [DONE] `backend/tests/integration/memory/test_scope_delete.py`

**Implementation tasks**

- [DONE] Implement provider-neutral lifecycle request handling for:
  - [DONE] promote
  - [DONE] supersede
  - [DONE] contradict
  - [DONE] expire
  - [DONE] forget
- [DONE] Implement privacy/admin operations for:
  - [DONE] delete by scope
  - [DONE] export by scope
  - [DONE] bounded stats
- [DONE] Apply explicit policy checks before all lifecycle and admin operations.
- [DONE] Require durable scope for delete/export operations.
- [DONE] Ensure `forget` remains separate from session reset and cannot be triggered accidentally by normal chat flows.
- [DONE] Normalize wrapper behaviors that return `None` versus `MemoryRecord` so the public backend contract stays consistent.
- [DONE] Return safe stats summaries only. Counts by status and type are acceptable; raw document text, raw source paths, and private scope identifiers are not.

**Validation**

- [DONE] Add and pass focused tests for lifecycle behavior, durable-scope requirements, policy denial, and bounded export/stats payloads.
- [DONE] Run `.venv\Scripts\python.exe -m pytest tests/unit/memory/test_lifecycle.py tests/unit/memory/test_privacy_operations.py tests/unit/memory/test_stats.py tests/integration/memory/test_scope_export.py tests/integration/memory/test_scope_delete.py` from `backend/`.
- [DONE] Run `.venv\Scripts\python.exe -m ruff check app/memory app/policy tests/unit/memory/test_lifecycle.py tests/unit/memory/test_privacy_operations.py tests/unit/memory/test_stats.py tests/integration/memory/test_scope_export.py tests/integration/memory/test_scope_delete.py` from `backend/`.

**Exit criteria**

- [DONE] Lifecycle and privacy operations are complete, policy-gated, and separate from workflow-state reset semantics.
- [DONE] Stats and export behavior are safe and bounded.

### [DONE] Phase 8. Composition Root, Orchestration Adoption, Health, Capabilities, and Agent Readiness

**Goal**

Wire the dedicated memory runtime into backend startup cleanly, keep orchestration as the only normal chat consumer, and expose safe memory readiness through health and capabilities.

**Files to create or update**

- [DONE] `backend/app/config/bootstrap.py`
- [DONE] `backend/app/foundation/container.py`
- [DONE] `backend/app/persistence/factory.py`
- [DONE] `backend/app/persistence/health.py`
- [DONE] `backend/app/foundation/health.py`
- [DONE] `backend/app/foundation/capabilities.py`
- [DONE] `backend/app/orchestration/core.py`
- [DONE] `backend/app/api/errors.py`
- [DONE] `backend/app/testing/fakes/fake_agent.py`
- [DONE] `backend/tests/unit/test_app_factory.py`
- [DONE] `backend/tests/unit/test_health.py`
- [DONE] `backend/tests/unit/test_capabilities.py`
- [DONE] `backend/tests/integration/test_startup_memory.py`
- [DONE] `backend/tests/integration/memory/test_orchestration_memory_usage.py`

**Implementation tasks**

- [DONE] Update startup wiring so `backend/app/config/bootstrap.py` builds memory through `backend/app/memory/factory.py`.
- [DONE] Remove long-term memory runtime ownership from `backend/app/persistence/factory.py` once the new memory factory path is in place. A compatibility shim remains explicit and short-lived in `backend/app/persistence/memory_store_adapter.py`.
- [DONE] Update `backend/app/foundation/container.py` so the container exposes a dedicated `memory` service alongside persistence, LLM, policy, and orchestration runtime members.
- [DONE] Update `backend/app/foundation/health.py` and `backend/app/foundation/capabilities.py` to report safe memory readiness from the real gateway instead of a coarse provider/feature flag only.
- [DONE] Keep API routes thin and unchanged in ownership: the normal chat path remains `API -> SessionService -> OrchestrationRuntime -> Agent/Strategy -> MemoryGateway`.
- [DONE] Update `backend/app/orchestration/core.py` and at least one focused test agent example so memory is actually exercised through `OrchestrationContext.memory`.
- [DONE] Ensure the direct runtime or example agent uses memory only through the gateway, not through the wrapper.
- [DONE] Keep `backend/app/api/errors.py` aligned with the new normalized memory error subclasses so policy denial, disabled memory, unavailable memory, and validation failures map cleanly when they surface through chat.
- [DONE] Explicitly preserve session reset semantics.
- [DONE] Document `agent_framework` readiness: future agent plugins that use the installed `backend/.venv/Lib/site-packages/agent_framework` must still receive memory only through `OrchestrationContext.memory` and must not import `memory_store` directly.

**Validation**

- [DONE] Add and pass focused startup, orchestration, health, and capability tests for the real memory wiring path.
- [DONE] Run `.venv\Scripts\python.exe -m pytest tests/unit/test_app_factory.py tests/unit/test_health.py tests/unit/test_capabilities.py tests/integration/test_startup_memory.py tests/integration/memory/test_orchestration_memory_usage.py` from `backend/`.
- [DONE] Run `.venv\Scripts\python.exe -m ruff check app/config/bootstrap.py app/foundation app/orchestration app/memory app/api/errors.py tests/unit/test_app_factory.py tests/unit/test_health.py tests/unit/test_capabilities.py tests/integration/test_startup_memory.py tests/integration/memory/test_orchestration_memory_usage.py` from `backend/`.
- [DONE] Run `.venv\Scripts\python.exe -m mypy app/config/bootstrap.py app/foundation app/orchestration app/memory app/api/errors.py` from `backend/`.

**Exit criteria**

- [DONE] Startup builds memory through one dedicated memory-factory path.
- [DONE] Orchestration is the only normal chat consumer of the memory layer.
- [DONE] Health and capabilities expose safe memory readiness without leaking storage internals.

### [DONE] Phase 9. Fixtures, Quality Gates, Freeze, and Handoff

**Goal**

Make the memory slice reproducible, backend-local, and safe to hand off to the next architecture phase.

**Files to create or update**

- [DONE] `backend/tests/fixtures/config/memory_trace_capture_disabled.yaml`
- [DONE] `backend/tests/fixtures/config/memory_trace_capture_enabled_local_only.yaml`
- [DONE] `backend/tests/fixtures/config/memory_store_real_local.yaml`
- [DONE] `backend/tests/fixtures/memory/golden_memories.jsonl`
- [DONE] `backend/tests/fixtures/memory/golden_search_cases.yaml`
- [DONE] `backend/README.md`
- [DONE] `docs/backend-memory-store-adapter-plan.md`

**Implementation tasks**

- [DONE] Add fixture-backed coverage for:
  - [DONE] disabled memory mode
  - [DONE] fake adapter mode
  - [DONE] basic wrapper-backed mode
  - [DONE] invalid config rejection
  - [DONE] local-only trace-capture-enabled mode
  - [DONE] optional real wrapper smoke mode
- [DONE] Keep unit tests under `backend/tests/unit/memory/`.
- [DONE] Keep integration tests under `backend/tests/integration/memory/`.
- [DONE] Add optional local suites that exercise the installed wrapper and its real retrieval/ingestion surface without making CI depend on a private local ArcadeDB state.
- [DONE] Update `backend/README.md` with:
  - [DONE] canonical memory config paths
  - [DONE] memory-specific test commands
  - [DONE] local-only wrapper smoke-test expectations
  - [DONE] explicit Phase 11 boundary rules
- [DONE] Run the full backend quality gate from `backend/`:
  - [DONE] `.venv\Scripts\python.exe -m pytest`
  - [DONE] `.venv\Scripts\python.exe -m ruff check .`
  - [DONE] `.venv\Scripts\python.exe -m mypy app`
- [DONE] Confirm that the acceptance criteria from `docs/backend-memory-store-adapter-architecture.md` are satisfied at repo-accurate paths under `backend/`.
- [DONE] Record the handoff target for the next architecture phase: `docs/backend-tooling-mcp-client-architecture.md`.

**Exit criteria**

- [DONE] Focused unit and integration coverage exists for the memory slice.
- [DONE] Optional real-wrapper tests are isolated from CI.
- [DONE] Repo documentation matches the actual backend-local layout and startup/test behavior.
- [DONE] The backend is ready to hand off to the tooling/MCP phase without reopening memory-boundary questions.

---

## 7. Phase-by-Phase Success Definition

The implementation phase is complete when the repo satisfies all of the following at `backend/`-accurate paths:

- `MemoryGateway` provides provider-neutral search, get, upsert, lifecycle, document ingestion, delete/export, health, and stats methods.
- The concrete `memory_store` adapter is the only backend component that calls the installed wrapper directly.
- Provider-neutral public memory contracts remain under `backend/app/contracts/`.
- Concrete runtime memory behavior lives under `backend/app/memory/`.
- `backend/app/persistence/` remains focused on SQLite workflow-state and trace stores.
- Orchestration and agents use memory only through `OrchestrationContext.memory`.
- API routes do not call `memory_store`, ArcadeDB, embeddings, rerankers, or vector search directly.
- Session reset clears workflow state only.
- Search returns relevant chunks and records, not full documents, by default.
- Document ingestion remains deterministic and idempotent for unchanged sources.
- Lifecycle, privacy, and stats operations are policy-gated and safe.
- Health and capabilities expose only frontend-safe memory metadata.
- Fake-adapter tests run without external services.
- Optional real-wrapper tests remain isolated from CI.

---

## 8. Recommended Execution Order Inside The Repo

When implementation begins, the lowest-risk order is:

1. Land Phase 1 and Phase 2 together so config, policy actions, and the public contract agree before runtime work begins.
2. Land Phase 3 immediately after so `backend/app/memory/` becomes the single runtime home early.
3. Land Phase 4 before widening the concrete adapter so policy, scope, and trace rules are in place first.
4. Land Phase 5 and Phase 6 next so the richer wrapper capabilities are exposed through stable gateway behavior.
5. Land Phase 7 before broad startup adoption so lifecycle and privacy semantics are complete.
6. Land Phase 8 once the gateway and adapter surface are stable enough to wire into startup, health, and orchestration.
7. Finish with Phase 9 and a full backend quality gate.

That sequence minimizes churn in startup wiring and avoids widening the concrete adapter before the provider-neutral backend contract is stable.