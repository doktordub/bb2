import {
  SAFE_OPTION_KEYS,
  SUPPORTED_CHART_TYPES,
  VISUALIZATION_RENDERER,
  VISUALIZATION_SPEC_VERSION,
  buildVisualizationLimits,
  hasBlockedKey,
  isPlainObject,
} from "./artifact-model.js";

const IDENTIFIER_PATTERN = /^[A-Za-z][A-Za-z0-9_:-]*$/;
const SCRIPT_PROTOCOL_PATTERN = /^(?:javascript|data|vbscript):/i;
const HTML_EVENT_HANDLER_PATTERN = /^on[a-z]+$/i;

export class VisualizationArtifactValidationError extends Error {
  constructor(message, { code = "invalid_artifact", details = null } = {}) {
    super(message);
    this.name = "VisualizationArtifactValidationError";
    this.code = code;
    this.details = details;
  }
}

function fail(message, options = {}) {
  throw new VisualizationArtifactValidationError(message, options);
}

function assertString(
  value,
  fieldName,
  limits,
  { allowEmpty = false, maxLength = limits.maxStringLength, rejectScriptProtocol = true } = {}
) {
  if (typeof value !== "string") {
    fail(`${fieldName} must be a string.`, { code: "invalid_field", details: { fieldName } });
  }

  const normalized = value.trim();
  if (!allowEmpty && !normalized) {
    fail(`${fieldName} must not be empty.`, { code: "invalid_field", details: { fieldName } });
  }
  if (normalized.length > maxLength) {
    fail(`${fieldName} exceeds the maximum length.`, { code: "limit_exceeded", details: { fieldName, maxLength } });
  }
  if (rejectScriptProtocol && SCRIPT_PROTOCOL_PATTERN.test(normalized)) {
    fail(`${fieldName} uses an unsafe script-like value.`, { code: "unsafe_value", details: { fieldName } });
  }

  return normalized;
}

function assertSafeFieldName(value, fieldName) {
  if (!IDENTIFIER_PATTERN.test(value) || HTML_EVENT_HANDLER_PATTERN.test(value)) {
    fail(`${fieldName} contains an unsupported field name.`, {
      code: "invalid_field_name",
      details: { fieldName, value },
    });
  }

  return value;
}

function assertFiniteNumber(value, fieldName) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    fail(`${fieldName} must be a finite number.`, { code: "invalid_number", details: { fieldName } });
  }

  return value;
}

function sanitizeScalar(value, fieldName, limits) {
  if (typeof value === "string") {
    return assertString(value, fieldName, limits, { allowEmpty: true });
  }
  if (typeof value === "number") {
    return assertFiniteNumber(value, fieldName);
  }
  if (typeof value === "boolean" || value === null) {
    return value;
  }

  fail(`${fieldName} must contain only scalar values.`, { code: "invalid_scalar", details: { fieldName } });
}

function sanitizeWarnings(value, limits) {
  if (value == null) {
    return [];
  }
  if (!Array.isArray(value)) {
    fail("warnings must be an array.", { code: "invalid_field", details: { fieldName: "warnings" } });
  }
  if (value.length > limits.maxWarnings) {
    fail("warnings exceeds the maximum count.", { code: "limit_exceeded", details: { fieldName: "warnings" } });
  }

  return value.map((warning, index) => assertString(warning, `warnings[${index}]`, limits));
}

function sanitizeMetadata(value, limits) {
  if (value == null) {
    return {};
  }
  if (!isPlainObject(value)) {
    fail("metadata must be an object.", { code: "invalid_field", details: { fieldName: "metadata" } });
  }

  const entries = Object.entries(value);
  if (entries.length > limits.maxMetadataEntries) {
    fail("metadata exceeds the maximum number of entries.", {
      code: "limit_exceeded",
      details: { fieldName: "metadata" },
    });
  }

  const sanitized = {};
  for (const [key, entryValue] of entries) {
    assertSafeFieldName(key, "metadata key");
    sanitized[key] = sanitizeScalar(entryValue, `metadata.${key}`, limits);
  }
  return sanitized;
}

