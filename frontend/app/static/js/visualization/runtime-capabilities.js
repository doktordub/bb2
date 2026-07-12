import { VISUALIZATION_RENDERER, VISUALIZATION_SPEC_VERSION } from "./artifact-model.js";
import { ChartRegistry } from "./chart-registry.js";
import { registerBaseEChartsAdapters } from "./echarts-adapter.js";

export const DEFAULT_FRONTEND_VISUALIZATION_LIMITS = Object.freeze({
  maxArtifactsPerResponse: 3,
  maxRowsInline: 5000,
  maxSeries: 12,
  maxCategories: 100,
});

const STARTUP_CHECK_ENVIRONMENTS = new Set(["local", "development", "dev", "test", "testing"]);

function toPositiveInteger(value, fallback) {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? Math.trunc(parsed) : fallback;
}

function normalizeString(value) {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function normalizeStringList(values) {
  if (!Array.isArray(values)) {
    return [];
  }

  return Array.from(new Set(
    values
      .map((value) => normalizeString(value))
      .filter(Boolean)
  ));
}

function buildRegistry(registry = null) {
  return registry || registerBaseEChartsAdapters(new ChartRegistry());
}

function normalizeClientLimits(clientLimits = {}) {
  return {
    maxArtifactsPerResponse: toPositiveInteger(
      clientLimits.maxArtifactsPerResponse,
      DEFAULT_FRONTEND_VISUALIZATION_LIMITS.maxArtifactsPerResponse
    ),
    maxRowsInline: toPositiveInteger(
      clientLimits.maxRowsInline,
      DEFAULT_FRONTEND_VISUALIZATION_LIMITS.maxRowsInline
    ),
    maxSeries: toPositiveInteger(
      clientLimits.maxSeries,
      DEFAULT_FRONTEND_VISUALIZATION_LIMITS.maxSeries
    ),
    maxCategories: toPositiveInteger(
      clientLimits.maxCategories,
      DEFAULT_FRONTEND_VISUALIZATION_LIMITS.maxCategories
    ),
  };
}

function buildEffectiveLimits(clientLimits, backendLimits = {}) {
  const resolvedClientLimits = normalizeClientLimits(clientLimits);
  return {
    maxArtifactsPerResponse: Math.min(
      resolvedClientLimits.maxArtifactsPerResponse,
      toPositiveInteger(
        backendLimits.max_artifacts_per_response,
        resolvedClientLimits.maxArtifactsPerResponse
      )
    ),
    maxRowsInline: Math.min(
      resolvedClientLimits.maxRowsInline,
      toPositiveInteger(backendLimits.max_rows_inline, resolvedClientLimits.maxRowsInline)
    ),
    maxSeries: Math.min(
      resolvedClientLimits.maxSeries,
      toPositiveInteger(backendLimits.max_series, resolvedClientLimits.maxSeries)
    ),
    maxCategories: Math.min(
      resolvedClientLimits.maxCategories,
      toPositiveInteger(backendLimits.max_categories, resolvedClientLimits.maxCategories)
    ),
  };
}

export function buildFrontendVisualizationProfile({ registry = null } = {}) {
  const resolvedRegistry = buildRegistry(registry);
  const implementedChartTypes = resolvedRegistry
    .listSupported()
    .filter(
      (entry) => entry.renderer === VISUALIZATION_RENDERER && entry.specVersion === VISUALIZATION_SPEC_VERSION
    )
    .map((entry) => entry.chartType)
    .sort();

  return Object.freeze({
    renderer: VISUALIZATION_RENDERER,
    specVersion: VISUALIZATION_SPEC_VERSION,
    implementedChartTypes,
    referenceModeSupported: true,
  });
}

export function resolveVisualizationCapabilityState(
  capabilities,
  { registry = null, clientLimits = {} } = {}
) {
  const frontend = buildFrontendVisualizationProfile({ registry });
  const rawVisualization = capabilities?.visualization && typeof capabilities.visualization === "object"
    ? capabilities.visualization
    : null;

  if (!rawVisualization) {
    return Object.freeze({
      source: "local",
      backendAdvertised: false,
      backendEnabled: null,
      enabled: true,
      renderer: frontend.renderer,
      specVersion: frontend.specVersion,
      backendRenderer: null,
      backendSpecVersion: null,
      frontendImplementedChartTypes: frontend.implementedChartTypes,
      backendSupportedChartTypes: [],
      intersectedChartTypes: frontend.implementedChartTypes,
      unsupportedBackendChartTypes: [],
      unadvertisedFrontendChartTypes: [],
      rendererCompatible: true,
      specCompatible: true,
      contextSummaryMode: "unknown",
      backendReferenceModeSupported: null,
      backendReferenceModeEnabled: null,
      referenceModeSupported: frontend.referenceModeSupported,
      referenceModeEnabled: frontend.referenceModeSupported,
      limits: buildEffectiveLimits(clientLimits),
      mismatches: [],
    });
  }

  const backendRenderer = normalizeString(rawVisualization.default_renderer);
  const backendSpecVersion = normalizeString(rawVisualization.spec_version);
  const backendSupportedChartTypes = normalizeStringList(rawVisualization.supported_chart_types);
  const backendAllowedRenderers = normalizeStringList(rawVisualization.allowed_renderers);
  const backendEnabled = Boolean(rawVisualization.enabled);
  const rendererCompatible = !backendEnabled
    || backendRenderer === frontend.renderer
    || (!backendRenderer && (!backendAllowedRenderers.length || backendAllowedRenderers.includes(frontend.renderer)));
  const specCompatible = !backendEnabled || !backendSpecVersion || backendSpecVersion === frontend.specVersion;
  const intersectedChartTypes = backendSupportedChartTypes.filter((chartType) => frontend.implementedChartTypes.includes(chartType));
  const unsupportedBackendChartTypes = backendSupportedChartTypes.filter((chartType) => !frontend.implementedChartTypes.includes(chartType));
  const unadvertisedFrontendChartTypes = frontend.implementedChartTypes.filter(
    (chartType) => !backendSupportedChartTypes.includes(chartType)
  );
  const backendReferenceModeSupported = Boolean(rawVisualization.reference_mode_supported);
  const backendReferenceModeEnabled = Boolean(rawVisualization.reference_mode_enabled);
  const referenceModeSupported = frontend.referenceModeSupported && backendReferenceModeSupported;
  const referenceModeEnabled = referenceModeSupported && backendReferenceModeEnabled;
  const mismatches = [];

  if (backendEnabled && !rendererCompatible) {
    mismatches.push(
      `Renderer mismatch: backend advertises ${backendRenderer || "an unknown renderer"} while the frontend is pinned to ${frontend.renderer}.`
    );
  }
  if (backendEnabled && !specCompatible) {
    mismatches.push(
      `Spec mismatch: backend advertises ${backendSpecVersion || "an unknown spec"} while the frontend supports ${frontend.specVersion}.`
    );
  }
  if (backendEnabled && unsupportedBackendChartTypes.length > 0) {
    mismatches.push(
      `Backend-only chart types: ${unsupportedBackendChartTypes.join(", ")}.`
    );
  }

  return Object.freeze({
    source: "capabilities",
    backendAdvertised: true,
    backendEnabled,
    enabled: backendEnabled && rendererCompatible && specCompatible && intersectedChartTypes.length > 0,
    renderer: frontend.renderer,
    specVersion: frontend.specVersion,
    backendRenderer,
    backendSpecVersion,
    frontendImplementedChartTypes: frontend.implementedChartTypes,
    backendSupportedChartTypes,
    intersectedChartTypes,
    unsupportedBackendChartTypes,
    unadvertisedFrontendChartTypes,
    rendererCompatible,
    specCompatible,
    contextSummaryMode: normalizeString(rawVisualization.context_summary_mode) || "disabled",
    backendReferenceModeSupported,
    backendReferenceModeEnabled,
    referenceModeSupported,
    referenceModeEnabled,
    limits: buildEffectiveLimits(clientLimits, rawVisualization.limits),
    mismatches,
  });
}

export function evaluateVisualizationArtifactCompatibility(artifactCandidate, visualizationState) {
  if (!artifactCandidate || typeof artifactCandidate !== "object" || !visualizationState) {
    return { allowed: true, code: null, message: null };
  }

  if (!visualizationState.backendAdvertised) {
    return { allowed: true, code: null, message: null };
  }

  if (!visualizationState.backendEnabled) {
    return {
      allowed: false,
      code: "visualization_disabled",
      message: "Visualization is currently disabled by backend capabilities.",
    };
  }

  if (!visualizationState.rendererCompatible) {
    return {
      allowed: false,
      code: "renderer_mismatch",
      message: "This frontend build cannot render backend visualizations until the configured renderer matches.",
    };
  }

  if (!visualizationState.specCompatible) {
    return {
      allowed: false,
      code: "spec_version_mismatch",
      message: "This frontend build does not support the backend visualization spec version.",
    };
  }

  const candidateRenderer = normalizeString(artifactCandidate.renderer);
  if (candidateRenderer && candidateRenderer !== visualizationState.renderer) {
    return {
      allowed: false,
      code: "renderer_mismatch",
      message: "This visualization uses a renderer that is not enabled in the current frontend build.",
    };
  }

  const candidateSpecVersion = normalizeString(artifactCandidate.spec_version);
  if (candidateSpecVersion && candidateSpecVersion !== visualizationState.specVersion) {
    return {
      allowed: false,
      code: "spec_version_mismatch",
      message: "This visualization uses a spec version that is not supported in the current frontend build.",
    };
  }

  const chartType = normalizeString(artifactCandidate.chart_type);
  if (chartType && !visualizationState.intersectedChartTypes.includes(chartType)) {
    const code = visualizationState.backendSupportedChartTypes.includes(chartType)
      ? "unsupported_client_chart_type"
      : "unadvertised_chart_type";
    return {
      allowed: false,
      code,
      message: visualizationState.backendSupportedChartTypes.includes(chartType)
        ? "This frontend build does not implement the returned chart type yet."
        : "The backend returned a visualization type that is not advertised by the current deployment capabilities.",
    };
  }

  if (artifactCandidate.data_mode === "reference" && !visualizationState.referenceModeEnabled) {
    return {
      allowed: false,
      code: "reference_mode_disabled",
      message: "This visualization requires reference-mode data loading, but that mode is not enabled for this deployment.",
    };
  }

  return { allowed: true, code: null, message: null };
}

export function buildVisualizationCompatibilityWarning(visualizationState) {
  if (!visualizationState?.backendAdvertised || !visualizationState.backendEnabled) {
    return null;
  }

  if (visualizationState.mismatches.length > 0) {
    return visualizationState.mismatches.join(" ");
  }

  if (!visualizationState.intersectedChartTypes.length) {
    return "No mutually supported visualization chart types are available for this deployment.";
  }

  return null;
}

export function shouldRunVisualizationStartupCheck(frontendFlags = {}) {
  if (frontendFlags.testing) {
    return true;
  }

  const environment = normalizeString(frontendFlags.environment);
  return environment ? STARTUP_CHECK_ENVIRONMENTS.has(environment.toLowerCase()) : false;
}