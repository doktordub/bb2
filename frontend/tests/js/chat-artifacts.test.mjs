import assert from "node:assert/strict";
import test from "node:test";

import { clearConversation } from "../../app/static/js/chat/conversation.js";
import {
  createChatVisualizationController,
  resolveChatVisualizationConfig,
  resolveHistoryArtifactReplay,
} from "../../app/static/js/chat/artifacts.js";
import { resolveVisualizationCapabilityState } from "../../app/static/js/visualization/runtime-capabilities.js";

function toDatasetKey(attributeName) {
  return attributeName
    .replace(/^data-/, "")
    .replace(/-([a-z])/g, (_, character) => character.toUpperCase());
}

function matchesSelector(element, selector) {
  const trimmed = selector.trim();
  const classMatches = [...trimmed.matchAll(/\.([a-zA-Z0-9_-]+)/g)].map((match) => match[1]);
  const attributeMatches = [...trimmed.matchAll(/\[([^\]=]+)(?:=\"([^\"]*)\")?\]/g)].map((match) => ({
    name: match[1],
    value: match[2] ?? null,
  }));

  const hasClasses = classMatches.every((className) => element.className.split(/\s+/).filter(Boolean).includes(className));
  if (!hasClasses) {
    return false;
  }

  return attributeMatches.every(({ name, value }) => {
    if (!(name in element.attributes)) {
      return false;
    }
    return value === null ? true : element.attributes[name] === value;
  });
}

function collectMatches(root, selector, matches = []) {
  for (const child of root.children) {
    if (matchesSelector(child, selector)) {
      matches.push(child);
    }
    collectMatches(child, selector, matches);
  }
  return matches;
}

function createFakeElement(tagName = "div") {
  return {
    tagName: tagName.toUpperCase(),
    className: "",
    textContent: "",
    innerHTML: "",
    dataset: {},
    attributes: {},
    children: [],
    parentNode: null,
    hidden: false,
    append(...children) {
      for (const child of children) {
        if (!child || typeof child !== "object") {
          continue;
        }
        child.parentNode = this;
        this.children.push(child);
      }
    },
    replaceChildren(...children) {
      this.children = [];
      this.append(...children);
    },
    setAttribute(name, value) {
      this.attributes[name] = String(value);
      if (name.startsWith("data-")) {
        this.dataset[toDatasetKey(name)] = String(value);
      }
    },
    remove() {
      if (!this.parentNode) {
        return;
      }
      this.parentNode.children = this.parentNode.children.filter((child) => child !== this);
      this.parentNode = null;
    },
    querySelector(selector) {
      return collectMatches(this, selector, [])[0] ?? null;
    },
    querySelectorAll(selector) {
      return collectMatches(this, selector, []);
    },
  };
}

function installFakeDom() {
  global.document = {
    createElement: (tagName) => createFakeElement(tagName),
    querySelector: () => null,
  };
}

test.afterEach(() => {
  delete global.document;
});

test("resolveChatVisualizationConfig reads chat workspace limits and falls back safely", () => {
  const config = resolveChatVisualizationConfig({
    dataset: {
      visualizationMaxArtifacts: "4",
      visualizationMaxRowsInline: "2500",
      visualizationMaxSeries: "8",
      visualizationMaxCategories: "60",
    },
  });

  assert.deepEqual(config, {
    maxArtifactsPerResponse: 4,
    maxRowsInline: 2500,
    maxSeries: 8,
    maxCategories: 60,
  });

  assert.deepEqual(resolveChatVisualizationConfig({ dataset: {} }), {
    maxArtifactsPerResponse: 3,
    maxRowsInline: 5000,
    maxSeries: 12,
    maxCategories: 100,
  });
});

test("resolveHistoryArtifactReplay prefers first-class message artifacts and falls back to legacy metadata", () => {
  const firstClassArtifact = { artifact_id: "chart-history-current-1" };
  const legacyArtifact = { artifact_id: "chart-history-legacy-1" };

  const preferred = resolveHistoryArtifactReplay({
    artifacts: [firstClassArtifact],
    metadata: {
      artifact_count: 2,
      artifact_replay_status: "partial",
      visualizations: [legacyArtifact],
    },
  });

  assert.equal(preferred.artifacts[0]?.artifact_id, "chart-history-current-1");
  assert.equal(preferred.artifactCount, 2);
  assert.equal(preferred.replayStatus, "partial");

  const fallback = resolveHistoryArtifactReplay({
    metadata: {
      artifact_count: 1,
      visualizations: [legacyArtifact],
    },
  });

  assert.equal(fallback.artifacts[0]?.artifact_id, "chart-history-legacy-1");
  assert.equal(fallback.artifactCount, 1);
  assert.equal(fallback.replayStatus, null);
});

