# MCP Phase 3 Implementation Plan: Tool Plugin Contract

**Document:** `mcp-phase-03-tool-plugin-contract-plan.md`  
**Phase:** 3 of 8 [DONE]  
**Architecture phase:** Tool Plugin Contract  
**Version:** 1.0  

**Source alignment:** `mcp-architecture.md`, `pluggable_agentic_ai_overall_architecture.md`, `backend-application-architecture.md`, `backend-tooling-mcp-client-architecture.md`, `backend-tooling-mcp-client-plan.md`, `backend-policy-architecture.md`, and `backend-observability-plan.md`  
**Repository rule:** all MCP server runtime code lives under `mcp/`  
**Runtime stack:** Python 3.12+, FastMCP, Pydantic, PyYAML, HTTPX, pytest, ruff, mypy

---


## 1. Purpose

This plan defines the reusable plugin contract that every MCP capability will follow. It introduces the `ToolPlugin` protocol, manifest schema, per-tool config schema validation, runtime context, descriptors, and validation helpers. The goal is to make new MCP capabilities easy to add by creating a folder under `mcp/tools/<tool_name>/` without editing MCP server core files.

Core rule for this phase:

> A tool plugin is a small, isolated package that declares metadata, receives common services through context, registers FastMCP handlers, and never imports backend or frontend code.

## 2. Scope

In scope:

- Define `ToolPlugin` protocol.
- Define `ToolRuntimeContext`.
- Define capability and tool descriptor models.
- Define manifest schema and config schema models.
- Add manifest/config validation helpers.
- Add a fake example plugin for contract tests.
- Add clear error classes for invalid manifests and plugins.

Out of scope:

- Full folder scanner and dynamic importer.
- Real registry implementation.
- Web search implementation.
- Security hardening.
- Backend integration.

## 3. Target Repository Shape

Create or update:

```text
mcp/app/
  context.py
  errors.py
  tools_base/
    __init__.py
    plugin.py
    models.py
    manifest.py
    validation.py
    results.py
    decorators.py
mcp/tools/
  example_tool/
    __init__.py
    manifest.yaml
    config.yaml
    plugin.py
mcp/tests/unit/
  test_plugin_contract.py
  test_manifest_validation.py
  test_tool_config_validation.py
  test_example_plugin.py
```

## 4. Implementation Steps

### Step 1: Define Descriptor Models [DONE]

Create `mcp/app/tools_base/models.py` with:

- `CapabilityDescriptor`
- `ToolDescriptor`
- `ToolHealth`
- `RiskLevel` literals
- `ToolStatus` literals

Recommended risk levels:

```text
read_only
write
destructive
external_side_effect
credential_access
```

V1 should default tools to `read_only` only when explicitly declared. Missing risk level should fail validation.

### Step 2: Define ToolPlugin Protocol [DONE]

Create `mcp/app/tools_base/plugin.py`:

```python
from typing import Protocol
from fastmcp import FastMCP

class ToolPlugin(Protocol):
    name: str
    version: str
    capabilities: list[CapabilityDescriptor]

    def register(self, mcp: FastMCP) -> None: ...
    async def health(self) -> ToolHealth: ...
```

Also define the expected module entry point:

```python
def create_plugin(context: ToolRuntimeContext) -> ToolPlugin:
    ...
```

The loader in Phase 4 will rely on this entry point.

### Step 3: Define Runtime Context [DONE]

Create or deepen `mcp/app/context.py` with:

```python
@dataclass(frozen=True, slots=True)
class ToolRuntimeContext:
    server_name: str
    environment: str
    tool_name: str
    tool_config: dict[str, Any]
    app_config: AppSettings
    logger: BoundLogger
    redactor: Redactor
    secrets: SecretResolver
    http_client_factory: HttpClientFactory
    auth: AuthService | None
    outbound_auth: OutboundAuthService | None
    rate_limiter: RateLimiter
    metrics: MetricsRecorder | None
    tracer: TraceRecorder | None
    clock: Clock
```

