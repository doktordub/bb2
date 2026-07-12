import { validateChartArtifact } from "./artifact-validator.js";
import { ChartInstanceStore } from "./chart-instance-store.js";
import { VisualizationDataLoader } from "./data-loader.js";
import {
  buildAccessibleChartSummary,
  mountChartScaffold,
  renderChartEmpty,
  renderChartError,
  renderChartLoading,
  renderChartReady,
  renderChartTable,
  updateChartShellMetadata,
} from "./chart-components.js";
import { ChartRegistry } from "./chart-registry.js";
import { registerBaseEChartsAdapters } from "./echarts-adapter.js";

function resolveEChartsRuntime(providedRuntime) {
  const runtime = providedRuntime || globalThis.echarts;
  if (!runtime || typeof runtime.init !== "function") {
    throw new Error("ECharts runtime is unavailable.");
  }
  return runtime;
}

function safeTelemetryPayload(artifact, status, error = null, extras = {}) {
  return {
    artifactId: artifact?.artifact_id || null,
    chartType: artifact?.chart_type || null,
    renderer: artifact?.renderer || null,
    specVersion: artifact?.spec_version || null,
    status,
    errorCode: error?.code || null,
    ...extras,
  };
}

function readNow() {
  if (typeof globalThis.performance?.now === "function") {
    return globalThis.performance.now();
  }
  return Date.now();
}

function toDurationMs(startedAt) {
  return Number(Math.max(0, readNow() - startedAt).toFixed(2));
}

function bindResize({ element, onResize }) {
  let timeoutId = null;
  let pendingSource = "observer";

  const flushResize = () => {
    timeoutId = null;
    onResize(pendingSource);
  };

  const scheduleResize = (source) => {
    pendingSource = source;
    if (timeoutId != null && typeof globalThis.clearTimeout === "function") {
      globalThis.clearTimeout(timeoutId);
    }

    if (typeof globalThis.setTimeout === "function") {
      timeoutId = globalThis.setTimeout(flushResize, 80);
      return;
    }

    flushResize();
  };

  const onWindowResize = () => scheduleResize("window");
  const onVisibilityChange = () => {
    if (globalThis.document?.visibilityState === "hidden") {
      return;
    }
    scheduleResize("visibility");
  };

  let resizeObserver = null;
  if (typeof globalThis.ResizeObserver === "function") {
    resizeObserver = new globalThis.ResizeObserver(() => scheduleResize("observer"));
    resizeObserver.observe(element);
  }

  if (globalThis.window && typeof globalThis.window.addEventListener === "function") {
    globalThis.window.addEventListener("resize", onWindowResize);
  }

  if (globalThis.document && typeof globalThis.document.addEventListener === "function") {
    globalThis.document.addEventListener("visibilitychange", onVisibilityChange);
  }

  return () => {
    if (timeoutId != null && typeof globalThis.clearTimeout === "function") {
      globalThis.clearTimeout(timeoutId);
    }
    resizeObserver?.disconnect?.();
    globalThis.window?.removeEventListener?.("resize", onWindowResize);
    globalThis.document?.removeEventListener?.("visibilitychange", onVisibilityChange);
  };
}

export class ChartRenderer {
  constructor({ registry, instanceStore, echartsRuntime, telemetry, dataLoader } = {}) {
    this.registry = registry || registerBaseEChartsAdapters(new ChartRegistry());
    this.instanceStore = instanceStore || new ChartInstanceStore();
    this.echartsRuntime = echartsRuntime || null;
    this.telemetry = telemetry && typeof telemetry.record === "function" ? telemetry : null;
    this.dataLoader = dataLoader || new VisualizationDataLoader();
    this.pendingLoads = new Map();
  }

