# [DONE] MCP Phase 6 Implementation Plan: Security Hardening

**Document:** `mcp-phase-06-security-hardening-plan.md`  
**Phase:** [DONE] 6 of 8  
**Architecture phase:** Security Hardening  
**Version:** 1.0  

**Source alignment:** `mcp-architecture.md`, `pluggable_agentic_ai_overall_architecture.md`, `backend-application-architecture.md`, `backend-tooling-mcp-client-architecture.md`, `backend-tooling-mcp-client-plan.md`, `backend-policy-architecture.md`, and `backend-observability-plan.md`  
**Repository rule:** all MCP server runtime code lives under `mcp/`  
**Runtime stack:** Python 3.12+, FastMCP, Pydantic, PyYAML, HTTPX, pytest, ruff, mypy

---


## 1. Purpose

This plan hardens the MCP server security boundary. The MCP server must be usable in local development without auth, but also support secured backend-to-MCP calls using bearer or JWT authentication. It also adds outbound OAuth provider interfaces for future downstream APIs, TLS-aware configuration, stronger secret handling, and tool argument secret detection.

Core rule for this phase:

> Security is centralized in MCP server common services. Individual plugins should not each implement inbound auth, OAuth token acquisition, TLS behavior, secret loading, or credential redaction.

## 2. Scope

In scope:

- Inbound auth modes: `none`, `bearer`, `jwt`.
- Auth middleware or FastMCP transport hook, depending on framework support.
- JWT verification service.
- Outbound OAuth client credentials provider interface.
- TLS-aware config validation.
- Secret resolver hardening.
- Secret-like argument detection.
- Safe auth health/capability summaries.
- Security-focused tests.

Out of scope:

- Full enterprise identity-provider rollout.
- OAuth introspection unless required immediately.
- mTLS implementation.
- Per-tool process sandboxing.
- OPA/Cedar external policy engine.
- Human approval workflow.

## 3. Target Repository Shape

Create or update:

```text
mcp/app/security/
  __init__.py
  auth.py
  jwt.py
  oauth.py
  tls.py
  secrets.py
  scopes.py
  redaction.py
  arguments.py
mcp/app/
  schemas.py
  bootstrap.py
  server.py
  health.py
  errors.py
mcp/tests/unit/security/
  test_inbound_auth.py
  test_bearer_auth.py
  test_jwt_auth.py
  test_oauth_provider.py
  test_tls_settings.py
  test_secret_resolver.py
  test_secret_argument_detection.py
```

## 4. Implementation Steps

### [DONE] Step 1: Deepen Security Settings

Update settings models to validate:

```yaml
security:
  inbound_auth:
    enabled: false
    mode: none
    bearer_token_env: MCP_BEARER_TOKEN
    jwt:
      issuer: ${env:MCP_JWT_ISSUER:}
      audience: ${env:MCP_JWT_AUDIENCE:}
      jwks_url: ${env:MCP_JWT_JWKS_URL:}
      allowed_algorithms: [RS256]
  outbound_auth:
    default_mode: none
    oauth_clients: {}
  tls:
    mode: terminate_upstream
    cert_file: ${env:MCP_TLS_CERT_FILE:}
    key_file: ${env:MCP_TLS_KEY_FILE:}
    behind_proxy: true
  secrets:
    provider: env
    allow_tool_env_prefixes:
      - MCP_TOOL_
      - WEBSEARCH_
```

Validation rules:

- `mode: none` is allowed only when `enabled: false` or local profile explicitly allows it.
- `bearer` mode requires the configured token env var to resolve.
- `jwt` mode requires issuer, audience, JWKS URL or configured key strategy.
- `terminate_here` requires cert/key file paths.
- OAuth client credentials require token URL, client ID env, and client secret env.

### [DONE] Step 2: Add Inbound Auth Models

Create `mcp/app/security/auth.py` with:

- `InboundRequestContext`
- `AuthVerifier` protocol
- `NoopAuthVerifier`
- `BearerAuthVerifier`
- `JWTAuthVerifier` wrapper
- `AuthError` mapping to safe MCP errors

The verified context should include:

```python
trace_id: str | None
request_id: str | None
caller_service: str | None
authenticated: bool
auth_subject: str | None
auth_scopes: tuple[str, ...]
```

Do not expose raw tokens or raw headers.

### [DONE] Step 3: Add Bearer Auth

