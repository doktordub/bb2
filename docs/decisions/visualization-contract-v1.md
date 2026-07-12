# Visualization Contract V1 Decision Record

**Status:** Accepted for backend visualization phase 0  
**Date:** 2026-07-10  
**Scope:** Backend visualization contract freeze before runtime implementation

## Purpose

Freeze repo-accurate visualization contract decisions before backend runtime code starts extending agent, orchestration, session, API, and SSE surfaces.

## Baseline Validation Commands

The backend phase-0 baseline is defined by these commands from `backend/`:

- `.venv\Scripts\python.exe -m pytest`
- `.venv\Scripts\python.exe -m ruff check .`
- `.venv\Scripts\python.exe -m mypy app`

## Baseline Validation Result (2026-07-10)

- Focused visualization fixture validation passed: `.venv\Scripts\python.exe -m pytest tests/unit/visualization/test_visualization_phase0_fixtures.py` -> `4 passed`.
- Full backend `pytest` baseline is currently red: `13 failed`, `807 passed`, `5 skipped`. The failing coverage is outside the new visualization slice and includes deployment/config validation, session-state assertions, and health/observability assertions.
- Full backend `ruff check .` baseline is currently red with `3` pre-existing unused-import findings in `app/memory/cli_support.py`, `tests/unit/api/test_restart_route.py`, and `tests/unit/memory/test_memory_cli_support.py`.
- Full backend `mypy app` baseline is currently red with pre-existing `subprocess.Popen` environment typing errors in `app/deployment/restart_helper.py` and `app/deployment/process_control.py`.
- No failures were reported by the new visualization fixture test.

## Current Backend Serialization Surfaces

| Surface | Current owner | Current serialized shape | Phase-0 note |
|---|---|---|---|
| Agent result | `backend/app/contracts/results.py` | `answer`, `agent_name`, `confidence`, `llm_profile`, `tool_calls`, `memory_updates`, `handoff_to`, `citations`, `metadata` | Visualization extends this additively. |
| Runtime orchestration result | `backend/app/orchestration/models.py` | `answer`, `session_id`, `trace_id`, `usecase`, `strategy_name`, `agent_name`, `llm_profile`, `steps`, `tool_calls`, `memory_searches`, `memory_updates`, `citations`, `state_delta`, `finish_reason`, `duration_ms`, `metadata` | The runtime already carries richer internal state than the API-facing compatibility contract. |
| API/session orchestration result | `backend/app/contracts/results.py` | `answer`, `session_id`, `trace_id`, `agent_name`, `strategy_name`, `llm_profile`, `tool_calls`, `memory_updates`, `citations`, `metadata` | Add `artifacts` and `context_contributions` here before API wiring changes. |
| Session chat result | `backend/app/session/models.py` | `answer`, `session_id`, `trace_id`, `agent_name`, `strategy_name`, `llm_profile`, `tool_calls`, `memory_updates`, `metadata` | Keep the session boundary thin and extend it additively later. |
| Chat response | `backend/app/api/schemas.py` | Top-level `schema_version`, `trace_id`, `session_id`, `data`, `metadata` | The repo-accurate response extension point is `data.artifacts`, not a second top-level `artifacts` block. |
| SSE envelope | `backend/app/api/sse.py` | `response.started`, `response.delta`, `response.metadata`, `response.completed`, `response.error`, `heartbeat` | Existing `response.*` names are canonical for frontend compatibility. |
| Workflow-state session document | `backend/app/contracts/state.py` | Document version `1` with `conversation`, `workflow`, `last_result`, and `metadata` sections | Visualization summaries must fit this bounded document model. |
| Health response | `backend/app/api/schemas.py` and `backend/app/foundation/health.py` | `status`, `trace_id`, `service`, `version`, `environment`, component payloads, `checks` | Visualization health must be additive. |
| Capabilities response | `backend/app/api/schemas.py` and `backend/app/foundation/capabilities.py` | Top-level `schema_version`, `trace_id`, `data`, `metadata` | Visualization capabilities must be additive under `data`. |

## Composition-Root Extension Points

- Settings and validated config: `backend/app/main.py:create_app` loads process settings, and `backend/app/config/bootstrap.py:build_container` loads the validated config view.
- Policy domains: `backend/app/policy/factory.py:build_policy_runtime` uses `load_default_policy_registry()` as the current domain/rule registration point.
- Gateways: `build_container()` composes persistence, memory, LLM, tooling, trace, and policy runtimes.
- Agents: `backend/app/orchestration/registry.py:AgentRegistry.from_config`.
- Strategies: `backend/app/orchestration/strategy_factory.py:build_strategy_registry`.
- Health contributors: `backend/app/foundation/health.py:build_foundation_health_registry` registers `settings`, `config`, `logging`, `policy`, `observability`, `mcp`, `llm`, `orchestration`, `persistence`, `memory`, `workflow_state`, and `trace`.
- Capability contributors: `backend/app/foundation/capabilities.py:CapabilitiesService.describe_api` composes chat, session, use-case, agent, debug, tool, memory, and LLM payloads.

## Phase-0 Decisions

1. Public V1 delivery mode is `inline` only.
2. Public reference-mode fetch routes remain deferred beyond phase 0.
3. Internal `data_ref` values remain allowed in `ChartContextSummary` for deterministic session-scoped retrieval once the artifact store lands.
4. The canonical backend renderer name exposed to clients is `echarts`.
5. The repo-accurate chat response extension point is `ChatResponse.data.artifacts`; do not add a second top-level `artifacts` field.
6. The canonical public text SSE event names remain `response.started`, `response.delta`, `response.metadata`, `response.completed`, `response.error`, and `heartbeat`.
7. The additive public visualization SSE event name is `response.artifact`, with one validated `ChartArtifact` per event.
8. `context_summary.created` stays internal-only in V1 and is not part of the frontend SSE contract.
9. Workflow-state JSON document version remains `1`, while the SQLite workflow-state schema remains version `2`; phase 0 adds no migration.

## Workflow-State Migration Note

- `backend/app/contracts/state.py:default_workflow_state()` still defines the logical workflow-state JSON document version as `1`.
- `backend/app/persistence/sqlite_workflow_state_schema.py` still defines `WORKFLOW_STATE_SCHEMA_VERSION = 2` for the persisted SQLite schema.
- Phase 0 adds no workflow-state schema or document migration. Visualization context will be added later as bounded state content inside the existing versioned document.

## Reference-Mode Decision

- Public V1 visualization delivery is `inline` only for both `/chat` and `/chat/stream`.
- Phase 0 does not freeze a public `GET /artifacts/{artifact_id}` route shape because public reference mode is deferred.
- Internal `data_ref` values remain reserved for later session-scoped retrieval once the visualization artifact store exists.

## Frozen Fixtures

- `backend/tests/fixtures/visualization/chart_artifact_v1.json`
- `backend/tests/fixtures/visualization/chart_context_summary_v1.json`
- `backend/tests/fixtures/visualization/chat_response_with_chart_v1.json`
- `backend/tests/fixtures/visualization/sse_artifact_events_v1.jsonl`