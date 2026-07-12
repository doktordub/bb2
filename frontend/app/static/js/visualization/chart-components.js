import { humanizeFieldName } from "./artifact-model.js";
import { formatCategoryValue, formatFieldLabel } from "./chart-formatters.js";

const CHART_TYPE_LABELS = Object.freeze({
  bar: "Bar chart",
  grouped_bar: "Grouped bar chart",
  stacked_bar: "Stacked bar chart",
  horizontal_bar: "Horizontal bar chart",
  line: "Line chart",
  multi_line: "Multi-line chart",
  area: "Area chart",
  pie: "Pie chart",
  donut: "Donut chart",
  scatter: "Scatter plot",
  bubble: "Bubble chart",
  histogram: "Histogram",
  box_plot: "Box plot",
  heatmap: "Heatmap",
  treemap: "Treemap",
  waterfall: "Waterfall chart",
  gantt: "Gantt chart",
  radar: "Radar chart",
  table: "Data table",
});

const MAX_SUMMARY_LENGTH = 360;

let shellSequence = 0;

function ensureContainer(container) {
  if (!container || typeof container !== "object") {
    throw new TypeError("A container element is required.");
  }
}

function clearNode(node) {
  if (typeof node.replaceChildren === "function") {
    node.replaceChildren();
    return;
  }
  node.children = [];
  node.textContent = "";
}

function appendChildren(node, children) {
  if (typeof node.append === "function") {
    node.append(...children);
    return;
  }
  if (!Array.isArray(node.children)) {
    node.children = [];
  }
  node.children.push(...children);
}

function createNode(tagName, className, textContent = "") {
  const element = typeof document !== "undefined" && typeof document.createElement === "function"
    ? document.createElement(tagName)
    : {
        tagName: tagName.toUpperCase(),
        className: "",
        textContent: "",
        attributes: {},
        dataset: {},
        children: [],
        append(...children) {
          this.children.push(...children);
        },
        replaceChildren(...children) {
          this.children = [...children];
        },
        setAttribute(name, value) {
          this.attributes[name] = String(value);
        },
        removeAttribute(name) {
          delete this.attributes[name];
        },
      };
  element.className = className;
  element.textContent = textContent;
  return element;
}

function nextShellId(suffix) {
  shellSequence += 1;
  return `chart-artifact-${suffix}-${shellSequence}`;
}

function clampText(value, maxLength = MAX_SUMMARY_LENGTH) {
  const normalized = String(value ?? "").replace(/\s+/g, " ").trim();
  if (normalized.length <= maxLength) {
    return normalized;
  }
  return `${normalized.slice(0, maxLength - 1).trimEnd()}…`;
}

function readCategoryField(artifact) {
  return artifact?.encoding?.x
    || artifact?.encoding?.category
    || artifact?.encoding?.dimension
    || artifact?.encoding?.task
    || null;
}

function readMetricFields(artifact) {
  const fieldNames = [];

  if (Array.isArray(artifact?.encoding?.y)) {
    fieldNames.push(...artifact.encoding.y);
  } else if (typeof artifact?.encoding?.y === "string") {
    fieldNames.push(artifact.encoding.y);
  }

  [artifact?.encoding?.value, artifact?.encoding?.size].forEach((value) => {
    if (typeof value === "string") {
      fieldNames.push(value);
    }
  });

  return Array.from(new Set(fieldNames.filter((value) => typeof value === "string" && value.trim())));
}

function summarizeList(values, { maxItems = 3, formatter = (value) => value } = {}) {
  const items = values
    .filter((value) => value != null && String(value).trim())
    .slice(0, maxItems)
    .map((value) => formatter(value));

  if (!items.length) {
    return "";
  }

  return items.join(", ");
}

function setNodeVisibility(node, visible) {
  if (!node) {
    return;
  }

  node.hidden = !visible;
  node.setAttribute?.("aria-hidden", visible ? "false" : "true");
}

function setStatusSemantics(node, { role = "status", live = "polite" } = {}) {
  node.setAttribute?.("role", role);
  node.setAttribute?.("aria-live", live);
  node.setAttribute?.("aria-atomic", "true");
}

