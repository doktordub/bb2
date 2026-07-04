import { bindMobileNavigation } from "../common/navigation.js";
import { setBackendStatus } from "../common/status.js";
import { getJson } from "../services/api-client.js";
import {
  dispatchShellEvent,
  getShellState as getTrackedShellState,
  mapHealthStatus,
  readFrontendFlags,
} from "./shell-state.js";

const THEME_STORAGE_KEY = "pluggable-agentic-ai.theme";
const THEMES = ["auto", "dark", "light"];

let shellReadyPromise = null;

function updateThemeLabels(themeMode) {
  document.querySelectorAll("[data-theme-label]").forEach((element) => {
    element.textContent = `Theme: ${themeMode.charAt(0).toUpperCase()}${themeMode.slice(1)}`;
  });
}

function applyThemePreference(themeMode) {
  if (themeMode === "auto") {
    delete document.documentElement.dataset.theme;
  } else {
    document.documentElement.dataset.theme = themeMode;
  }

  document.documentElement.dataset.themePreference = themeMode;
  updateThemeLabels(themeMode);
  return themeMode;
}

function persistThemePreference(themeMode) {
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, themeMode);
  } catch (_error) {
    return;
  }
}

function loadStoredThemePreference() {
  try {
    return window.localStorage.getItem(THEME_STORAGE_KEY) || "auto";
  } catch (_error) {
    return "auto";
  }
}

function applyStoredThemePreference() {
  return applyThemePreference(loadStoredThemePreference());
}

function bindThemeCycleButton(onChange) {
  document.querySelectorAll("[data-theme-cycle-button]").forEach((button) => {
    button.addEventListener("click", () => {
      const current = document.documentElement.dataset.themePreference || "auto";
      const currentIndex = THEMES.indexOf(current);
      const nextTheme = THEMES[(currentIndex + 1 + THEMES.length) % THEMES.length];
      persistThemePreference(nextTheme);
      applyThemePreference(nextTheme);
      if (typeof onChange === "function") {
        onChange(nextTheme);
      }
    });
  });
}

function whenDocumentReady() {
  if (document.readyState === "loading") {
    return new Promise((resolve) => {
      document.addEventListener("DOMContentLoaded", resolve, { once: true });
    });
  }

  return Promise.resolve();
}

async function initializeShell() {
  const shellState = getTrackedShellState();

  shellState.frontendFlags = readFrontendFlags();
  shellState.themeMode = applyStoredThemePreference();
  bindThemeCycleButton((themeMode) => {
    shellState.themeMode = themeMode;
  });
  bindMobileNavigation();
  setBackendStatus("checking", "Checking");

  const [healthResult, capabilitiesResult] = await Promise.allSettled([
    getJson("/backend/health"),
    getJson("/backend/capabilities"),
  ]);

  if (healthResult.status === "fulfilled") {
    const healthPayload = healthResult.value;
    const mapped = mapHealthStatus(healthPayload);
    shellState.backendStatus = mapped.state;
    shellState.healthPayload = healthPayload;
    shellState.healthError = null;
    setBackendStatus(mapped.state, mapped.label);
  } else {
    shellState.healthPayload = null;
    shellState.healthError = healthResult.reason;
    shellState.backendStatus = "offline";
    setBackendStatus("offline", "Offline");
  }

  if (capabilitiesResult.status === "fulfilled") {
    const capabilitiesPayload = capabilitiesResult.value;
    const capabilities = capabilitiesPayload?.data ?? null;
    shellState.capabilitiesPayload = capabilitiesPayload;
    shellState.capabilities = capabilities;
    shellState.capabilitiesError = null;
    shellState.preferredChatMode = capabilities?.chat?.streaming_enabled ? "stream" : "request";
  } else {
    shellState.capabilitiesPayload = null;
    shellState.capabilities = null;
    shellState.capabilitiesError = capabilitiesResult.reason;
    shellState.preferredChatMode = "request";
  }

  shellState.ready = true;
  document.body.dataset.appReady = "true";
  document.body.dataset.backendStatus = shellState.backendStatus;
  document.body.dataset.preferredChatMode = shellState.preferredChatMode;
  dispatchShellEvent("frontend-shell-ready");
  dispatchShellEvent("frontend-shell-updated");
}

function ensureShellReady() {
  if (!shellReadyPromise) {
    shellReadyPromise = whenDocumentReady().then(() => initializeShell());
  }

  return shellReadyPromise;
}

export function waitForShellReady() {
  return ensureShellReady().then(() => getTrackedShellState());
}

export function getShellState() {
  return getTrackedShellState();
}

void ensureShellReady();

export { mapHealthStatus };