export const VISUALIZATION_SPEC_VERSION = "1.0";
export const VISUALIZATION_RENDERER = "echarts";

export const SUPPORTED_CHART_TYPES = Object.freeze([
  "bar",
  "grouped_bar",
  "stacked_bar",
  "horizontal_bar",
  "line",
  "multi_line",
  "area",
  "pie",
  "donut",
  "scatter",
  "bubble",
  "histogram",
  "box_plot",
  "heatmap",
  "treemap",
  "waterfall",
  "gantt",
  "radar",
  "table",
]);

export const DEFAULT_VISUALIZATION_LIMITS = Object.freeze({
  maxRowsInline: 5000,
  maxFieldsPerRow: 24,
  maxSeries: 12,
  maxCategories: 100,
  maxWarnings: 8,
  maxMetadataEntries: 16,
  maxOptionEntries: 16,
  maxStringLength: 512,
  maxDataRefLength: 2048,
});

export const BLOCKED_OBJECT_KEYS = new Set(["__proto__", "constructor", "prototype"]);

export const SAFE_OPTION_KEYS = new Set([
  "currency",
  "stacked",
  "orientation",
  "timezone",
  "decimal_places",
  "percent",
  "unit",
  "inner_radius",
  "sort",
  "show_legend",
  "x_label",
  "y_label",
]);

export function buildVisualizationLimits(overrides = {}) {
  return {
    ...DEFAULT_VISUALIZATION_LIMITS,
    ...overrides,
  };
}

export function isPlainObject(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }

  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

export function hasBlockedKey(value) {
  if (Array.isArray(value)) {
    return value.some((item) => hasBlockedKey(item));
  }

  if (!isPlainObject(value)) {
    return false;
  }

  return Object.keys(value).some((key) => BLOCKED_OBJECT_KEYS.has(key) || hasBlockedKey(value[key]));
}

export function humanizeFieldName(value) {
  if (typeof value !== "string" || !value) {
    return "Series";
  }

  return value
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/\b\w/g, (match) => match.toUpperCase());
}