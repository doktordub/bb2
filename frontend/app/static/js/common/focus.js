const FOCUSABLE_SELECTORS = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[tabindex]:not([tabindex='-1'])",
].join(", ");

export function getFocusableElements(container) {
  if (!(container instanceof HTMLElement)) {
    return [];
  }

  return Array.from(container.querySelectorAll(FOCUSABLE_SELECTORS)).filter(
    (element) => element instanceof HTMLElement
  );
}

export function focusFirstDescendant(container) {
  if (!(container instanceof HTMLElement)) {
    return false;
  }

  const [first] = getFocusableElements(container);
  if (first) {
    first.focus();
    return true;
  }

  if (!container.hasAttribute("tabindex")) {
    container.setAttribute("tabindex", "-1");
  }
  container.focus();
  return true;
}

export function trapFocusWithin(container, event) {
  if (!(container instanceof HTMLElement) || event.key !== "Tab") {
    return;
  }

  const focusableElements = getFocusableElements(container);
  if (focusableElements.length === 0) {
    event.preventDefault();
    focusFirstDescendant(container);
    return;
  }

  const first = focusableElements[0];
  const last = focusableElements[focusableElements.length - 1];
  const activeElement = document.activeElement;

  if (!container.contains(activeElement)) {
    event.preventDefault();
    first.focus();
    return;
  }

  if (event.shiftKey && activeElement === first) {
    event.preventDefault();
    last.focus();
    return;
  }

  if (!event.shiftKey && activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}