test("chat visualization controller renders artifacts in order and enforces the configured response cap", () => {
  installFakeDom();

  const renderCalls = [];
  const disposedMessages = [];
  const renderer = {
    render(host, artifact, options) {
      renderCalls.push({ host, artifact, options });
      host.setAttribute("data-render-status", "rendered");
      return { status: "rendered", artifact, shell: { chartStatus: { textContent: "Chart ready." } } };
    },
    disposeByMessage(messageId) {
      disposedMessages.push(messageId);
      return 0;
    },
    disposeBySession() {
      return 0;
    },
    instanceStore: {
      disposeAll() {
        return 0;
      },
    },
  };

  const controller = createChatVisualizationController({
    renderer,
    config: {
      maxArtifactsPerResponse: 1,
      maxRowsInline: 2500,
      maxSeries: 8,
      maxCategories: 60,
    },
  });
  const card = createFakeElement("article");
  card.dataset.messageId = "message-1";

  controller.renderArtifacts(card, [
    { artifact_id: "chart-1", title: "Chart 1" },
    { artifact_id: "chart-2", title: "Chart 2" },
  ], { sessionId: "session-1" });

  assert.deepEqual(disposedMessages, ["message-1"]);
  assert.equal(renderCalls.length, 1);
  assert.equal(renderCalls[0].artifact.artifact_id, "chart-1");
  assert.equal(renderCalls[0].options.messageId, "message-1");
  assert.equal(renderCalls[0].options.sessionId, "session-1");
  assert.deepEqual(renderCalls[0].options.limits, {
    maxRowsInline: 2500,
    maxSeries: 8,
    maxCategories: 60,
  });
  assert.equal(card.dataset.sessionId, "session-1");

  const region = card.querySelector("[data-chat-artifacts]");
  assert.ok(region);
  assert.equal(region.children.length, 2);
  assert.match(region.children[1].textContent, /Only the first 1 of 2 visualizations were rendered/i);
});

test("chat visualization controller adds explicit fallback notices for failed artifacts", () => {
  installFakeDom();

  const controller = createChatVisualizationController({
    renderer: {
      render() {
        return {
          status: "render_error",
          artifact: { artifact_id: "chart-1" },
          shell: { chartStatus: { textContent: "Renderer failed." } },
        };
      },
      disposeByMessage() {
        return 0;
      },
      disposeBySession() {
        return 0;
      },
      instanceStore: {
        disposeAll() {
          return 0;
        },
      },
    },
  });
  const card = createFakeElement("article");
  card.dataset.messageId = "message-2";

  controller.renderArtifacts(card, [{
    artifact_id: "chart-1",
    title: "Broken chart",
    warnings: ["Backend trimmed long labels."],
  }]);

  const item = card.querySelector(".chat-message__artifact-item");
  assert.ok(item);
  assert.equal(item.querySelectorAll(".chat-message__artifact-summary").length, 2);
  assert.match(item.querySelectorAll(".chat-message__artifact-summary")[0].textContent, /Chart could not be displayed/i);
  assert.match(item.querySelectorAll(".chat-message__artifact-summary")[1].textContent, /Backend trimmed long labels/i);
});

