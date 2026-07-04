# Frontend Static Cleanup Plan

## Current State Review

The current frontend asset layout is functional, but it is now too flat and too page-heavy for the size of the UI surface.

| Current asset | Size | Lines | Review note |
| --- | ---: | ---: | --- |
| `frontend/app/static/js/chat-page.js` | 80.4 KB | 1885 | Largest refactor target. Owns refs, state, formatting helpers, session rail, history loading, request/response flow, streaming flow, drawer behavior, retry flow, and inspector rendering in one file. |
| `frontend/app/static/js/admin-page.js` | 31.6 KB | 696 | Still too large. Mixes refs, tab state, health/capabilities rendering, trace search/detail, restart flow, and formatting helpers. |
| `frontend/app/static/css/chat.css` | 18.5 KB | 819 | Mixes chat status bar, session rail, conversation thread, message cards, composer, inspector, drawers, and responsive rules. |
| `frontend/app/static/css/app.css` | 18.0 KB | 798 | Shared shell file is too broad. It contains the app shell, nav, buttons, cards, status banners, dialogs, workspace layout, and at least some help-specific leakage. |
| `frontend/app/static/js/ui-components.js` | 7.3 KB | 234 | Useful shared file, but still too broad. Theme, focus trap, toast, status chip updates, and mobile nav should not live together forever. |

Additional review findings:

- `frontend/app/static/css/` and `frontend/app/static/js/` are still flat top-level folders. Shared assets and page assets are mixed together.
- Common JavaScript helpers are duplicated across page files, especially `setBannerState`, `setText`, `boolLabel`, `formatDate`, `formatDuration`, and `copyText`.
- `frontend/app/static/js/chat-page.js` and `frontend/app/static/js/admin-page.js` both maintain very large DOM ref maps, which is a sign that page modules need local submodules.
- `frontend/app/static/css/app.css` is mostly shared shell styling, but it also contains help-specific selectors such as `.help-card` and `.help-note`, which should live in help page styles instead of the shared shell layer.
- Templates still point at flat asset names:
  - `frontend/app/templates/base.html` loads `css/theme.css`, `css/app.css`, and `js/app.js`.
  - `frontend/app/templates/chat.html` loads `css/chat.css` and `js/chat-page.js`.
  - `frontend/app/templates/admin.html` loads `css/admin.css` and `js/admin-page.js`.
  - `frontend/app/templates/help.html` loads `css/help.css` and `js/help-page.js`.

## Refactor Goals

- Split large CSS and JavaScript files by ownership, not arbitrarily by line count.
- Move shared browser utilities into shared JavaScript modules.
- Move shared visual primitives into shared CSS modules.
- Keep page templates simple by giving each page one CSS manifest and one JavaScript entrypoint.
- Preserve current backend routes, `data-*` contracts, and page behavior while the asset structure changes.
- Keep new files small enough to stay readable without scrolling through unrelated concerns.

Recommended guardrails for the refactor:

- Shared or feature modules should generally stay under 250 lines of JavaScript.
- Shared or feature CSS modules should generally stay under 200 lines.
- Manifest and entrypoint files may be smaller pass-through files that only import submodules.
- Do not split already-small single-purpose files just for symmetry. Keep `api-client.js`, `sse-client.js`, and `chat-markdown.js` focused unless a clear shared concern emerges.

## Target Asset Structure

```text
frontend/app/static/
  css/
    base/
      index.css
      theme.css
      shell.css
      typography.css
    components/
      index.css
      buttons.css
      cards.css
      dialogs.css
      forms.css
      nav.css
      status.css
      workspace.css
    pages/
      chat/
        index.css
        status-bar.css
        session-rail.css
        conversation.css
        composer.css
        inspector.css
        drawers.css
        responsive.css
      admin/
        index.css
        status-bar.css
        tabs.css
        cards.css
        traces.css
        dialogs.css
      help/
        index.css
        toolbar.css
        toc.css
        content.css
  js/
    core/
      app-shell.js
      shell-state.js
    common/
      banner.js
      clipboard.js
      dom.js
      focus.js
      formatters.js
      navigation.js
      status.js
      toast.js
    services/
      api-client.js
      session-store.js
      sse-client.js
    chat/
      index.js
      refs.js
      runtime-state.js
      conversation.js
      sessions.js
      inspector.js
      composer.js
      requests.js
      drawers.js
    admin/
      index.js
      refs.js
      tabs.js
      health.js
      capabilities.js
      traces.js
      restart.js
    help/
      index.js
      decorators.js
      search.js
      scrollspy.js
```

Notes on the target layout:

- Keep `frontend/app/static/vendor/` unchanged.
- Keep `frontend/app/static/img/` unchanged unless the image count grows enough to justify feature folders.
- Use CSS manifest files such as `pages/chat/index.css` to gather smaller CSS slices behind one template reference. If a build step is introduced later, those manifests can be replaced by bundling without changing page ownership.
- Use one JavaScript entrypoint per page. The entrypoint should only wire imports and call `initialize...Page()`.

