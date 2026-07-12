import assert from "node:assert/strict";
import fs from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { validateChartArtifact } from "../../app/static/js/visualization/artifact-validator.js";
import { ChartRegistry } from "../../app/static/js/visualization/chart-registry.js";
import { ChartInstanceStore } from "../../app/static/js/visualization/chart-instance-store.js";
import { ChartRenderer } from "../../app/static/js/visualization/chart-renderer.js";
import { VisualizationDataLoader } from "../../app/static/js/visualization/data-loader.js";
import {
  buildBarOptions,
  buildGroupedBarOptions,
  buildTableModel,
  registerBaseEChartsAdapters,
} from "../../app/static/js/visualization/echarts-adapter.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const workspaceRoot = path.resolve(__dirname, "../../..");
const sharedFixturePath = path.join(workspaceRoot, "backend", "tests", "fixtures", "visualization", "chart_artifact_v1.json");
const validationCasesPath = path.join(workspaceRoot, "backend", "tests", "fixtures", "visualization", "chart_validation_cases_v1.json");
const unsupportedFixturePath = path.join(workspaceRoot, "frontend", "tests", "fixtures", "visualization", "unsupported_chart_artifact_v1.json");
const referenceFixturePath = path.join(workspaceRoot, "frontend", "tests", "fixtures", "visualization", "reference_mode_artifact_provisional_v1.json");