function sanitizeOptions(value, limits) {
  if (value == null) {
    return {};
  }
  if (!isPlainObject(value)) {
    fail("options must be an object.", { code: "invalid_field", details: { fieldName: "options" } });
  }

  const entries = Object.entries(value);
  if (entries.length > limits.maxOptionEntries) {
    fail("options exceeds the maximum number of entries.", {
      code: "limit_exceeded",
      details: { fieldName: "options" },
    });
  }

  const sanitized = {};
  for (const [key, entryValue] of entries) {
    if (!SAFE_OPTION_KEYS.has(key)) {
      fail(`options.${key} is not allowlisted.`, {
        code: "unsupported_option",
        details: { fieldName: `options.${key}` },
      });
    }
    sanitized[key] = sanitizeScalar(entryValue, `options.${key}`, limits);
  }
  return sanitized;
}

function sanitizeEncoding(value, limits) {
  if (!isPlainObject(value)) {
    fail("encoding must be an object.", { code: "invalid_field", details: { fieldName: "encoding" } });
  }

  const sanitized = {};
  for (const [key, entryValue] of Object.entries(value)) {
    assertSafeFieldName(key, "encoding key");

    if (Array.isArray(entryValue)) {
      if (entryValue.length === 0) {
        fail(`encoding.${key} must not be empty.`, {
          code: "invalid_field",
          details: { fieldName: `encoding.${key}` },
        });
      }
      sanitized[key] = entryValue.map((item, index) => {
        const fieldValue = assertString(item, `encoding.${key}[${index}]`, limits);
        return assertSafeFieldName(fieldValue, `encoding.${key}[${index}]`);
      });
      continue;
    }

    const fieldValue = assertString(entryValue, `encoding.${key}`, limits);
    sanitized[key] = assertSafeFieldName(fieldValue, `encoding.${key}`);
  }

  return sanitized;
}

function countCategories(data, fieldName) {
  if (!fieldName) {
    return 0;
  }

  return new Set(data.map((row) => row[fieldName]).filter((value) => value != null)).size;
}

function readEncodingField(encoding, keys) {
  for (const key of keys) {
    if (typeof encoding[key] === "string") {
      return encoding[key];
    }
  }
  return null;
}

function readEncodingFieldList(encoding, key) {
  if (Array.isArray(encoding[key])) {
    return encoding[key];
  }
  if (typeof encoding[key] === "string") {
    return [encoding[key]];
  }
  return [];
}

function parseTemporalCandidate(value) {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value !== "string") {
    return null;
  }

  const normalized = value.trim();
  if (!normalized) {
    return null;
  }

  let candidate = normalized;
  if (/^\d{4}-\d{2}$/.test(normalized)) {
    candidate = `${normalized}-01T00:00:00Z`;
  } else if (/^\d{4}-\d{2}-\d{2}$/.test(normalized)) {
    candidate = `${normalized}T00:00:00Z`;
  }

  const parsed = Date.parse(candidate);
  return Number.isFinite(parsed) ? parsed : null;
}

function assertTemporalValue(value, fieldName) {
  if (value == null) {
    return null;
  }
  const parsed = parseTemporalCandidate(value);
  if (parsed == null) {
    fail(`${fieldName} must contain temporal values.`, {
      code: "invalid_time",
      details: { fieldName },
    });
  }
  return parsed;
}

function assertFieldPresentInRows(data, fieldName, { allowNull = true } = {}) {
  data.forEach((row, index) => {
    if (!(fieldName in row)) {
      fail(`${fieldName} is missing from data[${index}].`, {
        code: "invalid_encoding",
        details: { fieldName, rowIndex: index },
      });
    }
    if (!allowNull && row[fieldName] == null) {
      fail(`${fieldName} must not be null in data[${index}].`, {
        code: "invalid_field",
        details: { fieldName, rowIndex: index },
      });
    }
  });
}

function assertScalarField(data, fieldName, { allowNull = true } = {}) {
  assertFieldPresentInRows(data, fieldName, { allowNull });
}

function assertNumericField(data, fieldName, { allowNull = true, nonNegative = false } = {}) {
  assertFieldPresentInRows(data, fieldName, { allowNull });
  const numericValues = [];
  data.forEach((row, index) => {
    const value = row[fieldName];
    if (value == null) {
      return;
    }
    if (typeof value !== "number" || !Number.isFinite(value)) {
      fail(`${fieldName} must contain only finite numeric values.`, {
        code: "invalid_number",
        details: { fieldName, rowIndex: index },
      });
    }
    if (nonNegative && value < 0) {
      fail(`${fieldName} must not contain negative values.`, {
        code: "invalid_number",
        details: { fieldName, rowIndex: index },
      });
    }
    numericValues.push(value);
  });
  return numericValues;
}

