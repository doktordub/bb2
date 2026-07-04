import { focusFirstDescendant, trapFocusWithin } from "./focus.js";

export function bindMobileNavigation() {
  const toggleButton = document.querySelector("[data-mobile-nav-toggle]");
  const dismissButtons = document.querySelectorAll("[data-mobile-nav-dismiss]");
  const backdrop = document.querySelector("[data-mobile-nav-backdrop]");
  const panel = document.querySelector("[data-mobile-nav-panel]");

  if (!toggleButton || !backdrop || !panel) {
    return;
  }

  let lastTrigger = null;

  if (!panel.hasAttribute("tabindex")) {
    panel.setAttribute("tabindex", "-1");
  }

  const close = ({ restoreFocus = true } = {}) => {
    panel.hidden = true;
    backdrop.hidden = true;
    document.body.classList.remove("has-modal-nav");
    toggleButton.setAttribute("aria-expanded", "false");
    panel.setAttribute("aria-hidden", "true");
    panel.removeAttribute("aria-modal");
    panel.removeAttribute("role");

    if (restoreFocus && lastTrigger instanceof HTMLElement) {
      lastTrigger.focus();
    }
  };

  const open = () => {
    lastTrigger = document.activeElement instanceof HTMLElement ? document.activeElement : toggleButton;
    panel.hidden = false;
    backdrop.hidden = false;
    document.body.classList.add("has-modal-nav");
    toggleButton.setAttribute("aria-expanded", "true");
    panel.setAttribute("aria-hidden", "false");
    panel.setAttribute("aria-modal", "true");
    panel.setAttribute("role", "dialog");

    window.requestAnimationFrame(() => {
      focusFirstDescendant(panel);
    });
  };

  toggleButton.addEventListener("click", () => {
    if (panel.hidden) {
      open();
      return;
    }

    close();
  });

  backdrop.addEventListener("click", close);
  dismissButtons.forEach((button) => {
    button.addEventListener("click", close);
  });

  document.addEventListener("keydown", (event) => {
    if (panel.hidden) {
      return;
    }

    if (event.key === "Escape") {
      close();
      return;
    }

    trapFocusWithin(panel, event);
  });

  close({ restoreFocus: false });
}