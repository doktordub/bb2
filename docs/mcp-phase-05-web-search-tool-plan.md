# MCP Phase 5 Implementation Plan: Web Search Tool

**Document:** `mcp-phase-05-web-search-tool-plan.md`  
**Phase:** 5 of 8 [DONE]  
**Architecture phase:** Web Search Tool  
**Version:** 1.0  

**Source alignment:** `mcp-architecture.md`, `pluggable_agentic_ai_overall_architecture.md`, `backend-application-architecture.md`, `backend-tooling-mcp-client-architecture.md`, `backend-tooling-mcp-client-plan.md`, `backend-policy-architecture.md`, and `backend-observability-plan.md`  
**Repository rule:** all MCP server runtime code lives under `mcp/`  
**Runtime stack:** Python 3.12+, FastMCP, Pydantic, PyYAML, HTTPX, pytest, ruff, mypy

---


## 1. Purpose

This plan implements the first real MCP capability: `websearch.search`, backed by DuckDuckGo/DDGS. The tool searches public web results and returns bounded structured result summaries with titles, URLs, snippets, rank, and source metadata.

Core rule for this phase:

> The web search tool returns search-result summaries and citations only. It does not fetch full pages, crawl websites, execute JavaScript, call backend memory, or call backend LLM services.

## 2. Scope

In scope:

- Create `mcp/tools/websearch/`.
- Add manifest and config.
- Add Pydantic input/output models.
- Add DDGS-backed service.
- Register `websearch.search` as a FastMCP tool.
- Add result bounding and normalization.
- Add unit tests.
- Add optional external-network integration test.

Out of scope:

- Browser automation.
- Full-page retrieval.
- Search result ingestion into memory.
- News/image/video search variants.
- Ranking beyond provider order.
- Backend orchestration changes.

## 3. Target Repository Shape

Create:

```text
mcp/tools/websearch/
  __init__.py
  manifest.yaml
  config.yaml
  plugin.py
  models.py
  service.py
  README.md
  tests/
    test_websearch_models.py
    test_websearch_service.py
    test_websearch_plugin.py
    test_websearch_external.py
```

Update:

```text
mcp/config/app.yaml
mcp/pyproject.toml
mcp/tests/unit/test_loader.py
mcp/tests/integration/
```

## 4. Implementation Steps

### Step 1: Add Dependency [DONE]

Update `mcp/pyproject.toml`:

```toml
dependencies = [
  "fastmcp>=2.0",
  "pydantic>=2.0",
  "PyYAML>=6.0",
  "httpx>=0.27",
  "ddgs>=9.0",
]
```

Pin versions later if deployment reproducibility requires it.

### Step 2: Configure Tool Enablement [DONE]

Update `mcp/config/app.yaml`:

```yaml
tools:
  websearch:
    enabled: true
    required: true
    config_file: config.yaml
```

### Step 3: Add Manifest [DONE]

Create `mcp/tools/websearch/manifest.yaml`:

```yaml
name: websearch
package: mcp.tools.websearch
version: 1.0.0
status: stable
owner: platform
required: true

description: Search the public web through DuckDuckGo/DDGS and return bounded structured results.

capabilities:
  - name: web.search
    type: tool
    risk_level: read_only
    description: Search public web results.

tools:
  - name: websearch.search
    function: search
    capability: web.search
    description: Search public web results using DuckDuckGo/DDGS.
    risk_level: read_only
    input_schema: auto
    output_schema: structured_results
    timeout_seconds: 20
    max_result_bytes: 65536
    tags: [web, search, read_only]

config_schema:
  type: object
  required: [provider, max_results]
  properties:
    provider:
      type: string
      enum: [ddgs]
    max_results:
      type: integer
      minimum: 1
      maximum: 25
    region:
      type: string
    safesearch:
      type: string
      enum: [off, moderate, strict]
```

### Step 4: Add Tool Config [DONE]

Create `mcp/tools/websearch/config.yaml`:

