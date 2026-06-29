# Backend Agents Implementation Plan

**Document:** `backend-agents-plan.md`  
**Version:** 1.0  
**Source alignment:** `backend-agents-architecture.md`, `backend-workflow-strategies-architecture.md`, `backend-orchestration-plan.md`, `backend-llm-gateway-plan.md`, `backend-memory-store-adapter-plan.md`, `backend-tooling-mcp-client-plan.md`, and the current backend implementation baseline  
**Repository rule:** all backend application code lives under `backend/`

---

## 1. Purpose

This plan converts the backend agents architecture into a repo-accurate implementation sequence that can be delivered in small, low-risk phases.

The plan is intentionally strict about repository boundaries:

- Backend application code belongs in `backend/`.
- Backend source modules belong in `backend/app/`.
- Backend tests belong in `backend/tests/`.
- Backend configuration files belong in `backend/config/`.
- Backend local data files belong in `backend/data/`.
- Documentation updates belong in `docs/`.
- No backend agent, orchestration, strategy, session, gateway, or policy runtime code should be placed in the repository root, `frontend/`, or `mcp/`.

For clarity, this document uses filesystem paths such as `backend/app/agents/plugins/general_assistant.py`. Python imports may still use the `app.*` package path because `backend/` is the Python project root.

This phase is not greenfield work. The repository already contains a meaningful agent-related baseline under `backend/`, but that baseline is still centered on orchestration-owned loading plus generic fake agents. The implementation plan therefore focuses on extracting a dedicated `backend/app/agents/` runtime package and migrating current orchestration behavior onto it rather than creating a second parallel agent stack.

---

## 2. Review Outcomes

The agents architecture document is implementation-ready and strong on runtime boundaries, provider neutrality, safe streaming, policy-aware capability use, and the rule that strategies own workflow shape while agents own task-specific behavior.

The review also confirms that the repository already contains a narrower but important backend baseline that should be deepened rather than replaced:

- `backend/app/contracts/agents.py` already defines a minimal provider-neutral `AgentPlugin` protocol and static `AgentMetadata` shape.
- `backend/app/orchestration/registry.py` already loads enabled agents from validated configuration and provides a minimal registry for orchestration.
- `backend/app/config/schemas.py`, `backend/app/config/view.py`, and `backend/app/config/validation.py` already model and validate top-level agent references, strategy agent references, use-case agent references, LLM profile references, and allowed-tool relationships.
- `backend/app/config/bootstrap.py` already builds `AgentRegistry.from_config(...)` during backend startup and injects the registry into orchestration runtime construction.
- `backend/app/orchestration/runtime.py` and `backend/app/orchestration/strategies/` already route direct, retrieval, tool-assisted, memory-update, router, fallback, and bounded-planner flows through configured agents.
- `backend/app/orchestration/health.py` already includes a minimal configured-agent readiness summary inside orchestration health.
- `backend/app/testing/fakes/fake_agent.py` already provides a deterministic backend-owned fake agent used by contract and orchestration tests.
- `backend/tests/unit/orchestration/` and `backend/tests/integration/orchestration/` already contain meaningful agent-through-strategy coverage using the current fake agent path.
- `backend/config/app.yaml` currently enables only a placeholder `support_agent` backed by `app.testing.fakes.fake_agent`, which is sufficient for local startup but not the intended V1 agent catalog.

The main implementation concerns that must be resolved during execution are:

1. **A dedicated `backend/app/agents/` runtime package does not exist yet.**  
   Agent behavior is currently split across `backend/app/contracts/agents.py`, `backend/app/orchestration/registry.py`, orchestration strategy code, and `backend/app/testing/fakes/fake_agent.py` instead of living behind a dedicated agent-layer package.

2. **The current public agent contract is too thin for the architecture.**  
   `AgentPlugin` currently exposes only `run(context) -> AgentResult`. The architecture requires a richer contract with normalized run requests/results, streaming events, safe descriptors, and safe health reporting.

3. **The current config surface is still loader-oriented, not capability-oriented.**  
   Current agent config is effectively `module` + `class_name` plus a small set of optional fields. The architecture requires typed defaults, capability grants, limits, context policy, prompt profile selection, and safe self-managed-mode validation.

4. **Registry ownership still sits in orchestration instead of the agent layer.**  
   `backend/app/orchestration/registry.py` currently owns loading and lookup. The architecture requires `AgentRegistry` and `AgentFactory` to become first-class agent-layer concerns under `backend/app/agents/`.

5. **The current fake agent crosses the intended V1 default boundary.**  
   `backend/app/testing/fakes/fake_agent.py` can call memory and tools directly through the orchestration context. That is useful for current tests, but the V1 production default should be strategy-managed memory/tool behavior with agents producing answers, tool intents, and memory candidates instead of executing external capabilities directly.

