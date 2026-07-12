import { humanizeFieldName } from "./artifact-model.js";
import {
  formatCategoryValue,
  formatFieldLabel,
  formatMetricValue,
  formatTableCellValue,
  looksLikeTemporalValue,
  parseTemporalValue,
} from "./chart-formatters.js";

const DEFAULT_COLORS = Object.freeze([
  "#0078d4",
  "#ffb900",
  "#0f6cbd",
  "#d83b01",
  "#0f9d58",
  "#5c2d91",
  "#ca5010",
  "#038387",
]);

const TABLE_MAX_ROWS = 25;
const MAX_AXIS_LABEL_CHARS = 18;
const MAX_LEGEND_LABEL_CHARS = 24;
const MAX_TOOLTIP_TEXT_CHARS = 96;
const TOOLTIP_LINE_BREAK = "\n";
const LINE_SERIES_SYMBOLS = Object.freeze(["circle", "rect", "triangle", "diamond"]);
const LINE_SERIES_STYLES = Object.freeze(["solid", "dashed", "dotted", "solid"]);

function readArtifactValue(artifact, key) {
  return artifact?.options?.[key] ?? artifact?.metadata?.[key] ?? null;
}

function clampText(value, maxLength) {
  const normalized = String(value ?? "").replace(/\s+/g, " ").trim();
  if (normalized.length <= maxLength) {
    return normalized;
  }
  return `${normalized.slice(0, maxLength - 1).trimEnd()}…`;
}

function safeTooltipText(value, maxLength = MAX_TOOLTIP_TEXT_CHARS) {
  return clampText(value, maxLength);
}

function truncateLabelText(value, maxLength = MAX_AXIS_LABEL_CHARS) {
  return clampText(value ?? "-", maxLength);
}

function buildTooltipConfig(config) {
  return {
    confine: true,
    enterable: false,
    renderMode: "richText",
    ...config,
  };
}

function orderedUniqueValues(values) {
  const seen = new Set();
  const ordered = [];

  values.forEach((value) => {
    const key = `${typeof value}:${String(value)}`;
    if (!seen.has(key)) {
      seen.add(key);
      ordered.push(value);
    }
  });

  return ordered;
}

function uniqueFieldValues(data, fieldName) {
  return orderedUniqueValues(data.map((row) => row[fieldName]));
}

function buildCategoryValues(data, fieldName) {
  return data.map((row) => row[fieldName]);
}

function buildSeriesData(data, fieldName) {
  return data.map((row) => row[fieldName] ?? null);
}

function resolveCategoryField(artifact) {
  return artifact.encoding.x || artifact.encoding.category || artifact.encoding.dimension || null;
}

function resolveValueField(artifact) {
  if (typeof artifact.encoding.value === "string") {
    return artifact.encoding.value;
  }
  if (typeof artifact.encoding.y === "string") {
    return artifact.encoding.y;
  }
  if (Array.isArray(artifact.encoding.y) && artifact.encoding.y.length) {
    return artifact.encoding.y[0];
  }
  return null;
}

function resolveYFields(artifact) {
  if (Array.isArray(artifact.encoding.y)) {
    return artifact.encoding.y;
  }
  if (typeof artifact.encoding.y === "string") {
    return [artifact.encoding.y];
  }
  return [];
}

function resolveCategoryAxisName(artifact, fieldName) {
  return artifact.options.x_label || artifact.options.category_label || humanizeFieldName(fieldName);
}

function resolveValueAxisName(artifact, fieldName = null) {
  return artifact.options.y_label || readArtifactValue(artifact, "unit") || readArtifactValue(artifact, "currency") || (fieldName ? humanizeFieldName(fieldName) : "Value");
}

function buildLegendConfig(artifact, labels) {
  const showLegend = artifact.options.show_legend !== false && labels.length > 1;
  return {
    show: showLegend,
    top: 28,
    left: "center",
    type: labels.length > 4 ? "scroll" : "plain",
    data: labels,
    formatter: (value) => truncateLabelText(value, MAX_LEGEND_LABEL_CHARS),
  };
}

function buildBaseOptions(artifact) {
  return {
    animation: false,
    color: [...DEFAULT_COLORS],
    title: {
      text: artifact.title,
      left: "center",
    },
    aria: {
      enabled: true,
      decal: {
        show: true,
      },
    },
  };
}

