# Frontend Visualization Phase 0 Decision Record

**Status:** Accepted for frontend visualization phase 0  
**Date:** 2026-07-10  
**Scope:** Frontend visualization baseline, compatibility freeze, fixture intake, and payload-limit defaults before renderer work starts

## Purpose

Freeze the frontend-owned visualization compatibility decisions before adding parser, validator, renderer, and chart UI code.

## Baseline Validation Commands

The frontend phase-0 baseline is defined by this existing command from `frontend/`:

- `.venv\Scripts\python.exe -m pytest`

This command already covers the current Python page/proxy/settings/security/openapi tests and the Node-backed JavaScript module tests that run through `tests/test_frontend_js.py`.

## Baseline Validation Result (2026-07-10)

- Full frontend baseline is green after the Phase 0 additions: `.venv\Scripts\python.exe -m pytest` -> `47 passed`.
- The JavaScript module coverage runs inside that `pytest` command and remains green after adding `response.artifact` coverage.
- The current frontend repository does not yet contain a separate browser E2E suite; Phase 0 therefore treats the existing page, proxy, and JS-module coverage as the baseline.

## Current Frontend Behavior Snapshot

| Surface | Current owner | Phase-0 note |
|---|---|---|
| Message rendering | `frontend/app/static/js/chat/conversation.js` | Assistant and user messages are rendered as sanitized Markdown/text cards with metadata chips. |
| REST response handling | `frontend/app/static/js/chat/requests.js` | Non-streaming chat reads `payload.data.answer` and already tolerates additive response fields. |
| SSE event dispatch | `frontend/app/static/js/services/sse-client.js` | Canonical `response.*` events are recognized, and Phase 0 now accepts additive `response.artifact` frames. |
| Session ID storage | `frontend/app/static/js/services/session-store.js` | Only active session id, selected use case, and layout state are stored in `localStorage`. |
| Reset and history UX | `frontend/app/static/js/chat/sessions.js` | Session list, history load, reset, delete, and new-chat behavior already exist and remain unchanged in Phase 0. |
| Capabilities and health loading | `frontend/app/static/js/core/app-shell.js` plus `frontend/app/static/js/chat/inspector.js` | Shell startup already loads `/backend/health` and `/backend/capabilities` before chat initialization. |
| Error display | `frontend/app/static/js/common/banner.js`, `frontend/app/static/js/common/toast.js`, and `frontend/app/static/js/chat/requests.js` | Request failures already render readable inline and toast feedback without depending on artifacts. |
| Content security policy | `frontend/app/security/headers.py` | The current CSP is self-hosted only and already rejects third-party script/CDN assumptions. |

## Fixture Intake Decision

- Canonical shared happy-path fixtures remain under `backend/tests/fixtures/visualization/`.
- Frontend Phase 0 contract tests load those backend fixtures directly so the frontend and backend use the same artifact, chat-response, and SSE golden files.
- Frontend-local edge fixtures live under `frontend/tests/fixtures/visualization/` only for deferred client cases that backend phase 0 did not freeze publicly yet:
  - unsupported chart type;
  - provisional reference mode;
  - provisional expired reference error;
  - provisional multi-artifact response.

## Compatibility Decisions

1. The frontend compatibility extension point is `payload.data.artifacts`; missing `artifacts` still means no artifacts.
2. Unknown top-level response fields remain ignored unless a later phase binds them intentionally.
3. `response.artifact` is an additive SSE event in the existing `response.*` family and must be preserved even before charts are rendered.
4. Text answers remain visible even if artifact parsing, validation, loading, or rendering fails in later phases.
5. Unknown chart types and unknown spec versions must map to a non-executing unsupported state; the frontend must not attempt to execute backend-provided code or renderer specs.
6. The public reference-mode fetch route shape is still not frozen in phase 0. Any frontend-local reference fixtures remain provisional until backend API work freezes that contract.

## Renderer Packaging Decision

- Follow the repository's existing vendored static-asset pattern used for Bootstrap.
- Phase 1 should pin a specific ECharts version and serve it from `frontend/app/static/vendor/` or an equivalent self-hosted bundle path.
- Do not introduce a CDN dependency for charts in Phase 1 because the current CSP only allows self-hosted scripts.
- Do not introduce a new build system solely for visualization if a vendored bundle or the existing module layout is sufficient.

## Browser Support Matrix

| Browser family | Support target |
|---|---|
| Chrome | Current stable and previous stable |
| Edge | Current stable and previous stable |
| Firefox | Current stable and previous stable |
| Safari | Current stable |

Minimum supported viewport width for visualization work: `320px`.

Rationale: the existing frontend already depends on ES modules, `fetch`, `ReadableStream`, `AbortController`, and `localStorage`, so legacy browsers are out of scope for visualization.

## Client Payload-Limit Configuration

Phase 0 adds frontend settings that align with the backend visualization defaults already frozen in architecture and backend Phase 0:

- `FRONTEND_VISUALIZATION_MAX_ARTIFACTS_PER_RESPONSE=3`
- `FRONTEND_VISUALIZATION_MAX_ROWS_INLINE=5000`
- `FRONTEND_VISUALIZATION_MAX_SERIES=12`
- `FRONTEND_VISUALIZATION_MAX_CATEGORIES=100`

These limits are transport-level defaults only. Additional parser-specific bounds such as field-count, string-length, and metadata allowlists remain phase-1 work so the frontend does not freeze unbacked micro-limits ahead of the validator implementation.