6. **Current orchestration code still depends on legacy agent/result shapes.**  
   Strategies and runtime logic already work, but they are built around `AgentPlugin` and generic `AgentResult` behavior. The migration to structured `AgentRunRequest`, `AgentRunResult`, and `AgentStreamEvent` objects needs a compatibility bridge so the backend can evolve without breaking session or API behavior.

7. **There is no dedicated backend agent test and fixture surface yet.**  
   The repository does not yet have a focused `backend/tests/unit/agents/`, `backend/tests/integration/agents/`, or an agent-specific fixture suite that covers built-in plugin types, invalid capability combinations, stream safety, review behavior, and policy denial.

8. **Existing orchestration DTO ownership should be reused where it is already correct.**  
   Logical `ToolIntent`, memory-intent helpers, prompt-input helpers, and workflow-state-delta ownership already live under `backend/app/orchestration/`. Agent implementation should consume those bounded DTOs rather than duplicate them under a second package.

9. **One architecture illustration should be adapted to current repo conventions.**  
   The architecture suggests an agents-local config module, but this repository centralizes YAML-backed settings under `backend/app/config/`. This plan therefore keeps canonical YAML schema/view/validation work in `backend/app/config/` and uses `backend/app/agents/` for runtime-only code.

## 3. Non-Negotiable Boundary Rules

- Treat `backend/` as the Python project root for all agent work.
- Create runtime agent modules only under `backend/app/agents/` plus existing shared backend packages such as `backend/app/config/`, `backend/app/orchestration/`, `backend/app/testing/fakes/`, and `backend/app/foundation/` when integration requires it.
- Keep backend tests under `backend/tests/` and backend config fixtures under `backend/tests/fixtures/config/`.
- Keep backend configuration under `backend/config/` and backend-local runtime data under `backend/data/`.
- Keep documentation-only artifacts under `docs/`.
- Do not place backend agent, orchestration, session, LLM, memory, tool, or policy runtime code in the repository root, `frontend/`, or `mcp/`.
- Do not let `backend/app/agents/` import `backend/app/api/`, `backend/app/session/`, `sqlite3`, `aiosqlite`, `memory_store.service.MemoryService`, ArcadeDB clients, `backend/app/tools/mcp/`, provider SDKs, or frontend DTOs.
- Agents may call LLMs only through `LLMGateway`, memory only through `MemoryGateway`, and tools only through `ToolGateway`.
- Keep workflow shape in strategies. Agents may answer, review, emit logical tool intents, and emit memory candidates, but they must not persist workflow state directly.
- Do not let agents or the agent registry write directly to `TraceStore`; safe trace/event recording must go through the observability facade or helper layer.
- Keep API and session contracts unchanged while the agent layer is introduced underneath them.
- If compatibility shims are needed during migration, keep them under `backend/app/agents/`, `backend/app/contracts/`, or `backend/app/orchestration/` and remove or freeze them before phase close.
- Canonical backend YAML examples must use backend-root-relative paths and backend-owned module names only.
- Keep unique test basenames across backend test directories on Windows to avoid pytest import-file mismatches.

---

## 4. Phase Overview

| Phase | Name | Primary Outcome |
|---|---|---|
| 0 | [DONE] Current Minimal Agent Baseline | The repository already has config-backed agent loading and fake-agent coverage rooted under `backend/`. |
| 1 | Agent Configuration and Typed Settings Alignment | Canonical agent settings, defaults, plugin types, and validation live under `backend/app/config/` and `backend/config/app.yaml`. |
| 2 | [DONE] Dedicated Agent Models, Contracts, and Compatibility Surface | A real `backend/app/agents/` package exists with structured run/result/stream/error models while legacy imports keep working during migration. |
| 3 | [DONE] Agent Registry, Factory, and Startup Composition | Registry and factory ownership move into the agent layer, and backend startup builds agents through a redacted composition path. |
| 4 | [DONE] Base LLM Agent and General Assistant | The first built-in production agent exists and can answer through `LLMGateway` without memory or tool execution. |
| 5 | [DONE] Document Q&A and Tool-Using Agents | Retrieval-grounded answers and logical tool-intent generation are implemented as first-class backend agents. |
| 6 | [DONE] Project, Memory Curator, and Reviewer Agents | The remaining V1 built-in agent types are implemented with safe scope, review, and memory-candidate behavior. |
| 7 | [DONE] Strategy and Runtime Migration to Structured Agents | Orchestration strategies and runtime invoke agents through the new structured contract without changing API/session boundaries. |
| 8 | [DONE] Health, Capabilities, and Safe Exposure | Agent readiness and safe capability metadata flow through backend startup, health, and capabilities reporting. |
| 9 | [DONE] Fakes, Fixtures, Boundary Tests, and Freeze | Dedicated agent quality gates, dependency-boundary tests, fixtures, and documentation complete the phase and hand off to policy work. |

---

## 5. Detailed Implementation Phases

