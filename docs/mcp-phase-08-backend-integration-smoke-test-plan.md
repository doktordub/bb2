# [DONE] MCP Phase 8 Implementation Plan: Backend Integration Smoke Test

**Document:** `mcp-phase-08-backend-integration-smoke-test-plan.md`  
**Phase:** 8 of 8  
**Architecture phase:** Backend Integration Smoke Test  
**Version:** 1.0  

**Source alignment:** `mcp-architecture.md`, `pluggable_agentic_ai_overall_architecture.md`, `backend-application-architecture.md`, `backend-tooling-mcp-client-architecture.md`, `backend-tooling-mcp-client-plan.md`, `backend-policy-architecture.md`, and `backend-observability-plan.md`  
**Repository rule:** all MCP server runtime code lives under `mcp/`  
**Runtime stack:** Python 3.12+, FastMCP, Pydantic, PyYAML, HTTPX, pytest, ruff, mypy

---


## 1. Purpose

This plan verifies that the standalone MCP server integrates cleanly with the already-working backend. The backend should point `MCP_MAIN_URL` to the local MCP server, discover `websearch.search` through MCP, call it through the backend `ToolGateway` and `MCPClientAdapter`, and return a normalized result through the existing API/session/orchestration path.

Core rule for this phase:

> The integration test proves the three-tier boundary. The backend calls MCP over protocol; it does not import MCP server code or plugin modules.

## 2. Scope

In scope:

- Local end-to-end MCP startup.
- Backend configuration pointing to MCP local URL.
- Tool discovery of `websearch.search`.
- Backend tool gateway call to MCP.
- Optional chat request path that triggers web search.
- Trace/header correlation check.
- Safe normalized result verification.
- Smoke-test documentation.

Out of scope:

- Frontend UI changes.
- New backend orchestration architecture.
- Production deployment automation.
- External network dependency in default CI.
- Full browser-based E2E tests.

## 3. Target Repository Shape

Create or update:

```text
mcp/
  scripts/
    run_local.sh
    inspect_tools.py
  tests/integration/
    test_mcp_server_smoke.py
    test_backend_mcp_contract_smoke.py
backend/
  config/app.yaml            # only if MCP settings need local profile updates
  tests/integration/
    test_mcp_websearch_smoke.py
docs/
  mcp-local-smoke-test.md
```

Keep all MCP server runtime code under `mcp/`. Backend tests may live under `backend/tests/`, but they must call MCP over the configured endpoint rather than importing MCP plugin code.

## 4. Implementation Steps

### [DONE] Step 1: Add Local Run Script

Create `mcp/scripts/run_local.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python -m app.main
```

Also document Windows/PowerShell equivalent commands in `docs/mcp-local-smoke-test.md` if needed.

### [DONE] Step 2: Add Tool Inspection Script

Create `mcp/scripts/inspect_tools.py` that calls the local MCP endpoint and lists available tools/capabilities if the selected MCP client library provides a simple inspection API. If not, document the FastMCP-native command or test method used to inspect tools.

The script should print safe fields only:

- tool name
- capability
- risk level
- enabled status
- schema presence

### [DONE] Step 3: Confirm MCP Local Server

Manual smoke flow:

```bash
cd mcp
python -m app.main
```

Expected:

- Server starts on `http://localhost:9001/mcp`.
- Health/capabilities tools are registered if enabled.
- `websearch.search` is registered.
- Startup logs show loaded tool counts and no secrets.

### [DONE] Step 4: Configure Backend Local MCP URL

Set backend local environment/config:

```env
MCP_MAIN_URL=http://localhost:9001/mcp
```

or the equivalent value in the backend's local `backend/config/app.yaml` profile.

If auth is enabled for the MCP server, configure matching backend MCP client auth mode using existing backend tooling config:

```env
MCP_AUTH_MODE=bearer
MCP_BEARER_TOKEN=<local-test-token>
```

Do not hard-code tokens in committed config.

### [DONE] Step 5: Verify Backend Discovery

Using backend tests or a local script, assert that backend `MCPClientAdapter.list_tools()` or `ToolGateway.list_tools()` can see:

```text
websearch.search
```

Expected normalized backend tool metadata:

- logical tool name mapped to MCP tool name
- input schema present
- safety/risk level read-only
- source MCP server = `main_mcp`

### [DONE] Step 6: Verify Backend Tool Execution

Add a backend integration smoke test that calls the tool through the backend tooling boundary.

Test path:

```text
Backend ToolGateway
  -> MCPClientAdapter
    -> MCP Server
      -> websearch.search
```

Do not import:

```text
mcp.tools.websearch.plugin
mcp.tools.websearch.service
```

Expected result:

- status completed
- bounded result list
- title/url/snippet/rank/source fields
- safe summary metadata
- no raw DDGS objects
- no credentials

### [DONE] Step 7: Verify Optional Chat Path

If the backend already has a configured agent/use case that can call tools, add a local smoke scenario:

```text
User asks: "Search the web for current Python FastMCP information."
Backend route receives chat request.
Session service calls orchestration.
Agent/strategy requests allowed tool.
ToolGateway calls MCP.
MCP websearch returns results.
Backend normalizes result and responds.
```

This should be a smoke test only. Do not redesign the backend orchestration.

### [DONE] Step 8: Verify Trace Correlation

Ensure backend sends a trace header such as:

```text
x-trace-id: trace_...
```

MCP logs should include the same trace ID for the tool call.

Smoke assertion:

- backend trace ID exists
- MCP log/event contains same trace ID
- no raw query/result/credential payloads appear in MCP logs

### [DONE] Step 9: Isolate External Network Tests

Because DDGS/DuckDuckGo can be rate-limited or unstable, default CI should not require live external search.

Use markers:

```python
@pytest.mark.integration
@pytest.mark.external_network
```

Default integration tests can use a mocked/fake MCP tool or a local test provider. Live DDGS should be opt-in.

## 5. Boundary Rules

- Backend must call MCP over MCP protocol only.
- Backend must not import MCP server code.
- MCP server must not import backend code.
- Frontend remains unchanged.
- API/session/orchestration boundaries remain unchanged.
- Test tokens and secrets must not be committed.

## 6. Tests

Add tests for:

| Test File | Purpose |
|---|---|
| `mcp/tests/integration/test_mcp_server_smoke.py` | MCP server starts and exposes expected tools. |
| `mcp/tests/integration/test_backend_mcp_contract_smoke.py` | Contract-level MCP call works without backend import coupling, if practical. |
| `backend/tests/integration/test_mcp_websearch_smoke.py` | Backend can discover and call `websearch.search` through its existing tooling layer. |

Recommended local checks:

```bash
# Terminal 1
cd mcp
python -m app.main

# Terminal 2
cd backend
MCP_MAIN_URL=http://localhost:9001/mcp python -m pytest tests/integration/test_mcp_websearch_smoke.py -m integration
```

Optional external-network test:

```bash
cd mcp
python -m pytest tests/integration -m external_network
```

## 7. Acceptance Criteria

This phase is complete when:

- Local MCP server runs on `http://localhost:9001/mcp`.
- Backend points to MCP through `MCP_MAIN_URL` or equivalent validated config.
- Backend discovers `websearch.search` through MCP.
- Backend can execute `websearch.search` through `ToolGateway` and `MCPClientAdapter`.
- A chat/tool smoke path can return normalized web search results.
- Backend/session/orchestration boundaries remain unchanged.
- No backend code imports MCP plugin modules.
- Trace correlation works across backend and MCP logs/events.
- Secrets and raw payloads are not logged or returned.

## 8. Final Handoff

After this phase, the V1 MCP server is ready for normal extension. New tools should follow this process:

1. Create `mcp/tools/<tool_name>/`.
2. Add `manifest.yaml`.
3. Add optional `config.yaml`.
4. Implement `plugin.py`, models, service, and tests.
5. Enable the tool in `mcp/config/app.yaml`.
6. Add backend logical tool allowlist/policy entries if agents should use it.
7. Run MCP unit tests and backend integration smoke tests.
