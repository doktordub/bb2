import { ChartRegistry } from "./chart-registry.js";
import { registerBaseEChartsAdapters } from "./echarts-adapter.js";
import { ChartRenderer } from "./chart-renderer.js";

function parseFixture(scriptElement) {
  if (!(scriptElement instanceof HTMLScriptElement) && !scriptElement?.textContent) {
    return null;
  }

  try {
    return JSON.parse(scriptElement.textContent || "null");
  } catch (_error) {
    return null;
  }
}

function normalizeArtifacts(payload) {
  if (Array.isArray(payload)) {
    return payload.filter((item) => item && typeof item === "object");
  }
  if (Array.isArray(payload?.cases)) {
    return payload.cases
      .map((entry) => entry?.artifact)
      .filter((artifact) => artifact && typeof artifact === "object");
  }
  if (payload && typeof payload === "object" && payload.artifact_id) {
    return [payload];
  }
  return [];
}

function createGalleryFigure(artifact) {
  const figure = document.createElement("figure");
  figure.className = "visualization-foundation__card visualization-foundation__card--demo";
  figure.dataset.visualizationChartType = artifact.chart_type || "unknown";
  figure.setAttribute("aria-label", `${artifact.title || "Visualization"} demo`);
  return figure;
}

function setText(element, text) {
  if (element) {
    element.textContent = text;
  }
}

export function initializeVisualizationFoundationPage() {
  if (document.body?.dataset.page !== "visualization-foundation") {
    return null;
  }

  const container = document.querySelector("[data-visualization-demo-grid]");
  const status = document.querySelector("[data-visualization-status]");
  const supported = document.querySelector("[data-visualization-supported]");
  const fixtureScript = document.querySelector("[data-visualization-fixture]");

  const registry = registerBaseEChartsAdapters(new ChartRegistry());
  setText(
    supported,
    registry.listSupported().map((item) => `${item.chartType} (${item.renderer} ${item.specVersion})`).join(", ")
  );

  const artifacts = normalizeArtifacts(parseFixture(fixtureScript));
  if (!container || !artifacts.length) {
    setText(status, "The shared visualization fixtures could not be loaded.");
    return null;
  }

  const renderer = new ChartRenderer({ registry });
  const handles = artifacts.map((artifact, index) => {
    const figure = createGalleryFigure(artifact);
    container.append(figure);
    return renderer.render(figure, artifact, {
      sessionId: "phase2-fixture-session",
      messageId: `phase2-fixture-message-${index + 1}`,
    });
  });

  const successful = handles.filter((handle) => handle.status === "rendered" || handle.status === "updated").length;
  const failed = handles.length - successful;
  setText(
    status,
    failed === 0
      ? `Rendered ${successful} shared backend visualization fixtures.`
      : `Rendered ${successful} fixtures with ${failed} failures.`
  );
  return handles;
}

if (typeof document !== "undefined") {
  void initializeVisualizationFoundationPage();
}