### [DONE] Phase 0. Current Minimal Agent Baseline

**Goal**

Record the agent-related work that already exists so the plan extends the current backend instead of re-describing a greenfield slice.

**Files already present**

- [DONE] `backend/app/contracts/agents.py`
- [DONE] `backend/app/orchestration/registry.py`
- [DONE] `backend/app/orchestration/runtime.py`
- [DONE] `backend/app/orchestration/strategies/`
- [DONE] `backend/app/config/bootstrap.py`
- [DONE] `backend/app/testing/fakes/fake_agent.py`
- [DONE] `backend/tests/unit/contracts/test_fake_agent_strategy.py`
- [DONE] `backend/tests/unit/orchestration/test_direct_agent_strategy.py`
- [DONE] `backend/tests/unit/orchestration/test_retrieval_strategy.py`
- [DONE] `backend/tests/unit/orchestration/test_tool_assisted_strategy.py`
- [DONE] `backend/tests/integration/orchestration/`

**Implementation outcomes already in place**

- [DONE] Validated backend configuration can already reference enabled agents under `backend/config/app.yaml`.
- [DONE] Backend startup already builds a minimal agent registry during lifespan initialization in `backend/app/config/bootstrap.py`.
- [DONE] Orchestration runtime and strategies already resolve configured agents for direct, retrieval, tool-assisted, router, memory-update, fallback, and bounded-planner flows.
- [DONE] The current backend-owned fake agent already exercises LLM, memory, and tool access through provider-neutral context/gateway boundaries instead of importing provider SDKs directly.
- [DONE] Current unit and integration tests already prove the `API -> SessionService -> OrchestrationRuntime -> WorkflowStrategy -> configured agent` path using fakes.

**Current limitations that the next phases must fix**

- The current agent contract is still `run(context)` only.
- There is no dedicated `backend/app/agents/` runtime package.
- Registry ownership still lives under `backend/app/orchestration/`.
- The canonical config model does not yet express agent defaults, capability grants, limits, context policy, or prompt-profile behavior.
- The current fake agent is appropriate for tests but not as the production implementation model for safe V1 agents.
- Health and capabilities exposure is still minimal and registry-focused instead of plugin-focused.
- There is no dedicated backend agent test and fixture surface yet.

**Exit criteria**

- [DONE] The implementation plan starts from the real backend baseline under `backend/` instead of inventing a second agent stack.

### [DONE] Phase 1. Agent Configuration and Typed Settings Alignment

**Goal**

Introduce a canonical typed agent configuration surface that matches the architecture while remaining consistent with the repository's existing config ownership pattern under `backend/app/config/`.

**Files to create or update**

- [DONE] `backend/app/config/schemas.py`
- [DONE] `backend/app/config/validation.py`
- [DONE] `backend/app/config/view.py`
- [DONE] `backend/config/app.yaml`
- [DONE] `backend/tests/unit/config/test_config_view.py`
- [DONE] `backend/tests/unit/config/test_validation.py`
- [DONE] `backend/tests/unit/agents/test_agent_fixture_examples.py`
- [DONE] `backend/tests/fixtures/config/agents_general_assistant.yaml`
- [DONE] `backend/tests/fixtures/config/agents_document_qa.yaml`
- [DONE] `backend/tests/fixtures/config/agents_tool_using.yaml`
- [DONE] `backend/tests/fixtures/config/agents_project.yaml`
- [DONE] `backend/tests/fixtures/config/agents_memory_curator.yaml`
- [DONE] `backend/tests/fixtures/config/agents_reviewer.yaml`
- [DONE] `backend/tests/fixtures/config/agents_custom_legacy.yaml`
- [DONE] `backend/tests/fixtures/config/agents_invalid_missing_llm_profile.yaml`
- [DONE] `backend/tests/fixtures/config/agents_invalid_unknown_type.yaml`
- [DONE] `backend/tests/fixtures/config/agents_invalid_raw_mcp_tool.yaml`
- [DONE] `backend/tests/fixtures/config/agents_invalid_unbounded_self_managed.yaml`
- [DONE] `backend/tests/fixtures/config/agents_invalid_memory_write_without_policy.yaml`
- [DONE] `backend/tests/fixtures/config/agents_invalid_disabled_reference.yaml`

**Implementation tasks**

- [DONE] Add a canonical `agents.defaults` and `agents.plugins` config surface in `backend/config/app.yaml`.
- [DONE] Add typed settings in `backend/app/config/view.py` for:
   - [DONE] `AgentCapabilitySettings`
   - [DONE] `AgentLimitSettings`
   - [DONE] `AgentContextPolicySettings`
   - [DONE] `AgentPluginSettings`
   - [DONE] `AgentsSettings`
