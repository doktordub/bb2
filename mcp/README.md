# MCP Server

Phase 1 provides the standalone FastMCP walking skeleton for the MCP tier.

## Run Locally

PowerShell:

```bash
cd mcp
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .[dev]
python -m app.main
```

POSIX shell:

```bash
cd mcp
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
python -m app.main
```

Local MCP endpoint:

```text
http://localhost:9001/mcp
```

## Validation

```bash
cd mcp
python -m pytest
python -m ruff check app tests
python -m mypy app
```