function buildCartesianGrid(top = 72) {
  return {
    containLabel: true,
    left: 16,
    right: 24,
    top,
    bottom: 24,
  };
}

function buildResponsiveMedia({ hasLegend = false, categoryAxisTarget = null } = {}) {
  const option = {};

  if (hasLegend) {
    option.legend = {
      top: "bottom",
      left: "center",
      right: 12,
      type: "scroll",
    };
  }

  if (categoryAxisTarget) {
    option[categoryAxisTarget] = {
      axisLabel: {
        width: categoryAxisTarget === "yAxis" ? 120 : 88,
        overflow: "truncate",
        hideOverlap: true,
        rotate: categoryAxisTarget === "xAxis" ? 28 : 0,
      },
    };
    option.grid = buildCartesianGrid(hasLegend ? 58 : 48);
    option.grid.bottom = hasLegend ? 82 : 32;
  }

  if (!Object.keys(option).length) {
    return undefined;
  }

  return [
    {
      query: { maxWidth: 640 },
      option,
    },
  ];
}

function buildAxisTooltipFormatter(artifact, formatCategory) {
  return (params) => {
    const items = Array.isArray(params) ? params : [params];
    if (!items.length) {
      return "";
    }

    const lines = [safeTooltipText(formatCategory(items[0].axisValue ?? items[0].axisValueLabel), 72)];
    items.forEach((item) => {
      const value = Array.isArray(item.value) ? item.value[item.value.length - 1] : item.value;
      lines.push(`${safeTooltipText(item.seriesName || "Series", 48)}: ${safeTooltipText(formatMetricValue(value, artifact), 48)}`);
    });
    return lines.join(TOOLTIP_LINE_BREAK);
  };
}

function buildItemTooltipFormatter(artifact, formatter) {
  return (params) => formatter(params, artifact);
}

function buildCategoryAxis(artifact, fieldName, values, { temporal = false } = {}) {
  return {
    type: "category",
    data: values,
    name: resolveCategoryAxisName(artifact, fieldName),
    axisLabel: {
      width: 120,
      overflow: "truncate",
      hideOverlap: true,
      formatter: (value) => truncateLabelText(
        temporal ? formatCategoryValue(value, artifact) : String(value ?? "-"),
        MAX_AXIS_LABEL_CHARS
      ),
    },
  };
}

function buildValueAxis(artifact, fieldName = null) {
  return {
    type: "value",
    name: resolveValueAxisName(artifact, fieldName),
    axisLabel: {
      formatter: (value) => formatMetricValue(value, artifact, { compact: true }),
    },
  };
}

function buildMultiSeriesDefinition(artifact, xField) {
  const yFields = resolveYFields(artifact);
  if (yFields.length) {
    return {
      categories: buildCategoryValues(artifact.data, xField),
      series: yFields.map((fieldName) => ({
        key: fieldName,
        name: formatFieldLabel(fieldName),
        data: buildSeriesData(artifact.data, fieldName),
      })),
    };
  }

  const seriesField = artifact.encoding.series;
  const valueField = artifact.encoding.value;
  const categories = uniqueFieldValues(artifact.data, xField);
  const rawSeriesValues = uniqueFieldValues(artifact.data, seriesField);
  const seriesMaps = new Map(rawSeriesValues.map((value) => [value, new Map()]));

  artifact.data.forEach((row) => {
    const category = row[xField];
    const seriesName = row[seriesField];
    seriesMaps.get(seriesName)?.set(category, row[valueField] ?? null);
  });

  return {
    categories,
    series: rawSeriesValues.map((seriesValue) => ({
      key: seriesValue,
      name: formatFieldLabel(seriesValue),
      data: categories.map((category) => seriesMaps.get(seriesValue)?.get(category) ?? null),
    })),
  };
}

