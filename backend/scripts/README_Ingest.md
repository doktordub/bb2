# Docs Ingest And Chunk Search CLIs

These backend-local scripts load the same validated runtime config as the FastAPI app and operate only on the repository docs corpus.

## Scope

- `markdown_folder_ingest_cli.py` recursively ingests only `.md` files under the repository `docs/` tree.
- `chunk_search_cli.py` searches only `document_chunk` records from the same configured `memory_store` database.
- Both scripts default to `backend/config/app.yaml` and resolve `project_id` from the configured docs retrieval allowlist. In the canonical config, omitting `--project-id` resolves to `arch_docs`.
- Neither script accepts direct database or reranker overrides; those remain owned by backend config.

## Prerequisites

- Run from `backend/`.
- Use the repo-local virtual environment at `.venv/`.
- Ensure `.venv` already contains `agent_framework`, `memory_store`, and the backend dependencies.
- Ensure `backend/config/app.yaml` has `memory.enabled: true` and `memory.provider: memory_store`.

## Ingest Repository Docs

Ingest the full repository docs corpus:

```powershell
.\.venv\Scripts\python.exe .\scripts\markdown_folder_ingest_cli.py
```

Ingest only one subfolder under `docs/`:

```powershell
.\.venv\Scripts\python.exe .\scripts\markdown_folder_ingest_cli.py extra
```

Useful flags:

- `--config-path` overrides the backend config file. Default: `backend/config/app.yaml`.
- `--project-id` is optional. When omitted, the CLI resolves it from `architecture_document_qa` and `architecture_document_agent`, then prints whether the value was explicit, defaulted, or singleton-resolved.
- `--user-id` and `--agent-id` add durable scope dimensions when needed.
- `--fail-fast` stops on the first failed file instead of collecting all failures.

The script emits JSON with:

- `requested_scope`
- `docs_root`
- `database_path`
- `scope`
- `scope_resolution`
- `matched_files`, `processed_files`, `failed_files`
- `totals` for added, updated, unchanged, and removed chunks
- per-file `files` entries plus `failures`

## Search Document Chunks

Search the configured docs corpus:

```powershell
.\.venv\Scripts\python.exe .\scripts\chunk_search_cli.py "architecture" --limit 5
```

Include neighboring chunk context for manual review:

```powershell
.\.venv\Scripts\python.exe .\scripts\chunk_search_cli.py "memory gateway" --limit 3 --before 1 --after 1
```

Useful flags:

- `--config-path` overrides the backend config file. Default: `backend/config/app.yaml`.
- `--project-id` is optional. In the canonical config, omitting it resolves to `arch_docs` and the CLI prints the resolution summary before search begins.
- `--user-id` and `--agent-id` narrow the search scope when needed.
- `--limit` is capped by the backend-configured `memory.search.limit_max`.
- `--before` and `--after` fetch neighboring chunks through the backend adapter.

The search JSON payload includes:

- `query`
- `database_path`
- `requested_scope`
- `scope`
- `scope_resolution`
- `limit` and `limit_max`
- `count`
- `items`, with `memory_id`, `chunk_id`, `title`, `snippet`, `text`, `source_uri`, `document_id`, `heading_path`, `document_chunk_index`, `score`, optional `component_scores`, and optional `context`

## Failure Modes

The scripts return JSON errors and non-zero exit codes when:

- memory is disabled in backend config
- the configured memory provider is not `memory_store`
- writes are disabled for ingestion
- the docs CLI cannot resolve an effective `project_id` from explicit input or configured allowlists/defaults
- the requested docs subpath escapes the repository `docs/` tree
- the configured adapter cannot be initialized

If `memory.store.database.embedded_single_process` is enabled and the backend is already running against the same ArcadeDB path, the CLI may fail with a lock error. In that case, stop the backend before direct CLI ingestion or search, or use the live backend retrieval path for end-to-end validation.

## Rollout Note

- Re-ingest the docs corpus under `arch_docs` before validating `architecture_document_qa` end to end.
- Retain legacy `docs`-scoped records only until the `arch_docs` corpus is verified, then delete the old scope explicitly instead of leaving both corpora active.


