import { bindMobileNavigation } from "../common/navigation.js";
import { setBackendStatus } from "../common/status.js";
import { getJson } from "../services/api-client.js";
import {
  buildVisualizationCompatibilityWarning,
  resolveVisualizationCapabilityState,
  shouldRunVisualizationStartupCheck,
} from "../visualization/runtime-capabilities.js";
import {
  dispatchShellEvent,
  getShellState as getTrackedShellState,
  mapHealthStatus,
  readFrontendFlags,
} from "./shell-state.js";

const THEME_STORAGE_KEY = "pluggable-agentic-ai.theme";
const CAPABILITIES_CACHE_STORAGE_KEY = "pluggable-agentic-ai.capabilities.v1";
const CAPABILITIES_CACHE_TTL_MS = 5 * 60 * 1000;
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

function safeSessionStorage() {
  try {
    return window.sessionStorage;
  } catch (_error) {
    return null;
  }
}

function readCapabilitiesCache({ staticVersion, backendVersion = null } = {}) {
  const storage = safeSessionStorage();
  if (!storage) {
    return null;
  }

  try {
    const raw = storage.getItem(CAPABILITIES_CACHE_STORAGE_KEY);
    if (!raw) {
      return null;
    }

    const cached = JSON.parse(raw);
    if (!cached || typeof cached !== "object") {
      return null;
    }
    if (cached.staticVersion !== staticVersion) {
      return null;
    }
    if (!Number.isFinite(Number(cached.fetchedAt)) || (Date.now() - Number(cached.fetchedAt)) > CAPABILITIES_CACHE_TTL_MS) {
      return null;
    }
    if (backendVersion && cached.backendVersion && cached.backendVersion !== backendVersion) {
      return null;
    }
    return cached.payload ?? null;
  } catch (_error) {
    return null;
  }
}

function writeCapabilitiesCache(payload, { staticVersion, backendVersion = null } = {}) {
  const storage = safeSessionStorage();
  if (!storage || !payload) {
    return;
  }

  try {
    storage.setItem(CAPABILITIES_CACHE_STORAGE_KEY, JSON.stringify({
      staticVersion,
      backendVersion,
      fetchedAt: Date.now(),
      payload,
    }));
  } catch (_error) {
    return;
  }
}

async function settle(promise) {
  try {
    return { status: "fulfilled", value: await promise };
  } catch (error) {
    return { status: "rejected", reason: error };
  }
}

function updateVisualizationState(shellState) {
  shellState.visualization = resolveVisualizationCapabilityState(shellState.capabilities, {
    clientLimits: shellState.frontendFlags.visualizationLimits,
  });
  shellState.visualizationWarning = shouldRunVisualizationStartupCheck(shellState.frontendFlags)
    ? buildVisualizationCompatibilityWarning(shellState.visualization)
    : null;

  if (shellState.visualizationWarning) {
    console.warn(`[frontend-visualization] ${shellState.visualizationWarning}`);
  }
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

  const healthResult = await settle(getJson("/backend/health"));

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

  const backendVersion = healthResult.status === "fulfilled"
    ? healthResult.value?.version ?? null
    : null;
  const cachedCapabilities = readCapabilitiesCache({
    staticVersion: shellState.frontendFlags.staticVersion,
    backendVersion,
  });
  const capabilitiesResult = cachedCapabilities
    ? { status: "fulfilled", value: cachedCapabilities, source: "cache" }
    : await settle(getJson("/backend/capabilities"));

  if (capabilitiesResult.status === "fulfilled") {
    const capabilitiesPayload = capabilitiesResult.value;
    const capabilities = capabilitiesPayload?.data ?? null;
    shellState.capabilitiesPayload = capabilitiesPayload;
    shellState.capabilities = capabilities;
    updateVisualizationState(shellState);
    shellState.capabilitiesError = null;
    shellState.preferredChatMode = capabilities?.chat?.streaming_enabled ? "stream" : "request";
    if (!cachedCapabilities) {
      writeCapabilitiesCache(capabilitiesPayload, {
        staticVersion: shellState.frontendFlags.staticVersion,
        backendVersion,
      });
    }
  } else {
    shellState.capabilitiesPayload = null;
    shellState.capabilities = null;
    updateVisualizationState(shellState);
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