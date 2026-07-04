function assistiveTonePrefix(tone) {
  if (tone === "error") {
    return "Error: ";
  }
  if (tone === "warning") {
    return "Warning: ";
  }
  return "Notice: ";
}

export function showToast(message, { tone = "info", timeout = 4000 } = {}) {
  const container = document.getElementById("toast-container");
  if (!container) {
    return;
  }

  const toast = document.createElement("div");
  toast.className = `toast-message toast-message--${tone}`;
  toast.setAttribute("role", tone === "error" ? "alert" : "status");
  toast.setAttribute("aria-live", tone === "error" ? "assertive" : "polite");
  toast.setAttribute("aria-atomic", "true");

  const assistivePrefix = document.createElement("span");
  assistivePrefix.className = "visually-hidden";
  assistivePrefix.textContent = assistiveTonePrefix(tone);

  const body = document.createElement("span");
  body.textContent = message;

  toast.append(assistivePrefix, body);
  container.appendChild(toast);

  window.setTimeout(() => {
    toast.remove();
  }, timeout);
}