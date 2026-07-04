const shellState = {
  ready: false,
  phase: "phase-5",
  themeMode: "auto",
  backendStatus: "unknown",
  healthPayload: null,
  healthError: null,
  capabilitiesPayload: null,
  capabilities: null,
  capabilitiesError: null,
  preferredChatMode: "request",
  frontendFlags: {
    adminEnabled: false,
    debugTracesEnabled: false,
    restartEnabled: false,
  },
};

if (typeof window !== "undefined") {
  window.frontendShell = shellState;
}

function parseFlag(value) {
  return value === "true" || value === "1";
}

export function readFrontendFlags() {
  return {
    adminEnabled: parseFlag(document.body?.dataset.frontendAdminEnabled),
    debugTracesEnabled: parseFlag(document.body?.dataset.frontendDebugTracesEnabled),
    restartEnabled: parseFlag(document.body?.dataset.frontendRestartEnabled),
  };
}

export function dispatchShellEvent(name) {
  if (typeof window === "undefined") {
    return;
  }

  window.dispatchEvent(new CustomEvent(name, { detail: shellState }));
}

export function mapHealthStatus(payload) {
  const rawStatus = String(payload?.status ?? "unknown").toLowerCase();

  if (["healthy", "ok", "up", "online"].includes(rawStatus)) {
    return { state: "online", label: "Online" };
  }

  if (["degraded", "warn", "warning", "partial"].includes(rawStatus)) {
    return { state: "degraded", label: "Degraded" };
  }

  if (["offline", "down", "error", "failed", "unhealthy"].includes(rawStatus)) {
    return { state: "offline", label: "Offline" };
  }

  return { state: "unknown", label: "Unknown" };
}

export function getShellState() {
  return shellState;
}