export function buildAccessibleChartSummary(artifact) {
  if (!artifact || typeof artifact !== "object") {
    return "Visualization.";
  }

  const chartType = typeof artifact.chart_type === "string" && artifact.chart_type.trim()
    ? artifact.chart_type.trim()
    : "chart";
  const chartLabel = CHART_TYPE_LABELS[chartType] || `${humanizeFieldName(chartType)} chart`;
  const rowCount = Array.isArray(artifact.data) ? artifact.data.length : 0;
  const categoryField = readCategoryField(artifact);
  const metricFields = readMetricFields(artifact);
  const summaryParts = [
    `${chartLabel}.`,
    rowCount ? `${rowCount} ${rowCount === 1 ? "row" : "rows"} available.` : "No data rows are available.",
  ];

  if (categoryField) {
    summaryParts.push(`Primary category: ${formatFieldLabel(categoryField)}.`);
  }

  if (metricFields.length) {
    const metrics = summarizeList(metricFields, {
      formatter: (value) => formatFieldLabel(value),
    });
    if (metrics) {
      summaryParts.push(`Metrics: ${metrics}${metricFields.length > 3 ? ", and more" : ""}.`);
    }
  }

  if (typeof artifact?.encoding?.series === "string" && artifact.encoding.series.trim()) {
    summaryParts.push(`Series are grouped by ${formatFieldLabel(artifact.encoding.series)}.`);
  }

  if (categoryField && Array.isArray(artifact.data) && artifact.data.length) {
    const preview = summarizeList(artifact.data.map((row) => row?.[categoryField]), {
      formatter: (value) => formatCategoryValue(value, artifact),
    });
    if (preview) {
      summaryParts.push(`First categories: ${preview}${artifact.data.length > 3 ? ", and more" : ""}.`);
    }
  }

  return clampText(summaryParts.join(" ")) || "Visualization.";
}

export function updateChartShellMetadata(shell, artifact) {
  if (!shell) {
    return;
  }

  if (shell.titleNode) {
    shell.titleNode.textContent = artifact?.title || "Visualization";
  }
  if (shell.descriptionNode) {
    const description = artifact?.description || "";
    shell.descriptionNode.textContent = description;
    setNodeVisibility(shell.descriptionNode, Boolean(description));
  }
  if (shell.summaryNode) {
    shell.summaryNode.textContent = buildAccessibleChartSummary(artifact);
  }
}

export function mountChartScaffold(container, { title = "", description = "", accessibleSummary = "" } = {}) {
  ensureContainer(container);
  clearNode(container);
  container.className = [container.className, "chart-artifact"].filter(Boolean).join(" ").trim();

  const caption = createNode("figcaption", "chart-artifact__caption");
  const titleNode = createNode("p", "chart-artifact__title", title);
  const descriptionNode = createNode("p", "chart-artifact__description", description);
  const summaryNode = createNode(
    "p",
    "chart-artifact__summary chart-artifact__summary--sr",
    accessibleSummary || clampText(`${title || "Visualization"}. ${description || ""}`) || "Visualization."
  );

  const titleId = nextShellId("title");
  const descriptionId = nextShellId("description");
  const summaryId = nextShellId("summary");
  const statusId = nextShellId("status");

  titleNode.id = titleId;
  descriptionNode.id = descriptionId;
  summaryNode.id = summaryId;

  setNodeVisibility(descriptionNode, Boolean(description));

  appendChildren(caption, [titleNode, descriptionNode, summaryNode]);

  const chartSurface = createNode("div", "chart-artifact__surface");
  const chartCanvas = createNode("div", "chart-artifact__canvas");
  const chartStatus = createNode("div", "chart-artifact__status");
  chartStatus.id = statusId;
  setStatusSemantics(chartStatus, { role: "status", live: "polite" });
  chartCanvas.setAttribute?.("tabindex", "0");
  chartCanvas.setAttribute?.("role", "img");
  chartCanvas.setAttribute?.("aria-labelledby", titleId);
  chartCanvas.setAttribute?.("aria-describedby", [descriptionId, summaryId, statusId].join(" ").trim());
  appendChildren(chartSurface, [chartCanvas, chartStatus]);

  appendChildren(container, [caption, chartSurface]);
  container.setAttribute?.("role", "group");
  container.setAttribute?.("aria-labelledby", titleId);
  container.setAttribute?.("aria-describedby", [descriptionId, summaryId, statusId].join(" ").trim());
  container.dataset.chartArtifact = "true";

  return {
    caption,
    titleNode,
    descriptionNode,
    summaryNode,
    chartSurface,
    chartCanvas,
    chartStatus,
  };
}