function rowsLookTemporal(data, fieldName) {
  const definedValues = data.map((row) => row[fieldName]).filter((value) => value != null);
  if (!definedValues.length) {
    return false;
  }
  return definedValues.every((value) => parseTemporalCandidate(value) != null);
}

function assertTemporalOrder(data, fieldName) {
  let previous = null;
  data.forEach((row) => {
    const current = assertTemporalValue(row[fieldName], fieldName);
    if (current == null) {
      return;
    }
    if (previous != null && current < previous) {
      fail(`${fieldName} must be in ascending temporal order.`, {
        code: "invalid_time_order",
        details: { fieldName },
      });
    }
    previous = current;
  });
}

function fieldNamesForCategoryLimit(chartType, encoding) {
  if (["bar", "grouped_bar", "stacked_bar", "horizontal_bar", "line", "multi_line", "area", "box_plot", "radar", "waterfall"].includes(chartType)) {
    return [readEncodingField(encoding, ["x", "category", "dimension"])].filter(Boolean);
  }
  if (["pie", "donut", "treemap"].includes(chartType)) {
    return [readEncodingField(encoding, ["category", "x", "dimension"])].filter(Boolean);
  }
  if (chartType === "heatmap") {
    return [readEncodingField(encoding, ["x"]), readEncodingField(encoding, ["y"])].filter(Boolean);
  }
  if (chartType === "gantt") {
    return [readEncodingField(encoding, ["task"])].filter(Boolean);
  }
  return [];
}

function sanitizeDataRow(row, index, limits) {
  if (!isPlainObject(row)) {
    fail(`data[${index}] must be an object.`, {
      code: "invalid_row",
      details: { fieldName: `data[${index}]` },
    });
  }

  const entries = Object.entries(row);
  if (entries.length === 0) {
    fail(`data[${index}] must not be empty.`, {
      code: "invalid_row",
      details: { fieldName: `data[${index}]` },
    });
  }
  if (entries.length > limits.maxFieldsPerRow) {
    fail(`data[${index}] exceeds the maximum field count.`, {
      code: "limit_exceeded",
      details: { fieldName: `data[${index}]`, maxFieldsPerRow: limits.maxFieldsPerRow },
    });
  }

  const sanitizedRow = {};
  for (const [key, entryValue] of entries) {
    assertSafeFieldName(key, `data[${index}] field`);
    sanitizedRow[key] = sanitizeScalar(entryValue, `data[${index}].${key}`, limits);
  }
  return sanitizedRow;
}