- [DONE] Keep YAML-backed settings ownership in `backend/app/config/` rather than creating a parallel settings parser under `backend/app/agents/`.
- [DONE] Normalize built-in plugin `type` values to the architecture vocabulary:
   - [DONE] `general_assistant`
   - [DONE] `document_qa`
   - [DONE] `tool_using`
   - [DONE] `project_agent`
   - [DONE] `memory_curator`
   - [DONE] `reviewer`
   - [DONE] `custom`
- [DONE] Keep a bounded compatibility bridge so the current legacy flat `agents.<name>` entries and `module` / `class_name` fields can be translated into the canonical plugin model during migration.
- [DONE] Validate missing or unknown LLM profiles, missing or unsafe prompt-profile references when strict checking is enabled, invalid tool-intent allowlists, invalid self-managed settings, and memory-write settings without policy gates.
- [DONE] Validate that use-case and strategy references point only at enabled agents and that tool allowlists remain subsets of allowed logical backend tool names.
- [DONE] Treat `custom` as an explicit escape hatch rather than the default pattern; canonical backend examples should move toward built-in plugin types.

**Validation**

- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m pytest tests/unit/config/test_config_view.py tests/unit/config/test_validation.py tests/unit/agents/test_agent_fixture_examples.py`
- Run from `backend/`: `.venv\Scripts\python.exe -m ruff check app/config tests/unit/config/test_config_view.py tests/unit/config/test_validation.py tests/unit/agents/test_agent_fixture_examples.py`
- Run from `backend/`: `.venv\Scripts\python.exe -m mypy app/config`

**Exit criteria**

- [DONE] Typed agent settings are available through the validated config pipeline.
- [DONE] Invalid agent config fails fast during backend startup.
- [DONE] Canonical backend YAML and fixture examples reference backend-owned agent settings under `backend/config/` and `backend/tests/fixtures/config/` only.

### [DONE] Phase 2. Dedicated Agent Models, Contracts, and Compatibility Surface

**Goal**

Create a real `backend/app/agents/` runtime package with normalized models and error types while preserving compatibility for current orchestration code during the migration window.

**Files to create or update**

- [DONE] `backend/app/agents/__init__.py`
- [DONE] `backend/app/agents/base.py`
- [DONE] `backend/app/agents/models.py`
- [DONE] `backend/app/agents/capabilities.py`
- [DONE] `backend/app/agents/errors.py`
- [DONE] `backend/app/agents/prompts.py`
- [DONE] `backend/app/agents/result_builder.py`
- [DONE] `backend/app/agents/stream_mapping.py`
- [DONE] `backend/app/agents/policy.py`
- [DONE] `backend/app/agents/trace_helpers.py`
- [DONE] `backend/app/contracts/agents.py`
- [DONE] `backend/app/testing/fakes/fake_agent.py`
- [DONE] `backend/tests/unit/agents/test_agent_models.py`
- [DONE] `backend/tests/unit/agents/test_agent_errors.py`
- [DONE] `backend/tests/unit/agents/test_agent_capabilities.py`
- [DONE] `backend/tests/unit/agents/test_agent_stream_mapping.py`

**Implementation tasks**

- [DONE] Define the structured agent-layer contracts and models, including:
   - [DONE] `AgentHandle`
   - [DONE] `AgentRunRequest`
   - [DONE] `AgentRunResult`
   - [DONE] `AgentStreamEvent`
   - [DONE] `AgentDescriptor`
   - [DONE] `AgentHealthResult`
   - [DONE] `AgentReviewResult`
   - [DONE] `AgentUsageSummary`
- [DONE] Keep logical `ToolIntent`, memory-intent, prompt-context, and workflow-state-delta ownership in `backend/app/orchestration/` where the repo already owns those DTOs.
- [DONE] Add agent-layer error types for configuration, capability, policy denial, prompt build, LLM, tool-intent, memory-candidate, review, limit, and cancellation failures.
- [DONE] Make `backend/app/contracts/agents.py` a compatibility surface that re-exports or adapts the new agent-layer protocol while current orchestration code is migrated.
- [DONE] Update or wrap `backend/app/testing/fakes/fake_agent.py` so tests can exercise the new protocol without reaching real providers or stores.
- [DONE] Ensure the new models cannot carry raw prompts, raw provider payloads, raw tool payloads, raw memory records, raw workflow-state documents, credentials, hidden scratchpads, or stack traces.

**Validation**

- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m pytest tests/unit/agents/test_agent_models.py tests/unit/agents/test_agent_errors.py tests/unit/agents/test_agent_capabilities.py tests/unit/agents/test_agent_stream_mapping.py tests/unit/contracts/test_fake_agent_strategy.py`
- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m ruff check app/agents app/contracts/agents.py app/testing/fakes/fake_agent.py tests/unit/agents tests/unit/contracts/test_fake_agent_strategy.py`
- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m mypy app/agents app/contracts/agents.py`

**Exit criteria**

