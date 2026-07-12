import { humanizeFieldName } from "./artifact-model.js";

const HTML_ESCAPE_MAP = Object.freeze({
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
});

const MONTH_ONLY_PATTERN = /^\d{4}-\d{2}$/;
const DATE_ONLY_PATTERN = /^\d{4}-\d{2}-\d{2}$/;
const MAX_DECIMAL_PLACES = 6;

function readArtifactValue(artifact, key) {
  return artifact?.options?.[key] ?? artifact?.metadata?.[key] ?? null;
}

function clampDecimalPlaces(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return null;
  }

  return Math.max(0, Math.min(MAX_DECIMAL_PLACES, Math.trunc(value)));
}

function normalizeUnit(value) {
  if (typeof value !== "string") {
    return "";
  }

  return value.trim();
}

function buildDateFormatterOptions(value, artifact) {
  const timezone = readArtifactValue(artifact, "timezone");
  const baseOptions = {
    timeZone: typeof timezone === "string" && timezone.trim() ? timezone.trim() : undefined,
  };

  if (typeof value === "string" && MONTH_ONLY_PATTERN.test(value.trim())) {
    return { ...baseOptions, month: "short", year: "numeric" };
  }
  if (typeof value === "string" && DATE_ONLY_PATTERN.test(value.trim())) {
    return { ...baseOptions, month: "short", day: "numeric", year: "numeric" };
  }

  return { ...baseOptions, month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" };
}

function buildNumberFormatOptions(artifact, { compact = false } = {}) {
  const decimalPlaces = clampDecimalPlaces(readArtifactValue(artifact, "decimal_places"));
  const currency = readArtifactValue(artifact, "currency");
  const percent = readArtifactValue(artifact, "percent") === true;
  const options = {
    maximumFractionDigits: decimalPlaces ?? (compact ? 1 : 2),
  };

  if (decimalPlaces != null) {
    options.minimumFractionDigits = decimalPlaces;
  }
  if (compact) {
    options.notation = "compact";
    options.compactDisplay = "short";
  }
  if (percent) {
    options.style = "percent";
    return options;
  }
  if (typeof currency === "string" && currency.trim()) {
    options.style = "currency";
    options.currency = currency.trim().toUpperCase();
    options.currencyDisplay = "narrowSymbol";
    return options;
  }

  options.style = "decimal";
  return options;
}

export function escapeText(value) {
  return String(value ?? "").replace(/[&<>"']/g, (match) => HTML_ESCAPE_MAP[match]);
}

export function parseTemporalValue(value) {
  if (value instanceof Date && Number.isFinite(value.getTime())) {
    return value;
  }
  if (typeof value === "number" && Number.isFinite(value)) {
    const numericDate = new Date(value);
    return Number.isFinite(numericDate.getTime()) ? numericDate : null;
  }
  if (typeof value !== "string") {
    return null;
  }

  const normalized = value.trim();
  if (!normalized) {
    return null;
  }

  let candidate = normalized;
  if (MONTH_ONLY_PATTERN.test(normalized)) {
    candidate = `${normalized}-01T00:00:00Z`;
  } else if (DATE_ONLY_PATTERN.test(normalized)) {
    candidate = `${normalized}T00:00:00Z`;
  }

  const parsed = new Date(candidate);
  return Number.isFinite(parsed.getTime()) ? parsed : null;
}

export function looksLikeTemporalValue(value) {
  return parseTemporalValue(value) !== null;
}

export function formatTemporalValue(value, artifact) {
  const parsed = parseTemporalValue(value);
  if (!parsed) {
    return String(value ?? "");
  }

  try {
    return new Intl.DateTimeFormat(undefined, buildDateFormatterOptions(value, artifact)).format(parsed);
  } catch (_error) {
    return String(value ?? "");
  }
}

export function formatMetricValue(value, artifact, { compact = false } = {}) {
  if (value == null || value === "") {
    return "-";
  }
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return String(value);
  }

  let formatted = String(value);
  try {
    formatted = new Intl.NumberFormat(undefined, buildNumberFormatOptions(artifact, { compact })).format(value);
  } catch (_error) {
    formatted = String(value);
  }

  const currency = readArtifactValue(artifact, "currency");
  const percent = readArtifactValue(artifact, "percent") === true;
  const unit = normalizeUnit(readArtifactValue(artifact, "unit"));
  if (!percent && !(typeof currency === "string" && currency.trim()) && unit) {
    return `${formatted} ${unit}`;
  }
  return formatted;
}

export function formatCategoryValue(value, artifact) {
  if (value == null || value === "") {
    return "-";
  }
  if (looksLikeTemporalValue(value)) {
    return formatTemporalValue(value, artifact);
  }
  return String(value);
}

export function formatTableCellValue(value, artifact) {
  if (typeof value === "number") {
    return formatMetricValue(value, artifact);
  }
  if (looksLikeTemporalValue(value)) {
    return formatTemporalValue(value, artifact);
  }
  if (value == null || value === "") {
    return "-";
  }
  return String(value);
}

export function formatFieldLabel(value) {
  return humanizeFieldName(String(value || "Series"));
}