Bearer auth should:

- Read the expected token through `SecretResolver`.
- Compare with constant-time comparison.
- Reject missing/malformed Authorization headers.
- Return safe denial errors.

Expected header:

```text
Authorization: Bearer <token>
```

### [DONE] Step 4: Add JWT Auth

Create `mcp/app/security/jwt.py`.

JWT verifier responsibilities:

- Validate signature.
- Validate issuer.
- Validate audience.
- Validate expiration.
- Validate allowed algorithms.
- Extract subject and scopes safely.

Implementation can use a standard Python JWT library if added to `pyproject.toml`. Keep the dependency isolated in `security/jwt.py`.

### [DONE] Step 5: Add Outbound OAuth Provider Interface

Create `mcp/app/security/oauth.py` with:

- `OutboundAuthService` protocol.
- `OAuthClientCredentialsProvider`.
- Token cache by logical client name.
- Safe error handling.

Plugins should call:

```python
token = await context.outbound_auth.get_access_token("example_api")
```

Plugins should not construct OAuth token requests themselves.

### [DONE] Step 6: Add TLS-Aware Config Helpers

Create `mcp/app/security/tls.py` with helpers that validate TLS mode and produce safe status summaries.

Modes:

```text
off
terminate_here
terminate_upstream
```

Production recommendations should be represented in README/deployment notes, but this phase does not need to create reverse proxy configuration.

### [DONE] Step 7: Harden Secret Resolver

Enhance `mcp/app/security/secrets.py`:

- Restrict direct tool secret access to allowed prefixes.
- Support required vs optional secret lookups.
- Add safe missing-secret errors.
- Ensure secret values never appear in repr/log/health outputs.

### [DONE] Step 8: Add Argument Secret Detection

Create `mcp/app/security/arguments.py` with:

- Recursive key scanning.
- Secret-like key detection.
- Optional value pattern detection for bearer tokens/JWT-looking strings.
- Safe `ToolInputValidationError` output.

Integrate this with base validation and `websearch.search`.

### [DONE] Step 9: Wire Auth into Server

Depending on FastMCP transport support, use one of these patterns:

1. Framework-supported middleware/auth hook.
2. HTTP transport wrapper that validates requests before dispatch.
3. Tool-call wrapper/decorator that validates context for each call.

Prefer a transport-level boundary, but keep tool-level validation as a fallback when framework constraints require it.

### [DONE] Step 10: Update Health

Health may expose safe booleans:

```json
"security": {
  "inbound_auth_enabled": true,
  "inbound_auth_mode": "jwt",
  "tls_mode": "terminate_upstream",
  "outbound_oauth_clients_configured": 1
}
```

Never expose tokens, client secrets, JWKS contents, or private keys.

## 5. Boundary Rules

- Backend policy remains the primary tool-authorization layer. MCP auth verifies service identity and protects the integration tier.
- Plugins do not receive raw inbound tokens.
- Plugins do not pass credentials through tool arguments.
- Plugins use outbound auth by logical client name.
- Logs and health never expose credential material.

## 6. Tests

Add tests for:

| Test File | Purpose |
|---|---|
| `test_inbound_auth.py` | Auth mode selection and safe request context. |
| `test_bearer_auth.py` | Valid/missing/invalid bearer token behavior. |
| `test_jwt_auth.py` | JWT validation success/failure cases. |
| `test_oauth_provider.py` | Token fetch, cache, and safe failure behavior. |
| `test_tls_settings.py` | TLS mode validation. |
| `test_secret_resolver.py` | Prefix restrictions and redaction behavior. |
| `test_secret_argument_detection.py` | Secret-like argument keys are rejected. |

Recommended checks:

```bash
cd mcp
python -m pytest tests/unit/security
python -m ruff check app tests
python -m mypy app
```

## 7. Acceptance Criteria

This phase is complete when:

- MCP can run locally with no auth.
- MCP can run in bearer auth mode.
- MCP can run in JWT auth mode.
- Outbound OAuth provider interface exists and is testable.
- TLS mode is validated and summarized safely.
- Tool arguments are checked for secret-like fields.
- Credentials never appear in logs, health, traces, tool output, or test snapshots.

## 8. Handoff to Phase 7

Phase 7 should add deeper operations features: trace correlation, tool-call events, metrics recorder, readiness checks, and startup diagnostics.
