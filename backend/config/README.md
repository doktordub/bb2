# Backend Configuration Reference

This directory holds the backend runtime configuration. The main file is `backend/config/app.yaml`.

The backend loads this YAML through the validated loader in `app/config/loader.py`, then applies strict schema and cross-reference validation from `app/config/schemas.py` and `app/config/validation.py`.

## How the file is interpreted

- Environment interpolation uses the form `${env:NAME:default}`.
  - If the environment variable exists and is non-empty, its value is used.
  - Otherwise the fallback after the second `:` is used.
  - Values are still parsed into their target types after interpolation, so strings like `"8000"` or `"true"` become an integer or boolean if the schema expects that.
- Relative paths usually resolve from `backend/`, not from the shell working directory.
- Persistence SQLite filenames resolve relative to `persistence.base_dir`.
- `memory.store.config_path` resolves from `backend/`, while `memory.store.database.path` resolves relative to `persistence.base_dir`.
- The loader rejects committed literal secrets. Real secrets should come from environment variables.

## Important compatibility notes

- `features.memory_enabled` and `features.tools_enabled` are compatibility flags. When canonical `memory.enabled` or `tooling.enabled` are present, the loader normalizes the feature flags to match those canonical sections.
  - In this file, raw `features.memory_enabled` is `true`, but effective runtime memory enablement is `false` because `memory.enabled` is `false`.
  - In this file, raw `features.tools_enabled` is `true`, but effective runtime tool enablement is `false` because `tooling.enabled` is `false`.
- `mcp.main.endpoint` is a compatibility alias for the canonical internal `mcp.main.url` field.
- Several `policy.profiles.*` top-level booleans are compatibility shortcuts that feed the nested `llm`, `memory`, and `tools` policy blocks when those nested keys are not explicitly set.

## Current runtime shape at a glance

- The default use case is `default_chat`, routed through the `direct_agent` strategy and the `support_agent` plugin.
- The only active LLM profile is `local_reasoning`, backed by `local_provider` at the configured OpenAI-compatible endpoint.
- Workflow state and trace persistence are enabled through SQLite files under `backend/data/` by default.
- Long-term memory is configured but disabled.
- MCP/tooling is configured but disabled.
- Policy runs in fail-closed `enforce` mode and denies unknown or unsafe actions by default.

## `app`

- `app.name`: `pluggable-agentic-ai-backend`. Human-readable service name used in runtime summaries, health output, and diagnostics. Expected value: non-empty string.
- `app.environment`: `local`. High-level environment classification. Allowed values: `local`, `test`, `staging`, `production`. Must match `deployment.profile`.
- `app.active_usecase`: `default_chat`. Default orchestration use case the backend should run. It must exist and be enabled under `orchestration.usecases`.
- `app.data_dir`: `${env:APP_DATA_DIR:./data}`. Legacy top-level data directory fallback. If `APP_DATA_DIR` is unset, this resolves to `backend/data`. It also acts as the fallback source for `persistence.base_dir` if that section is not explicitly set.

## `deployment`

- `deployment.profile`: `${env:APP_ENV:local}`. Deployment profile used by startup validation and deployment path safety checks. Must match `app.environment`. Allowed values: `local`, `test`, `staging`, `production`.
- `deployment.host`: `${env:APP_HOST:127.0.0.1}`. Main API bind address for the FastAPI server. Expected value: non-empty host string.
- `deployment.port`: `${env:APP_PORT:8000}`. Main API port. Allowed range: `1..65535`.
- `deployment.public_base_url`: `${env:APP_PUBLIC_BASE_URL:http://localhost:8000}`. Public URL that clients should use to reach the backend. Expected value: valid `http` or `https` URL.
- `deployment.log_dir`: `${env:APP_LOG_DIR:./logs}`. Directory for backend-generated logs. Relative paths resolve from `backend/`. It must not point into `backend/app`, `backend/config`, or `backend/tests`. In `staging` or `production`, it cannot stay at the bare default `logs` path.
- `deployment.runtime_dir`: `${env:APP_RUNTIME_DIR:./runtime}`. Directory for runtime-owned files such as restart control files. Relative paths resolve from `backend/`. It must not point into `backend/app`, `backend/config`, or `backend/tests`. In `staging` or `production`, it cannot stay at the bare default `runtime` path.
- `deployment.graceful_shutdown_seconds`: `${env:APP_GRACEFUL_SHUTDOWN_SECONDS:20}`. Shutdown grace period before the process is considered hard-stopped. Allowed range: `1..3600` seconds.
- `deployment.metrics.enabled`: `${env:METRICS_ENABLED:true}`. Turns the metrics listener/runtime metrics support on or off. It cannot be `true` if `observability.metrics_enabled` is `false`.
- `deployment.metrics.bind_host`: `${env:METRICS_BIND_HOST:127.0.0.1}`. Bind address for the metrics endpoint if metrics are enabled. Expected value: non-empty host string.
- `deployment.metrics.port`: `${env:METRICS_PORT:9102}`. Metrics endpoint port. Allowed range: `1..65535`.
- `deployment.readiness.enabled`: `true`. Enables readiness-related deployment behavior. The schema also supports a separate readiness bind host and port, but this file only turns the feature on and does not define a dedicated readiness listener.

## `orchestration.defaults`

- `orchestration.enabled`: `true`. Master switch for orchestration features.
- `orchestration.defaults.strategy`: `direct_agent`. Default strategy name used if a use case does not override strategy selection. It must reference a configured strategy.
- `orchestration.defaults.fallback_strategy`: `fallback_answer`. Default strategy to use when the runtime needs an approved fallback path. It must reference a configured strategy.
- `orchestration.defaults.max_steps`: `8`. Global per-turn cap on orchestration steps. Allowed range: `1..100`.
- `orchestration.defaults.max_tool_calls`: `4`. Global per-turn cap on tool invocations. Allowed range: `1..100`.
- `orchestration.defaults.max_memory_searches`: `3`. Global per-turn cap on long-term memory search operations. Allowed range: `1..100`.
- `orchestration.defaults.max_memory_writes`: `1`. Global per-turn cap on memory write operations. Allowed range: `1..100`.
- `orchestration.defaults.max_llm_calls`: `6`. Global per-turn cap on LLM calls. Allowed range: `1..100`.
- `orchestration.defaults.max_tool_loop_iterations`: `3`. Cap on repeated tool-plan-tool loops inside one turn. Allowed range: `1..100`.
- `orchestration.defaults.max_context_bytes`: `64000`. Overall context budget for orchestration inputs. Allowed range: `1..10485760` bytes.
- `orchestration.defaults.max_turn_duration_seconds`: `120`. Maximum allowed orchestration turn duration. Allowed range: `1..3600` seconds.
- `orchestration.defaults.max_stream_duration_seconds`: `300`. Maximum allowed streaming turn duration. Allowed range: `1..3600` seconds and must be greater than or equal to `max_turn_duration_seconds`.
- `orchestration.defaults.emit_step_events`: `true`. Emits trace/observer events for orchestration step boundaries.
- `orchestration.defaults.emit_tool_events`: `true`. Emits trace/observer events for tool actions.
- `orchestration.defaults.emit_memory_events`: `true`. Emits trace/observer events for memory actions.
- `orchestration.defaults.stream_strategy_events`: `true`. Allows strategy progress events to be surfaced while streaming.
- `orchestration.defaults.expose_strategy_metadata`: `true`. Allows safe strategy metadata to appear in results and capabilities.
- `orchestration.defaults.expose_chain_of_thought`: `false`. Keeps private chain-of-thought hidden. This should remain off unless the design explicitly changes.
- `orchestration.defaults.save_runtime_snapshots`: `false`. Disables runtime snapshot persistence for each turn.