  render(container, artifactCandidate, { sessionId = null, messageId = null, limits = {} } = {}) {
    const shell = mountChartScaffold(container, {
      title: artifactCandidate?.title || "Visualization",
      description: artifactCandidate?.description || "",
      accessibleSummary: buildAccessibleChartSummary(artifactCandidate),
    });
    renderChartLoading(shell);

    let artifact = null;
    try {
      artifact = validateChartArtifact(artifactCandidate, limits);
    } catch (error) {
      renderChartError(shell, error.message || "Chart could not be displayed.");
      this.#recordTelemetry(artifactCandidate, "validation_error", error);
      return this.#buildHandle({ artifact: artifactCandidate, shell, status: "validation_error", error });
    }

    this.#cancelPendingLoad(artifact.artifact_id);

    return this.#renderValidatedArtifact(container, shell, artifact, {
      sessionId,
      messageId,
      limits,
    });
  }

  dispose(artifactId) {
    const canceledPending = this.#cancelPendingLoad(artifactId);
    const disposed = this.instanceStore.dispose(artifactId);
    return canceledPending || disposed;
  }

  disposeByMessage(messageId) {
    this.#cancelPendingBy((record) => record.messageId === messageId);
    return this.instanceStore.disposeByMessage(messageId);
  }

  disposeBySession(sessionId) {
    this.#cancelPendingBy((record) => record.sessionId === sessionId);
    this.dataLoader.clearSession?.(sessionId);
    return this.instanceStore.disposeBySession(sessionId);
  }

  disposeAll() {
    this.#cancelPendingBy(() => true);
    this.dataLoader.clearAll?.();
    return this.instanceStore.disposeAll();
  }

  #renderValidatedArtifact(container, shell, artifact, { sessionId = null, messageId = null, limits = {} } = {}) {
    const adapterEntry = this.registry.resolve(artifact);
    if (!adapterEntry) {
      const error = new Error(`No adapter is registered for ${artifact.chart_type}.`);
      error.code = "unsupported_chart_type";
      renderChartError(shell, "This chart type is not available in the current frontend build.");
      this.#recordTelemetry(artifact, "unsupported", error);
      return this.#buildHandle({ artifact, shell, status: "unsupported", error });
    }

    if (artifact.data_mode !== "inline") {
      return this.#renderReferenceArtifact(container, shell, artifact, {
        sessionId,
        messageId,
        limits,
      });
    }

    return this.#renderInlineArtifact(shell, artifact, adapterEntry, {
      sessionId,
      messageId,
    });
  }

  #renderReferenceArtifact(container, shell, artifact, { sessionId = null, messageId = null, limits = {} } = {}) {
    if (!sessionId) {
      const error = new Error("Visualization data requires an active session.");
      error.code = "missing_session";
      renderChartError(shell, error.message);
      this.#recordTelemetry(artifact, "reference_error", error);
      return this.#buildHandle({ artifact, shell, status: "reference_error", error });
    }

    renderChartLoading(shell, "Loading chart data...");
    this.#recordTelemetry(artifact, "loading_reference");

    const abortController = new AbortController();
    const pendingRecord = {
      artifactId: artifact.artifact_id,
      sessionId,
      messageId,
      container,
      shell,
      abortController,
    };
    this.pendingLoads.set(artifact.artifact_id, pendingRecord);

    void this.dataLoader.loadArtifact(artifact, {
      sessionId,
      signal: abortController.signal,
      limits,
    }).then((loadedArtifact) => {
      if (this.pendingLoads.get(artifact.artifact_id) !== pendingRecord) {
        return;
      }
      this.pendingLoads.delete(artifact.artifact_id);

      const loadedAdapterEntry = this.registry.resolve(loadedArtifact);
      if (!loadedAdapterEntry) {
        const error = new Error(`No adapter is registered for ${loadedArtifact.chart_type}.`);
        error.code = "unsupported_chart_type";
        renderChartError(shell, "This chart type is not available in the current frontend build.");
        this.#recordTelemetry(loadedArtifact, "unsupported", error);
        return;
      }

      updateChartShellMetadata(shell, loadedArtifact);
      this.#renderInlineArtifact(shell, loadedArtifact, loadedAdapterEntry, {
        sessionId,
        messageId,
      });
    }).catch((error) => {
      if (this.pendingLoads.get(artifact.artifact_id) !== pendingRecord) {
        return;
      }
      this.pendingLoads.delete(artifact.artifact_id);

      if (error?.code === "request_aborted") {
        this.#recordTelemetry(artifact, "reference_aborted", error);
        return;
      }

      renderChartError(shell, error?.message || "Chart could not be displayed.");
      this.#recordTelemetry(artifact, "reference_error", error);
    });

    return this.#buildHandle({ artifact, shell, status: "loading_reference" });
  }

  #renderInlineArtifact(shell, artifact, adapterEntry, { sessionId = null, messageId = null } = {}) {
    const renderStartedAt = readNow();

    updateChartShellMetadata(shell, artifact);

    if (!artifact.data.length) {
      renderChartEmpty(shell);
      this.#recordTelemetry(artifact, "empty");
      return this.#buildHandle({ artifact, shell, status: "empty" });
    }

    let adaptedOutput = null;
    try {
      adaptedOutput = adapterEntry.adapter(artifact);
    } catch (error) {
      renderChartError(shell, error.message || "Chart could not be displayed.");
      this.#recordTelemetry(artifact, "render_error", error);
      return this.#buildHandle({ artifact, shell, status: "render_error", error });
    }

    const existing = this.instanceStore.get(artifact.artifact_id);
    if (existing && existing.element === shell.chartCanvas) {
      existing.update(adaptedOutput);
      renderChartReady(shell, artifact.warnings);
      this.#recordTelemetry(artifact, "updated", null, {
        durationMs: toDurationMs(renderStartedAt),
        dataMode: artifact.data_mode,
        renderMode: adapterEntry.renderMode,
      });
      return this.#buildHandle({ artifact, shell, status: "updated", chart: existing.chart, record: existing });
    }

    if (adapterEntry.renderMode === "dom") {
      renderChartTable(shell, adaptedOutput);
      const record = this.instanceStore.upsert({
        artifactId: artifact.artifact_id,
        sessionId,
        messageId,
        element: shell.chartCanvas,
        chart: null,
        update: (nextModel) => renderChartTable(shell, nextModel),
        dispose: () => {},
      });
      renderChartReady(shell, artifact.warnings);
      this.#recordTelemetry(artifact, "rendered", null, {
        durationMs: toDurationMs(renderStartedAt),
        dataMode: artifact.data_mode,
        renderMode: adapterEntry.renderMode,
      });
      return this.#buildHandle({ artifact, shell, status: "rendered", record });
    }

    try {
      const echartsRuntime = resolveEChartsRuntime(this.echartsRuntime);
      const chart = echartsRuntime.init(shell.chartCanvas, null, {
        renderer: "canvas",
        useDirtyRect: true,
      });
      chart.setOption(adaptedOutput, true);

      const resizeChart = (source = "manual") => {
        const resizeStartedAt = readNow();
        chart.resize();
        this.#recordTelemetry(artifact, "resized", null, {
          durationMs: toDurationMs(resizeStartedAt),
          dataMode: artifact.data_mode,
          renderMode: adapterEntry.renderMode,
          source,
        });
      };

      const unbindResize = bindResize({
        element: shell.chartCanvas,
        onResize: resizeChart,
      });
      const record = this.instanceStore.upsert({
        artifactId: artifact.artifact_id,
        sessionId,
        messageId,
        element: shell.chartCanvas,
        chart,
        resize: () => resizeChart("manual"),
        update: (nextOptions) => chart.setOption(nextOptions, true),
        dispose: () => {
          unbindResize();
          chart.dispose();
        },
      });

      renderChartReady(shell, artifact.warnings);
      this.#recordTelemetry(artifact, "rendered", null, {
        durationMs: toDurationMs(renderStartedAt),
        dataMode: artifact.data_mode,
        renderMode: adapterEntry.renderMode,
      });
      return this.#buildHandle({ artifact, shell, status: "rendered", chart, record });
    } catch (error) {
      renderChartError(shell, error.message || "Chart could not be displayed.");
      this.#recordTelemetry(artifact, "render_error", error);
      return this.#buildHandle({ artifact, shell, status: "render_error", error });
    }
  }

  #buildHandle({ artifact, shell, status, error = null, chart = null, record = null }) {
    return {
      artifact,
      shell,
      status,
      error,
      chart,
      resize: () => {
        if (record?.resize) {
          record.resize();
          return record;
        }
        if (artifact?.artifact_id) {
          return this.instanceStore.resize(artifact.artifact_id);
        }
        return null;
      },
      dispose: () => (artifact?.artifact_id ? this.dispose(artifact.artifact_id) : false),
    };
  }

  #cancelPendingLoad(artifactId) {
    const pending = this.pendingLoads.get(artifactId);
    if (!pending) {
      return false;
    }

    this.pendingLoads.delete(artifactId);
    pending.abortController.abort();
    return true;
  }

  #cancelPendingBy(predicate) {
    const artifactIds = Array.from(this.pendingLoads.values())
      .filter((record) => predicate(record))
      .map((record) => record.artifactId);
    artifactIds.forEach((artifactId) => this.#cancelPendingLoad(artifactId));
    return artifactIds.length;
  }

  #recordTelemetry(artifact, status, error = null, extras = {}) {
    this.telemetry?.record("visualization.render", safeTelemetryPayload(artifact, status, error, extras));
  }
}