- [DONE] `backend/app/agents/` exists as a first-class backend runtime package.
- [DONE] Legacy imports still work during migration.
- [DONE] Structured agent models are available without requiring API or session objects.

### [DONE] Phase 3. Agent Registry, Factory, and Startup Composition

**Goal**

Move registry and factory ownership into the agent layer and make backend startup construct agents through a safe, redacted composition path.

**Files to create or update**

- [DONE] `backend/app/agents/registry.py`
- [DONE] `backend/app/agents/factory.py`
- [DONE] `backend/app/agents/plugins/__init__.py`
- [DONE] `backend/app/orchestration/registry.py`
- [DONE] `backend/app/config/bootstrap.py`
- [DONE] `backend/app/orchestration/health.py`
- [DONE] `backend/app/orchestration/capabilities.py`
- [DONE] `backend/tests/unit/agents/test_agent_registry.py`
- [DONE] `backend/tests/unit/agents/test_agent_factory.py`
- [DONE] `backend/tests/unit/orchestration/test_orchestration_health_summary.py`

**Implementation tasks**

- [DONE] Move `AgentRegistry` ownership from `backend/app/orchestration/registry.py` to `backend/app/agents/registry.py`.
- [DONE] Implement a `DefaultAgentRegistry` with safe `register`, `resolve`, `list`, and `contains` behavior.
- [DONE] Implement an `AgentFactory` that builds built-in agent types by `type` and supports `custom` entrypoints only when explicitly configured.
- [DONE] Keep `backend/app/orchestration/registry.py` as a thin compatibility wrapper or re-export during the migration window so existing imports do not break immediately.
- [DONE] Emit a redacted startup summary from `backend/app/config/bootstrap.py` that reports configured counts, built-in types, and streaming support without exposing prompts, credentials, endpoints, or paths.
- [DONE] Keep registry/factory code free of provider-SDK, SQLite, MCP-client, and API-route dependencies.
- [DONE] Update orchestration health/capability helpers to consume safe registry descriptors instead of the old component-only shape.

**Validation**

- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m pytest tests/unit/agents/test_agent_registry.py tests/unit/agents/test_agent_factory.py tests/unit/orchestration/test_orchestration_health_summary.py`
- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m ruff check app/agents app/orchestration/registry.py app/config/bootstrap.py app/orchestration/health.py app/orchestration/capabilities.py tests/unit/agents tests/unit/orchestration/test_orchestration_health_summary.py`
- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m mypy app/agents app/orchestration/registry.py app/config/bootstrap.py`

**Exit criteria**

- [DONE] Backend startup can build a structured agent registry through `backend/app/agents/`.
- [DONE] Duplicate, missing, and disabled agent references fail clearly.
- [DONE] Orchestration health can report safe registry readiness without depending on orchestration-owned loading logic.

### [DONE] Phase 4. Base LLM Agent and General Assistant

**Goal**

Implement the first production agent path and establish the shared LLM-agent helper that later plugins build on.

**Files to create or update**

- [DONE] `backend/app/agents/plugins/base_llm_agent.py`
- [DONE] `backend/app/agents/plugins/general_assistant.py`
- [DONE] `backend/app/agents/prompts.py`
- [DONE] `backend/app/agents/result_builder.py`
- [DONE] `backend/app/agents/trace_helpers.py`
- [DONE] `backend/config/app.yaml`
- [DONE] `backend/tests/unit/agents/test_base_llm_agent.py`
- [DONE] `backend/tests/unit/agents/test_general_assistant.py`
- [DONE] `backend/tests/integration/agents/test_general_assistant_runtime.py`

**Implementation tasks**

- [DONE] Implement `BaseLlmAgent` with:
   - [DONE] LLM profile resolution
   - [DONE] policy-aware profile use
   - [DONE] prompt-builder hooks
   - [DONE] safe output normalization
   - [DONE] safe trace summaries
   - [DONE] normalized streaming support
- [DONE] Implement `GeneralAssistantAgent` as the smallest built-in production agent.
- [DONE] Keep default general-assistant behavior limited to direct answering through `LLMGateway` without memory or tool execution.
- [DONE] Use fake LLM coverage first, then wire runtime integration through existing orchestration tests.
- [DONE] Replace the canonical default backend example from a placeholder fake support agent to a built-in general-assistant plugin when the implementation is stable.

**Validation**

- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m pytest tests/unit/agents/test_base_llm_agent.py tests/unit/agents/test_general_assistant.py tests/integration/agents/test_general_assistant_runtime.py tests/integration/orchestration/test_direct_runtime_with_fake_llm.py`
- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m ruff check app/agents tests/unit/agents tests/integration/agents tests/integration/orchestration/test_direct_runtime_with_fake_llm.py`
- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m mypy app/agents`

**Exit criteria**

- [DONE] A built-in backend agent can answer through `LLMGateway` without memory or tools.
- [DONE] No raw provider responses leave the gateway boundary.
- [DONE] The canonical backend config can use a built-in assistant plugin instead of only the placeholder fake path.