## `orchestration.strategies.direct_agent`

- `orchestration.strategies.direct_agent.enabled`: `true`. Enables the direct agent strategy.
- `orchestration.strategies.direct_agent.type`: `direct_agent`. Strategy implementation type. Allowed strategy types include `echo`, `direct_agent`, `retrieval_augmented`, `tool_assisted`, `router`, `bounded_planner`, `memory_update`, and `fallback_answer`.
- `orchestration.strategies.direct_agent.description`: `Run the configured default agent directly.` Human-readable description for diagnostics and capabilities.
- `orchestration.strategies.direct_agent.default_agent`: `support_agent`. Default agent to execute through this strategy. It must reference an enabled configured agent.
- `orchestration.strategies.direct_agent.allowed_usecases`: `[default_chat]`. Restricts this strategy to the listed use cases.
- `orchestration.strategies.direct_agent.llm_profile`: `local_reasoning`. Default LLM profile this strategy uses when it needs model access. It must reference a configured profile.
- `orchestration.strategies.direct_agent.memory_enabled`: `false`. Keeps long-term memory retrieval turned off for this strategy.
- `orchestration.strategies.direct_agent.memory_write_enabled`: `false`. Prevents this strategy from writing long-term memory.
- `orchestration.strategies.direct_agent.tools_enabled`: `false`. Prevents this strategy from issuing tool calls.
- `orchestration.strategies.direct_agent.stream_llm_deltas`: `true`. Allows model token deltas to flow through streaming responses.
- `orchestration.strategies.direct_agent.expose_strategy_metadata`: `true`. Allows safe strategy metadata in outputs.

## `orchestration.strategies.bounded_planner`

- `orchestration.strategies.bounded_planner.enabled`: `false`. Disables the bounded planner strategy by default.
- `orchestration.strategies.bounded_planner.type`: `bounded_planner`. Strategy type used for small structured plan-and-execute flows.
- `orchestration.strategies.bounded_planner.default_agent`: `support_agent`. Default execution agent if the planner delegates agent steps.
- `orchestration.strategies.bounded_planner.planner_llm_profile`: `local_reasoning`. LLM profile used to generate a bounded plan.
- `orchestration.strategies.bounded_planner.executor_llm_profile`: `local_reasoning`. LLM profile used when executing plan steps that need model help.
- `orchestration.strategies.bounded_planner.memory_enabled`: `true`. Allows memory search during planning/execution.
- `orchestration.strategies.bounded_planner.memory_write_enabled`: `false`. Disables durable memory writes for this planner.
- `orchestration.strategies.bounded_planner.tools_enabled`: `true`. Allows tool usage inside bounded plans.
- `orchestration.strategies.bounded_planner.max_plan_steps`: `4`. Max number of planner-produced plan steps. Allowed range: `1..100`.
- `orchestration.strategies.bounded_planner.max_execute_steps`: `4`. Max number of execution steps the runtime will carry out. Allowed range: `1..100`.
- `orchestration.strategies.bounded_planner.max_memory_writes`: `1`. Planner-local cap on memory writes.
- `orchestration.strategies.bounded_planner.max_tool_loop_iterations`: `2`. Planner-local limit on repeated tool loops.
- `orchestration.strategies.bounded_planner.max_context_bytes`: `32000`. Planner-local context budget.
- `orchestration.strategies.bounded_planner.stream_strategy_events`: `true`. Allows planner step events to stream outward.
- `orchestration.strategies.bounded_planner.expose_strategy_metadata`: `true`. Allows safe planner metadata in outputs.

## `orchestration.strategies.memory_update`

- `orchestration.strategies.memory_update.enabled`: `false`. Disables the memory update strategy by default.
- `orchestration.strategies.memory_update.type`: `memory_update`. Strategy type for extracting and writing durable memory.
- `orchestration.strategies.memory_update.default_agent`: `support_agent`. Agent used when the strategy needs agent logic during memory extraction.
- `orchestration.strategies.memory_update.llm_profile`: `local_reasoning`. LLM profile used for memory extraction/ranking decisions.
- `orchestration.strategies.memory_update.memory_enabled`: `true`. Allows memory reads.
- `orchestration.strategies.memory_update.memory_write_enabled`: `true`. Allows memory writes, subject to policy and lifecycle rules.
- `orchestration.strategies.memory_update.max_memory_writes`: `1`. Per-turn cap on durable memory writes.
- `orchestration.strategies.memory_update.candidate_limit`: `3`. Max number of extracted candidate memories to consider.
- `orchestration.strategies.memory_update.require_policy_approval`: `true`. Requires policy approval before a write proceeds.
- `orchestration.strategies.memory_update.expose_strategy_metadata`: `true`. Allows safe strategy metadata in outputs.

## `orchestration.strategies.fallback_answer`

- `orchestration.strategies.fallback_answer.enabled`: `true`. Enables the safe fallback strategy.
- `orchestration.strategies.fallback_answer.type`: `fallback_answer`. Strategy type that produces a best-effort fallback response.
- `orchestration.strategies.fallback_answer.llm_profile`: `local_reasoning`. LLM profile used if the fallback needs model generation.
- `orchestration.strategies.fallback_answer.message`: `I could not complete the full workflow, but here is the safest answer I can provide.` Safe default fallback text when a full workflow cannot complete.
- `orchestration.strategies.fallback_answer.allowed_usecases`: `[default_chat]`. Restricts fallback strategy use to the listed use cases.
- `orchestration.strategies.fallback_answer.expose_strategy_metadata`: `true`. Allows safe fallback metadata in outputs.

## `orchestration.usecases.default_chat`