function validateInlineDataForKnownTypes(chartType, encoding, data) {
  if (chartType === "table") {
    return;
  }

  if (["bar", "horizontal_bar", "line", "area", "radar"].includes(chartType)) {
    const xField = readEncodingField(encoding, ["x", "category", "dimension"]);
    const yFields = readEncodingFieldList(encoding, "y");
    assertScalarField(data, xField, { allowNull: false });
    yFields.forEach((fieldName) => assertNumericField(data, fieldName));
    if (["line", "area"].includes(chartType)) {
      const timeField = readEncodingField(encoding, ["time"]) || (rowsLookTemporal(data, xField) ? xField : null);
      if (timeField) {
        assertTemporalOrder(data, timeField);
      }
    }
    return;
  }

  if (["grouped_bar", "stacked_bar", "multi_line"].includes(chartType)) {
    const xField = readEncodingField(encoding, ["x", "category"]);
    const yFields = readEncodingFieldList(encoding, "y");
    const seriesField = readEncodingField(encoding, ["series"]);
    const valueField = readEncodingField(encoding, ["value"]);
    assertScalarField(data, xField, { allowNull: false });
    if (yFields.length) {
      yFields.forEach((fieldName) => assertNumericField(data, fieldName));
      if (yFields.length < 2 && !seriesField) {
        fail(`${chartType} charts require multiple y fields or a series/value encoding pair.`, {
          code: "invalid_encoding",
          details: { chartType },
        });
      }
    } else {
      assertScalarField(data, seriesField, { allowNull: false });
      assertNumericField(data, valueField);
    }
    if (chartType === "multi_line") {
      const timeField = readEncodingField(encoding, ["time"]) || (rowsLookTemporal(data, xField) ? xField : null);
      if (timeField) {
        assertTemporalOrder(data, timeField);
      }
    }
    return;
  }

  if (["pie", "donut", "treemap", "waterfall"].includes(chartType)) {
    const categoryField = readEncodingField(encoding, ["category", "x", "dimension"]);
    const valueField = readEncodingField(encoding, ["value"]);
    assertScalarField(data, categoryField, { allowNull: false });
    const values = assertNumericField(data, valueField, {
      nonNegative: chartType === "pie" || chartType === "donut",
    });
    if ((chartType === "pie" || chartType === "donut") && values.every((value) => value === 0)) {
      fail(`${chartType} charts require at least one non-zero value.`, {
        code: "invalid_number",
        details: { chartType, fieldName: valueField },
      });
    }
    if (chartType === "waterfall" && values.every((value) => value === 0)) {
      fail("waterfall charts require at least one non-zero contribution.", {
        code: "invalid_number",
        details: { chartType, fieldName: valueField },
      });
    }
    return;
  }

  if (chartType === "scatter") {
    assertNumericField(data, readEncodingField(encoding, ["x"]));
    assertNumericField(data, readEncodingField(encoding, ["y"]));
    return;
  }

  if (chartType === "bubble") {
    assertNumericField(data, readEncodingField(encoding, ["x"]));
    assertNumericField(data, readEncodingField(encoding, ["y"]));
    assertNumericField(data, readEncodingField(encoding, ["size"]));
    return;
  }

  if (chartType === "histogram") {
    assertNumericField(data, readEncodingField(encoding, ["x", "value"]), { allowNull: false });
    return;
  }

  if (chartType === "box_plot") {
    assertScalarField(data, readEncodingField(encoding, ["x", "category"]), { allowNull: false });
    readEncodingFieldList(encoding, "y").forEach((fieldName) => assertNumericField(data, fieldName));
    return;
  }

  if (chartType === "heatmap") {
    assertScalarField(data, readEncodingField(encoding, ["x"]), { allowNull: false });
    assertScalarField(data, readEncodingField(encoding, ["y"]), { allowNull: false });
    assertNumericField(data, readEncodingField(encoding, ["value"]), { allowNull: false });
    return;
  }

  if (chartType === "gantt") {
    const taskField = readEncodingField(encoding, ["task"]);
    const startField = readEncodingField(encoding, ["start"]);
    const endField = readEncodingField(encoding, ["end"]);
    assertScalarField(data, taskField, { allowNull: false });
    assertFieldPresentInRows(data, startField, { allowNull: false });
    assertFieldPresentInRows(data, endField, { allowNull: false });
    data.forEach((row) => {
      const startTime = assertTemporalValue(row[startField], startField);
      const endTime = assertTemporalValue(row[endField], endField);
      if (startTime != null && endTime != null && endTime < startTime) {
        fail(`${endField} must not be earlier than ${startField}.`, {
          code: "invalid_time_order",
          details: { startField, endField },
        });
      }
    });
  }
}

function sanitizeInlineData(value, chartType, encoding, limits) {
  if (!Array.isArray(value)) {
    fail("data must be an array when data_mode is inline.", {
      code: "missing_data",
      details: { fieldName: "data" },
    });
  }
  if (value.length > limits.maxRowsInline) {
    fail("data exceeds the maximum row count.", {
      code: "limit_exceeded",
      details: { fieldName: "data", maxRowsInline: limits.maxRowsInline },
    });
  }

  const sanitized = value.map((row, index) => sanitizeDataRow(row, index, limits));
  const yFields = Array.isArray(encoding.y) ? encoding.y : typeof encoding.y === "string" ? [encoding.y] : [];
  if (yFields.length > limits.maxSeries) {
    fail("encoding.y exceeds the maximum series count.", {
      code: "limit_exceeded",
      details: { fieldName: "encoding.y", maxSeries: limits.maxSeries },
    });
  }

  const longSeriesField = readEncodingField(encoding, ["series"]);
  if (!yFields.length && longSeriesField) {
    const seriesCount = countCategories(sanitized, longSeriesField);
    if (seriesCount > limits.maxSeries) {
      fail("chart series exceed the maximum supported count.", {
        code: "limit_exceeded",
        details: { fieldName: longSeriesField, maxSeries: limits.maxSeries },
      });
    }
  }

  fieldNamesForCategoryLimit(chartType, encoding).forEach((fieldName) => {
    const categories = countCategories(sanitized, fieldName);
    if (categories > limits.maxCategories) {
      fail("chart categories exceed the maximum supported count.", {
        code: "limit_exceeded",
        details: { fieldName, maxCategories: limits.maxCategories },
      });
    }
  });

  validateInlineDataForKnownTypes(chartType, encoding, sanitized);

  return sanitized;
}