export function renderChartLoading(shell, message = "Rendering chart...") {
  if (!shell?.chartStatus) {
    throw new TypeError("Chart shell is required.");
  }
  shell.chartStatus.className = "chart-artifact__status chart-artifact__status--loading";
  shell.chartStatus.textContent = message;
  setStatusSemantics(shell.chartStatus, { role: "status", live: "polite" });
}

export function renderChartEmpty(shell, message = "No chart data is available.") {
  if (!shell?.chartStatus) {
    throw new TypeError("Chart shell is required.");
  }
  shell.chartStatus.className = "chart-artifact__status chart-artifact__status--empty";
  shell.chartStatus.textContent = message;
  setStatusSemantics(shell.chartStatus, { role: "status", live: "polite" });
}

export function renderChartError(shell, message = "Chart could not be displayed.") {
  if (!shell?.chartStatus) {
    throw new TypeError("Chart shell is required.");
  }
  shell.chartStatus.className = "chart-artifact__status chart-artifact__status--error";
  shell.chartStatus.textContent = message;
  setStatusSemantics(shell.chartStatus, { role: "alert", live: "assertive" });
}

export function renderChartReady(shell, warnings = []) {
  if (!shell?.chartStatus) {
    throw new TypeError("Chart shell is required.");
  }
  shell.chartStatus.className = "chart-artifact__status chart-artifact__status--ready";
  shell.chartStatus.textContent = warnings.length ? warnings.join(" ") : "Chart ready.";
  setStatusSemantics(shell.chartStatus, { role: "status", live: "polite" });
}

export function renderChartTable(shell, tableModel) {
  if (!shell?.chartCanvas) {
    throw new TypeError("Chart shell is required.");
  }

  clearNode(shell.chartCanvas);
  shell.chartCanvas.className = "chart-artifact__canvas chart-artifact__canvas--table";
  shell.chartCanvas.removeAttribute?.("role");
  shell.chartCanvas.removeAttribute?.("tabindex");

  const wrapper = createNode("div", "chart-artifact__table-wrap");
  wrapper.setAttribute?.("tabindex", "0");
  wrapper.setAttribute?.("role", "region");
  wrapper.setAttribute?.("aria-label", "Chart data table. Scroll horizontally to reveal additional columns when needed.");
  const table = createNode("table", "chart-artifact__table");
  table.setAttribute?.("role", "table");
  if (shell.summaryNode?.id) {
    table.setAttribute?.("aria-describedby", shell.summaryNode.id);
  }

  const thead = createNode("thead", "chart-artifact__table-head");
  const headRow = createNode("tr", "chart-artifact__table-row chart-artifact__table-row--head");
  for (const column of tableModel.columns || []) {
    const headerCell = createNode("th", "chart-artifact__table-header", column.label || "Column");
    headerCell.setAttribute?.("scope", "col");
    if (column.align === "end") {
      headerCell.setAttribute?.("data-align", "end");
    }
    appendChildren(headRow, [headerCell]);
  }
  appendChildren(thead, [headRow]);

  const tbody = createNode("tbody", "chart-artifact__table-body");
  for (const row of tableModel.rows || []) {
    const bodyRow = createNode("tr", "chart-artifact__table-row");
    for (const cell of row.cells || []) {
      const cellNode = createNode("td", "chart-artifact__table-cell", cell.text || "");
      if (cell.align === "end") {
        cellNode.setAttribute?.("data-align", "end");
      }
      appendChildren(bodyRow, [cellNode]);
    }
    appendChildren(tbody, [bodyRow]);
  }

  appendChildren(table, [thead, tbody]);
  appendChildren(wrapper, [table]);
  appendChildren(shell.chartCanvas, [wrapper]);

  if (tableModel.notice) {
    const notice = createNode("p", "chart-artifact__table-notice", tableModel.notice);
    appendChildren(shell.chartCanvas, [notice]);
  }
}