- `orchestration.usecases.default_chat.enabled`: `true`. Enables the default chat use case.
- `orchestration.usecases.default_chat.description`: `Default local backend use case.` Human-readable description for this use case.
- `orchestration.usecases.default_chat.strategy`: `direct_agent`. Strategy selected for this use case. It must reference an enabled strategy.
- `orchestration.usecases.default_chat.agent`: `support_agent`. Primary agent for this use case.
- `orchestration.usecases.default_chat.llm_profile`: `local_reasoning`. Use-case-level LLM profile routing preference.
- `orchestration.usecases.default_chat.allowed_agents`: `[support_agent]`. Agent allowlist for this use case.
- `orchestration.usecases.default_chat.allowed_strategies`: `[direct_agent, fallback_answer]`. Strategy allowlist for this use case.
- `orchestration.usecases.default_chat.policy_profile`: `default`. Policy profile applied to this use case.

## `api`

- `api.enabled`: `true`. Enables API route registration.
- `api.base_path`: `""`. Empty string means routes mount at the root. If a non-empty value is used later, it must start with `/`, must not end with `/`, and must not contain empty path segments.
- `api.docs_enabled`: `true`. Enables API docs routes. It requires `api.openapi_enabled` to also be `true`.
- `api.openapi_enabled`: `true`. Enables OpenAPI schema generation.
- `api.cors.enabled`: `false`. Disables CORS handling by default.
- `api.cors.allow_origins`: `[]`. List of allowed origins if CORS is enabled. When CORS is turned on, this list cannot be empty and each origin must be a valid `http` or `https` origin.
- `api.cors.allow_credentials`: `true`. Allows credentials on CORS requests when CORS is enabled.
- `api.cors.allow_methods`: `[GET, POST, OPTIONS]`. Allowed HTTP methods for CORS preflight and browser requests. Methods are normalized to uppercase.
- `api.cors.allow_headers`: `[Authorization, Content-Type, X-Request-Id, X-Trace-Id]`. Allowed request headers for CORS. Header names must be valid HTTP header tokens.
- `api.request_limits.max_body_bytes`: `1048576`. Maximum accepted request body size in bytes.
- `api.request_limits.max_message_chars`: `20000`. Maximum accepted message length after request parsing.
- `api.request_limits.max_metadata_bytes`: `65536`. Maximum metadata payload size in bytes. It must be less than or equal to `max_body_bytes`.
- `api.request_limits.request_timeout_seconds`: `120`. Timeout budget for non-streaming requests.
- `api.request_limits.stream_timeout_seconds`: `300`. Timeout budget for streaming requests. It must be greater than or equal to `request_timeout_seconds`.
- `api.sessions.accept_client_session_id`: `true`. Allows clients to send a session id header. It must match `session.identifiers.accept_client_session_id`.
- `api.sessions.create_session_when_missing`: `true`. Allows the API layer to create a session when the client omits one. It must match `session.identifiers.generate_when_missing`.
- `api.sessions.session_id_header`: `X-Session-Id`. Header name used for session ids. It must not equal the trace response header.
- `api.tracing.accept_client_trace_id`: `true`. Allows incoming trace ids from the client when they pass validation.
- `api.tracing.response_trace_header`: `X-Trace-Id`. Header name returned on responses so callers can correlate logs and traces.
- `api.tracing.record_request_received`: `true`. Emits a trace event when a request arrives.
- `api.tracing.record_response_returned`: `true`. Emits a trace event when a response is sent.
- `api.tracing.record_validation_errors`: `true`. Emits trace events for validation failures.
- `api.debug_routes.enabled`: `true`. Enables debug/admin trace routes. It requires `features.trace_enabled` to stay `true`.
- `api.debug_routes.require_localhost`: `true`. Restricts debug routes to localhost callers.
- `api.debug_routes.restart_enabled`: `true`. Enables the debug restart route. It requires `api.debug_routes.enabled` to be `true`.
- `api.debug_routes.max_trace_events`: `500`. Max number of trace events returned from a single debug trace read.
- `api.debug_routes.max_search_results`: `50`. Max number of results returned from a debug trace search.
- `api.sse.heartbeat_seconds`: `15`. Interval between SSE heartbeat events.
- `api.sse.send_trace_id_event`: `true`. Emits a trace-id SSE event during streaming.
- `api.sse.send_metadata_events`: `true`. Emits non-content metadata SSE events during streaming.

## `session`

- `session.enabled`: `true`. Enables session service behavior.
- `session.identifiers.prefix`: `session`. Prefix used when the backend generates new session ids. It must contain only session-safe characters.
- `session.identifiers.accept_client_session_id`: `true`. Allows caller-supplied session ids when they match the configured pattern.
- `session.identifiers.generate_when_missing`: `true`. Generates a new session id when the client omits one.
- `session.identifiers.max_length`: `128`. Maximum session id length. Allowed range: `3..128`.
- `session.identifiers.allowed_pattern`: `^[A-Za-z0-9_.:-]{3,128}$`. Regex used to validate session ids.
- `session.defaults.default_user_id`: `local_user`. Fallback user id when no user identity is supplied. Expected value: non-empty string.
- `session.defaults.default_usecase`: `default_chat`. Default use case for session operations. It must reference an enabled configured use case.
- `session.defaults.default_history_limit`: `50`. Default number of history items returned when callers do not request a custom limit.
- `session.defaults.max_history_limit`: `200`. Hard cap on returned history items. `default_history_limit` must be less than or equal to this value.
- `session.defaults.timezone_metadata_key`: `timezone`. Metadata field used to store timezone information.
- `session.lifecycle.create_on_first_chat`: `true`. Creates persistent session state when the first chat request arrives.
- `session.lifecycle.resume_existing_sessions`: `true`. Attempts to resume previously known sessions.
- `session.lifecycle.reject_unknown_client_session_id`: `false`. If set to `true`, unknown caller-supplied session ids would be rejected instead of created. It can only be `true` when client-supplied session ids are accepted.
- `session.lifecycle.update_last_seen_on_load`: `true`. Updates session activity metadata when a session is loaded.
- `session.lifecycle.save_after_failed_orchestration`: `true`. Persists session state even after orchestration failures.
- `session.lifecycle.save_after_cancelled_stream`: `true`. Persists state after stream cancellation.
- `session.concurrency.mode`: `optimistic_version`. Session concurrency mode. The current schema only allows `optimistic_version`.
- `session.concurrency.conflict_policy`: `reject`. Session write conflict policy. The current schema only allows `reject`.
- `session.concurrency.max_retries`: `1`. Retry count for optimistic conflicts. Allowed range: `0..10`.
- `session.state.save_on_chat_completion`: `true`. Persists state after non-streaming chat completion.
- `session.state.save_on_stream_completion`: `true`. Persists state after streaming completion.
- `session.state.save_on_stream_cancellation`: `true`. Persists state when a stream is cancelled.
- `session.state.save_on_stream_failure`: `true`. Persists state when streaming fails.
- `session.state.save_each_stream_delta`: `false`. Keeps persistence at end-of-stream only instead of storing every token delta. If this is ever set to `true`, `save_on_stream_completion` must also stay `true`.
- `session.history.enabled`: `true`. Enables history retrieval/projection.
- `session.history.include_tool_summaries`: `true`. Keeps safe tool summaries in stored/rendered session history.
- `session.history.include_system_messages`: `true`. Includes system messages in history views.
- `session.history.include_metadata`: `true`. Includes message metadata in history output.
- `session.history.max_message_chars`: `4000`. Max text stored or returned per message in history. Allowed range: `1..20000`.
- `session.history.redaction_enabled`: `true`. Applies redaction to history output.
- `session.management.list_enabled`: `true`. Enables session listing operations.
- `session.management.delete_enabled`: `true`. Enables session deletion operations.
- `session.management.default_list_limit`: `50`. Default number of sessions returned from a list call.
- `session.management.max_list_limit`: `200`. Hard cap on list page size. Allowed range: `1..500`.
- `session.tracing.record_session_created`: `true`. Emits a trace event when a session is created.
- `session.tracing.record_session_resumed`: `true`. Emits a trace event when a session is resumed.
- `session.tracing.record_session_reset`: `true`. Emits a trace event when a session is reset.
- `session.tracing.record_state_loaded`: `true`. Emits a trace event when workflow state is loaded.
- `session.tracing.record_state_saved`: `true`. Emits a trace event when workflow state is saved.
- `session.tracing.record_history_returned`: `true`. Emits a trace event when session history is returned.
- `session.tracing.record_stream_lifecycle`: `true`. Emits trace events for stream start, progress, completion, and cancellation.