test("chat visualization controller blocks artifacts outside runtime visualization capabilities before renderer execution", () => {
  installFakeDom();

  const renderCalls = [];
  const visualizationState = resolveVisualizationCapabilityState({
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
  const controller = createChatVisualizationController({
    renderer: {
      render(host, artifact, options) {
        renderCalls.push({ host, artifact, options });
        return {
          status: "rendered",
          artifact,
          shell: { chartStatus: { textContent: "Chart ready." } },
        };
      },
      disposeByMessage() {
        return 0;
      },
      disposeBySession() {
        return 0;
      },
      instanceStore: {
        disposeAll() {
          return 0;
        },
      },
    },
    visualizationState,
  });
  const card = createFakeElement("article");
  card.dataset.messageId = "message-capability-1";

  controller.renderArtifacts(card, [{
    artifact_id: "chart-radar-1",
    title: "Radar chart",
    chart_type: "radar",
    renderer: "echarts",
    spec_version: "1.0",
    data_mode: "inline",
  }], { sessionId: "session-1" });

  assert.equal(renderCalls.length, 0);
  const status = card.querySelector(".chart-artifact__status");
  assert.ok(status);
  assert.match(status.textContent, /not advertised by the current deployment capabilities/i);
  const notices = card.querySelectorAll(".chat-message__artifact-summary");
  assert.equal(notices.length, 1);
  assert.match(notices[0].textContent, /not advertised by the current deployment capabilities/i);
});

test("chat visualization controller replays history artifacts with multi-chart layout and collapse control", () => {
  installFakeDom();

  const renderCalls = [];
  const controller = createChatVisualizationController({
    renderer: {
      render(host, artifact, options) {
        renderCalls.push({ host, artifact, options });
        host.setAttribute("data-render-status", "rendered");
        return {
          status: "rendered",
          artifact,
          shell: { chartStatus: { textContent: "Chart ready." } },
        };
      },
      disposeByMessage() {
        return 0;
      },
      disposeBySession() {
        return 0;
      },
      instanceStore: {
        disposeAll() {
          return 0;
        },
      },
    },
  });

  const card = createFakeElement("article");
  card.dataset.messageId = "message-history-1";

  controller.renderHistoryArtifacts(card, {
    artifactCount: 2,
    sessionId: "session-history-1",
    artifacts: [
      {
        artifact_id: "chart-history-1",
        type: "chart",
        chart_type: "bar",
        title: "History 1",
        description: "Reloaded from history",
        renderer: "echarts",
        spec_version: "1.0",
        data_mode: "reference",
        data: null,
        data_ref: "/artifacts/chart-history-1",
        encoding: { x: "month", y: ["value"] },
        options: {},
        warnings: [],
        metadata: {},
      },
      {
        artifact_id: "chart-history-2",
        type: "chart",
        chart_type: "line",
        title: "History 2",
        description: "Reloaded from history",
        renderer: "echarts",
        spec_version: "1.0",
        data_mode: "reference",
        data: null,
        data_ref: "/artifacts/chart-history-2",
        encoding: { x: "month", y: ["value"] },
        options: {},
        warnings: [],
        metadata: {},
      },
    ],
  });

  assert.equal(renderCalls.length, 2);
  const region = card.querySelector("[data-chat-artifacts]");
  assert.ok(region);
  assert.match(region.className, /chat-message__artifacts--multi/);
  const toggle = card.querySelector("[data-chat-artifact-toggle]");
  assert.ok(toggle);
  assert.match(toggle.textContent, /Hide charts \(2\)/i);
});

test("chat visualization controller replays inline history artifacts from first-class message payloads", () => {
  installFakeDom();

  const renderCalls = [];
  const controller = createChatVisualizationController({
    renderer: {
      render(host, artifact, options) {
        renderCalls.push({ host, artifact, options });
        host.setAttribute("data-render-status", "rendered");
        return {
          status: "rendered",
          artifact,
          shell: { chartStatus: { textContent: "Chart ready." } },
        };
      },
      disposeByMessage() {
        return 0;
      },
      disposeBySession() {
        return 0;
      },
      instanceStore: {
        disposeAll() {
          return 0;
        },
      },
    },
  });

  const card = createFakeElement("article");
  card.dataset.messageId = "message-history-inline-1";

  controller.renderHistoryArtifacts(card, {
    artifactCount: 1,
    sessionId: "session-history-inline-1",
    artifacts: [
      {
        artifact_id: "chart-history-inline-1",
        type: "chart",
        chart_type: "bar",
        title: "History Inline",
        description: "Reloaded inline from history",
        renderer: "echarts",
        spec_version: "1.0",
        data_mode: "inline",
        data: [{ month: "Jan", revenue: 1200 }],
        data_ref: null,
        encoding: { x: "month", y: ["revenue"] },
        options: {},
        warnings: [],
        metadata: {},
      },
    ],
  });

  assert.equal(renderCalls.length, 1);
  assert.equal(renderCalls[0]?.artifact?.artifact_id, "chart-history-inline-1");
  assert.equal(renderCalls[0]?.artifact?.data_mode, "inline");
  assert.equal(card.querySelectorAll(".chat-message__artifact-summary").length, 0);
});

test("chat visualization controller shows regenerate notice when history cannot replay artifacts", () => {
  installFakeDom();

  let renderCount = 0;
  const controller = createChatVisualizationController({
    renderer: {
      render() {
        renderCount += 1;
        return {
          status: "rendered",
          shell: { chartStatus: { textContent: "Chart ready." } },
        };
      },
      disposeByMessage() {
        return 0;
      },
      disposeBySession() {
        return 0;
      },
      instanceStore: {
        disposeAll() {
          return 0;
        },
      },
    },
  });

  const card = createFakeElement("article");
  card.dataset.messageId = "message-history-2";

  controller.renderHistoryArtifacts(card, {
    artifactCount: 1,
    replayStatus: "unavailable",
    sessionId: "session-history-2",
    artifacts: [],
  });

  assert.equal(renderCount, 0);
  const region = card.querySelector("[data-chat-artifacts]");
  assert.ok(region);
  assert.match(region.children[0]?.textContent || "", /no replayable chart payload was retained in session history/i);
  assert.equal(card.querySelector("[data-chat-artifact-toggle]"), null);
});

test("chat visualization controller keeps the legacy history warning for older sessions without saved payloads", () => {
  installFakeDom();

  const controller = createChatVisualizationController({
    renderer: {
      render() {
        return {
          status: "rendered",
          shell: { chartStatus: { textContent: "Chart ready." } },
        };
      },
      disposeByMessage() {
        return 0;
      },
      disposeBySession() {
        return 0;
      },
      instanceStore: {
        disposeAll() {
          return 0;
        },
      },
    },
  });

  const card = createFakeElement("article");
  card.dataset.messageId = "message-history-legacy-1";

  controller.renderHistoryArtifacts(card, {
    artifactCount: 2,
    sessionId: "session-history-legacy-1",
    artifacts: [],
  });

  const region = card.querySelector("[data-chat-artifacts]");
  assert.ok(region);
  assert.match(region.children[0]?.textContent || "", /older saved reply/i);
  assert.match(region.children[0]?.textContent || "", /no chart payload was stored in session history/i);
});

test("chat visualization controller distinguishes reference reload failures from missing saved payloads", () => {
  installFakeDom();

  const controller = createChatVisualizationController({
    renderer: {
      render() {
        const error = new Error("Visualization data could not be loaded.");
        return {
          status: "reference_error",
          error,
          shell: { chartStatus: { textContent: error.message } },
        };
      },
      disposeByMessage() {
        return 0;
      },
      disposeBySession() {
        return 0;
      },
      instanceStore: {
        disposeAll() {
          return 0;
        },
      },
    },
  });

  const card = createFakeElement("article");
  card.dataset.messageId = "message-history-reference-error-1";

  controller.renderHistoryArtifacts(card, {
    artifactCount: 1,
    sessionId: "session-history-reference-error-1",
    artifacts: [
      {
        artifact_id: "chart-history-reference-error-1",
        type: "chart",
        chart_type: "line",
        title: "History Ref",
        description: "Reload through saved reference",
        renderer: "echarts",
        spec_version: "1.0",
        data_mode: "reference",
        data: null,
        data_ref: "/artifacts/chart-history-reference-error-1",
        encoding: { x: "month", y: ["value"] },
        options: {},
        warnings: [],
        metadata: {},
      },
    ],
  });

  const notices = card.querySelectorAll(".chat-message__artifact-summary");
  assert.equal(notices.length, 1);
  assert.match(notices[0]?.textContent || "", /Visualization data could not be loaded/i);
  assert.doesNotMatch(notices[0]?.textContent || "", /no replayable chart payload|no chart payload was stored/i);
});

test("chat visualization controller renders streamed artifacts once and ignores replayed lifecycle frames", () => {
  installFakeDom();

  const renderCalls = [];
  const controller = createChatVisualizationController({
    renderer: {
      render(host, artifact, options) {
        renderCalls.push({ host, artifact, options });
        host.setAttribute("data-render-status", "rendered");
        return {
          status: "rendered",
          artifact,
          shell: { chartStatus: { textContent: "Chart ready." } },
        };
      },
      disposeByMessage() {
        return 0;
      },
      disposeBySession() {
        return 0;
      },
      instanceStore: {
        disposeAll() {
          return 0;
        },
      },
    },
  });

  const card = createFakeElement("article");
  card.dataset.messageId = "message-stream-1";
  controller.beginStreamingMessage(card, { sessionId: "session-stream-1" });

  controller.handleStreamingArtifact(card, {
    event: "artifact.started",
    id: "evt-artifact-1-started",
    data: { artifact_id: "chart-1", type: "chart", chart_type: "bar" },
  }, { sessionId: "session-stream-1" });

  const statusBeforeRender = card.querySelector(".chart-artifact__status");
  assert.ok(statusBeforeRender);
  assert.match(statusBeforeRender.textContent, /Visualization is streaming/i);

  const completedFrame = {
    event: "artifact.completed",
    id: "evt-artifact-1-completed",
    data: {
      artifact: {
        artifact_id: "chart-1",
        type: "chart",
        chart_type: "bar",
        title: "Chart 1",
        description: "Streaming chart",
        renderer: "echarts",
        spec_version: "1.0",
        data_mode: "inline",
        data: [{ month: "Jan", value: 12 }],
        encoding: { x: "month", y: "value" },
        options: {},
        warnings: [],
        metadata: {},
      },
    },
  };
  controller.handleStreamingArtifact(card, completedFrame, { sessionId: "session-stream-1" });
  controller.handleStreamingArtifact(card, completedFrame, { sessionId: "session-stream-1" });
  controller.handleStreamingArtifact(card, {
    event: "artifact.started",
    id: "evt-artifact-1-started-replay",
    data: { artifact_id: "chart-1", type: "chart", chart_type: "bar" },
  }, { sessionId: "session-stream-1" });

  assert.equal(renderCalls.length, 1);
  assert.equal(renderCalls[0].options.messageId, "message-stream-1");
  assert.equal(renderCalls[0].options.sessionId, "session-stream-1");

  const region = card.querySelector("[data-chat-artifacts]");
  assert.ok(region);
  assert.equal(region.children.length, 1);
});

test("chat visualization controller accepts artifact lifecycle frames that reuse the same SSE id", () => {
  installFakeDom();

  const renderCalls = [];
  const controller = createChatVisualizationController({
    renderer: {
      render(host, artifact, options) {
        renderCalls.push({ host, artifact, options });
        host.setAttribute("data-render-status", "rendered");
        return {
          status: "rendered",
          artifact,
          shell: { chartStatus: { textContent: "Chart ready." } },
        };
      },
      disposeByMessage() {
        return 0;
      },
      disposeBySession() {
        return 0;
      },
      instanceStore: {
        disposeAll() {
          return 0;
        },
      },
    },
  });

  const card = createFakeElement("article");
  card.dataset.messageId = "message-stream-same-id-1";
  controller.beginStreamingMessage(card, { sessionId: "session-stream-same-id-1" });

  controller.handleStreamingArtifact(card, {
    event: "artifact.started",
    id: "chart-1",
    data: { artifact_id: "chart-1", type: "chart", chart_type: "line" },
  }, { sessionId: "session-stream-same-id-1" });

  controller.handleStreamingArtifact(card, {
    event: "artifact.completed",
    id: "chart-1",
    data: {
      artifact: {
        artifact_id: "chart-1",
        type: "chart",
        chart_type: "line",
        title: "Chart 1",
        description: "Streaming chart",
        renderer: "echarts",
        spec_version: "1.0",
        data_mode: "inline",
        data: [{ day: "2026-06-17", price: 279.21 }],
        encoding: { x: "day", y: ["price"] },
        options: {},
        warnings: [],
        metadata: {},
      },
    },
  }, { sessionId: "session-stream-same-id-1" });

  controller.handleStreamingArtifact(card, {
    event: "artifact.completed",
    id: "chart-1",
    data: {
      artifact: {
        artifact_id: "chart-1",
        type: "chart",
        chart_type: "line",
        title: "Chart 1",
        description: "Streaming chart",
        renderer: "echarts",
        spec_version: "1.0",
        data_mode: "inline",
        data: [{ day: "2026-06-17", price: 279.21 }],
        encoding: { x: "day", y: ["price"] },
        options: {},
        warnings: [],
        metadata: {},
      },
    },
  }, { sessionId: "session-stream-same-id-1" });

  assert.equal(renderCalls.length, 1);
  assert.equal(renderCalls[0].options.messageId, "message-stream-same-id-1");
  assert.equal(controller.finalizeStreamingMessage(card, { reason: "completed" }), 0);
});

test("chat visualization controller keeps streamed artifacts mounted when later payload artifacts are undefined", () => {
  installFakeDom();

  const controller = createChatVisualizationController({
    renderer: {
      render(host, artifact) {
        host.setAttribute("data-rendered-artifact-id", artifact.artifact_id);
        return {
          status: "rendered",
          artifact,
          shell: { chartStatus: { textContent: "Chart ready." } },
        };
      },
      disposeByMessage() {
        return 0;
      },
      disposeBySession() {
        return 0;
      },
      instanceStore: {
        disposeAll() {
          return 0;
        },
      },
    },
  });

  const card = createFakeElement("article");
  card.dataset.messageId = "message-stream-2";
  controller.beginStreamingMessage(card, { sessionId: "session-stream-2" });
  controller.handleStreamingArtifact(card, {
    event: "artifact.completed",
    data: {
      artifact: {
        artifact_id: "chart-keep-1",
        type: "chart",
        chart_type: "bar",
        title: "Keep me",
        description: "Streaming chart",
        renderer: "echarts",
        spec_version: "1.0",
        data_mode: "inline",
        data: [{ month: "Jan", value: 10 }],
        encoding: { x: "month", y: "value" },
        options: {},
        warnings: [],
        metadata: {},
      },
    },
  }, { sessionId: "session-stream-2" });

  controller.renderArtifacts(card, undefined, { sessionId: "session-stream-2" });

  const host = card.querySelector(".chat-message__artifact-host");
  assert.ok(host);
  assert.equal(host.dataset.artifactId, "chart-keep-1");
  assert.equal(host.dataset.sessionId, "session-stream-2");
});

test("chat visualization controller does not re-render streamed reference artifacts after loading has started", () => {
  installFakeDom();

  const renderCalls = [];
  const controller = createChatVisualizationController({
    renderer: {
      render(host, artifact, options) {
        renderCalls.push({ host, artifact, options });
        return {
          status: "loading_reference",
          artifact,
          shell: {
            chartStatus: {
              textContent: "Loading chart data...",
            },
          },
        };
      },
      disposeByMessage() {
        return 0;
      },
      disposeBySession() {
        return 0;
      },
      disposeAll() {
        return 0;
      },
      instanceStore: {
        disposeAll() {
          return 0;
        },
      },
    },
  });

  const card = createFakeElement("article");
  card.dataset.messageId = "message-stream-reference-1";
  controller.beginStreamingMessage(card, { sessionId: "session-stream-reference-1" });

  const referenceArtifact = {
    artifact_id: "chart-reference-1",
    type: "chart",
    chart_type: "line",
    title: "Reference chart",
    description: "Deferred chart rows",
    renderer: "echarts",
    spec_version: "1.0",
    data_mode: "reference",
    data: null,
    data_ref: "/ui-api/artifacts/chart-reference-1",
    encoding: { x: "month", y: ["tickets"] },
    options: {},
    warnings: [],
    metadata: {},
  };

  controller.handleStreamingArtifact(card, {
    event: "artifact.completed",
    id: "evt-reference-1",
    data: { artifact: referenceArtifact },
  }, { sessionId: "session-stream-reference-1" });

  controller.handleStreamingArtifact(card, {
    event: "artifact.completed",
    id: "evt-reference-2",
    data: { artifact: referenceArtifact },
  }, { sessionId: "session-stream-reference-1" });

  assert.equal(renderCalls.length, 1);
});

test("chat visualization controller marks unfinished streamed artifacts when streaming stops", () => {
  installFakeDom();

  const controller = createChatVisualizationController({
    renderer: {
      render() {
        throw new Error("renderer should not run for an unfinished artifact");
      },
      disposeByMessage() {
        return 0;
      },
      disposeBySession() {
        return 0;
      },
      instanceStore: {
        disposeAll() {
          return 0;
        },
      },
    },
  });

  const card = createFakeElement("article");
  card.dataset.messageId = "message-stream-3";
  controller.beginStreamingMessage(card);
  controller.handleStreamingArtifact(card, {
    event: "artifact.started",
    data: { artifact_id: "chart-pending-1", type: "chart", chart_type: "bar" },
  });

  const finalizedCount = controller.finalizeStreamingMessage(card, { reason: "aborted" });
  assert.equal(finalizedCount, 1);

  const status = card.querySelector(".chart-artifact__status");
  assert.ok(status);
  assert.match(status.textContent, /canceled before completion/i);
});

test("clearConversation disposes tracked chart artifacts before removing message cards", () => {
  const disposedMessages = [];
  const thread = createFakeElement("section");
  const card = createFakeElement("article");
  card.className = "chat-message";
  card.setAttribute("data-message-id", "message-9");
  thread.append(card);

  clearConversation({
    conversationThread: thread,
    emptyChatCard: createFakeElement("article"),
    loadingChatCard: createFakeElement("article"),
    historyTruncatedCard: createFakeElement("article"),
    chatVisualization: {
      disposeMessage(target) {
        disposedMessages.push(target.dataset.messageId);
      },
    },
  });

  assert.deepEqual(disposedMessages, ["message-9"]);
  assert.equal(thread.children.length, 0);
});