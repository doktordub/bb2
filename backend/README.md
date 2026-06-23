# Backend Foundation

All backend application work lives under `backend/`. Run backend commands from this directory.

## Boundaries

- Application source lives in `app/`.
- Backend tests live in `tests/`.
- `frontend/`, `mcp/`, and the repository root are not backend runtime code locations.
- `.venv/` and `dist/` are local or generated artifacts, not the application source tree.

## Phase Scope

The foundation is complete through Phase 6:

- deterministic settings and raw config loading
- application startup through `app.main`
- structured logging and trace IDs
- foundation-only `/health` and `/capabilities` routes
- unit tests plus baseline linting and type checks

## Foundation Freeze

The following foundation surfaces are now the stable handoff boundary for deeper backend work:

- `app.main:create_app()`
- `FoundationContainer`
- `GET /health`
- `GET /capabilities`
- the backend settings loader and bootstrap path

The following concerns remain intentionally deferred:

- MCP client integration
- LLM gateway implementations
- `memory_store` integration behind a backend `MemoryGateway`
- SQLite workflow state and trace stores
- auth and authorization behavior
- streaming chat routes
- orchestration runtime and `agent_framework` integration

The next architecture document is `../docs/backend-core-contracts-architecture.md` at the repository root.

## Setup

Use the existing virtual environment in `.venv/`.

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

## Local Configuration

Copy `.env.example` to `.env` before local development.

Relative paths such as `APP_CONFIG_PATH` are always resolved from `backend/`, not from the caller's current working directory.

## Validation

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy app
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```