## `features`

- `features.streaming_enabled`: `true`. High-level feature flag for streaming behavior.
- `features.memory_enabled`: raw YAML value `true`. Compatibility flag for long-term memory availability. Effective runtime value is `false` in this file because canonical `memory.enabled` is `false`.
- `features.tools_enabled`: raw YAML value `true`. Compatibility flag for tool availability. Effective runtime value is `false` in this file because canonical `tooling.enabled` is `false`.
- `features.trace_enabled`: `true`. High-level feature flag for trace behavior. `api.debug_routes.enabled` depends on this staying `true`.

## `tooling`

- `tooling.enabled`: `false`. Master switch for tool runtime integration. Even though MCP settings are defined below, tool execution stays off until this is turned on.
- `tooling.defaults.timeout_seconds`: `60`. Default tool call timeout. Allowed range: `1..600` seconds.
- `tooling.defaults.stream_timeout_seconds`: `300`. Default streaming tool timeout. Allowed range: `1..600` seconds and must be greater than or equal to `timeout_seconds`.
- `tooling.defaults.max_retries`: `1`. Retry count for retryable tool failures. Allowed range: `0..10`.
- `tooling.defaults.max_argument_bytes`: `65536`. Max serialized tool argument payload size.
- `tooling.defaults.max_result_bytes`: `262144`. Max serialized tool result payload size.
- `tooling.defaults.trace_arguments`: `false`. Prevents raw tool arguments from being written into traces by default.
- `tooling.defaults.trace_results`: `false`. Prevents raw tool results from being written into traces by default.
- `tooling.defaults.discovery_on_startup`: `true`. Allows MCP tool discovery during startup when tooling is enabled.
- `tooling.defaults.discovery_refresh_seconds`: `300`. Refresh interval for discovered tool metadata.
- `tooling.registry.allow_discovered_tools`: `true`. Lets the runtime accept tools discovered from MCP.
- `tooling.registry.require_configured_allowlist`: `true`. Requires policy/config allowlisting before discovered tools become callable.
- `tooling.registry.tools`: `{}`. No named logical tools are configured yet. This means discovered MCP tools still need explicit policy/allowlist decisions before use.

## `agents.defaults`

- `agents.defaults.enabled`: `true`. Global default enablement for agent plugins.
- `agents.defaults.stream_llm_deltas`: `true`. Agents stream token deltas by default when their strategy allows it.
- `agents.defaults.expose_agent_metadata`: `true`. Allows safe agent metadata in results and capabilities.
- `agents.defaults.strict_prompt_profile_validation`: `false`. Allows looser startup behavior when prompt profile declarations are incomplete.
- `agents.defaults.known_prompt_profiles`: `[general_assistant_v1]`. Allowed/known prompt profile names for validation and diagnostics.
- `agents.defaults.max_prompt_context_bytes`: `32000`. Default prompt-context budget passed to agents.
- `agents.defaults.max_output_chars`: `12000`. Max safe output length per agent response.
- `agents.defaults.max_tool_intents`: `3`. Max number of tool intents an agent may request.
- `agents.defaults.max_memory_candidates`: `5`. Max number of memory candidates an agent may reason over.
- `agents.defaults.max_llm_calls`: `1`. Max number of model calls an agent may make in one run by default.
- `agents.defaults.max_self_managed_tool_calls`: `0`. Self-managed tool usage is disabled by default.
- `agents.defaults.max_self_managed_memory_searches`: `0`. Self-managed memory search is disabled by default.
- `agents.defaults.allow_self_managed_tools`: `false`. Prevents agents from bypassing orchestration-managed tool handling.
- `agents.defaults.allow_self_managed_memory`: `false`. Prevents agents from bypassing orchestration-managed memory handling.
- `agents.defaults.allow_memory_write`: `false`. Prevents agent-driven memory writes by default.

## `agents.plugins.support_agent`

- `agents.plugins.support_agent.enabled`: `true`. Enables the built-in support agent.
- `agents.plugins.support_agent.type`: `general_assistant`. Built-in agent type. Allowed agent types include `general_assistant`, `document_qa`, `tool_using`, `project_agent`, `memory_curator`, `reviewer`, and `custom`.
- `agents.plugins.support_agent.display_name`: `Support Agent`. Human-readable name exposed in safe capability and health summaries.
- `agents.plugins.support_agent.description`: `General purpose assistant for direct answers.` Human-readable purpose summary.
- `agents.plugins.support_agent.llm_profile`: `local_reasoning`. Default model profile used by this agent.
- `agents.plugins.support_agent.prompt_profile`: `general_assistant_v1`. Prompt profile name used by the built-in general assistant plugin.
- `agents.plugins.support_agent.capabilities.answer`: `true`. The agent may produce direct answers.
- `agents.plugins.support_agent.capabilities.review`: `false`. The agent is not configured as a review-only agent.
- `agents.plugins.support_agent.capabilities.stream`: `true`. The agent may stream output.
- `agents.plugins.support_agent.capabilities.memory_read`: `false`. The agent does not directly read long-term memory.
- `agents.plugins.support_agent.capabilities.memory_write`: `false`. The agent does not directly write long-term memory.
- `agents.plugins.support_agent.capabilities.memory_candidate_extract`: `false`. The agent does not extract memory candidates for memory-update workflows.
- `agents.plugins.support_agent.capabilities.tool_intents`: `false`. The agent does not declare tool intents.
- `agents.plugins.support_agent.capabilities.tool_execute`: `false`. The agent does not directly execute tools.
- `agents.plugins.support_agent.capabilities.self_managed_memory`: `false`. The agent does not manage memory on its own.
- `agents.plugins.support_agent.capabilities.self_managed_tools`: `false`. The agent does not manage tools on its own.
- `agents.plugins.support_agent.allowed_tool_intents`: `[]`. No tool intents are allowed for this agent.
- `agents.plugins.support_agent.allowed_memory_scopes`: `[project]`. If memory were enabled for this agent later, the safe scope allowlist would currently only permit the `project` scope.

