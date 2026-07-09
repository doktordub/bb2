# Websearch MCP Tool

`websearch.search` exposes bounded public web text search through DDGS.

## Behavior

- Searches public web results only.
- Returns structured summaries with title, URL, snippet, rank, and source.
- Does not fetch full pages, run JavaScript, crawl, or call backend services.
- Applies request, result, timeout, rate-limit, and cache bounds locally.

## Validation

```bash
cd mcp
python -m pytest tools/websearch/tests -m "not external_network"
python -m ruff check app tools tests
python -m mypy app tools/websearch
```