# Frontend

Thin Flask user-experience layer for the pluggable agentic AI backend. The frontend owns page rendering, browser-safe routing, and later `/ui-api/*` proxy routes. The backend remains the source of truth for orchestration, agents, sessions, tools, memory, policy, and trace data.

## Source of Truth

- Architecture: `../docs/frontend-architecture.md`
- Implementation plan: `../docs/frontend-plan.md`
- Backend contract snapshot: `./openAPI.json`
- Backend contract refresh source: live backend `http://127.0.0.1:8000/openapi.json`
- Help content source: `../docs/Training_Readme.md`

The frontend now keeps a checked-in `openAPI.json` snapshot for contract tests. Refresh it from the live backend when the backend contract changes.

## Backend Routes Used by the Frontend

- `GET /health`
- `GET /capabilities`
- `POST /chat`
- `POST /chat/stream`
- `GET /sessions`
- `GET /sessions/{session_id}/history`
- `POST /sessions/{session_id}/reset`
- `DELETE /sessions/{session_id}`
- `GET /debug/traces`
- `GET /debug/traces/{trace_id}`
- `POST /restart`

## Quick Start

1. Create a local env file from `.env.example` if you need custom settings.
2. Install dependencies:

   ```powershell
   .\.venv\Scripts\python.exe -m pip install -e .[dev]
   ```

3. Run the frontend:

   ```powershell
   .\.venv\Scripts\python.exe -m app.main
   ```

4. Open `http://127.0.0.1:5000/chat`.

## Test

```powershell
.\.venv\Scripts\python.exe -m pytest
```

This runs:

- Python unit tests for settings, backend client, proxy routes, pages, help content, headers, and the checked-in OpenAPI contract.
- Node-backed JavaScript module tests for the canonical files under `app/static/js/services/` plus the chat markdown renderer through the built-in `node --test` runner.

Node.js 24+ is required for the JavaScript module tests that are invoked from `pytest`.

## Static Asset Ownership

- Shared shell bootstrapping belongs in `app/static/js/core/`.
- Shared browser utilities belong in `app/static/js/common/` and `app/static/js/services/`.
- Page behavior belongs in `app/static/js/chat/`, `app/static/js/admin/`, and `app/static/js/help/`.
- Shared styles belong in `app/static/css/base/` and `app/static/css/components/`.
- Page styles belong in `app/static/css/pages/<page>/`.
- Keep `app/static/js/` and `app/static/css/` as directory-only roots so page-level flat files do not return.

## Implementation Checklist

- [DONE] Phase 0: Confirmed the frontend remains a thin UX/proxy layer.
- [DONE] Phase 0: Verified architecture inputs, live OpenAPI contract, and help-content source path.
- [DONE] Phase 0: Documented the backend routes the frontend will call.
- [DONE] Phase 0: Switched Bootstrap delivery to local vendored assets for CSP-safe development.
- [DONE] Phase 0: Chose Markdown-plus-sanitization as the future assistant/help rendering mode.
- [DONE] Phase 0: Configured `FRONTEND_HELP_MARKDOWN_PATH=../docs/Training_Readme.md`.
- [DONE] Phase 1: Added a Flask app factory, settings loader, page blueprint, security headers, error handlers, placeholder templates, and test coverage.
- [DONE] Phase 2 backend client and `/ui-api/*` proxy routes.
- [DONE] Phase 3 shared Bootstrap layout, theme, and navbar polish.
- [DONE] Phase 4 capabilities and health integration.
- [DONE] Phase 5 chat workspace shell.
- [DONE] Phase 6 session list, history loading, reset/delete actions, and new-chat handling.
- [DONE] Phase 7 non-streaming chat flow, inspector response metadata, retry action, and copy helpers.
- [DONE] Phase 8 streaming chat.
- [DONE] Phase 9 richer right-panel inspector details.
- [DONE] Phase 10 admin data workflows, trace search/detail, and gated restart confirmation.
- [DONE] Phase 11 help Markdown rendering, sanitization, TOC, search, and copy helpers.
- [DONE] Phase 12 responsive UX, keyboard accessibility, focus-managed drawers, live announcements, and accessible confirmations.
- [DONE] Phase 13 contract snapshot, Python/JavaScript test coverage, and manual QA checklist.

## Manual QA Checklist

- [DONE] Keyboard-only chat flow: tab through navbar, session rail, composer, send/stop, retry, and inspector actions without using a pointer.
- [DONE] Session rail keyboard support: use `ArrowUp`, `ArrowDown`, `Home`, and `End` to move between saved sessions.
- [DONE] Mobile/tablet drawer flow: open sessions and inspector drawers from the toolbar, verify focus lands inside, and close with `Escape`, backdrop click, or the close button.
- [DONE] Confirmation dialogs: verify reset/delete session and admin restart confirmations are reachable and operable with keyboard only.
- [DONE] Streaming announcements: verify screen readers receive start/stop/fallback/result announcements from the hidden live region without every token being announced.
- [DONE] Toasts and banners: verify warnings/errors are announced and also contain readable text beyond color cues.
- [DONE] Theme contrast: review both dark and light modes for readable pills, banners, buttons, and message cards.
- [DONE] Reduced motion: verify transitions/animations are effectively suppressed when `prefers-reduced-motion` is enabled.
- [DONE] Offline/error states: verify backend-offline, capabilities-unavailable, empty-session, retry, and truncated-history states remain readable on desktop and mobile.

## Bootstrap Asset Strategy

Phase 0 now vendors Bootstrap 5.3.3 under `app/static/vendor/bootstrap/` and serves those files directly so strict CSP policies do not trigger outbound sourcemap fetches.