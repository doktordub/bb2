const STATE_PILL_TONES = [
  "online",
  "degraded",
  "offline",
  "unknown",
  "checking",
  "disabled",
  "available",
  "info",
];

export function setBackendStatus(state, label) {
  document.querySelectorAll("[data-backend-status-chip]").forEach((chip) => {
    chip.classList.remove(
      "status-chip--online",
      "status-chip--degraded",
      "status-chip--offline",
      "status-chip--unknown",
      "status-chip--checking"
    );
    chip.classList.add(`status-chip--${state}`);

    const textNode = chip.querySelector("[data-status-text]");
    if (textNode) {
      textNode.textContent = label;
    }
  });
}

export function setStatePill(element, label, tone = "unknown") {
  if (!element) {
    return;
  }

  element.classList.add("state-pill");
  STATE_PILL_TONES.forEach((value) => {
    element.classList.remove(`state-pill--${value}`);
  });
  element.classList.add(`state-pill--${tone}`);
  element.textContent = label;
}