function buildBarFamilyOptions(artifact, { orientation = "vertical", stacked = false } = {}) {
  const xField = artifact.encoding.x;
  const multiSeries = buildMultiSeriesDefinition(artifact, xField);
  const temporalAxis = artifact.encoding.time === xField || multiSeries.categories.some((value) => looksLikeTemporalValue(value));
  const legendLabels = multiSeries.series.map((entry) => entry.name);
  const base = buildBaseOptions(artifact);
  const categoryAxis = buildCategoryAxis(artifact, xField, multiSeries.categories, { temporal: temporalAxis });
  const valueAxis = buildValueAxis(artifact, resolveValueField(artifact));
  const isHorizontal = orientation === "horizontal" || artifact.chart_type === "horizontal_bar";

  return {
    ...base,
    tooltip: buildTooltipConfig({
      trigger: "axis",
      axisPointer: {
        type: "shadow",
      },
      formatter: buildAxisTooltipFormatter(artifact, (value) => formatCategoryValue(value, artifact)),
    }),
    legend: buildLegendConfig(artifact, legendLabels),
    grid: buildCartesianGrid(legendLabels.length > 1 ? 72 : 58),
    xAxis: isHorizontal ? valueAxis : categoryAxis,
    yAxis: isHorizontal ? categoryAxis : valueAxis,
    media: buildResponsiveMedia({
      hasLegend: legendLabels.length > 1,
      categoryAxisTarget: isHorizontal ? "yAxis" : "xAxis",
    }),
    series: multiSeries.series.map((entry) => ({
      name: entry.name,
      type: "bar",
      stack: stacked ? "total" : undefined,
      data: entry.data,
      emphasis: {
        focus: "series",
      },
    })),
  };
}

function buildLineFamilyOptions(artifact, { area = false } = {}) {
  const xField = artifact.encoding.x;
  const multiSeries = artifact.chart_type === "multi_line"
    ? buildMultiSeriesDefinition(artifact, xField)
    : {
        categories: buildCategoryValues(artifact.data, xField),
        series: resolveYFields(artifact).map((fieldName) => ({
          key: fieldName,
          name: formatFieldLabel(fieldName),
          data: buildSeriesData(artifact.data, fieldName),
        })),
      };
  const temporalAxis = artifact.encoding.time === xField || multiSeries.categories.some((value) => looksLikeTemporalValue(value));
  const legendLabels = multiSeries.series.map((entry) => entry.name);

  return {
    ...buildBaseOptions(artifact),
    tooltip: buildTooltipConfig({
      trigger: "axis",
      formatter: buildAxisTooltipFormatter(artifact, (value) => formatCategoryValue(value, artifact)),
    }),
    legend: buildLegendConfig(artifact, legendLabels),
    grid: buildCartesianGrid(legendLabels.length > 1 ? 72 : 58),
    xAxis: buildCategoryAxis(artifact, xField, multiSeries.categories, { temporal: temporalAxis }),
    yAxis: buildValueAxis(artifact, resolveValueField(artifact)),
    media: buildResponsiveMedia({
      hasLegend: legendLabels.length > 1,
      categoryAxisTarget: "xAxis",
    }),
    series: multiSeries.series.map((entry, index) => ({
      name: entry.name,
      type: "line",
      smooth: false,
      connectNulls: false,
      symbol: LINE_SERIES_SYMBOLS[index % LINE_SERIES_SYMBOLS.length],
      showSymbol: true,
      lineStyle: {
        width: 2.5,
        type: LINE_SERIES_STYLES[index % LINE_SERIES_STYLES.length],
      },
      areaStyle: area ? { opacity: 0.24 } : undefined,
      data: entry.data,
      emphasis: {
        focus: "series",
      },
    })),
  };
}

function buildPieSeriesData(artifact) {
  const categoryField = resolveCategoryField(artifact);
  const valueField = resolveValueField(artifact);
  return artifact.data.map((row) => ({
    name: formatCategoryValue(row[categoryField], artifact),
    value: row[valueField],
  }));
}

