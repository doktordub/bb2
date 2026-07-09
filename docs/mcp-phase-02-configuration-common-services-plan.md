# MCP Phase 2 Implementation Plan: Configuration and Common Services [DONE]

**Document:** `mcp-phase-02-configuration-common-services-plan.md`  
**Phase:** 2 of 8 [DONE]  
**Architecture phase:** Configuration and Common Services  
**Version:** 1.0  

**Source alignment:** `mcp-architecture.md`, `pluggable_agentic_ai_overall_architecture.md`, `backend-application-architecture.md`, `backend-tooling-mcp-client-architecture.md`, `backend-tooling-mcp-client-plan.md`, `backend-policy-architecture.md`, and `backend-observability-plan.md`  
**Repository rule:** all MCP server runtime code lives under `mcp/`  
**Runtime stack:** Python 3.12+, FastMCP, Pydantic, PyYAML, HTTPX, pytest, ruff, mypy

---


## 1. Purpose

This plan deepens the MCP walking skeleton into a configuration-driven runtime. It adds typed settings, environment interpolation, shared redaction, structured logging, secret resolution, a shared HTTP client factory, and a rate limiter stub. These common services become the platform layer that future tool plugins use through `ToolRuntimeContext`.

Core rule for this phase:

> Tool plugins must not build their own configuration loader, secret reader, logger, HTTP client, or rate limiter. The MCP server core provides those services consistently.

## 2. Scope

In scope:

- Load and validate `mcp/config/app.yaml`.
- Resolve `${env:VAR:default}` placeholders.
- Add typed settings models.
- Add redactor and structured logger.
- Add secret resolver abstraction.
- Add shared HTTP client factory.
- Add basic rate limiter stub.
- Add common service container for later plugin context.
- Update health output to include safe config and service readiness summaries.

Out of scope:

- Real tool plugin loading.
- JWT/OAuth implementation internals.
- Real metrics backend.
- Real web search.
- Backend smoke test.

## 3. Target Repository Shape

Create or update:

```text
mcp/app/
  bootstrap.py
  config.py
  schemas.py
  health.py
  context.py
  security/
    __init__.py
    redaction.py
    secrets.py
  observability/
    __init__.py
    logging.py
  services/
    __init__.py
    http_client.py
    rate_limit.py
    clock.py
mcp/config/
  app.yaml
mcp/tests/unit/
  test_config.py
  test_env_interpolation.py
  test_redaction.py
  test_secrets.py
  test_http_client_factory.py
  test_rate_limit.py
```

## 4. Implementation Steps

### Step 1: Add Typed Settings Models [DONE]

Create `mcp/app/schemas.py` with Pydantic models for:

- `ServerSettings`
- `RuntimeSettings`
- `InboundAuthSettings` placeholder
- `OutboundAuthSettings` placeholder
- `TLSSettings` placeholder
- `SecretsSettings`
- `PolicySettings`
- `ObservabilitySettings`
- `DefaultsSettings`
- `RateLimitSettings`
- `ToolEnablementSettings`
- `AppSettings`

Keep V1 fields aligned to the architecture:

```yaml
server:
  name: main_mcp
  version: 1.0.0
  environment: ${env:MCP_ENV:local}
  host: ${env:MCP_HOST:0.0.0.0}
  port: ${env:MCP_PORT:9001}
  path: /mcp
  transport: http

runtime:
  tools_dir: mcp/tools
  discovery_on_startup: true
  fail_on_required_tool_error: true
  fail_on_optional_tool_error: false

security:
  inbound_auth:
    enabled: false
    mode: none
  outbound_auth:
    default_mode: none
  tls:
    mode: terminate_upstream
    behind_proxy: true
  secrets:
    provider: env
    allow_tool_env_prefixes: [MCP_TOOL_, WEBSEARCH_]

observability:
  log_level: INFO
  json_logs: true
  redact_secrets: true
  max_log_payload_chars: 2000

defaults:
  timeout_seconds: 30
  max_result_bytes: 262144
  max_argument_bytes: 65536
  max_results: 10
  rate_limit:
    enabled: true
    per_tool_per_minute: 60
```

### Step 2: Implement Config Loader [DONE]

Create `mcp/app/config.py` with:

