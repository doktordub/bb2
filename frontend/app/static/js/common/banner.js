const BANNER_TONES = ["status-banner--warning", "status-banner--error", "status-banner--info"];

export function setBannerState(
  section,
  titleElement,
  bodyElement,
  { hidden = false, tone = "warning", title = "", body = "" } = {}
) {
  if (!section) {
    return;
  }

  section.hidden = hidden;
  section.setAttribute("aria-hidden", String(hidden));
  section.classList.remove(...BANNER_TONES);
  section.classList.add(`status-banner--${tone}`);

  if (hidden) {
    section.removeAttribute("role");
    section.removeAttribute("aria-live");
  } else {
    section.setAttribute("role", tone === "error" ? "alert" : "status");
    section.setAttribute("aria-live", tone === "error" ? "assertive" : "polite");
  }

  if (titleElement) {
    titleElement.textContent = title;
  }
  if (bodyElement) {
    bodyElement.textContent = body;
  }
}