For Phase 3, `auth`, `outbound_auth`, `metrics`, and `tracer` may be placeholders or protocols. They will be implemented/deepened in later phases.

### Step 4: Define Manifest Schema [DONE]

Create `mcp/app/tools_base/manifest.py` with Pydantic models for:

- `ToolManifest`
- `ManifestCapability`
- `ManifestTool`
- `ToolConfigSchema`

Required manifest fields:

```yaml
name: example_tool
package: mcp.tools.example_tool
version: 1.0.0
status: experimental
owner: platform
required: false
description: Example plugin for MCP contract validation.
capabilities: []
tools: []
config_schema: {}
```

Validation rules:

- `name` must match folder-safe naming.
- `package` must match `mcp.tools.<tool_name>`.
- `version` must be present.
- Every declared tool must reference a declared capability.
- Tool names must be unique inside a manifest.
- Risk level must be explicit and valid.
- Input schema must be `auto` or a JSON-schema-shaped object.
- Config schema must be a JSON-schema-shaped object when present.

### Step 5: Define Config Validation Helpers [DONE]

Create `mcp/app/tools_base/validation.py` with:

- `load_manifest(path) -> ToolManifest`
- `load_tool_config(path) -> dict`
- `validate_tool_config(manifest, config) -> None`
- `validate_plugin_instance(plugin, manifest) -> None`

For Phase 3, config-schema validation can be minimal but should still enforce required keys declared in `config_schema`. Deeper JSON Schema validation can be added later if needed.

### Step 6: Add Result Envelope Models [DONE]

Create `mcp/app/tools_base/results.py` with:

- `ToolResultEnvelope`
- `ToolErrorEnvelope`
- `ToolResultSummary`

These models should reinforce the MCP output rule: structured, bounded, no credentials, no raw downstream HTTP response objects.

### Step 7: Add Example Plugin [DONE]

Create `mcp/tools/example_tool/` as a non-production fake plugin used for contract tests.

It should:

- Have a valid manifest.
- Have simple config.
- Implement `create_plugin(context)`.
- Register one FastMCP tool, such as `example.echo`.
- Return structured output.

Mark it disabled in `mcp/config/app.yaml` so it does not become a real production tool by accident.

## 5. Boundary Rules

- Tool plugins do not import `backend/*`.
- Tool plugins do not import `frontend/*`.
- Tool plugins do not read environment variables directly.
- Tool plugins do not create unbounded HTTP clients.
- Tool plugins do not log raw arguments or raw results.
- Tool plugin metadata is declarative and validated before registration.

## 6. Tests

Add tests for:

| Test File | Purpose |
|---|---|
| `test_plugin_contract.py` | Ensures expected protocol and `create_plugin` pattern works. |
| `test_manifest_validation.py` | Valid and invalid manifests fail clearly. |
| `test_tool_config_validation.py` | Tool config is validated against declared schema. |
| `test_example_plugin.py` | Fake plugin can be instantiated and returns safe health. |

Recommended checks:

```bash
cd mcp
python -m pytest tests/unit/test_plugin_contract.py tests/unit/test_manifest_validation.py tests/unit/test_tool_config_validation.py tests/unit/test_example_plugin.py
python -m ruff check app tools tests
python -m mypy app
```

## 7. Acceptance Criteria

This phase is complete when:

- `ToolPlugin` protocol exists.
- `ToolRuntimeContext` exists.
- Manifest models and validation helpers exist.
- Tool config validation helpers exist.
- A fake example plugin can be instantiated.
- Invalid manifests fail with clear MCP-owned errors.
- No plugin contract code imports backend or frontend modules.

## 8. Handoff to Phase 4

Phase 4 should implement the loader and registry that use this contract to scan `mcp/tools/`, import enabled plugins, register them with FastMCP, and expose safe capability summaries.