```yaml
provider: ddgs
backend: duckduckgo
region: us-en
safesearch: moderate
time_limit: null
max_results: 10
max_query_chars: 500
timeout_seconds: 15
cache_seconds: 300
allowed_result_fields:
  - title
  - href
  - body
result_limits:
  max_title_chars: 200
  max_url_chars: 1000
  max_snippet_chars: 500
  max_results: 10
```

### Step 5: Add Models [DONE]

Create `mcp/tools/websearch/models.py`:

- `WebSearchRequest`
- `WebSearchResult`
- `WebSearchResponse`
- `WebSearchProviderError` if useful

Validation requirements:

- `query`: 1 to 500 chars.
- `max_results`: 1 to configured max, default 5.
- `region`: bounded string.
- `safesearch`: `off`, `moderate`, or `strict`.
- `time_limit`: optional provider-supported value.

Output bounding:

- title <= 200 chars
- URL <= 1000 chars
- snippet <= 500 chars
- results <= configured max

### Step 6: Add Search Service [DONE]

Create `mcp/tools/websearch/service.py`.

Responsibilities:

1. Validate effective limits from tool config.
2. Check rate limiter with key `websearch.search`.
3. Use DDGS in a thread if the API is synchronous.
4. Convert provider items into `WebSearchResult`.
5. Drop malformed results without failing the entire call when possible.
6. Return `WebSearchResponse`.
7. Normalize provider exceptions into MCP-owned safe errors.

Do not log raw queries by default. If needed, log query length and result count only.

### Step 7: Add Plugin [DONE]

Create `mcp/tools/websearch/plugin.py` with:

```python
def create_plugin(context: ToolRuntimeContext) -> ToolPlugin:
    return WebSearchPlugin(context)
```

The plugin registers:

```text
websearch.search
```

The FastMCP function should be a small wrapper:

```text
FastMCP wrapper -> Pydantic request -> service.search -> model_dump(mode="json")
```

### Step 8: Add Health [DONE]

The websearch plugin health should return a safe local readiness payload. It should not call DuckDuckGo during normal health checks unless an explicit deep-health mode is enabled.

Safe health:

```json
{
  "status": "ok",
  "provider": "ddgs",
  "network_check": "skipped"
}
```

### Step 9: Optional Cache [DONE]

If the cache service exists from Phase 2 or a simple cache is available, cache identical read-only queries for `cache_seconds`. Keep this optional and do not block completion on a sophisticated cache.

## 5. Safety Rules

The web search tool must:

- Limit query length.
- Limit result count.
- Bound title, URL, and snippet lengths.
- Return result summaries and URLs.
- Treat snippets as untrusted data.
- Avoid fetching full pages.
- Avoid raw HTML.
- Avoid file downloads.
- Avoid recursive crawling.
- Avoid long-running calls.
- Avoid storing search results as memory.
- Avoid calling backend services.

## 6. Tests

Add tests under `mcp/tools/websearch/tests/`:

| Test File | Purpose |
|---|---|
| `test_websearch_models.py` | Input/output model validation and bounds. |
| `test_websearch_service.py` | Mocked DDGS success/failure, normalization, truncation. |
| `test_websearch_plugin.py` | Plugin creates and registers `websearch.search`. |
| `test_websearch_external.py` | Optional real DDGS smoke test, marked external network. |

Recommended external markers:

```python
@pytest.mark.integration
@pytest.mark.external_network
```

Recommended checks:

```bash
cd mcp
python -m pytest tools/websearch/tests -m "not external_network"
python -m ruff check app tools tests
python -m mypy app tools/websearch
```

Optional:

```bash
python -m pytest tools/websearch/tests -m external_network
```

## 7. Acceptance Criteria

This phase is complete when:

- `mcp/tools/websearch/` exists.
- `websearch.search` loads through the Phase 4 loader.
- `websearch.search` appears in tool/capability listing.
- Valid search inputs return bounded structured results.
- Invalid inputs fail safely.
- Provider failures become normalized safe errors.
- No full-page crawling or raw HTML return behavior exists in V1.
- Unit tests pass without external network dependency.

## 8. Handoff to Phase 6

Phase 6 should harden the server security boundary: inbound bearer/JWT auth, outbound OAuth provider interfaces, TLS-aware configuration, secret resolver hardening, and argument secret detection.
