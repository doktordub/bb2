import assert from "node:assert/strict";
import test from "node:test";

import {
  buildVisualizationCompatibilityWarning,
  buildFrontendVisualizationProfile,
  evaluateVisualizationArtifactCompatibility,
  resolveVisualizationCapabilityState,
} from "../../app/static/js/visualization/runtime-capabilities.js";

test("buildFrontendVisualizationProfile reflects the locally implemented chart registry", () => {
  const profile = buildFrontendVisualizationProfile();

  assert.equal(profile.renderer, "echarts");
  assert.equal(profile.specVersion, "1.0");
  assert.equal(profile.referenceModeSupported, true);
  assert.ok(profile.implementedChartTypes.includes("bar"));
  assert.ok(profile.implementedChartTypes.includes("table"));
});

test("resolveVisualizationCapabilityState intersects backend visualization capabilities with frontend adapters", () => {
  const state = resolveVisualizationCapabilityState(
    {
      visualization: {
        enabled: true,
        default_renderer: "echarts",
        allowed_renderers: ["echarts"],
        spec_version: "1.0",
        context_summary_mode: "summary_only",
        supported_chart_types: ["bar", "radar", "custom_heatmap"],
        reference_mode_supported: true,
        reference_mode_enabled: false,
        limits: {
          max_rows_inline: 500,
          max_series: 8,
          max_categories: 60,
          max_artifacts_per_response: 1,
        },
      },
    },
    {
      clientLimits: {
        maxArtifactsPerResponse: 3,
        maxRowsInline: 2500,
        maxSeries: 12,
        maxCategories: 100,
      },
    }
  );

  assert.equal(state.backendAdvertised, true);
  assert.equal(state.backendEnabled, true);
  assert.equal(state.enabled, true);
  assert.deepEqual(state.intersectedChartTypes, ["bar", "radar"]);
  assert.deepEqual(state.unsupportedBackendChartTypes, ["custom_heatmap"]);
  assert.equal(state.referenceModeEnabled, false);
  assert.deepEqual(state.limits, {
    maxArtifactsPerResponse: 1,
    maxRowsInline: 500,
    maxSeries: 8,
    maxCategories: 60,
  });
  assert.match(state.mismatches[0], /Backend-only chart types/i);
});

test("evaluateVisualizationArtifactCompatibility blocks disabled, unsupported, and reference-only artifacts", () => {
  const disabledState = resolveVisualizationCapabilityState({
    visualization: {
      enabled: false,
      default_renderer: "echarts",
      allowed_renderers: ["echarts"],
      spec_version: "1.0",
      supported_chart_types: ["bar"],
      reference_mode_supported: false,
      reference_mode_enabled: false,
      limits: {},
    },
  });

  assert.deepEqual(
    evaluateVisualizationArtifactCompatibility({ chart_type: "bar" }, disabledState),
    {
      allowed: false,
      code: "visualization_disabled",
      message: "Visualization is currently disabled by backend capabilities.",
    }
  );

  const state = resolveVisualizationCapabilityState({
    visualization: {
      enabled: true,
      default_renderer: "echarts",
      allowed_renderers: ["echarts"],
      spec_version: "1.0",
      supported_chart_types: ["bar"],
      reference_mode_supported: false,
      reference_mode_enabled: false,
      limits: {},
    },
  });

  const unsupported = evaluateVisualizationArtifactCompatibility(
    {
      chart_type: "radar",
      renderer: "echarts",
      spec_version: "1.0",
    },
    state
  );
  assert.equal(unsupported.allowed, false);
  assert.equal(unsupported.code, "unadvertised_chart_type");

  const referenceBlocked = evaluateVisualizationArtifactCompatibility(
    {
      chart_type: "bar",
      renderer: "echarts",
      spec_version: "1.0",
      data_mode: "reference",
    },
    state
  );
  assert.equal(referenceBlocked.allowed, false);
  assert.equal(referenceBlocked.code, "reference_mode_disabled");
});

test("buildVisualizationCompatibilityWarning summarizes backend/frontend mismatches only when relevant", () => {
  const healthyState = resolveVisualizationCapabilityState({
    visualization: {
      enabled: true,
      default_renderer: "echarts",
      allowed_renderers: ["echarts"],
      spec_version: "1.0",
      supported_chart_types: ["bar", "radar"],
      reference_mode_supported: true,
      reference_mode_enabled: true,
      limits: {},
    },
  });
  assert.equal(buildVisualizationCompatibilityWarning(healthyState), null);

  const mismatchedState = resolveVisualizationCapabilityState({
    visualization: {
      enabled: true,
      default_renderer: "echarts",
      allowed_renderers: ["echarts"],
      spec_version: "1.0",
      supported_chart_types: ["bar", "custom_heatmap"],
      reference_mode_supported: true,
      reference_mode_enabled: true,
      limits: {},
    },
  });
  assert.match(
    buildVisualizationCompatibilityWarning(mismatchedState),
    /Backend-only chart types/i
  );
});