## `llm.defaults`

- `llm.defaults.profile`: `local_reasoning`. Default model profile name. It must reference an enabled profile.
- `llm.defaults.timeout_seconds`: `120`. Default non-streaming LLM timeout. Allowed range: `1..600` seconds.
- `llm.defaults.stream_timeout_seconds`: `300`. Default streaming LLM timeout. Allowed range: `1..600` seconds and must be greater than or equal to `timeout_seconds`.
- `llm.defaults.max_retries`: `1`. Retry count for retryable LLM failures. Allowed range: `0..10`.
- `llm.defaults.trace_prompts`: `false`. Prevents prompt text capture in traces by default.
- `llm.defaults.trace_completions`: `false`. Prevents completion text capture in traces by default.

## `llm.providers.local_provider`

- `llm.providers.local_provider.type`: `openai_compatible`. Uses the OpenAI-compatible adapter implementation.
- `llm.providers.local_provider.enabled`: `true`. Enables this provider.
- `llm.providers.local_provider.base_url`: `${env:LOCAL_LLM_BASE_URL:http://192.168.1.80:8081/v1}`. Base URL for the local OpenAI-compatible endpoint. Expected value: valid `http` or `https` URL.
- `llm.providers.local_provider.api_key`: `${env:LOCAL_LLM_API_KEY:fake_key}`. API key or placeholder key for the local provider. Real credentials should come from the environment, not from YAML.
- `llm.providers.local_provider.timeout_seconds`: `120`. Provider-specific request timeout.
- `llm.providers.local_provider.stream_timeout_seconds`: `300`. Provider-specific streaming timeout. Must be greater than or equal to `timeout_seconds`.
- `llm.providers.local_provider.headers.Content-Type`: `application/json`. Static request header added to provider calls.

## `llm.profiles.local_reasoning`

- `llm.profiles.local_reasoning.enabled`: `true`. Enables this LLM profile.
- `llm.profiles.local_reasoning.provider`: `local_provider`. Provider backing this profile.
- `llm.profiles.local_reasoning.model`: `qwen3.5-27b-claude-4.6-opus-reasoning-distilled-i1`. Provider-specific model identifier. Expected value: non-empty string.
- `llm.profiles.local_reasoning.temperature`: `0.7`. Sampling temperature. Allowed range: `0..2`.
- `llm.profiles.local_reasoning.max_output_tokens`: `2048`. Max completion token budget for this profile.
- `llm.profiles.local_reasoning.supports_streaming`: `true`. Declares streaming support.
- `llm.profiles.local_reasoning.supports_json_schema`: `false`. Declares that structured JSON-schema output is not supported.
- `llm.profiles.local_reasoning.supports_tool_calling`: `false`. Declares that native model-side tool calling is not supported.
- `llm.profiles.local_reasoning.allowed_for.usecases`: `[default_chat]`. Use-case allowlist for this profile.
- `llm.profiles.local_reasoning.allowed_for.agents`: `[support_agent]`. Agent allowlist for this profile.
- `llm.profiles.local_reasoning.allowed_for.strategies`: `[direct_agent]`. Strategy allowlist for this profile.
- `llm.profiles.local_reasoning.fallback_profiles`: `[]`. No LLM fallback chain is configured for this profile.

## `memory`