function buildPieFamilyOptions(artifact, { donut = false } = {}) {
  const pieData = buildPieSeriesData(artifact);
  const radius = donut ? [readArtifactValue(artifact, "inner_radius") || "50%", "72%"] : [0, "72%"];

  return {
    ...buildBaseOptions(artifact),
    tooltip: buildTooltipConfig({
      trigger: "item",
      formatter: buildItemTooltipFormatter(artifact, (params, currentArtifact) => {
        const value = Array.isArray(params.value) ? params.value[params.value.length - 1] : params.value;
        return `${safeTooltipText(params.name, 48)}${TOOLTIP_LINE_BREAK}${safeTooltipText(formatMetricValue(value, currentArtifact), 48)}`;
      }),
    }),
    legend: buildLegendConfig(artifact, pieData.map((item) => item.name)),
    media: buildResponsiveMedia({
      hasLegend: pieData.length > 1,
    }),
    series: [
      {
        name: artifact.title,
        type: "pie",
        radius,
        center: ["50%", "58%"],
        avoidLabelOverlap: true,
        data: pieData,
        label: {
          formatter: ({ name, value }) => `${truncateLabelText(name, MAX_LEGEND_LABEL_CHARS)}: ${formatMetricValue(value, artifact)}`,
        },
      },
    ],
  };
}

function buildScatterOptions(artifact) {
  const xField = artifact.encoding.x;
  const yField = artifact.encoding.y;
  const data = artifact.data.map((row) => [row[xField], row[yField]]);

  return {
    ...buildBaseOptions(artifact),
    tooltip: buildTooltipConfig({
      trigger: "item",
      formatter: buildItemTooltipFormatter(artifact, (params, currentArtifact) => {
        const [xValue, yValue] = params.value || [];
        return [
          `${safeTooltipText(resolveCategoryAxisName(currentArtifact, xField), 48)}: ${safeTooltipText(formatMetricValue(xValue, currentArtifact), 48)}`,
          `${safeTooltipText(resolveValueAxisName(currentArtifact, yField), 48)}: ${safeTooltipText(formatMetricValue(yValue, currentArtifact), 48)}`,
        ].join(TOOLTIP_LINE_BREAK);
      }),
    }),
    grid: buildCartesianGrid(56),
    xAxis: buildValueAxis(artifact, xField),
    yAxis: buildValueAxis(artifact, yField),
    series: [
      {
        name: artifact.title,
        type: "scatter",
        data,
        emphasis: {
          focus: "series",
        },
      },
    ],
  };
}

function buildBubbleOptions(artifact) {
  const xField = artifact.encoding.x;
  const yField = artifact.encoding.y;
  const sizeField = artifact.encoding.size;
  const values = artifact.data.map((row) => row[sizeField]).filter((value) => typeof value === "number");
  const minSize = Math.min(...values);
  const maxSize = Math.max(...values);
  const range = Math.max(maxSize - minSize, 1);

  return {
    ...buildBaseOptions(artifact),
    tooltip: buildTooltipConfig({
      trigger: "item",
      formatter: buildItemTooltipFormatter(artifact, (params, currentArtifact) => {
        const [xValue, yValue, bubbleSize] = params.value || [];
        return [
          `${safeTooltipText(resolveCategoryAxisName(currentArtifact, xField), 48)}: ${safeTooltipText(formatMetricValue(xValue, currentArtifact), 48)}`,
          `${safeTooltipText(resolveValueAxisName(currentArtifact, yField), 48)}: ${safeTooltipText(formatMetricValue(yValue, currentArtifact), 48)}`,
          `${safeTooltipText(formatFieldLabel(sizeField), 48)}: ${safeTooltipText(formatMetricValue(bubbleSize, currentArtifact), 48)}`,
        ].join(TOOLTIP_LINE_BREAK);
      }),
    }),
    grid: buildCartesianGrid(56),
    xAxis: buildValueAxis(artifact, xField),
    yAxis: buildValueAxis(artifact, yField),
    series: [
      {
        name: artifact.title,
        type: "scatter",
        data: artifact.data.map((row) => [row[xField], row[yField], row[sizeField]]),
        symbolSize(value) {
          const size = Array.isArray(value) ? value[2] : value;
          if (typeof size !== "number" || !Number.isFinite(size)) {
            return 14;
          }
          return 14 + ((size - minSize) / range) * 28;
        },
        emphasis: {
          focus: "series",
        },
      },
    ],
  };
}