### [DONE] Phase 5. Document Q&A and Tool-Using Agents

**Goal**

Implement the first two strategy-specialized built-in agents: one for retrieval-grounded answers and one for logical tool-intent generation.

**Files to create or update**

- [DONE] `backend/app/agents/plugins/document_qa.py`
- [DONE] `backend/app/agents/plugins/tool_using.py`
- [DONE] `backend/app/agents/prompts.py`
- [DONE] `backend/app/agents/result_builder.py`
- [DONE] `backend/tests/unit/agents/test_document_qa.py`
- [DONE] `backend/tests/unit/agents/test_tool_using.py`
- [DONE] `backend/tests/integration/agents/test_document_qa_runtime.py`
- [DONE] `backend/tests/integration/agents/test_tool_using_runtime.py`

**Implementation tasks**

- [DONE] Implement `DocumentQaAgent` so retrieval strategies can pass bounded prompt context into the agent without giving it direct storage access in default mode.
- [DONE] Implement `ToolUsingAgent` so tool-assisted strategies can request logical tool intents and final answers from safe tool context.
- [DONE] Treat retrieved memory/document/tool text as untrusted data in all prompt builders.
- [DONE] Reuse existing orchestration prompt-context and tool-intent helpers instead of duplicating those DTOs in `backend/app/agents/`.
- [DONE] Reject tool names outside configured `available_tools` or configured logical agent allowlists.
- [DONE] Keep both agents in strategy-managed mode by default: no direct memory search and no direct tool execution.

**Validation**

- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m pytest tests/unit/agents/test_document_qa.py tests/unit/agents/test_tool_using.py tests/integration/agents/test_document_qa_runtime.py tests/integration/agents/test_tool_using_runtime.py tests/unit/orchestration/test_retrieval_strategy.py tests/unit/orchestration/test_tool_assisted_strategy.py`
- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m ruff check app/agents tests/unit/agents tests/integration/agents tests/unit/orchestration/test_retrieval_strategy.py tests/unit/orchestration/test_tool_assisted_strategy.py`
- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m mypy app/agents`

**Exit criteria**

- [DONE] Retrieval-grounded answers and logical tool-intent generation are available as built-in backend agents.
- [DONE] Tool execution still occurs only through strategies and `ToolGateway` in the default V1 flow.

### [DONE] Phase 6. Project, Memory Curator, and Reviewer Agents

**Goal**

Implement the remaining V1 built-in agents for project-scoped work, memory-candidate extraction, and bounded review behavior.

**Files to create or update**

- [DONE] `backend/app/agents/plugins/project_agent.py`
- [DONE] `backend/app/agents/plugins/memory_curator.py`
- [DONE] `backend/app/agents/plugins/reviewer.py`
- [DONE] `backend/app/agents/prompts.py`
- [DONE] `backend/app/agents/policy.py`
- [DONE] `backend/app/agents/trace_helpers.py`
- [DONE] `backend/tests/unit/agents/test_project_agent.py`
- [DONE] `backend/tests/unit/agents/test_memory_curator.py`
- [DONE] `backend/tests/unit/agents/test_reviewer.py`
- [DONE] `backend/tests/integration/agents/test_memory_curator_runtime.py`
- [DONE] `backend/tests/integration/agents/test_reviewer_runtime.py`

**Implementation tasks**

- [DONE] Implement `ProjectAgent` with explicit project-scope validation and project-oriented prompt/tool-intent restrictions.
- [DONE] Implement `MemoryCuratorAgent` so memory-update strategies can request bounded `MemoryCandidate` outputs without direct writes in the default flow.
- [DONE] Implement `ReviewerAgent` so planner or post-processing flows can perform bounded review passes with safe findings only.
- [DONE] Keep self-managed memory/tool behavior disabled by default even if the config model can express it; any later enablement must remain explicit, limited, and policy-guarded.
- [DONE] Ensure candidate extraction, review findings, and project outputs remain safe for trace/state/capability exposure.

**Validation**

- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m pytest tests/unit/agents/test_project_agent.py tests/unit/agents/test_memory_curator.py tests/unit/agents/test_reviewer.py tests/integration/agents/test_memory_curator_runtime.py tests/integration/agents/test_reviewer_runtime.py tests/unit/orchestration/test_memory_update_strategy.py tests/unit/orchestration/test_bounded_planner_strategy.py`
- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m ruff check app/agents tests/unit/agents tests/integration/agents tests/unit/orchestration/test_memory_update_strategy.py tests/unit/orchestration/test_bounded_planner_strategy.py`
- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m mypy app/agents`

**Exit criteria**

- [DONE] All V1 built-in backend agent types from the architecture are implemented.
- [DONE] Memory candidates still flow through strategy, policy, and `MemoryGateway` before any write occurs.
- [DONE] Review behavior is safe and bounded.