function sanitizeDataRef(value, limits) {
  const dataRef = assertString(value, "data_ref", limits, {
    maxLength: limits.maxDataRefLength,
    rejectScriptProtocol: false,
  });
  if (SCRIPT_PROTOCOL_PATTERN.test(dataRef) || !dataRef.startsWith("/")) {
    fail("data_ref must be a same-origin absolute path.", {
      code: "unsafe_data_ref",
      details: { fieldName: "data_ref" },
    });
  }
  return dataRef;
}

function validateRootShape(candidate) {
  if (!isPlainObject(candidate)) {
    fail("artifact must be an object.", { code: "invalid_artifact" });
  }
  if (hasBlockedKey(candidate)) {
    fail("artifact contains blocked keys.", { code: "unsafe_object_keys" });
  }
}

function validateEncodingForKnownTypes(chartType, encoding) {
  if (["bar", "horizontal_bar", "line", "area", "radar", "box_plot"].includes(chartType)) {
    if (!readEncodingField(encoding, ["x", "category", "dimension"])) {
      fail(`encoding.x is required for ${chartType}.`, {
        code: "invalid_encoding",
        details: { chartType, fieldName: "encoding.x" },
      });
    }
    const yFields = readEncodingFieldList(encoding, "y");
    if (!yFields.length) {
      fail(`encoding.y must be a non-empty array for ${chartType}.`, {
        code: "invalid_encoding",
        details: { chartType, fieldName: "encoding.y" },
      });
    }
    if (chartType === "box_plot" && yFields.length !== 1) {
      fail("box_plot charts require exactly one y field.", {
        code: "invalid_encoding",
        details: { chartType, fieldName: "encoding.y" },
      });
    }
    return;
  }

  if (["grouped_bar", "stacked_bar", "multi_line"].includes(chartType)) {
    if (!readEncodingField(encoding, ["x", "category"])) {
      fail(`encoding.x is required for ${chartType}.`, {
        code: "invalid_encoding",
        details: { chartType, fieldName: "encoding.x" },
      });
    }
    const yFields = readEncodingFieldList(encoding, "y");
    const seriesField = readEncodingField(encoding, ["series"]);
    const valueField = readEncodingField(encoding, ["value"]);
    if (yFields.length >= 2) {
      return;
    }
    if (seriesField && valueField) {
      return;
    }
    fail(`${chartType} charts require multiple y fields or a series/value encoding pair.`, {
      code: "invalid_encoding",
      details: { chartType },
    });
  }

  if (["pie", "donut", "treemap"].includes(chartType)) {
    if (!readEncodingField(encoding, ["category", "x", "dimension"])) {
      fail(`encoding.category is required for ${chartType}.`, {
        code: "invalid_encoding",
        details: { chartType, fieldName: "encoding.category" },
      });
    }
    if (!readEncodingField(encoding, ["value"])) {
      fail(`encoding.value is required for ${chartType}.`, {
        code: "invalid_encoding",
        details: { chartType, fieldName: "encoding.value" },
      });
    }
    return;
  }

  if (chartType === "waterfall") {
    if (!readEncodingField(encoding, ["x", "category", "dimension"])) {
      fail("encoding.x is required for waterfall.", {
        code: "invalid_encoding",
        details: { chartType, fieldName: "encoding.x" },
      });
    }
    if (!readEncodingField(encoding, ["value"])) {
      fail("encoding.value is required for waterfall.", {
        code: "invalid_encoding",
        details: { chartType, fieldName: "encoding.value" },
      });
    }
    return;
  }

  if (chartType === "scatter") {
    if (!readEncodingField(encoding, ["x"]) || !readEncodingField(encoding, ["y"])) {
      fail("scatter charts require encoding.x and encoding.y.", {
        code: "invalid_encoding",
        details: { chartType },
      });
    }
    return;
  }

  if (chartType === "bubble") {
    if (!readEncodingField(encoding, ["x"]) || !readEncodingField(encoding, ["y"]) || !readEncodingField(encoding, ["size"])) {
      fail("bubble charts require encoding.x, encoding.y, and encoding.size.", {
        code: "invalid_encoding",
        details: { chartType },
      });
    }
    return;
  }

  if (chartType === "histogram") {
    if (!readEncodingField(encoding, ["x", "value"])) {
      fail("histogram charts require encoding.x.", {
        code: "invalid_encoding",
        details: { chartType, fieldName: "encoding.x" },
      });
    }
    return;
  }

  if (chartType === "heatmap") {
    if (!readEncodingField(encoding, ["x"]) || !readEncodingField(encoding, ["y"]) || !readEncodingField(encoding, ["value"])) {
      fail("heatmap charts require encoding.x, encoding.y, and encoding.value.", {
        code: "invalid_encoding",
        details: { chartType },
      });
    }
    return;
  }

  if (chartType === "gantt") {
    if (!readEncodingField(encoding, ["task"]) || !readEncodingField(encoding, ["start"]) || !readEncodingField(encoding, ["end"])) {
      fail("gantt charts require encoding.task, encoding.start, and encoding.end.", {
        code: "invalid_encoding",
        details: { chartType },
      });
    }
    return;
  }

  if (chartType === "table") {
    return;
  }
}