function buildHistogramBins(values) {
  if (!values.length) {
    return [];
  }

  const min = Math.min(...values);
  const max = Math.max(...values);
  if (min === max) {
    return [{ start: min, end: max, count: values.length }];
  }

  const binCount = Math.min(8, Math.max(3, Math.ceil(Math.sqrt(values.length))));
  const width = (max - min) / binCount;
  const bins = Array.from({ length: binCount }, (_, index) => ({
    start: min + (index * width),
    end: index === binCount - 1 ? max : min + ((index + 1) * width),
    count: 0,
  }));

  values.forEach((value) => {
    const index = value === max ? binCount - 1 : Math.min(binCount - 1, Math.floor((value - min) / width));
    bins[index].count += 1;
  });

  return bins;
}

function buildHistogramOptions(artifact) {
  const valueField = artifact.encoding.x || artifact.encoding.value;
  const values = artifact.data.map((row) => row[valueField]).filter((value) => typeof value === "number");
  const bins = buildHistogramBins(values);

  return {
    ...buildBaseOptions(artifact),
    tooltip: buildTooltipConfig({
      trigger: "axis",
      axisPointer: { type: "shadow" },
      formatter: buildAxisTooltipFormatter(artifact, (value) => String(value ?? "-")),
    }),
    grid: buildCartesianGrid(56),
    xAxis: {
      type: "category",
      name: resolveCategoryAxisName(artifact, valueField),
      data: bins.map((bin) => `${formatMetricValue(bin.start, artifact)} to ${formatMetricValue(bin.end, artifact)}`),
      axisLabel: {
        width: 120,
        overflow: "truncate",
        hideOverlap: true,
        formatter: (value) => truncateLabelText(value, MAX_AXIS_LABEL_CHARS),
      },
    },
    yAxis: {
      type: "value",
      name: "Count",
      minInterval: 1,
    },
    media: buildResponsiveMedia({
      categoryAxisTarget: "xAxis",
    }),
    series: [
      {
        name: formatFieldLabel(valueField),
        type: "bar",
        data: bins.map((bin) => bin.count),
        emphasis: { focus: "series" },
      },
    ],
  };
}

function quantile(values, percentile) {
  if (!values.length) {
    return 0;
  }
  const index = (values.length - 1) * percentile;
  const lowerIndex = Math.floor(index);
  const upperIndex = Math.ceil(index);
  if (lowerIndex === upperIndex) {
    return values[lowerIndex];
  }
  const weight = index - lowerIndex;
  return values[lowerIndex] + ((values[upperIndex] - values[lowerIndex]) * weight);
}

function buildBoxPlotOptions(artifact) {
  const categoryField = artifact.encoding.x;
  const valueField = resolveYFields(artifact)[0];
  const categories = uniqueFieldValues(artifact.data, categoryField);
  const groupedValues = new Map(categories.map((category) => [category, []]));

  artifact.data.forEach((row) => {
    if (typeof row[valueField] === "number") {
      groupedValues.get(row[categoryField])?.push(row[valueField]);
    }
  });

  const summaries = categories.map((category) => {
    const values = [...(groupedValues.get(category) || [])].sort((left, right) => left - right);
    return [
      values[0] ?? 0,
      quantile(values, 0.25),
      quantile(values, 0.5),
      quantile(values, 0.75),
      values[values.length - 1] ?? 0,
    ];
  });

  return {
    ...buildBaseOptions(artifact),
    tooltip: buildTooltipConfig({
      trigger: "item",
      formatter: buildItemTooltipFormatter(artifact, (params, currentArtifact) => {
        const [min, q1, median, q3, max] = params.value || [];
        return [
          safeTooltipText(String(params.name || "Series"), 48),
          `Min: ${safeTooltipText(formatMetricValue(min, currentArtifact), 48)}`,
          `Q1: ${safeTooltipText(formatMetricValue(q1, currentArtifact), 48)}`,
          `Median: ${safeTooltipText(formatMetricValue(median, currentArtifact), 48)}`,
          `Q3: ${safeTooltipText(formatMetricValue(q3, currentArtifact), 48)}`,
          `Max: ${safeTooltipText(formatMetricValue(max, currentArtifact), 48)}`,
        ].join(TOOLTIP_LINE_BREAK);
      }),
    }),
    grid: buildCartesianGrid(56),
    xAxis: buildCategoryAxis(artifact, categoryField, categories),
    yAxis: buildValueAxis(artifact, valueField),
    media: buildResponsiveMedia({
      categoryAxisTarget: "xAxis",
    }),
    series: [
      {
        name: artifact.title,
        type: "boxplot",
        data: summaries,
      },
    ],
  };
}