### [DONE] Phase 7. Strategy and Runtime Migration to Structured Agents

**Goal**

Cut orchestration over from the legacy `AgentPlugin` shape to the new structured agent layer while keeping API and session behavior stable.

**Files to create or update**

- [DONE] `backend/app/orchestration/strategy.py`
- [DONE] `backend/app/orchestration/strategy_factory.py`
- [DONE] `backend/app/orchestration/runtime.py`
- [DONE] `backend/app/orchestration/result_builder.py`
- [DONE] `backend/app/orchestration/stream_mapping.py`
- [DONE] `backend/app/orchestration/strategies/direct_agent.py`
- [DONE] `backend/app/orchestration/strategies/retrieval_augmented.py`
- [DONE] `backend/app/orchestration/strategies/tool_assisted.py`
- [DONE] `backend/app/orchestration/strategies/memory_update.py`
- [DONE] `backend/app/orchestration/strategies/router.py`
- [DONE] `backend/app/orchestration/strategies/bounded_planner.py`
- [DONE] `backend/app/testing/fakes/fake_agent.py`
- [DONE] `backend/app/testing/fakes/fake_strategy.py`
- [DONE] `backend/tests/unit/orchestration/`
- [DONE] `backend/tests/integration/orchestration/`
- [DONE] `backend/tests/unit/session/test_session_handle_chat.py`
- [DONE] `backend/tests/unit/session/test_session_stream_chat.py`

**Implementation tasks**

- [DONE] Build `AgentRunRequest` objects from bounded orchestration request, prompt context, tool context, session summary, and strategy constraints.
- [DONE] Replace direct legacy `run(context)` usage with `AgentHandle.run(...)` and `AgentHandle.stream(...)` across built-in strategies.
- [DONE] Preserve existing orchestration ownership of memory retrieval, tool execution, fallback routing, and workflow-state-delta construction.
- [DONE] Map `AgentRunResult` and `AgentStreamEvent` into strategy/runtime result shapes without exposing raw provider or gateway payloads.
- [DONE] Keep or remove compatibility shims deliberately; do not let the migration leave two competing production agent paths in place indefinitely.
- [DONE] Remove remaining production reliance on the fake agent's direct memory/tool execution behavior.

**Validation**

- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m pytest tests/unit/orchestration tests/integration/orchestration tests/unit/session/test_session_handle_chat.py tests/unit/session/test_session_stream_chat.py`
- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m ruff check app/agents app/orchestration app/testing/fakes tests/unit/agents tests/unit/orchestration tests/integration/orchestration tests/unit/session/test_session_handle_chat.py tests/unit/session/test_session_stream_chat.py`
- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m mypy app/agents app/orchestration`

**Exit criteria**

- [DONE] All built-in strategies invoke agents only through the structured registry/handle abstraction.
- [DONE] `/chat` and `/chat/stream` continue to work without API or session contract changes.
- [DONE] No production orchestration path depends on the old agent loader and result shape by default.

### [DONE] Phase 8. Health, Capabilities, and Safe Exposure

**Goal**

Expose safe agent readiness and capability metadata through the existing backend startup, health, and capabilities surfaces.

**Files to create or update**

- [DONE] `backend/app/agents/health.py`
- [DONE] `backend/app/orchestration/health.py`
- [DONE] `backend/app/orchestration/capabilities.py`
- [DONE] `backend/app/config/bootstrap.py`
- [DONE] `backend/app/foundation/container.py`
- [DONE] `backend/app/foundation/health.py`
- [DONE] `backend/app/foundation/capabilities.py`
- [DONE] `backend/app/api/schemas.py`
- [DONE] `backend/tests/unit/agents/test_agent_health.py`
- [DONE] `backend/tests/unit/orchestration/test_orchestration_capabilities_summary.py`
- [DONE] `backend/tests/unit/test_health.py`
- [DONE] `backend/tests/unit/test_capabilities.py`

**Implementation tasks**

- [DONE] Add safe agent health summaries that report enabled status, agent type, configured LLM profile, prompt profile, memory/tool requirements, and streaming support without exposing prompts, endpoints, credentials, or paths.
- [DONE] Add safe agent capability descriptors to the existing backend capability surface.
- [DONE] Preserve the current API route contracts while deepening the internal health/capability summaries.
- [DONE] Extend startup logging so redacted agent registration summaries appear alongside existing orchestration startup metadata.
- [DONE] Ensure missing required agents degrade or fail startup in a clear way depending on configuration criticality.

**Validation**

- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m pytest tests/unit/agents/test_agent_health.py tests/unit/orchestration/test_orchestration_capabilities_summary.py tests/unit/test_health.py tests/unit/test_capabilities.py tests/unit/test_app_factory.py`
- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m ruff check app/agents app/orchestration app/foundation app/config/bootstrap.py tests/unit/agents tests/unit/orchestration/test_orchestration_capabilities_summary.py tests/unit/test_health.py tests/unit/test_capabilities.py tests/unit/test_app_factory.py`
- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m mypy app/agents app/orchestration app/foundation`