- `memory.enabled`: `false`. Canonical master switch for long-term memory. Memory is configured but inactive in the current file.
- `memory.provider`: `memory_store`. Memory backend type. Allowed values: `disabled`, `fake`, `memory_store`, `none`.
- `memory.required`: `false`. If `true`, startup would fail when memory cannot initialize. It cannot be `true` while memory is disabled.
- `memory.defaults.default_scope`: `project`. Default durable memory scope used by searches and writes. Allowed values: `project`, `user`.
- `memory.defaults.top_k`: `10`. Default number of memory results returned from a search. It must be less than or equal to `memory.search.limit_max`.
- `memory.defaults.include_agent_memories`: `true`. Includes agent-generated durable memories when building retrieval context.
- `memory.defaults.include_document_chunks`: `true`. Includes document chunks in retrieval context.
- `memory.defaults.include_graph_context`: `true`. Includes graph/neighborhood context when the adapter supports it.
- `memory.defaults.max_result_chars`: `1200`. Max characters kept from any one retrieved memory. It must be less than or equal to `memory.defaults.max_total_context_chars`.
- `memory.defaults.max_total_context_chars`: `8000`. Total character budget for all memory context combined.
- `memory.defaults.trace_query_capture`: `none`. Trace capture mode for memory queries. Allowed values: `none`, `summaries_only`.
- `memory.defaults.trace_result_content_capture`: `none`. Trace capture mode for memory result content. Allowed values: `none`, `summaries_only`.
- `memory.store.database.path`: `${env:MEMORY_STORE_DB_PATH:memory}`. Memory-store database path. Relative values resolve under `persistence.base_dir`, so the default becomes `backend/data/memory`.
- `memory.store.database.create_if_missing`: `true`. Allows the adapter to create its database on first use.
- `memory.store.database.schema_version`: `1`. Expected schema version for the memory store.
- `memory.store.database.embedded_single_process`: `true`. Declares the database is used in embedded single-process mode.
- `memory.store.embeddings.provider`: `fastembed`. Embedding provider implementation name.
- `memory.store.embeddings.model`: `BAAI/bge-small-en-v1.5`. Embedding model identifier.
- `memory.store.embeddings.dimension`: `384`. Expected embedding vector size. This cannot be null for the `memory_store` provider.
- `memory.store.embeddings.batch_size`: `64`. Batch size used for embedding generation.
- `memory.store.embeddings.normalize`: `true`. Normalizes vectors before storage/search.
- `memory.store.embeddings.dimension_mismatch`: `error`. Policy used when stored vectors do not match the configured dimension. Allowed values: `error`, `quarantine`, `reembed`.
- `memory.store.reranker.enabled`: `true`. Enables a reranker after initial retrieval.
- `memory.store.reranker.provider`: `fastembed`. Reranker provider implementation name.
- `memory.store.reranker.model`: `Xenova/ms-marco-MiniLM-L-6-v2`. Reranker model identifier.
- `memory.store.reranker.top_n`: `60`. Number of candidates kept for reranking.
- `memory.chunking.strategy`: `markdown_section`. Chunking strategy used for document ingestion.
- `memory.chunking.max_tokens`: `350`. Max token budget per chunk.
- `memory.chunking.overlap_tokens`: `50`. Token overlap between adjacent chunks. It must be less than `max_tokens`.
- `memory.chunking.include_heading_path`: `true`. Stores heading hierarchy with chunks.
- `memory.chunking.include_frontmatter_in_embedding`: `true`. Includes frontmatter text in the embedding input.
- `memory.chunking.preserve_code_blocks`: `true`. Keeps code blocks intact when chunking markdown.
- `memory.chunking.removed_chunk_policy`: `mark_removed`. Behavior when previously ingested chunks disappear from source content. Allowed values: `hard_delete`, `mark_removed`.
- `memory.search.limit_max`: `30`. Hard cap on requested search result counts.
- `memory.search.vector_top_n`: `30`. Candidate count taken from vector search before fusion.
- `memory.search.fts_top_n`: `30`. Candidate count taken from full-text search before fusion.
- `memory.search.rrf_k`: `60`. Reciprocal-rank-fusion tuning constant.
- `memory.search.graph_expansion_enabled`: `true`. Enables graph-based context expansion when supported.
- `memory.search.graph_expansion_hops`: `1`. Number of graph hops added during expansion. Current schema allows `0` or `1`.
- `memory.search.final_top_k`: `10`. Final result count after fusion and reranking. It must be less than or equal to `limit_max`.
- `memory.search.include_component_scores`: `true`. Includes per-component scoring details in internal result metadata.
- `memory.search.include_debug`: `false`. Keeps low-level debug payloads out of normal results.
- `memory.scoring.weights.reranker`: `0.45`. Weight assigned to reranker score.
- `memory.scoring.weights.retrieval_fusion`: `0.15`. Weight assigned to retrieval-fusion score.
- `memory.scoring.weights.vector`: `0.10`. Weight assigned to vector similarity.
- `memory.scoring.weights.full_text`: `0.08`. Weight assigned to full-text relevance.
- `memory.scoring.weights.temporal`: `0.07`. Weight assigned to recency.
- `memory.scoring.weights.importance`: `0.06`. Weight assigned to importance metadata.
- `memory.scoring.weights.confidence`: `0.04`. Weight assigned to confidence metadata.
- `memory.scoring.weights.graph`: `0.03`. Weight assigned to graph-derived context.
- `memory.scoring.weights.user_rating`: `0.02`. Weight assigned to explicit user ratings. At least one scoring weight must remain above zero.
- `memory.lifecycle.allow_writes`: `false`. Prevents durable memory writes even if a strategy asks for them.
- `memory.lifecycle.default_ttl_days`: `null`. No default automatic expiration is applied to new memories.
- `memory.lifecycle.contradiction_policy`: `keep_both_mark_conflict`. Policy name used when a new memory conflicts with an older one.
- `memory.lifecycle.supersede_policy`: `mark_previous_superseded`. Policy name used when a new memory supersedes an older one.
- `memory.lifecycle.require_durable_scope_for_writes`: `true`. Prevents writes into transient scopes when only durable scopes are allowed.
- `memory.lifecycle.allow_session_scope_only_writes`: `false`. Keeps session-only durable writes disabled.
- `memory.lifecycle.require_durable_scope_for_delete_export`: `true`. Requires delete/export operations to target durable scopes.
- `memory.privacy.default_sensitivity`: `internal`. Default sensitivity label assigned to memory items. Allowed values: `internal`, `private`, `public`, `sensitive`.
- `memory.privacy.allow_llm_context_default`: `true`. Retrieved memories are allowed into LLM context by default unless item-level policy says otherwise.
- `memory.privacy.allow_retrieval_default`: `true`. Retrieved memories are eligible for retrieval by default unless item-level policy says otherwise.
- `memory.privacy.delete_by_scope_requires_confirm`: `true`. Bulk delete-by-scope operations require explicit confirmation.
- `memory.privacy.enable_export_by_scope`: `false`. Scope-level export is disabled.
- `memory.privacy.enable_delete_by_scope`: `false`. Scope-level delete is disabled.
- `memory.privacy.hard_delete_enabled`: `false`. Permanent deletion is disabled.
- `memory.privacy.tombstone_on_forget`: `true`. Forget/delete operations leave a tombstone marker instead of immediately hard-deleting data.
- `memory.privacy.require_policy_approval_for_delete_export`: `true`. Delete/export operations need policy approval.
- `memory.health.deep_check_enabled`: `false`. Keeps memory health checks shallow instead of running deeper provider validation.

## `mcp.main`

- `mcp.main.name`: `main`. Human-readable server name for the configured MCP endpoint.
- `mcp.main.enabled`: `true`. Declares that the MCP server definition is valid and usable. Because `tooling.enabled` is still `false`, the server is configured but not currently active in the runtime tool path.
- `mcp.main.endpoint`: `${env:MCP_MAIN_URL:http://localhost:9001/mcp}`. MCP server URL. This is accepted as the external YAML key and normalized internally to the server `url` field. Allowed schemes: `http`, `https`, `ws`, `wss`.
- `mcp.main.transport`: `http`. MCP transport type. Allowed values: `http`, `sse`, `websocket`.
- `mcp.main.timeout_seconds`: `60`. Default non-streaming MCP call timeout.
- `mcp.main.stream_timeout_seconds`: `300`. Default streaming MCP call timeout. It must be greater than or equal to `timeout_seconds`.
- `mcp.main.auth.mode`: `${env:MCP_AUTH_MODE:none}`. Authentication mode. Allowed values: `none`, `bearer`, `jwt`, `oauth_client_credentials`.
- `mcp.main.auth.token`: `${env:MCP_BEARER_TOKEN:}`. Bearer token used when auth mode is `bearer`. Empty default means unset.
- `mcp.main.auth.jwt`: `${env:MCP_JWT:}`. JWT used when auth mode is `jwt`. Empty default means unset.
- `mcp.main.auth.oauth.token_url`: `${env:MCP_OAUTH_TOKEN_URL:}`. OAuth token endpoint for client-credentials mode. Empty default means unset.
- `mcp.main.auth.oauth.client_id`: `${env:MCP_OAUTH_CLIENT_ID:}`. OAuth client id. Empty default means unset.
- `mcp.main.auth.oauth.client_secret`: `${env:MCP_OAUTH_CLIENT_SECRET:}`. OAuth client secret. Empty default means unset.
- `mcp.main.auth.oauth.scopes`: `[]`. OAuth scopes requested for client-credentials mode.
- `mcp.main.tool_discovery_enabled`: `true`. Allows tool discovery from the MCP server when tooling is active.