function buildHeatmapOptions(artifact) {
  const xField = artifact.encoding.x;
  const yField = artifact.encoding.y;
  const valueField = artifact.encoding.value;
  const xCategories = uniqueFieldValues(artifact.data, xField);
  const yCategories = uniqueFieldValues(artifact.data, yField);
  const values = artifact.data.map((row) => row[valueField]).filter((value) => typeof value === "number");
  const min = Math.min(...values);
  const max = Math.max(...values);

  return {
    ...buildBaseOptions(artifact),
    tooltip: buildTooltipConfig({
      position: "top",
      formatter: buildItemTooltipFormatter(artifact, (params, currentArtifact) => {
        const [xIndex, yIndex, value] = params.value || [];
        return [
          `${safeTooltipText(formatCategoryValue(xCategories[xIndex], currentArtifact), 48)} / ${safeTooltipText(formatCategoryValue(yCategories[yIndex], currentArtifact), 48)}`,
          safeTooltipText(formatMetricValue(value, currentArtifact), 48),
        ].join(TOOLTIP_LINE_BREAK);
      }),
    }),
    grid: buildCartesianGrid(72),
    xAxis: buildCategoryAxis(artifact, xField, xCategories, { temporal: xCategories.some((value) => looksLikeTemporalValue(value)) }),
    yAxis: {
      type: "category",
      name: resolveCategoryAxisName(artifact, yField),
      data: yCategories,
      axisLabel: {
        width: 120,
        overflow: "truncate",
        hideOverlap: true,
        formatter: (value) => truncateLabelText(formatCategoryValue(value, artifact), MAX_AXIS_LABEL_CHARS),
      },
    },
    visualMap: {
      min,
      max,
      calculable: false,
      orient: "horizontal",
      left: "center",
      bottom: 0,
    },
    media: buildResponsiveMedia({
      categoryAxisTarget: "xAxis",
    }),
    series: [
      {
        name: artifact.title,
        type: "heatmap",
        data: artifact.data.map((row) => [
          xCategories.indexOf(row[xField]),
          yCategories.indexOf(row[yField]),
          row[valueField],
        ]),
        emphasis: {
          itemStyle: {
            shadowBlur: 10,
            shadowColor: "rgba(0, 0, 0, 0.24)",
          },
        },
      },
    ],
  };
}

function buildTreemapOptions(artifact) {
  const categoryField = resolveCategoryField(artifact);
  const valueField = resolveValueField(artifact);

  return {
    ...buildBaseOptions(artifact),
    tooltip: buildTooltipConfig({
      trigger: "item",
      formatter: buildItemTooltipFormatter(artifact, (params, currentArtifact) => `${safeTooltipText(params.name, 48)}${TOOLTIP_LINE_BREAK}${safeTooltipText(formatMetricValue(params.value, currentArtifact), 48)}`),
    }),
    series: [
      {
        name: artifact.title,
        type: "treemap",
        roam: false,
        nodeClick: false,
        breadcrumb: { show: false },
        label: {
          formatter: ({ name }) => truncateLabelText(name, MAX_LEGEND_LABEL_CHARS),
        },
        data: artifact.data.map((row) => ({
          name: formatCategoryValue(row[categoryField], artifact),
          value: row[valueField],
        })),
      },
    ],
  };
}