function createFakeElement(tagName = "div") {
  return {
    tagName: tagName.toUpperCase(),
    className: "",
    textContent: "",
    innerHTML: "",
    dataset: {},
    children: [],
    attributes: {},
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
}

function createHeaders(values = {}) {
  const normalized = Object.fromEntries(
    Object.entries(values).map(([key, value]) => [key.toLowerCase(), value])
  );
  return {
    get(name) {
      return normalized[String(name).toLowerCase()] ?? null;
    },
  };
}

function installFakeDom() {
  const documentListeners = new Map();
  global.document = {
    visibilityState: "visible",
    createElement: (tagName) => createFakeElement(tagName),
    addEventListener(eventName, callback) {
      documentListeners.set(eventName, callback);
    },
    removeEventListener(eventName) {
      documentListeners.delete(eventName);
    },
  };

  const listeners = new Map();
  global.window = {
    addEventListener(eventName, callback) {
      listeners.set(eventName, callback);
    },
    removeEventListener(eventName) {
      listeners.delete(eventName);
    },
  };

  return {
    listeners,
    documentListeners,
  };
}

async function readJson(filePath) {
  return JSON.parse(await fs.readFile(filePath, "utf-8"));
}

async function readValidationCases() {
  const payload = await readJson(validationCasesPath);
  return payload.cases;
}

test.afterEach(() => {
  delete global.document;
  delete global.window;
  delete global.echarts;
  delete global.fetch;
});

test("validateChartArtifact accepts the shared grouped-bar fixture and preserves safe fields", async () => {
  const artifact = await readJson(sharedFixturePath);

  const validated = validateChartArtifact(artifact);

  assert.equal(validated.artifact_id, "chart_income_expense_last_6_months");
  assert.equal(validated.chart_type, "grouped_bar");
  assert.equal(validated.data.length, 6);
  assert.deepEqual(validated.encoding.y, ["income", "expense"]);
  assert.equal(validated.options.currency, "USD");
});

test("validateChartArtifact rejects unsupported chart types with a safe error", async () => {
  const artifact = await readJson(unsupportedFixturePath);

  assert.throws(
    () => validateChartArtifact(artifact),
    (error) => error.code === "unsupported_chart_type"
  );
});

test("validateChartArtifact rejects blocked object keys anywhere in the artifact payload", async () => {
  const artifact = await readJson(sharedFixturePath);
  artifact.metadata = JSON.parse('{"__proto__":{"polluted":true}}');

  assert.throws(
    () => validateChartArtifact(artifact),
    (error) => error.code === "unsafe_object_keys"
  );
});

test("validateChartArtifact accepts same-origin reference mode artifacts and rejects unsafe data refs", async () => {
  const artifact = await readJson(referenceFixturePath);
  const validated = validateChartArtifact(artifact);

  assert.equal(validated.data_mode, "reference");
  assert.equal(validated.data_ref, "/ui-api/artifacts/chart_ticket_volume_24_months");

  artifact.data_ref = "javascript:alert(1)";
  assert.throws(
    () => validateChartArtifact(artifact),
    (error) => error.code === "unsafe_data_ref"
  );
});

test("VisualizationDataLoader uses the standard API client with session headers and caches authorized artifact fetches", async () => {
  const referenceArtifact = await readJson(referenceFixturePath);
  const inlineArtifact = {
    ...referenceArtifact,
    data_mode: "inline",
    data: [
      { month: "2025-01", tickets: 24 },
      { month: "2025-02", tickets: 31 },
      { month: "2025-03", tickets: 29 },
    ],
    data_ref: null,
  };

  global.document = {
    body: {
      dataset: {
        uiApiBase: "/ui-api",
      },
    },
  };

  const fetchCalls = [];
  global.fetch = async (url, options) => {
    fetchCalls.push({ url, options });
    return {
      ok: true,
      headers: createHeaders({
        "content-type": "application/json",
        "cache-control": "private, max-age=60",
        etag: '"chart_ticket_volume_24_months-v1"',
      }),
      async json() {
        return {
          schema_version: "1.0",
          trace_id: "trace-reference-loader-1",
          session_id: "session-reference-1",
          data: inlineArtifact,
          metadata: {
            return_type: "artifact",
          },
        };
      },
      async text() {
        return "";
      },
    };
  };

  const loader = new VisualizationDataLoader();
  const first = await loader.loadArtifact(referenceArtifact, {
    sessionId: "session-reference-1",
  });
  const second = await loader.loadArtifact(referenceArtifact, {
    sessionId: "session-reference-1",
  });

  assert.equal(fetchCalls.length, 1);
  assert.equal(fetchCalls[0].url, "/ui-api/artifacts/chart_ticket_volume_24_months");
  assert.equal(fetchCalls[0].options.credentials, "same-origin");
  assert.equal(fetchCalls[0].options.headers["X-Session-Id"], "session-reference-1");
  assert.equal(first.data_mode, "inline");
  assert.deepEqual(second.data, first.data);
});

test("buildGroupedBarOptions uses only artifact-owned fields to produce local ECharts options", async () => {
  const artifact = validateChartArtifact(await readJson(sharedFixturePath));

  const options = buildGroupedBarOptions(artifact);
  const tooltipText = options.tooltip.formatter([
    { axisValue: "Jan", seriesName: "Income", value: 145000 },
    { axisValue: "Jan", seriesName: "Expense", value: 98000 },
  ]);

  assert.equal(options.xAxis.type, "category");
  assert.deepEqual(options.xAxis.data, ["Jan", "Feb", "Mar", "Apr", "May", "Jun"]);
  assert.equal(options.series.length, 2);
  assert.equal(options.series[0].type, "bar");
  assert.equal(options.legend.data[0], "Income");
  assert.equal(options.tooltip.renderMode, "richText");
  assert.match(tooltipText, /\n/);
  assert.doesNotMatch(tooltipText, /<br\s*\/?/i);
  assert.equal(options.xAxis.axisLabel.overflow, "truncate");
  assert.equal(options.media[0].query.maxWidth, 640);
  assert.equal(options.media[0].option.legend.type, "scroll");
});

test("radar chart adapters use rich-text tooltips so strict CSP does not require inline tooltip styles", async () => {
  const cases = await readValidationCases();
  const radarArtifact = validateChartArtifact(structuredClone(cases.find((entry) => entry.chart_type === "radar")?.artifact));
  const registry = registerBaseEChartsAdapters(new ChartRegistry());

  const options = registry.resolve(radarArtifact).adapter(radarArtifact);

  assert.equal(options.tooltip.trigger, "item");
  assert.equal(options.tooltip.renderMode, "richText");
});

test("validateChartArtifact accepts every shared V1 chart validation case", async () => {
  const cases = await readValidationCases();

  for (const entry of cases) {
    const validated = validateChartArtifact(entry.artifact);
    assert.equal(validated.chart_type, entry.chart_type);
  }
});

test("validateChartArtifact rejects incomplete grouped adapters that lack multi-series encoding", async () => {
  const cases = await readValidationCases();
  const groupedBar = structuredClone(cases.find((entry) => entry.chart_type === "grouped_bar")?.artifact);

  groupedBar.encoding = {
    x: "month",
    y: ["income"],
  };

  assert.throws(
    () => validateChartArtifact(groupedBar),
    (error) => error.code === "invalid_encoding"
  );
});

test("validateChartArtifact keeps non-temporal line categories valid when no explicit time field is present", async () => {
  const cases = await readValidationCases();
  const line = structuredClone(cases.find((entry) => entry.chart_type === "line")?.artifact);
  line.data = [
    { segment: "Bronze", signups: 42 },
    { segment: "Silver", signups: 45 },
    { segment: "Gold", signups: 51 },
  ];
  line.encoding = { x: "segment", y: ["signups"] };

  const validated = validateChartArtifact(line);

  assert.equal(validated.encoding.x, "segment");
  assert.equal(validated.data.length, 3);
});

test("buildBarOptions preserves null values and bounded long labels without changing numeric meaning", async () => {
  const cases = await readValidationCases();
  const bar = structuredClone(cases.find((entry) => entry.chart_type === "bar")?.artifact);
  bar.data[1].revenue = null;
  bar.data[0].month = "M".repeat(512);

  const validated = validateChartArtifact(bar);
  const options = buildBarOptions(validated);

  assert.equal(options.series[0].data[1], null);
  assert.equal(options.xAxis.data[0].length, 512);
});

test("buildTableModel creates a semantic table payload with numeric alignment and row-limit notice", () => {
  const artifact = validateChartArtifact({
    artifact_id: "chart_table_large",
    type: "chart",
    chart_type: "table",
    title: "Table",
    description: "Large table",
    renderer: "echarts",
    spec_version: "1.0",
    data_mode: "inline",
    data: Array.from({ length: 28 }, (_, index) => ({
      month: `2026-${String(index + 1).padStart(2, "0")}`,
      revenue: 1000 + index,
    })),
    encoding: {},
    options: { currency: "USD" },
    warnings: [],
    metadata: {},
  });

  const model = buildTableModel(artifact);

  assert.equal(model.columns.length, 2);
  assert.equal(model.columns[1].align, "end");
  assert.equal(model.rows.length, 25);
  assert.match(model.notice, /Showing the first 25 rows/i);
});

test("ChartRegistry rejects duplicate registrations and exposes supported types", () => {
  const registry = registerBaseEChartsAdapters(new ChartRegistry());

  assert.equal(registry.listSupported().length, 19);
  assert.deepEqual(registry.listSupported()[0], {
    chartType: "bar",
    renderer: "echarts",
    specVersion: "1.0",
  });
  assert.equal(registry.resolve({ chart_type: "table", renderer: "echarts", spec_version: "1.0" }).renderMode, "dom");
  assert.throws(
    () => registerBaseEChartsAdapters(registry),
    /already registered/
  );
});

test("ChartRenderer renders the shared fixture into an isolated chart shell and reuses the tracked instance lifecycle", async () => {
  installFakeDom();

  const initCalls = [];
  const chartRecords = [];
  global.echarts = {
    graphic: {
      clipRectByRect(shape) {
        return shape;
      },
    },
    init(element) {
      initCalls.push(element);
      const record = {
        element,
        options: [],
        resized: 0,
        disposed: 0,
        setOption(option) {
          this.options.push(option);
        },
        resize() {
          this.resized += 1;
        },
        dispose() {
          this.disposed += 1;
        },
      };
      chartRecords.push(record);
      return record;
    },
  };

  const telemetryEvents = [];
  const renderer = new ChartRenderer({
    instanceStore: new ChartInstanceStore(),
    telemetry: {
      record(name, payload) {
        telemetryEvents.push({ name, payload });
      },
    },
  });

  const artifact = await readJson(sharedFixturePath);
  const container = createFakeElement("figure");
  const firstHandle = renderer.render(container, artifact, {
    sessionId: "session-1",
    messageId: "message-1",
  });

  assert.equal(firstHandle.status, "rendered");
  assert.equal(initCalls.length, 1);
  assert.equal(container.dataset.chartArtifact, "true");
  assert.match(firstHandle.shell.summaryNode.textContent, /grouped bar chart/i);
  assert.equal(firstHandle.shell.chartCanvas.attributes.role, "img");
  assert.equal(firstHandle.shell.chartStatus.attributes.role, "status");
  assert.equal(firstHandle.shell.chartStatus.textContent, "Chart ready.");
  assert.equal(chartRecords[0].options.length, 1);
  assert.equal(telemetryEvents[0].payload.status, "rendered");

  firstHandle.resize();
  assert.equal(chartRecords[0].resized, 1);

  const secondContainer = createFakeElement("figure");
  const secondHandle = renderer.render(secondContainer, artifact, {
    sessionId: "session-1",
    messageId: "message-2",
  });

  assert.equal(secondHandle.status, "rendered");
  assert.equal(initCalls.length, 2);
  assert.equal(chartRecords[0].disposed, 1);

  assert.equal(renderer.disposeBySession("session-1"), 1);
  assert.equal(chartRecords[1].disposed, 1);
});

test("ChartRenderer debounces ResizeObserver callbacks and resizes again when the page becomes visible", async () => {
  const { listeners, documentListeners } = installFakeDom();

  const observers = [];
  global.ResizeObserver = class FakeResizeObserver {
    constructor(callback) {
      this.callback = callback;
      this.observed = [];
      this.disconnected = false;
      observers.push(this);
    }

    observe(target) {
      this.observed.push(target);
    }

    disconnect() {
      this.disconnected = true;
    }

    trigger(entries = []) {
      this.callback(entries);
    }
  };

  let resizeCount = 0;
  global.echarts = {
    graphic: {
      clipRectByRect(shape) {
        return shape;
      },
    },
    init() {
      return {
        setOption() {},
        resize() {
          resizeCount += 1;
        },
        dispose() {},
      };
    },
  };

  const renderer = new ChartRenderer();
  const artifact = await readJson(sharedFixturePath);
  const handle = renderer.render(createFakeElement("figure"), artifact, {
    sessionId: "session-resize-1",
    messageId: "message-resize-1",
  });

  assert.equal(handle.status, "rendered");
  assert.equal(observers.length, 1);
  assert.equal(observers[0].observed[0], handle.shell.chartCanvas);
  assert.equal(typeof listeners.get("resize"), "function");
  assert.equal(typeof documentListeners.get("visibilitychange"), "function");

  observers[0].trigger([{ target: handle.shell.chartCanvas }]);
  observers[0].trigger([{ target: handle.shell.chartCanvas }]);
  await new Promise((resolve) => setTimeout(resolve, 120));
  assert.equal(resizeCount, 1);

  global.document.visibilityState = "visible";
  documentListeners.get("visibilitychange")();
  await new Promise((resolve) => setTimeout(resolve, 120));
  assert.equal(resizeCount, 2);

  handle.dispose();
  assert.equal(observers[0].disconnected, true);
  assert.equal(listeners.has("resize"), false);
  assert.equal(documentListeners.has("visibilitychange"), false);
});

test("ChartRenderer resolves reference artifacts through the data loader and renders them into the existing shell", async () => {
  installFakeDom();

  const initCalls = [];
  global.echarts = {
    graphic: {
      clipRectByRect(shape) {
        return shape;
      },
    },
    init(element) {
      initCalls.push(element);
      return {
        element,
        options: [],
        setOption(option) {
          this.options.push(option);
        },
        resize() {},
        dispose() {},
      };
    },
  };

  const referenceArtifact = await readJson(referenceFixturePath);
  const inlineArtifact = {
    ...referenceArtifact,
    data_mode: "inline",
    data: [
      { month: "2025-01", tickets: 24 },
      { month: "2025-02", tickets: 31 },
      { month: "2025-03", tickets: 29 },
    ],
    data_ref: null,
  };
  const renderer = new ChartRenderer({
    dataLoader: {
      async loadArtifact() {
        return inlineArtifact;
      },
      clearSession() {
        return 0;
      },
      clearAll() {
        return 0;
      },
    },
  });

  const container = createFakeElement("figure");
  const handle = renderer.render(container, referenceArtifact, {
    sessionId: "session-reference-2",
    messageId: "message-reference-2",
  });

  assert.equal(handle.status, "loading_reference");
  assert.match(handle.shell.chartStatus.textContent, /loading chart data/i);

  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(initCalls.length, 1);
  assert.equal(handle.shell.chartStatus.textContent, "Chart ready.");
  assert.equal(container.dataset.chartArtifact, "true");
});

test("ChartRenderer aborts pending reference loads when the artifact is disposed", async () => {
  installFakeDom();

  const referenceArtifact = await readJson(referenceFixturePath);
  let capturedSignal = null;
  const renderer = new ChartRenderer({
    dataLoader: {
      loadArtifact(_artifact, { signal }) {
        capturedSignal = signal;
        return new Promise(() => {});
      },
      clearSession() {
        return 0;
      },
      clearAll() {
        return 0;
      },
    },
  });

  const handle = renderer.render(createFakeElement("figure"), referenceArtifact, {
    sessionId: "session-reference-3",
    messageId: "message-reference-3",
  });

  assert.equal(handle.status, "loading_reference");
  assert.equal(capturedSignal?.aborted, false);
  assert.equal(renderer.dispose(referenceArtifact.artifact_id), true);
  assert.equal(capturedSignal?.aborted, true);
});

test("ChartRenderer renders every shared V1 validation case and uses DOM rendering only for table artifacts", async () => {
  installFakeDom();

  const initCalls = [];
  global.echarts = {
    graphic: {
      clipRectByRect(shape) {
        return shape;
      },
    },
    init(element) {
      initCalls.push(element);
      return {
        element,
        options: [],
        setOption(option) {
          this.options.push(option);
        },
        resize() {},
        dispose() {},
      };
    },
  };

  const cases = await readValidationCases();
  const renderer = new ChartRenderer();
  const handles = cases.map((entry, index) => renderer.render(createFakeElement("figure"), entry.artifact, {
    sessionId: "session-matrix",
    messageId: `message-${index + 1}`,
  }));

  handles.forEach((handle) => assert.equal(handle.status, "rendered"));
  assert.equal(initCalls.length, cases.length - 1);
  const tableHandle = handles.find((handle) => handle.artifact.chart_type === "table");
  assert.equal(tableHandle.shell.chartCanvas.children.length > 0, true);
  assert.equal(tableHandle.shell.chartCanvas.attributes.role, undefined);
  assert.equal(renderer.disposeBySession("session-matrix"), cases.length);
});

test("ChartRenderer renders a safe validation error without touching the ECharts runtime", async () => {
  installFakeDom();
  let initCount = 0;
  global.echarts = {
    init() {
      initCount += 1;
      throw new Error("init should not be called");
    },
  };

  const artifact = await readJson(sharedFixturePath);
  artifact.data[0].income = Number.POSITIVE_INFINITY;

  const renderer = new ChartRenderer();
  const container = createFakeElement("figure");
  const handle = renderer.render(container, artifact);

  assert.equal(handle.status, "validation_error");
  assert.equal(initCount, 0);
  assert.match(handle.shell.chartStatus.textContent, /finite number/i);
});