## `persistence`

- `persistence.base_dir`: `${env:APP_DATA_DIR:./data}`. Canonical persistence base directory. Relative values resolve from `backend/`, so the default is `backend/data`.

### `persistence.workflow_state`

- `persistence.workflow_state.provider`: `sqlite`. Workflow-state backend type.
- `persistence.workflow_state.sqlite.path`: `workflow_state.db`. SQLite database filename for workflow state. Relative values resolve under `persistence.base_dir`, so the default becomes `backend/data/workflow_state.db`.
- `persistence.workflow_state.sqlite.create_parent_dirs`: `true`. Creates parent directories for the workflow-state database if needed.
- `persistence.workflow_state.sqlite.initialize_schema`: `true`. Bootstraps or migrates the schema on startup.
- `persistence.workflow_state.sqlite.journal_mode`: `WAL`. SQLite journal mode.
- `persistence.workflow_state.sqlite.synchronous`: `NORMAL`. SQLite synchronous mode. Allowed values: `NORMAL`, `FULL`.
- `persistence.workflow_state.sqlite.busy_timeout_ms`: `5000`. SQLite busy timeout in milliseconds.
- `persistence.workflow_state.sqlite.foreign_keys`: `true`. Enables SQLite foreign key enforcement.
- `persistence.workflow_state.sqlite.required`: `true`. Startup should fail if workflow-state persistence cannot initialize.
- `persistence.workflow_state.sqlite.max_state_bytes`: `1048576`. Max serialized workflow state size.
- `persistence.workflow_state.sqlite.max_history_messages`: `50`. Max number of history messages kept in workflow state.
- `persistence.workflow_state.sqlite.reset_mode`: `replace_with_empty_state`. Session reset behavior. It must be one of the supported reset modes defined by the workflow-state contract.
- `persistence.workflow_state.sqlite.store_user_id`: `false`. Raw user ids are not stored in workflow-state persistence.
- `persistence.workflow_state.sqlite.store_user_id_hash`: `true`. Hashed user ids are stored for safe correlation.

### `persistence.trace`

- `persistence.trace.provider`: `sqlite`. Trace backend type.
- `persistence.trace.sqlite.path`: `trace.db`. SQLite database filename for trace data. Relative values resolve under `persistence.base_dir`, so the default becomes `backend/data/trace.db`.
- `persistence.trace.sqlite.create_parent_dirs`: `true`. Creates parent directories for the trace database if needed.
- `persistence.trace.sqlite.initialize_schema`: `true`. Bootstraps or migrates the trace schema on startup.
- `persistence.trace.sqlite.journal_mode`: `WAL`. SQLite journal mode for trace writes.
- `persistence.trace.sqlite.synchronous`: `NORMAL`. SQLite synchronous mode. Allowed values: `NORMAL`, `FULL`.
- `persistence.trace.sqlite.busy_timeout_ms`: `5000`. SQLite busy timeout in milliseconds.
- `persistence.trace.sqlite.foreign_keys`: `true`. Enables SQLite foreign key enforcement.
- `persistence.trace.sqlite.required`: `true`. Startup should fail if trace persistence cannot initialize.
- `persistence.trace.sqlite.max_event_payload_bytes`: `32768`. Max serialized payload size stored for one trace event.
- `persistence.trace.sqlite.max_error_detail_bytes`: `4096`. Max serialized error-detail payload size.
- `persistence.trace.sqlite.max_events_per_trace_read`: `1000`. Hard cap on how many events a single trace read may return.
- `persistence.trace.sqlite.max_search_results`: `200`. Hard cap on trace search result count.
- `persistence.trace.sqlite.store_raw_session_id`: `false`. Raw session ids are not stored in traces.
- `persistence.trace.sqlite.store_session_id_hash`: `true`. Hashed session ids are stored for correlation.
- `persistence.trace.sqlite.store_raw_user_id`: `false`. Raw user ids are not stored in traces.
- `persistence.trace.sqlite.store_user_id_hash`: `true`. Hashed user ids are stored for correlation.
- `persistence.trace.sqlite.capture_request_body`: `false`. Raw request bodies are not stored.
- `persistence.trace.sqlite.capture_response_body`: `false`. Raw response bodies are not stored.
- `persistence.trace.sqlite.capture_llm_prompts`: `false`. Raw prompts are not stored.
- `persistence.trace.sqlite.capture_llm_completions`: `false`. Raw completions are not stored.
- `persistence.trace.sqlite.capture_tool_payloads`: `summaries_only`. Tool payload capture mode. Allowed values: `none`, `summaries_only`.
- `persistence.trace.sqlite.capture_memory_queries`: `summaries_only`. Memory query capture mode. Allowed values: `none`, `summaries_only`.
- `persistence.trace.sqlite.retention.enabled`: `false`. Automatic retention cleanup is disabled.
- `persistence.trace.sqlite.retention.keep_days`: `30`. Retention target age in days if cleanup is later enabled.
- `persistence.trace.sqlite.retention.cleanup_batch_size`: `1000`. Number of rows cleaned per retention pass if retention is enabled.

## `policy`

- `policy.enabled`: `true`. Enables policy evaluation.
- `policy.mode`: `enforce`. Policy engine mode. Allowed values: `enforce`, `report_only`.
- `policy.default_decision`: `deny`. Default decision when no allow rule applies. Allowed values: `allow`, `deny`.
- `policy.fail_closed`: `true`. Turns runtime failures inside policy evaluation into denials rather than implicit allows.
- `policy.default_profile`: `default`. Default named policy profile. It must reference a configured entry in `policy.profiles`.

### `policy.profiles.default`

