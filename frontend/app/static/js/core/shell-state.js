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
  visualization: null,
  preferredChatMode: "request",
  frontendFlags: {
    adminEnabled: false,
    debugTracesEnabled: false,
    restartEnabled: false,
    environment: "local",
    testing: false,
    staticVersion: "local-dev",
    visualizationLimits: {
      maxArtifactsPerResponse: 3,
      maxRowsInline: 5000,
      maxSeries: 12,
      maxCategories: 100,
    },
  },
};

if (typeof window !== "undefined") {
  window.frontendShell = shellState;
}

function parseFlag(value) {
  return value === "true" || value === "1";
}

function parsePositiveInt(value, fallback) {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? Math.trunc(parsed) : fallback;
}

export function readFrontendFlags() {
  return {
    adminEnabled: parseFlag(document.body?.dataset.frontendAdminEnabled),
    debugTracesEnabled: parseFlag(document.body?.dataset.frontendDebugTracesEnabled),
    restartEnabled: parseFlag(document.body?.dataset.frontendRestartEnabled),
    environment: document.body?.dataset.frontendEnv || "local",
    testing: parseFlag(document.body?.dataset.frontendTesting),
    staticVersion: document.body?.dataset.frontendStaticVersion || "local-dev",
    visualizationLimits: {
      maxArtifactsPerResponse: parsePositiveInt(document.body?.dataset.frontendVisualizationMaxArtifacts, 3),
      maxRowsInline: parsePositiveInt(document.body?.dataset.frontendVisualizationMaxRowsInline, 5000),
      maxSeries: parsePositiveInt(document.body?.dataset.frontendVisualizationMaxSeries, 12),
      maxCategories: parsePositiveInt(document.body?.dataset.frontendVisualizationMaxCategories, 100),
    },
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