export function validateChartArtifact(candidate, limitsOverride = {}) {
  validateRootShape(candidate);

  const limits = buildVisualizationLimits(limitsOverride);
  const artifactId = assertString(candidate.artifact_id, "artifact_id", limits);
  const type = assertString(candidate.type, "type", limits);
  if (type !== "chart") {
    fail("type must be chart.", { code: "unsupported_artifact_type", details: { artifactId } });
  }

  const chartType = assertString(candidate.chart_type, "chart_type", limits);
  if (!SUPPORTED_CHART_TYPES.includes(chartType)) {
    fail(`chart_type ${chartType} is not supported by the frontend contract.`, {
      code: "unsupported_chart_type",
      details: { artifactId, chartType },
    });
  }

  const renderer = assertString(candidate.renderer, "renderer", limits);
  if (renderer !== VISUALIZATION_RENDERER) {
    fail(`renderer ${renderer} is not supported.`, {
      code: "unsupported_renderer",
      details: { artifactId, renderer },
    });
  }

  const specVersion = assertString(candidate.spec_version, "spec_version", limits);
  if (specVersion !== VISUALIZATION_SPEC_VERSION) {
    fail(`spec_version ${specVersion} is not supported.`, {
      code: "unsupported_spec_version",
      details: { artifactId, specVersion },
    });
  }

  const title = assertString(candidate.title, "title", limits);
  const description = candidate.description == null
    ? ""
    : assertString(candidate.description, "description", limits, { allowEmpty: true });
  const dataMode = assertString(candidate.data_mode, "data_mode", limits);
  if (!["inline", "reference"].includes(dataMode)) {
    fail("data_mode must be inline or reference.", {
      code: "invalid_data_mode",
      details: { artifactId, dataMode },
    });
  }

  const encoding = sanitizeEncoding(candidate.encoding, limits);
  validateEncodingForKnownTypes(chartType, encoding);

  const sanitized = {
    artifact_id: artifactId,
    type,
    chart_type: chartType,
    title,
    description,
    renderer,
    spec_version: specVersion,
    data_mode: dataMode,
    data: null,
    data_ref: null,
    encoding,
    options: sanitizeOptions(candidate.options, limits),
    warnings: sanitizeWarnings(candidate.warnings, limits),
    metadata: sanitizeMetadata(candidate.metadata, limits),
  };

  if (dataMode === "inline") {
    if (candidate.data_ref != null) {
      fail("inline artifacts must not include data_ref.", {
        code: "invalid_data_mode",
        details: { artifactId, fieldName: "data_ref" },
      });
    }
    sanitized.data = sanitizeInlineData(candidate.data, chartType, encoding, limits);
    return sanitized;
  }

  if (candidate.data != null) {
    fail("reference artifacts must not include inline data.", {
      code: "invalid_data_mode",
      details: { artifactId, fieldName: "data" },
    });
  }

  sanitized.data_ref = sanitizeDataRef(candidate.data_ref, limits);
  return sanitized;
}