## Template Reference Changes

| Template | Current refs | Planned refs |
| --- | --- | --- |
| `frontend/app/templates/base.html` | `css/theme.css`, `css/app.css`, `js/app.js` | `css/base/index.css`, `css/components/index.css`, `js/core/app-shell.js` |
| `frontend/app/templates/chat.html` | `css/chat.css`, `js/chat-page.js` | `css/pages/chat/index.css`, `js/chat/index.js` |
| `frontend/app/templates/admin.html` | `css/admin.css`, `js/admin-page.js` | `css/pages/admin/index.css`, `js/admin/index.js` |
| `frontend/app/templates/help.html` | `css/help.css`, `js/help-page.js` | `css/pages/help/index.css`, `js/help/index.js` |

The base template should keep loading Bootstrap from `frontend/app/static/vendor/bootstrap/`. This cleanup is about ownership and organization, not replacing the current vendor strategy.

## Phase 1: Shared Foundations First [DONE]

Goal: create the folder structure and extract shared shell concerns before touching the largest page modules.

Work:

- [DONE] Create the new `css/base/`, `css/components/`, `css/pages/`, `js/core/`, `js/common/`, `js/services/`, and page-specific folders.
- [DONE] Move the shell bootstrap logic from `frontend/app/static/js/app.js` into `js/core/app-shell.js` and keep `waitForShellReady()` as the public API for page entrypoints.
- [DONE] Split `frontend/app/static/js/ui-components.js` into smaller shared modules:
  - [DONE] `common/focus.js`
  - [DONE] `common/toast.js`
  - [DONE] `common/status.js`
  - [DONE] `common/navigation.js`
  - [DONE] `common/dom.js` for simple text/setter helpers
  - [DONE] `common/banner.js` for banner state management
  - [DONE] `common/formatters.js` for shared date, duration, and boolean labels
  - [DONE] `common/clipboard.js` for copy helpers
- [DONE] Split `frontend/app/static/css/app.css` into shared layers:
  - [DONE] base shell and typography
  - [DONE] buttons/forms
  - [DONE] cards/panels
  - [DONE] nav/mobile nav
  - [DONE] banners/status pills
  - [DONE] dialogs/workspace layout
- [DONE] Move `.help-card` and `.help-note` out of shared CSS and into help page CSS.
- [DONE] Update `frontend/app/templates/base.html` to reference the new shared CSS and JS entrypoints.

Why first:

- This removes duplication before chat and admin are split.
- It keeps page refactors focused on page logic instead of redoing shared helpers more than once.

Validation:

- [DONE] `frontend/.venv/Scripts/python.exe -m pytest tests/test_pages.py tests/test_security_headers.py tests/test_frontend_js.py`

## Phase 2: Decompose Chat JavaScript [DONE]

Goal: turn `frontend/app/static/js/chat-page.js` into a small entrypoint backed by focused chat modules.

Work:

- [DONE] Create `frontend/app/static/js/chat/index.js` as the only chat template entrypoint.
- [DONE] Split current chat responsibilities into focused modules:
  - [DONE] `refs.js` for DOM queries only
  - [DONE] `runtime-state.js` for page state creation and mutation helpers
  - [DONE] `conversation.js` for message card rendering, thread visibility, counters, and markdown replacement
  - [DONE] `sessions.js` for session rail rendering, load/reset/delete/new-chat actions, and history loading
  - [DONE] `inspector.js` for inspector state, trace summary, tool summaries, and capability summaries
  - [DONE] `composer.js` for form wiring, validation, send/stop, and composer pin behavior
  - [DONE] `requests.js` for request/response and streaming orchestration
  - [DONE] `drawers.js` for responsive panel drawer behavior and focus management
- [DONE] Move duplicated helpers such as banner setters, text setters, formatting, and clipboard copy into the shared modules created in Phase 1.
- [DONE] Keep `chat-markdown.js` separate, then decide later whether it belongs in `js/common/` or should remain chat-owned.
- [DONE] Update `frontend/app/templates/chat.html` to reference `js/chat/index.js`.

Specific design rule for this phase:

- `index.js` should read like wiring code only. If it starts growing beyond basic initialization, the split did not go far enough.

Validation:

- [DONE] `frontend/.venv/Scripts/python.exe -m pytest tests/test_pages.py tests/test_proxy_routes.py tests/test_frontend_js.py`
- Manual chat smoke check for send, stop, retry, copy, session switch, delete, reset, and mobile drawers.

## Phase 3: Decompose Chat CSS [DONE]

Goal: split `frontend/app/static/css/chat.css` by visual ownership so chat layout changes stop colliding with every other chat concern.

