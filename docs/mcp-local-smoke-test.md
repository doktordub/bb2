# MCP Local Smoke Test

This document captures the local phase 8 smoke flow for the standalone MCP server and the backend tooling boundary.

## Prerequisites

- Python dependencies are installed in `mcp/.venv`.
- The backend is reachable at `http://127.0.0.1:8000` for live contract checks.
- The MCP server listens on `http://127.0.0.1:9001/mcp`.
- Live DDGS checks are opt-in because they depend on external network availability.

## Start The MCP Server

Shell:

```bash
cd mcp
./scripts/run_local.sh
```

PowerShell:

```powershell
Set-Location E:\KODE\tools\bb2\mcp
& .venv\Scripts\Activate.ps1
python -m app.main
```

Expected runtime behavior:

- The server starts on `http://127.0.0.1:9001/mcp`.
- `websearch.search`, `mcp.health`, `mcp.capabilities`, and `mcp.tools.list` are registered.
- Startup logs contain safe counts and configuration summaries only.

## Inspect Registered Tools

```powershell
Set-Location E:\KODE\tools\bb2\mcp
& .venv\Scripts\Activate.ps1
python scripts/inspect_tools.py --endpoint http://127.0.0.1:9001/mcp
```

The script prints safe inspection columns only:

- tool name
- capability
- risk level
- enabled
- status
- schema presence

## Run MCP Smoke Tests

Local protocol smoke without external network:

```powershell
Set-Location E:\KODE\tools\bb2\mcp
& .venv\Scripts\Activate.ps1
python -m pytest tests/integration/test_mcp_server_smoke.py -m integration
```

Opt-in live DDGS smoke:

```powershell
Set-Location E:\KODE\tools\bb2\mcp
& .venv\Scripts\Activate.ps1
$env:BB2_RUN_EXTERNAL_MCP_WEBSEARCH_TESTS = "1"
python -m pytest tests/integration/test_mcp_server_smoke.py -m external_network
```

## Run Backend MCP Smoke Tests

Discovery and gateway smoke against the local MCP endpoint:

```powershell
Set-Location E:\KODE\tools\bb2\backend
& .venv\Scripts\Activate.ps1
$env:MCP_MAIN_URL = "http://127.0.0.1:9001/mcp"
$env:BB2_RUN_LOCAL_MCP_TESTS = "1"
python -m pytest tests/integration/test_mcp_websearch_smoke.py -m integration
```

Opt-in live DDGS execution through the backend tooling boundary:

```powershell
Set-Location E:\KODE\tools\bb2\backend
& .venv\Scripts\Activate.ps1
$env:MCP_MAIN_URL = "http://127.0.0.1:9001/mcp"
$env:BB2_RUN_EXTERNAL_MCP_WEBSEARCH_TESTS = "1"
python -m pytest tests/integration/test_mcp_websearch_smoke.py -m external_network
```

## Run Live Backend Contract Smoke

This verifies the already-running backend reports MCP readiness and tooling availability through its public API.

```powershell
Set-Location E:\KODE\tools\bb2\mcp
& .venv\Scripts\Activate.ps1
$env:BB2_RUN_LIVE_BACKEND_MCP_TESTS = "1"
python -m pytest tests/integration/test_backend_mcp_contract_smoke.py -m integration
```

If this contract smoke reports `adapter_reachable=false` or `discovery_state=error`, restart the backend after the MCP server is already listening on `http://127.0.0.1:9001/mcp`. The current backend runtime only refreshes discovery on startup in this local flow.

## Optional Manual Chat Scenario

If the live backend is configured with a tool-using agent or use case, send a chat request such as:

```text
Search the web for current Python FastMCP information.
```

Expected behavior:

- The backend returns a response with a stable `trace_id`.
- The MCP server records the same trace ID on the tool call event.
- The tool result remains structured and bounded, even if the upstream provider returns a safe transient error.
- No secrets or raw provider objects appear in logs or responses.