# [DONE] MCP Phase 4 Implementation Plan: Tool Loader and Registry

**Document:** `mcp-phase-04-tool-loader-registry-plan.md`  
**Phase:** [DONE] 4 of 8  
**Architecture phase:** Tool Loader and Registry  
**Version:** 1.0  

**Source alignment:** `mcp-architecture.md`, `pluggable_agentic_ai_overall_architecture.md`, `backend-application-architecture.md`, `backend-tooling-mcp-client-architecture.md`, `backend-tooling-mcp-client-plan.md`, `backend-policy-architecture.md`, and `backend-observability-plan.md`  
**Repository rule:** all MCP server runtime code lives under `mcp/`  
**Runtime stack:** Python 3.12+, FastMCP, Pydantic, PyYAML, HTTPX, pytest, ruff, mypy

---


## 1. Purpose

This plan implements automatic tool discovery and registration. On boot, the MCP server scans `mcp/tools/`, reads manifests and configs, imports enabled plugin modules, validates descriptors, registers FastMCP handlers, and records loaded capabilities in an internal registry.

Core rule for this phase:

> Developers add tools by adding a folder under `mcp/tools/<tool_name>/`; they should not edit MCP server core files for every new tool.

## 2. Scope

In scope:

- Deterministic tool folder scanning.
- Manifest/config loading.
- Enabled/disabled resolution from `mcp/config/app.yaml`.
- Dynamic plugin import.
- Plugin context factory.
- FastMCP registration.
- Internal `ToolRegistry`.
- Capability summary support.
- Required vs optional tool load behavior.
- Duplicate tool-name detection.

Out of scope:

- Real web search implementation.
- Production JWT/OAuth/TLS.
- Full external network integration.
- Backend smoke test.

## 3. Target Repository Shape

Create or update:

```text
mcp/app/
  bootstrap.py
  loader.py
  registry.py
  capabilities.py
  health.py
  context.py
  server.py
  errors.py
mcp/tests/unit/
  test_loader.py
  test_registry.py
  test_capabilities.py
  test_loader_failure_modes.py
  fixtures/
    tools/
      valid_tool/
      disabled_tool/
      duplicate_tool_a/
      duplicate_tool_b/
      invalid_manifest/
      failing_plugin/
```

## 4. Implementation Steps

### [DONE] Step 1: Define Registered Tool Models

Create `mcp/app/registry.py` models:

- `RegisteredTool`
- `RegisteredCapability`
- `ToolLoadStatus`
- `ToolRegistryHealth`
- `ToolLoadErrorSummary`

Registry fields should include:

- tool folder name
- package name
- manifest name
- version
- enabled/disabled status
- required/optional flag
- FastMCP tool names
- capabilities
- risk levels
- owner
- tags
- health status
- last load error

Do not expose raw config values or secrets in registry summaries.

### [DONE] Step 2: Implement ToolRegistry

Add a `ToolRegistry` class with:

```python
register_plugin(plugin, manifest, config)
register_disabled(manifest)
register_failed(manifest_or_name, error, required)
get_tool(tool_name)
list_tools()
list_capabilities()
mark_unhealthy(tool_name, reason)
health_summary()
```

Duplicate detection must consider all registered FastMCP tool names, not just plugin folder names. Duplicate enabled tools should fail startup.

### [DONE] Step 3: Implement Context Factory

Create a context factory that builds `ToolRuntimeContext` per plugin. It should inject:

- server name
- environment
- tool name
- merged tool config
- validated app settings
- logger
- redactor
- secret resolver
- HTTP client factory
- rate limiter
- clock
- placeholders for future auth/metrics/tracing

The context should expose safe config only.

### [DONE] Step 4: Implement Loader

Create `mcp/app/loader.py` with deterministic load flow:

```text
1. Sort folders under tools_dir.
2. Skip files and folders starting with `_`.
3. Require `manifest.yaml` when policy requires manifests.
4. Read manifest.
5. Resolve enabled/required status using app config and manifest.
6. If disabled, register as disabled and do not import plugin.
7. Read optional `config.yaml`.
8. Merge config.
9. Validate config.
10. Import `mcp.tools.<folder>.plugin`.
11. Call `create_plugin(context)`.
12. Validate plugin instance.
13. Register plugin with FastMCP.
14. Register plugin metadata in ToolRegistry.
```

### [DONE] Step 5: Implement Config Merge Rules

Tool config merge order:

```text
1. Server defaults from `mcp/config/app.yaml`
2. Global tool settings from `mcp/config/app.yaml tools.<tool_name>`
3. Tool-local `mcp/tools/<tool_name>/config.yaml`
4. Environment variable substitutions
5. Runtime-safe computed defaults
```

Test precedence explicitly.

### [DONE] Step 6: Wire Loader into Bootstrap

Update `mcp/app/bootstrap.py` so startup does this:

1. Load settings.
2. Build common services.
3. Build FastMCP server.
4. Build registry.
5. Load tools if `runtime.discovery_on_startup` is true.
6. Register internal health/capability tools using the registry.
7. Return container/server.

### [DONE] Step 7: Add Capabilities Tool Support

Create `mcp/app/capabilities.py` with safe summaries:

```json
{
  "server": "main_mcp",
  "capabilities": [
    {
      "name": "web.search",
      "type": "tool",
      "tool_name": "websearch.search",
      "risk_level": "read_only",
      "enabled": true
    }
  ]
}
```

Register optional internal tools:

```text
mcp.capabilities
mcp.tools.list
```

when enabled by policy.

### [DONE] Step 8: Update Health

Health should now show loaded, enabled, disabled, failed, and unhealthy tool counts. It should not expose raw load exception stack traces in production output.

## 5. Failure Mode Rules

- Missing manifest for enabled tool fails when manifests are required.
- Invalid manifest fails required tool startup.
- Required enabled tool import failure fails startup.
- Optional enabled tool import failure degrades only when `fail_on_optional_tool_error: false`.
- Duplicate FastMCP tool names fail startup.
- Disabled tools are not imported and not registered with FastMCP.

## 6. Tests

Add tests for:

| Test File | Purpose |
|---|---|
| `test_loader.py` | Enabled tools load in deterministic order. |
| `test_registry.py` | Registry records tools/capabilities and detects duplicates. |
| `test_capabilities.py` | Capability summaries are safe and accurate. |
| `test_loader_failure_modes.py` | Required/optional failure behavior is correct. |

Recommended checks:

```bash
cd mcp
python -m pytest tests/unit/test_loader.py tests/unit/test_registry.py tests/unit/test_capabilities.py tests/unit/test_loader_failure_modes.py
python -m ruff check app tools tests
python -m mypy app
```

## 7. Acceptance Criteria

This phase is complete when:

- [DONE] MCP server scans `mcp/tools/` on startup.
- [DONE] Enabled tools are imported and registered.
- [DONE] Disabled tools are skipped.
- [DONE] Tool loading order is deterministic.
- [DONE] Duplicate tool names fail startup.
- [DONE] Registry lists tools and capabilities safely.
- [DONE] Health shows tool counts.
- [DONE] Internal capability tools can be enabled by config.

## 8. Handoff to Phase 5

Phase 5 should add the first real production tool: `mcp/tools/websearch/`, using DDGS/DuckDuckGo and the plugin contract implemented here.
