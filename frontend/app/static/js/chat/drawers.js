import { focusFirstDescendant, trapFocusWithin } from "../common/focus.js";
import { setPanelCollapsed } from "../services/session-store.js";

const DRAWER_BREAKPOINT = "(max-width: 1180px)";

export function bindDrawers(refs) {
  const drawers = {
    sessions: refs.sessionDrawer,
    inspector: refs.inspectorDrawer,
  };
  const mediaQuery = window.matchMedia(DRAWER_BREAKPOINT);
  let openDrawerName = null;
  let lastTrigger = null;

  function restoreFocus() {
    if (lastTrigger instanceof HTMLElement) {
      lastTrigger.focus();
    }
  }

  function syncPanelToggleVisibility() {
    if (!refs.statusBar) {
      return;
    }

    const shouldShowPanelButtons = mediaQuery.matches && openDrawerName === null;
    refs.statusBar.dataset.panelsVisible = String(shouldShowPanelButtons);
  }

  function applyLayoutState() {
    syncPanelToggleVisibility();

    if (!mediaQuery.matches) {
      openDrawerName = null;
      document.body.classList.remove("has-chat-drawer");
      if (refs.drawerBackdrop) {
        refs.drawerBackdrop.hidden = true;
      }
      Object.values(drawers).forEach((drawer) => {
        if (!drawer) {
          return;
        }
        drawer.hidden = false;
        drawer.classList.remove("is-open");
        drawer.setAttribute("aria-hidden", "false");
        drawer.removeAttribute("aria-modal");
        drawer.removeAttribute("role");
      });
      refs.openButtons.forEach((button) => {
        button.setAttribute("aria-expanded", "false");
      });
      setPanelCollapsed("sessionsCollapsed", false);
      setPanelCollapsed("inspectorCollapsed", false);
      return;
    }

    Object.entries(drawers).forEach(([name, drawer]) => {
      if (!drawer) {
        return;
      }
      const isOpen = openDrawerName === name;
      drawer.hidden = !isOpen;
      drawer.classList.toggle("is-open", isOpen);
      drawer.setAttribute("aria-hidden", String(!isOpen));
      if (isOpen) {
        drawer.setAttribute("aria-modal", "true");
        drawer.setAttribute("role", "dialog");
      } else {
        drawer.removeAttribute("aria-modal");
        drawer.removeAttribute("role");
      }
    });

    setPanelCollapsed("sessionsCollapsed", openDrawerName !== "sessions");
    setPanelCollapsed("inspectorCollapsed", openDrawerName !== "inspector");

    if (refs.drawerBackdrop) {
      refs.drawerBackdrop.hidden = openDrawerName === null;
    }
    document.body.classList.toggle("has-chat-drawer", openDrawerName !== null);
    refs.openButtons.forEach((button) => {
      button.setAttribute("aria-expanded", String(button.dataset.chatPanelOpen === openDrawerName));
    });
  }

  function closeDrawer({ restore = true } = {}) {
    const hadOpenDrawer = openDrawerName !== null;
    openDrawerName = null;
    applyLayoutState();
    if (hadOpenDrawer && restore) {
      restoreFocus();
    }
  }

  function openDrawer(name, trigger) {
    if (!mediaQuery.matches) {
      return;
    }

    lastTrigger = trigger instanceof HTMLElement
      ? trigger
      : document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    openDrawerName = name;
    applyLayoutState();

    const activeDrawer = name ? drawers[name] : null;
    window.requestAnimationFrame(() => {
      if (activeDrawer) {
        focusFirstDescendant(activeDrawer);
      }
    });
  }

  refs.openButtons.forEach((button) => {
    button.addEventListener("click", () => {
      if (!mediaQuery.matches) {
        return;
      }

      const drawerName = button.dataset.chatPanelOpen || null;
      if (drawerName && openDrawerName === drawerName) {
        closeDrawer();
        return;
      }

      openDrawer(drawerName, button);
    });
  });

  refs.closeButtons.forEach((button) => {
    button.addEventListener("click", () => {
      closeDrawer();
    });
  });

  refs.drawerBackdrop?.addEventListener("click", () => {
    closeDrawer();
  });

  document.addEventListener("keydown", (event) => {
    if (!mediaQuery.matches || openDrawerName === null) {
      return;
    }

    if (event.key === "Escape") {
      event.preventDefault();
      closeDrawer();
      return;
    }

    const activeDrawer = openDrawerName ? drawers[openDrawerName] : null;
    if (activeDrawer) {
      trapFocusWithin(activeDrawer, event);
    }
  });

  if (typeof mediaQuery.addEventListener === "function") {
    mediaQuery.addEventListener("change", applyLayoutState);
  } else {
    mediaQuery.addListener(applyLayoutState);
  }

  applyLayoutState();
}