# Task Execution Chat Rollout Decision

## Decision

Keep multiple parallel use cases. `task_execution_chat` is ready for staged activation, but it should not replace `default_chat` or `support_web_chat` as the unconditional default yet.

## Options Reviewed

- keep opt-in only
- replace `default_chat`
- replace `support_web_chat`
- keep multiple parallel use cases

## Selected Rollout Shape

- keep a disabled baseline fixture for config validation and rollback rehearsals
- enable `task_execution_chat` in staged environments first while callers opt in explicitly through the request use case
- switch `app.active_usecase` and `session.defaults.default_usecase` only when the task-first flow has enough runtime evidence to displace an existing default path

## Rationale

- `default_chat` remains the lowest-friction path for simple direct-answer traffic
- `support_web_chat` still provides the clearest path for current-information questions that depend on web search
- `task_execution_chat` adds valuable assessment, clarification, deterministic synthesis, and bounded multi-step execution behavior, but it also adds latency and more operational surface than the direct paths
- the backend can now enable the task-first flow through configuration only, without changing API routes or frontend transport contracts

## Validation Evidence

- rollout fixtures added under `backend/tests/fixtures/config/` for disabled, staged, and default-enabled states
- real runtime assessment coverage added in `backend/tests/integration/orchestration/test_bounded_planner_runtime.py`
- task-first chart generation and exact follow-up coverage added in `backend/tests/integration/visualization/test_session_chart_pipeline.py`
- focused config fixture coverage added in `backend/tests/unit/config/test_loader_valid_config.py`

## Exit Criteria For Default Replacement

- the full backend quality gate stays green with `task_execution_chat` enabled
- fallback answers remain exceptional for multi-step chart requests
- clarification and resume behavior remain stable under normal session traffic
- operators are comfortable with the activation flags, health expectations, and rollback steps documented in `backend/README.md`

## Current Recommendation

Treat `task_execution_chat` as production-ready for selective rollout. Keep it parallel to `default_chat` and `support_web_chat` until live usage data shows that the task-first flow should become the default for a broader request mix.