- `load_yaml(path: Path) -> dict`
- `resolve_env_placeholders(value: object) -> object`
- `load_settings(path: Path) -> AppSettings`
- `redacted_settings_summary(settings: AppSettings) -> dict`

Placeholder behavior:

```text
${env:VAR}          -> required; fail if missing
${env:VAR:default}  -> use default if missing
```

Fail fast for malformed placeholders, invalid YAML, missing required settings, invalid transport, invalid TLS mode, or invalid auth mode.

### Step 3: Add Runtime Redactor [DONE]

Create `mcp/app/security/redaction.py`. It should:

- Recursively traverse dictionaries/lists.
- Redact secret-like keys.
- Truncate long strings.
- Safely serialize unsupported values.
- Never raise from error/health/logging paths.

Default secret-like keys:

```text
api_key, authorization, bearer, client_secret, cookie, credential, jwt, password, refresh_token, secret, token
```

### Step 4: Add Structured Logging [DONE]

Create `mcp/app/observability/logging.py` with:

- Bootstrap logging before config is loaded.
- Runtime logging after config validation.
- Optional JSON logs.
- Redaction before payload logging.

Do not include raw config, secrets, bearer tokens, JWTs, OAuth credentials, tool arguments, or tool results by default.

### Step 5: Add Secret Resolver [DONE]

Create `mcp/app/security/secrets.py` with a `SecretResolver` interface and an environment-backed implementation.

Rules:

- Plugins ask for secrets by logical name or configured env var name.
- Plugins do not call `os.environ` directly.
- Missing required secrets fail clearly.
- Resolved secret values are never returned by health/capability/log summaries.

### Step 6: Add Shared HTTP Client Factory [DONE]

Create `mcp/app/services/http_client.py` with:

- Shared default timeout.
- Optional default headers.
- TLS verification configuration placeholder.
- A context-managed `httpx.AsyncClient` factory.

Plugins should receive this factory through context instead of creating global clients.

### Step 7: Add Rate Limiter Stub [DONE]

Create `mcp/app/services/rate_limit.py` with:

- `RateLimiter.check(key: str) -> None`
- A no-op implementation for disabled mode.
- A simple in-memory per-key limiter for local mode if practical.

This phase can keep rate limiting simple. Phase 7 can add metrics around rate-limit events.

### Step 8: Update Bootstrap [DONE]

Update `mcp/app/bootstrap.py` to create a container with:

- settings
- redactor
- logger
- secret resolver
- HTTP client factory
- rate limiter
- clock

Pass the container into server construction.

## 5. Boundary Rules

- Plugins must eventually use the common services, not raw environment variables or ad hoc clients.
- Configuration is loaded and validated once during startup.
- Health and logs use redacted summaries only.
- Do not introduce backend dependencies.
- Do not start external network calls during config validation.

## 6. Tests

Add tests for:

| Test File | Purpose |
|---|---|
| `test_config.py` | Valid config loads and invalid config fails fast. |
| `test_env_interpolation.py` | Required and default env placeholders work. |
| `test_redaction.py` | Secrets and long strings are redacted. |
| `test_secrets.py` | Secret resolver reads allowed environment-backed secrets safely. |
| `test_http_client_factory.py` | HTTP client factory applies timeout settings. |
| `test_rate_limit.py` | No-op and basic limiter behavior are deterministic. |

Recommended checks:

```bash
cd mcp
python -m pytest tests/unit/test_config.py tests/unit/test_env_interpolation.py tests/unit/test_redaction.py tests/unit/test_secrets.py tests/unit/test_http_client_factory.py tests/unit/test_rate_limit.py
python -m ruff check app tests
python -m mypy app
```

## 7. Acceptance Criteria

This phase is complete when:

- `mcp/config/app.yaml` is validated through typed settings.
- Environment interpolation works.
- Invalid config fails before server startup completes.
- Logs and health summaries are secret-safe.
- A redactor, secret resolver, HTTP client factory, rate limiter, logger, and clock are wired in bootstrap.
- Startup remains import-safe and external-network-free.

## 8. Handoff to Phase 3

Phase 3 should define the plugin contract, manifest schema, tool config schema, and `ToolRuntimeContext` that exposes these common services to tools.
