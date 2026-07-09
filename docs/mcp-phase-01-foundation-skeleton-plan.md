# MCP Phase 1 Implementation Plan [DONE]: Foundation Skeleton

**Document:** `mcp-phase-01-foundation-skeleton-plan.md`  
**Phase:** 1 of 8 [DONE]  
**Architecture phase:** MCP Foundation Skeleton  
**Version:** 1.0  

**Source alignment:** `mcp-architecture.md`, `pluggable_agentic_ai_overall_architecture.md`, `backend-application-architecture.md`, `backend-tooling-mcp-client-architecture.md`, `backend-tooling-mcp-client-plan.md`, `backend-policy-architecture.md`, and `backend-observability-plan.md`  
**Repository rule:** all MCP server runtime code lives under `mcp/`  
**Runtime stack:** Python 3.12+, FastMCP, Pydantic, PyYAML, HTTPX, pytest, ruff, mypy

---


## 1. Purpose

This plan creates the initial standalone MCP server deployable under `mcp/`. The goal is to establish a minimal FastMCP application that can start locally, expose a reachable MCP endpoint, provide a safe health tool, and prove the MCP tier is separate from the already-working frontend and backend tiers.

This phase intentionally avoids real tool loading, DuckDuckGo search, full security, and production observability. It creates the walking skeleton that later phases will deepen.

Core rule for this phase:

> Build the smallest separate MCP process that starts, serves FastMCP, reports safe health, and can later accept plugin registration.

## 2. Scope

In scope:

- Create the `mcp/` Python package.
- Add `mcp/pyproject.toml`.
- Add the basic `mcp/app/` package.
- Create a FastMCP server construction path.
- Add minimal `mcp/config/app.yaml`.
- Add an internal `mcp.health` FastMCP tool.
- Add unit tests proving app construction and health behavior.
- Add basic developer commands in `mcp/README.md`.

Out of scope:

- Dynamic tool discovery.
- Real web search.
- JWT/OAuth/TLS hardening.
- Backend integration.
- Full metrics and trace correlation.
- Per-tool plugin manifest validation.

## 3. Target Repository Shape

Create this initial layout:

```text
mcp/
  pyproject.toml
  README.md
  app/
    __init__.py
    main.py
    bootstrap.py
    server.py
    health.py
    errors.py
  config/
    app.yaml
  tools/
    .gitkeep
  tests/
    unit/
      test_server.py
      test_health.py
```

## 4. Implementation Steps

### Step 1 [DONE]: Create MCP Python Project

Add `mcp/pyproject.toml` with Python 3.12+ and dependencies needed for the walking skeleton:

```toml
[project]
name = "pluggable-agentic-ai-mcp"
version = "1.0.0"
requires-python = ">=3.12"
dependencies = [
  "fastmcp>=2.0",
  "pydantic>=2.0",
  "PyYAML>=6.0",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.0",
  "pytest-asyncio>=0.23",
  "ruff>=0.6",
  "mypy>=1.10",
]

[tool.ruff]
line-length = 100

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

If the repository pins the official MCP SDK import path instead of the standalone FastMCP package, update the dependency and imports consistently in this phase. Do not mix both import styles across files.

### Step 2 [DONE]: Add Minimal Global Configuration

Create `mcp/config/app.yaml`:

```yaml
server:
  name: main_mcp
  version: 1.0.0
  environment: local
  host: 0.0.0.0
  port: 9001
  path: /mcp
  transport: http

policy:
  expose_health_tool: true

observability:
  log_level: INFO
  json_logs: false
```

For this phase, config may be read minimally as a dictionary. Typed settings arrive in Phase 2.

### Step 3 [DONE]: Create Server Builder

Implement `mcp/app/server.py` with one function that builds and returns a FastMCP app. Keep all server construction inside this function so tests can create an in-memory server without starting a process.

Expected responsibilities:

- Create `FastMCP("main_mcp")`.
- Register the internal health tool if enabled.
- Return the server instance.

### Step 4 [DONE]: Create Health Tool

Implement `mcp/app/health.py` with a safe health payload:

```json
{
  "status": "ok",
  "server": {
    "name": "main_mcp",
    "version": "1.0.0",
    "environment": "local"
  },
  "tools": {
    "loaded": 0,
    "enabled": 0,
    "disabled": 0,
    "unhealthy": 0
  }
}
```

Do not include environment variables, process secrets, absolute private paths, tokens, or stack traces.

### Step 5 [DONE]: Add Bootstrap Composition Root

Implement `mcp/app/bootstrap.py` as the phase-level composition root. It should:

1. Locate `mcp/config/app.yaml`.
2. Load the minimal YAML config.
3. Build the FastMCP server.
4. Return a lightweight container object or server object.

Avoid import-time I/O. Tests should be able to import `app.main` without reading files or starting the server.

### Step 6 [DONE]: Add Process Entry Point

Implement `mcp/app/main.py` with:

- `create_server()` for tests and future composition.
- A guarded `if __name__ == "__main__":` block that calls `server.run(...)`.

Use settings from `app.yaml` for host, port, transport, and path.

### Step 7 [DONE]: Add README

Create `mcp/README.md` with:

```bash
cd mcp
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
python -m app.main
```

Include the expected local endpoint:

```text
http://localhost:9001/mcp
```

## 5. Boundary Rules

- Do not put MCP server code in `backend/`.
- Do not import backend modules from `mcp/`.
- Do not import frontend modules from `mcp/`.
- Do not create real tool plugins yet.
- Do not require backend to be running for MCP server startup.
- Do not let server startup make external network calls.

## 6. Tests

Add tests under `mcp/tests/unit/`:

| Test File | Purpose |
|---|---|
| `test_server.py` | Proves the FastMCP server can be constructed without starting the process. |
| `test_health.py` | Proves the health payload is safe and contains no secrets. |

Recommended checks:

```bash
cd mcp
python -m pytest
python -m ruff check app tests
python -m mypy app
```

## 7. Acceptance Criteria

This phase is complete when:

- `mcp/` exists as a standalone Python project.
- `mcp/app/main.py` can start a FastMCP server locally.
- `mcp/config/app.yaml` exists.
- `mcp.health` is registered when enabled.
- Health returns safe server status.
- No MCP implementation code is placed inside `backend/` or `frontend/`.
- Unit tests pass.

## 8. Handoff to Phase 2

Phase 2 should replace the minimal dictionary config with typed validated settings and introduce shared common services: redaction, logging, secret resolution, HTTP client factory, and rate limiting.