- `policy.profiles.default.enabled`: `true`. Enables the named default policy profile.
- `policy.profiles.default.deny_unknown_tools`: `true`. Unknown logical tool names are denied.
- `policy.profiles.default.deny_unknown_llm_profiles`: `true`. Unknown LLM profiles are denied. This is a compatibility shortcut for the nested LLM policy block.
- `policy.profiles.default.require_memory_scope`: `true`. Memory actions must declare a scope. This is a compatibility shortcut for the nested memory policy block.
- `policy.profiles.default.allow_memory_writes`: `false`. Memory writes are denied by default. This is a compatibility shortcut for the nested memory policy block.
- `policy.profiles.default.allow_write_tools`: `false`. Write-capable tools are denied by default. This is a compatibility shortcut for the nested tools policy block.
- `policy.profiles.default.allow_destructive_tools`: `false`. Destructive tools are denied by default.
- `policy.profiles.default.allow_external_side_effect_tools`: `false`. Tools with external side effects are denied by default.
- `policy.profiles.default.allow_approval_required_tools`: `false`. Tools marked as approval-required are still denied unless specifically allowed by policy flow.
- `policy.profiles.default.usecases.allowed`: `[default_chat]`. Use cases this profile permits.
- `policy.profiles.default.strategies.allowed`: `[direct_agent, fallback_answer]`. Strategies this profile permits.
- `policy.profiles.default.agents.allowed`: `[support_agent]`. Agents this profile permits.
- `policy.profiles.default.llm.allowed_profiles`: `[local_reasoning]`. LLM profiles this profile permits.
- `policy.profiles.default.llm.allow_prompt_trace`: `false`. Prompt tracing stays disallowed.
- `policy.profiles.default.llm.allow_completion_trace`: `false`. Completion tracing stays disallowed.
- `policy.profiles.default.memory.allowed_read_scopes`: `[project]`. Durable memory reads are only allowed from the `project` scope.
- `policy.profiles.default.memory.allowed_write_scopes`: `[]`. No durable memory scopes are writable.
- `policy.profiles.default.tools.allowed_tools`: `[]`. No logical tools are explicitly allowed.
- `policy.profiles.default.approval.require_approval_for_write_tools`: `true`. Any write-capable tool would need approval before policy could allow it.
- `policy.profiles.default.approval.require_approval_for_destructive_tools`: `true`. Any destructive tool would need approval before policy could allow it.
- `policy.profiles.default.approval.require_approval_for_external_side_effect_tools`: `true`. Any external-side-effect tool would need approval before policy could allow it.
- `policy.profiles.default.approval.require_approval_for_memory_writes`: `false`. Memory writes are already denied outright here, so extra approval is not required.
- `policy.profiles.default.fallback.allow_fallbacks`: `true`. Safe fallback strategies are allowed.
- `policy.profiles.default.fallback.allow_after_denial`: `false`. A normal denial does not automatically trigger fallback.
- `policy.profiles.default.fallback.allow_after_external_side_effects`: `false`. Fallbacks are not allowed after external-side-effect operations.
- `policy.profiles.default.fallback.allowed_strategies`: `[fallback_answer]`. Only the named fallback strategy is permitted.
- `policy.profiles.default.trace.allow_trace`: `true`. Safe trace emission is allowed.
- `policy.profiles.default.trace.expose_raw_payloads`: `false`. Raw payload exposure is disallowed and must remain `false` in V1.
- `policy.profiles.default.trace.expose_prompt_text`: `false`. Raw prompt exposure is disallowed and must remain `false` in V1.
- `policy.profiles.default.trace.expose_completion_text`: `false`. Raw completion exposure is disallowed and must remain `false` in V1.
- `policy.profiles.default.stream.allow_stream_events`: `true`. Safe stream events are allowed.
- `policy.profiles.default.stream.expose_internal_events`: `false`. Internal-only stream events are not exposed.
- `policy.profiles.default.stream.expose_raw_deltas`: `false`. Raw LLM deltas are not exposed by policy and must remain `false` in V1.
- `policy.profiles.default.capabilities.expose_enabled`: `true`. Capabilities output is allowed.
- `policy.profiles.default.capabilities.include_policy_profiles`: `false`. Capabilities output does not enumerate policy profiles.
- `policy.profiles.default.capabilities.include_denied_actions`: `false`. Capabilities output does not expose denied-action detail.
- `policy.profiles.default.health.expose_enabled`: `true`. Health output may include safe policy information.
- `policy.profiles.default.health.include_profile_names`: `true`. Health output may include the profile name.
- `policy.profiles.default.health.include_decision_counts`: `false`. Health output does not expose decision counters.
- `policy.profiles.default.audit.enabled`: `true`. Audit records are enabled.
- `policy.profiles.default.audit.include_reason_codes`: `true`. Audit records include policy reason codes.
- `policy.profiles.default.audit.include_actor_identifiers`: `false`. Raw actor identifiers are not included in audit records.
- `policy.profiles.default.audit.include_resource_names`: `true`. Safe resource names may be included in audits.
- `policy.profiles.default.decision_cache.enabled`: `true`. Enables short-lived caching for repeated policy decisions.
- `policy.profiles.default.decision_cache.ttl_seconds`: `30`. Decision-cache TTL in seconds. Allowed range: `0..3600`.
- `policy.profiles.default.decision_cache.max_entries`: `1024`. Max number of cached policy decisions. Allowed range: `1..100000`.

## `observability`

- `observability.log_level`: `${env:LOG_LEVEL:INFO}`. Logging level used after validated startup. Expected values are standard Python logging levels such as `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL`.
- `observability.structured_logging`: `true`. Enables structured log formatting rather than plain readable logs.
- `observability.trace_enabled`: `true`. Enables trace recording.
- `observability.trace_payloads_enabled`: `false`. Keeps payload-heavy trace capture off at the observability layer.
- `observability.trace_store_required`: `true`. Treats trace persistence as required for healthy startup/runtime behavior.
- `observability.redact_secrets`: `true`. Enables secret redaction across config summaries, logs, traces, and health output. Outside `test` environments this must remain `true`.
- `observability.include_stack_traces_in_logs`: `false`. Keeps stack traces out of normal log records.
- `observability.include_stack_traces_in_traces`: `false`. Keeps stack traces out of trace payloads.
- `observability.max_trace_payload_chars`: `8000`. Maximum character length retained for trace payload fragments.
- `observability.slow_request_ms`: `5000`. Threshold for marking a request as slow.
- `observability.slow_llm_call_ms`: `30000`. Threshold for marking an LLM call as slow.
- `observability.slow_tool_call_ms`: `10000`. Threshold for marking a tool call as slow.
- `observability.metrics_enabled`: `true`. Global metrics feature flag. If this is `false`, `deployment.metrics.enabled` must also be `false`.

## `health`

- `health.expose_config_summary`: `true`. Health output may include a safe redacted configuration summary.
- `health.expose_provider_names`: `true`. Health output may include safe provider names.
- `health.expose_secret_values`: `false`. Health output never exposes secrets. Outside `test` environments this must remain `false`.
- `health.include_component_details`: `true`. Health output may include per-component readiness/detail blocks.

## Practical change guidance

- To change the default model or backend endpoint, start with `llm.providers.local_provider.*` and `llm.profiles.local_reasoning.*`.
- To enable real tool use, change `tooling.enabled` to `true`, define logical tools under `tooling.registry.tools`, and update `policy.profiles.default.tools.allowed_tools` plus the relevant strategy and agent capabilities.
- To enable long-term memory, change `memory.enabled` to `true`, then verify policy, strategy, and agent settings still align with the desired scopes and write rules.
- To harden a deployed environment, set both `app.environment` and `deployment.profile` to `staging` or `production`, then move `deployment.log_dir` and `deployment.runtime_dir` outside the backend source defaults.