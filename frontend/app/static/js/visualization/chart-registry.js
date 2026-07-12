import { VISUALIZATION_RENDERER, VISUALIZATION_SPEC_VERSION } from "./artifact-model.js";

const SUPPORTED_RENDER_MODES = new Set(["echarts", "dom"]);

export class ChartRegistry {
  constructor() {
    this.adapters = new Map();
  }

  register(definition) {
    if (!definition || typeof definition !== "object") {
      throw new TypeError("Chart adapter definition must be an object.");
    }

    const chartType = String(definition.chartType || "").trim();
    const renderer = String(definition.renderer || "").trim();
    const specVersion = String(definition.specVersion || "").trim();
    const adapter = definition.adapter;
    const renderMode = String(definition.renderMode || "echarts").trim();

    if (!chartType) {
      throw new TypeError("Chart adapter definitions require chartType.");
    }
    if (renderer !== VISUALIZATION_RENDERER) {
      throw new TypeError(`Unsupported renderer ${renderer}.`);
    }
    if (specVersion !== VISUALIZATION_SPEC_VERSION) {
      throw new TypeError(`Unsupported spec version ${specVersion}.`);
    }
    if (typeof adapter !== "function") {
      throw new TypeError("Chart adapter definitions require an adapter function.");
    }
    if (!SUPPORTED_RENDER_MODES.has(renderMode)) {
      throw new TypeError(`Unsupported render mode ${renderMode}.`);
    }

    const key = this.#buildKey({ chartType, renderer, specVersion });
    if (this.adapters.has(key)) {
      throw new Error(`Adapter ${key} is already registered.`);
    }

    this.adapters.set(key, Object.freeze({ chartType, renderer, specVersion, renderMode, adapter }));
    return this;
  }

  resolve({ chart_type: chartType, renderer, spec_version: specVersion }) {
    return this.adapters.get(this.#buildKey({ chartType, renderer, specVersion })) || null;
  }

  listSupported() {
    return Array.from(this.adapters.values()).map((entry) => ({
      chartType: entry.chartType,
      renderer: entry.renderer,
      specVersion: entry.specVersion,
    }));
  }

  #buildKey({ chartType, renderer, specVersion }) {
    return `${chartType}::${renderer}::${specVersion}`;
  }
}