Work:

- [DONE] Create `frontend/app/static/css/pages/chat/index.css` as the chat manifest.
- [DONE] Split chat CSS into focused files:
  - [DONE] `status-bar.css`
  - [DONE] `session-rail.css`
  - [DONE] `conversation.css`
  - [DONE] `composer.css`
  - [DONE] `inspector.css`
  - [DONE] `drawers.css`
  - [DONE] `responsive.css`
- [DONE] Keep shared primitives such as `.state-pill`, `.status-banner`, `.btn-shell`, `.info-card`, `.panel`, and `.workspace-status-bar` in the shared component layer created in Phase 1.
- [DONE] Keep chat-specific selectors in chat page CSS only. That includes session rail rows, conversation placeholders, message bubbles, composer shell, inspector cards, and drawer breakpoints.
- [DONE] Update `frontend/app/templates/chat.html` to reference `css/pages/chat/index.css`.

Validation:

- [DONE] `frontend/.venv/Scripts/python.exe -m pytest tests/test_pages.py`
- [DONE] Responsive browser smoke for pinned composer, desktop layout, tablet drawer mode, and mobile stacking.

## Phase 4: Decompose Admin and Help Assets [DONE]

Goal: finish the remaining page entrypoints and remove the last flat page-level files.

Work on admin assets:

- [DONE] Replace `frontend/app/static/js/admin-page.js` with `frontend/app/static/js/admin/index.js` plus focused admin modules:
  - [DONE] `refs.js`
  - [DONE] `tabs.js`
  - [DONE] `health.js`
  - [DONE] `capabilities.js`
  - [DONE] `traces.js`
  - [DONE] `restart.js`
- [DONE] Extract shared formatting, banner, and clipboard logic into the common layer instead of copying it again.
- [DONE] Replace `frontend/app/static/css/admin.css` with `frontend/app/static/css/pages/admin/index.css` plus status bar, tabs, trace, card, and dialog slices.
- [DONE] Update `frontend/app/templates/admin.html` to reference the admin page manifests.

Work on help assets:

- [DONE] Replace `frontend/app/static/js/help-page.js` with `frontend/app/static/js/help/index.js` and focused helpers for decorators, search, and scrollspy.
- [DONE] Use the shared clipboard helper instead of keeping a page-local copy helper.
- [DONE] Replace `frontend/app/static/css/help.css` with `frontend/app/static/css/pages/help/index.css` plus toolbar, TOC, and content slices.
- [DONE] Update `frontend/app/templates/help.html` to reference the help page manifests.

Validation:

- [DONE] `frontend/.venv/Scripts/python.exe -m pytest tests/test_pages.py tests/test_help_content.py tests/test_proxy_routes.py tests/test_frontend_js.py`
- Manual admin smoke check for tab switching, trace search/detail, JSON copy, and restart confirmation.
- [DONE] Manual help smoke check for heading link copy, code copy, search, and TOC scrollspy.

## Phase 5: Remove Legacy Flat Files and Add Guardrails [DONE]

Goal: finish the migration cleanly and keep the asset tree from drifting back into large flat files.

Work:

- [DONE] Delete legacy flat page assets only after all templates point at the new locations and imports are stable:
  - [DONE] `frontend/app/static/js/chat-page.js`
  - [DONE] `frontend/app/static/js/admin-page.js`
  - [DONE] `frontend/app/static/js/help-page.js`
  - [DONE] `frontend/app/static/css/chat.css`
  - [DONE] `frontend/app/static/css/admin.css`
  - [DONE] `frontend/app/static/css/help.css`
  - [DONE] Removed leftover compatibility shims that were no longer needed, including the flat `app.js`, `ui-components.js`, `api-client.js`, `sse-client.js`, `session-store.js`, `chat-markdown.js`, `app.css`, and `theme.css` wrappers.
- [DONE] Review for leftover duplicated helpers after migration. Shared banner, DOM, formatter, and clipboard helpers remain centralized under `frontend/app/static/js/common/`.
- [DONE] Add a short asset ownership note to the frontend README so new work lands in the right folder.
- [DONE] Add a simple pytest guard that fails if legacy flat assets or new top-level static files reappear.

Validation:

- [DONE] `frontend/.venv/Scripts/python.exe -m pytest`

## Recommended Execution Order

1. Shared foundations
2. Chat JavaScript
3. Chat CSS
4. Admin and help assets
5. Legacy file removal and guardrails

This order minimizes churn because the largest page, chat, benefits most from shared helpers being extracted first.

## Success Criteria

- No template points at the old flat page-level asset names.
- Shared helpers exist only once.
- Shared shell CSS contains only shared shell concerns.
- Chat, admin, and help entrypoints are small wiring files instead of implementation dumps.
- Refactor-only changes pass the existing frontend tests and preserve current page behavior.