function buildWaterfallOptions(artifact) {
  const categoryField = artifact.encoding.x || artifact.encoding.category;
  const valueField = artifact.encoding.value;
  const categories = buildCategoryValues(artifact.data, categoryField);
  const deltas = buildSeriesData(artifact.data, valueField);
  let runningTotal = 0;
  const baseData = [];
  const deltaData = [];

  deltas.forEach((delta) => {
    const safeDelta = typeof delta === "number" ? delta : 0;
    const baseValue = safeDelta >= 0 ? runningTotal : runningTotal + safeDelta;
    baseData.push(baseValue);
    deltaData.push(Math.abs(safeDelta));
    runningTotal += safeDelta;
  });

  return {
    ...buildBaseOptions(artifact),
    tooltip: buildTooltipConfig({
      trigger: "axis",
      axisPointer: { type: "shadow" },
      formatter: buildAxisTooltipFormatter(artifact, (value) => formatCategoryValue(value, artifact)),
    }),
    grid: buildCartesianGrid(56),
    xAxis: buildCategoryAxis(artifact, categoryField, categories),
    yAxis: buildValueAxis(artifact, valueField),
    media: buildResponsiveMedia({
      categoryAxisTarget: "xAxis",
    }),
    series: [
      {
        name: "offset",
        type: "bar",
        stack: "waterfall",
        silent: true,
        itemStyle: {
          color: "transparent",
          borderColor: "transparent",
        },
        emphasis: {
          disabled: true,
        },
        data: baseData,
      },
      {
        name: formatFieldLabel(valueField),
        type: "bar",
        stack: "waterfall",
        data: deltaData,
        itemStyle: {
          color(params) {
            return deltas[params.dataIndex] >= 0 ? "#0f9d58" : "#d83b01";
          },
        },
        emphasis: {
          focus: "series",
        },
      },
    ],
  };
}

function buildGanttOptions(artifact) {
  const taskField = artifact.encoding.task;
  const startField = artifact.encoding.start;
  const endField = artifact.encoding.end;
  const tasks = artifact.data.map((row, index) => ({
    index,
    task: row[taskField],
    start: parseTemporalValue(row[startField])?.getTime(),
    end: parseTemporalValue(row[endField])?.getTime(),
  }));

  return {
    ...buildBaseOptions(artifact),
    tooltip: buildTooltipConfig({
      trigger: "item",
      formatter: buildItemTooltipFormatter(artifact, (params, currentArtifact) => {
        const task = tasks[params.value?.[0]];
        if (!task) {
          return "";
        }
        return [
          safeTooltipText(String(task.task), 48),
          `Start: ${safeTooltipText(formatCategoryValue(task.start, currentArtifact), 48)}`,
          `End: ${safeTooltipText(formatCategoryValue(task.end, currentArtifact), 48)}`,
        ].join(TOOLTIP_LINE_BREAK);
      }),
    }),
    grid: buildCartesianGrid(56),
    xAxis: {
      type: "time",
      axisLabel: {
        formatter: (value) => formatCategoryValue(value, artifact),
      },
    },
    yAxis: {
      type: "category",
      inverse: true,
      name: resolveCategoryAxisName(artifact, taskField),
      data: tasks.map((task) => task.task),
      axisLabel: {
        width: 120,
        overflow: "truncate",
        hideOverlap: true,
        formatter: (value) => truncateLabelText(value, MAX_AXIS_LABEL_CHARS),
      },
    },
    media: buildResponsiveMedia({
      categoryAxisTarget: "yAxis",
    }),
    series: [
      {
        name: artifact.title,
        type: "custom",
        renderItem(params, api) {
          const categoryIndex = api.value(0);
          const start = api.coord([api.value(1), categoryIndex]);
          const end = api.coord([api.value(2), categoryIndex]);
          const height = api.size([0, 1])[1] * 0.6;
          const shape = {
            x: start[0],
            y: start[1] - (height / 2),
            width: Math.max(2, end[0] - start[0]),
            height,
          };
          const clipRect = globalThis.echarts?.graphic?.clipRectByRect;
          const clippedShape = typeof clipRect === "function"
            ? clipRect(shape, {
                x: params.coordSys.x,
                y: params.coordSys.y,
                width: params.coordSys.width,
                height: params.coordSys.height,
              })
            : shape;
          return clippedShape ? {
            type: "rect",
            shape: clippedShape,
            style: api.style({
              fill: DEFAULT_COLORS[categoryIndex % DEFAULT_COLORS.length],
              stroke: "rgba(7, 16, 24, 0.14)",
            }),
          } : null;
        },
        encode: {
          x: [1, 2],
          y: 0,
          tooltip: [3],
        },
        data: tasks.map((task) => [task.index, task.start, task.end, String(task.task)]),
      },
    ],
  };
}