**Exit criteria**

- [DONE] Health exposes safe agent readiness.
- [DONE] Capabilities expose only frontend-safe agent metadata.
- [DONE] Startup logs a redacted agent summary without leaking prompts, credentials, endpoints, or raw tool schemas.

### [DONE] Phase 9. Fakes, Fixtures, Boundary Tests, and Freeze

**Goal**

Lock in the agent boundary with deterministic fakes, fixture coverage, import-boundary tests, and full backend validation before handing off to the policy phase.

**Files to create or update**

- [DONE] `backend/app/testing/fakes/fake_agent.py`
- [DONE] `backend/app/testing/fakes/fake_policy.py`
- [DONE] `backend/app/testing/fakes/fake_llm.py`
- [DONE] `backend/app/testing/fakes/fake_memory.py`
- [DONE] `backend/app/testing/fakes/fake_tools.py`
- [DONE] `backend/tests/unit/agents/`
- [DONE] `backend/tests/integration/agents/`
- [DONE] `backend/tests/fixtures/config/agents_*.yaml`
- [DONE] `backend/tests/unit/agents/test_agent_dependency_boundaries.py`
- [DONE] `backend/tests/unit/agents/test_agent_trace_redaction.py`
- [DONE] `backend/tests/unit/agents/test_agent_policy_denial.py`
- [DONE] `backend/tests/unit/agents/test_agent_cancellation.py`
- [DONE] `backend/README.md`

**Implementation tasks**

- [DONE] Deepen deterministic fakes so agent tests can cover run, stream, policy denial, limit enforcement, and health behavior without real providers or external stores.
- [DONE] Add import-boundary tests that prevent `backend/app/agents/` from importing:
  - `app/api`
  - `app/session`
  - `sqlite3`
  - `memory_store`
  - ArcadeDB clients
  - `app/tools/mcp`
  - provider SDKs
  - frontend DTOs
- [DONE] Add dedicated fixture coverage for valid built-in agent configs plus invalid capability, memory-write, raw-MCP-tool, unknown-profile, and unbounded self-managed cases.
- [DONE] Run the full backend quality gate from `backend/` and record the frozen agent boundary in `backend/README.md`.
- [DONE] Hand off to `docs/backend-policy-architecture.md` once the agent layer is stable.

**Validation**

- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m pytest`
- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m ruff check .`
- [DONE] Run from `backend/`: `.venv\Scripts\python.exe -m mypy app`

**Exit criteria**

- [DONE] Dedicated unit and integration coverage exists for the backend agent layer.
- [DONE] Import-boundary tests prevent common architectural drift.
- [DONE] The full backend quality gate passes from `backend/`.
- [DONE] The backend is ready for the next document: `backend-policy-architecture.md`.

---

## 6. Implementation Notes

- The architecture's illustrative agents-local config module should not become a second YAML parser. In this repository, YAML-backed settings remain under `backend/app/config/`.
- The current orchestration-owned prompt, tool-intent, memory-intent, and workflow-state-delta helpers should be reused where they already represent the correct ownership boundary.
- The current placeholder `support_agent` config is useful for local startup but should not be treated as the long-term production example.
- If a compatibility shim is introduced for legacy `module` / `class_name` agent loading, it should be explicitly temporary or clearly scoped to `type: custom`.
- If reviewer support is wired into bounded planning, it should remain opt-in and bounded by explicit config limits.

---

## 7. Acceptance Criteria

This implementation plan is satisfied when:

- Backend agent runtime code lives under `backend/app/agents/` and related backend-owned integration packages only.
- Agent settings are configuration-driven and validated at startup through `backend/app/config/`.
- `AgentRegistry` and `AgentFactory` are owned by the backend agent layer rather than orchestration.
- Built-in backend agents exist for `general_assistant`, `document_qa`, `tool_using`, `project_agent`, `memory_curator`, and `reviewer`.
- Strategies invoke agents through a structured registry/handle abstraction rather than direct module/class wiring.
- Agents call LLMs only through `LLMGateway`, memory only through `MemoryGateway` when explicitly allowed, and tools only through `ToolGateway` when explicitly allowed.
- Default V1 tool and memory behavior remains strategy-managed rather than direct agent execution.
- Agents do not import API routes, session services, SQLite, `memory_store`, ArcadeDB clients, MCP clients, provider SDKs, or frontend DTOs.
- Agent outputs and stream events remain safe for runtime, session, and API/SSE mapping.
- Health and capabilities expose only safe backend-facing agent metadata.
- Full backend validation passes from `backend/`.
- The resulting backend agent layer is ready for `docs/backend-policy-architecture.md`.