function buildRadarOptions(artifact) {
  const metricField = artifact.encoding.x;
  const yFields = resolveYFields(artifact);
  const indicators = artifact.data.map((row) => ({
    name: formatCategoryValue(row[metricField], artifact),
    max: 0,
  }));

  let maxValue = 0;
  yFields.forEach((fieldName) => {
    artifact.data.forEach((row) => {
      if (typeof row[fieldName] === "number") {
        maxValue = Math.max(maxValue, row[fieldName]);
      }
    });
  });

  const indicatorMax = maxValue > 0 ? Math.ceil(maxValue * 1.1) : 1;
  indicators.forEach((indicator) => {
    indicator.max = indicatorMax;
  });

  return {
    ...buildBaseOptions(artifact),
    legend: buildLegendConfig(artifact, yFields.map((fieldName) => formatFieldLabel(fieldName))),
    tooltip: buildTooltipConfig({
      trigger: "item",
    }),
    media: buildResponsiveMedia({
      hasLegend: yFields.length > 1,
    }),
    radar: {
      indicator: indicators,
      radius: "64%",
    },
    series: [
      {
        name: artifact.title,
        type: "radar",
        data: yFields.map((fieldName) => ({
          name: formatFieldLabel(fieldName),
          value: artifact.data.map((row) => row[fieldName] ?? null),
        })),
      },
    ],
  };
}

export function buildTableModel(artifact) {
  const rows = artifact.data || [];
  const columnKeys = rows.length ? Object.keys(rows[0]) : [];
  const visibleRows = rows.slice(0, TABLE_MAX_ROWS);

  return {
    columns: columnKeys.map((columnKey) => ({
      key: columnKey,
      label: formatFieldLabel(columnKey),
      align: visibleRows.some((row) => typeof row[columnKey] === "number") ? "end" : "start",
    })),
    rows: visibleRows.map((row, rowIndex) => ({
      key: `${artifact.artifact_id}:${rowIndex}`,
      cells: columnKeys.map((columnKey) => ({
        key: columnKey,
        align: typeof row[columnKey] === "number" ? "end" : "start",
        text: formatTableCellValue(row[columnKey], artifact),
      })),
    })),
    notice: rows.length > TABLE_MAX_ROWS ? `Showing the first ${TABLE_MAX_ROWS} rows of ${rows.length}.` : "",
  };
}

export function buildBarOptions(artifact) {
  return buildBarFamilyOptions(artifact);
}

export function buildGroupedBarOptions(artifact) {
  return buildBarFamilyOptions(artifact);
}

export function buildStackedBarOptions(artifact) {
  return buildBarFamilyOptions(artifact, { stacked: true });
}

export function buildHorizontalBarOptions(artifact) {
  return buildBarFamilyOptions(artifact, { orientation: "horizontal" });
}

export function buildLineOptions(artifact) {
  return buildLineFamilyOptions(artifact);
}

export function buildMultiLineOptions(artifact) {
  return buildLineFamilyOptions(artifact);
}

export function buildAreaOptions(artifact) {
  return buildLineFamilyOptions(artifact, { area: true });
}

export function buildPieOptions(artifact) {
  return buildPieFamilyOptions(artifact);
}

export function buildDonutOptions(artifact) {
  return buildPieFamilyOptions(artifact, { donut: true });
}

export function registerBaseEChartsAdapters(registry) {
  const registrations = [
    ["bar", buildBarOptions],
    ["grouped_bar", buildGroupedBarOptions],
    ["stacked_bar", buildStackedBarOptions],
    ["horizontal_bar", buildHorizontalBarOptions],
    ["line", buildLineOptions],
    ["multi_line", buildMultiLineOptions],
    ["area", buildAreaOptions],
    ["pie", buildPieOptions],
    ["donut", buildDonutOptions],
    ["scatter", buildScatterOptions],
    ["bubble", buildBubbleOptions],
    ["histogram", buildHistogramOptions],
    ["box_plot", buildBoxPlotOptions],
    ["heatmap", buildHeatmapOptions],
    ["treemap", buildTreemapOptions],
    ["waterfall", buildWaterfallOptions],
    ["gantt", buildGanttOptions],
    ["radar", buildRadarOptions],
  ];

  registrations.forEach(([chartType, adapter]) => {
    registry.register({
      chartType,
      renderer: "echarts",
      specVersion: "1.0",
      adapter,
    });
  });

  registry.register({
    chartType: "table",
    renderer: "echarts",
    specVersion: "1.0",
    renderMode: "dom",
    adapter: buildTableModel,
  });

  return registry;
}