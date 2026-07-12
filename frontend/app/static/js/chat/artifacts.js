import { ChartRenderer } from "../visualization/chart-renderer.js";
import { mountChartScaffold, renderChartError, renderChartLoading } from "../visualization/chart-components.js";
import { evaluateVisualizationArtifactCompatibility } from "../visualization/runtime-capabilities.js";

const DEFAULT_CHAT_VISUALIZATION_CONFIG = Object.freeze({
  maxArtifactsPerResponse: 3,
  maxRowsInline: 5000,
  maxSeries: 12,
  maxCategories: 100,
});

const DEFAULT_STREAM_ARTIFACT_LIMITS = Object.freeze({
  maxBufferedEvents: 24,
  maxBufferedPayloadBytes: 131072,
});

function parsePositiveInt(value, fallback) {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function resolveConfigSource(source) {
  if (source && typeof source === "object") {
    if (source.dataset && typeof source.dataset === "object") {
      return source.dataset;
    }
    return source;
  }

  if (typeof document !== "undefined") {
    return document.querySelector("[data-chat-workspace]")?.dataset ?? {};
  }

  return {};
}

function buildRenderLimits(config) {
  return {
    maxRowsInline: config.maxRowsInline,
    maxSeries: config.maxSeries,
    maxCategories: config.maxCategories,
  };
}

function resolveMessageId(card) {
  return typeof card?.dataset?.messageId === "string" && card.dataset.messageId
    ? card.dataset.messageId
    : null;
}

function findArtifactRegion(card) {
  if (typeof card?.querySelector === "function") {
    return card.querySelector("[data-chat-artifacts]");
  }
  return card?._artifactRegion ?? null;
}

function findArtifactToggle(card) {
  if (typeof card?.querySelector === "function") {
    return card.querySelector("[data-chat-artifact-toggle]");
  }
  return card?._artifactToggle ?? null;
}

function removeArtifactRegion(card) {
  const region = findArtifactRegion(card);
  region?.remove?.();
  if (card && card._artifactRegion === region) {
    card._artifactRegion = null;
  }
  const toggle = findArtifactToggle(card);
  toggle?.remove?.();
  if (card && card._artifactToggle === toggle) {
    card._artifactToggle = null;
  }
}

function ensureArtifactRegion(card) {
  const existing = findArtifactRegion(card);
  if (existing) {
    existing.hidden = false;
    existing.replaceChildren();
    return existing;
  }

  const section = document.createElement("section");
  section.className = "chat-message__artifacts";
  section.setAttribute("aria-label", "Visualizations");
  section.setAttribute("data-chat-artifacts", "true");
  card.append(section);
  card._artifactRegion = section;
  return section;
}

function createArtifactItem() {
  const item = document.createElement("div");
  item.className = "chat-message__artifact-item";
  return item;
}

function createArtifactHost({ artifactId, messageId, sessionId }) {
  const figure = document.createElement("figure");
  figure.className = "chat-message__artifact-host";
  figure.dataset.artifactId = artifactId;
  figure.dataset.messageId = messageId;
  if (sessionId) {
    figure.dataset.sessionId = sessionId;
  }
  return figure;
}

function createArtifactNotice(message, tone = "warning") {
  const notice = document.createElement("p");
  notice.className = `chat-message__artifact-summary chat-message__artifact-summary--${tone}`;
  notice.textContent = message;
  return notice;
}

function normalizeArtifactCount(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? Math.trunc(parsed) : 0;
}

function normalizeHistoryArtifactList(value) {
  return Array.isArray(value) ? value.filter(Boolean) : [];
}

function normalizeReplayStatus(value) {
  if (typeof value !== "string") {
    return null;
  }

  const normalized = value.trim().toLowerCase();
  return normalized || null;
}

function buildLegacyHistoryArtifactNotice(artifactCount) {
  return `This older saved reply referenced ${artifactCount} visualization${artifactCount === 1 ? "" : "s"}, but no chart payload was stored in session history. Regenerate the chart in this session to view it again.`;
}

function buildUnavailableHistoryArtifactNotice(artifactCount, replayStatus) {
  if (replayStatus === "disabled") {
    return `This saved reply referenced ${artifactCount} visualization${artifactCount === 1 ? "" : "s"}, but visualization history replay was disabled when it was saved. Regenerate the chart in this session to view it again.`;
  }

  if (replayStatus === "unavailable") {
    return `This saved reply referenced ${artifactCount} visualization${artifactCount === 1 ? "" : "s"}, but no replayable chart payload was retained in session history. Regenerate the chart in this session to view it again.`;
  }

  return buildLegacyHistoryArtifactNotice(artifactCount);
}

function buildPartialHistoryArtifactNotice(unavailableCount) {
  return `${unavailableCount} saved visualization${unavailableCount === 1 ? "" : "s"} did not include replay data in session history. Regenerate the chart if you need the full result again.`;
}

export function resolveHistoryArtifactReplay(message = null) {
  const metadata = message?.metadata && typeof message.metadata === "object"
    ? message.metadata
    : {};
  const firstClassArtifacts = normalizeHistoryArtifactList(message?.artifacts);
  const compatibilityArtifacts = normalizeHistoryArtifactList(metadata.visualizations);
  const artifacts = firstClassArtifacts.length ? firstClassArtifacts : compatibilityArtifacts;
  const artifactCount = normalizeArtifactCount(metadata.artifact_count || artifacts.length) || artifacts.length;

  return {
    artifacts,
    artifactCount,
    replayStatus: normalizeReplayStatus(metadata.artifact_replay_status),
    replayReason: typeof metadata.artifact_replay_reason === "string" && metadata.artifact_replay_reason.trim()
      ? metadata.artifact_replay_reason.trim()
      : null,
  };
}

function setCardSessionId(card, sessionId = null) {
  if (!card?.dataset || !sessionId) {
    return true;
  }

  const lockedSessionId = typeof card.dataset.sessionId === "string" && card.dataset.sessionId
    ? card.dataset.sessionId
    : null;
  if (lockedSessionId && lockedSessionId !== sessionId) {
    return false;
  }

  card.dataset.sessionId = sessionId;
  return true;
}

function applyArtifactLayout(region, artifactCount) {
  const normalizedCount = normalizeArtifactCount(artifactCount);
  const layoutClass = normalizedCount > 1
    ? "chat-message__artifacts chat-message__artifacts--multi"
    : "chat-message__artifacts chat-message__artifacts--single";
  region.className = layoutClass;
}

function syncArtifactToggle(card, artifactCount, collapsed = false) {
  const normalizedCount = normalizeArtifactCount(artifactCount);
  if (!normalizedCount) {
    const existingToggle = findArtifactToggle(card);
    existingToggle?.remove?.();
    if (card && card._artifactToggle === existingToggle) {
      card._artifactToggle = null;
    }
    return null;
  }

  let toggle = findArtifactToggle(card);
  if (!toggle) {
    toggle = document.createElement("button");
    toggle.className = "btn btn-shell btn-shell--compact chat-message__artifact-toggle";
    toggle.type = "button";
    toggle.setAttribute("data-chat-artifact-toggle", "true");
    if (typeof toggle.addEventListener === "function") {
      toggle.addEventListener("click", () => {
        const region = findArtifactRegion(card);
        if (!region) {
          return;
        }
        const nextCollapsed = !region.hidden;
        region.hidden = nextCollapsed;
        syncArtifactToggle(card, normalizedCount, nextCollapsed);
      });
    }
    card.append(toggle);
    card._artifactToggle = toggle;
  }

  toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
  toggle.textContent = `${collapsed ? "Show" : "Hide"} ${normalizedCount === 1 ? "chart" : "charts"} (${normalizedCount})`;
  return toggle;
}

function setArtifactHostContext(host, { messageId = null, sessionId = null } = {}) {
  if (!host?.dataset) {
    return false;
  }

  if (messageId) {
    host.dataset.messageId = messageId;
  }
  if (sessionId) {
    const lockedSessionId = typeof host.dataset.sessionId === "string" && host.dataset.sessionId
      ? host.dataset.sessionId
      : null;
    if (lockedSessionId && lockedSessionId !== sessionId) {
      return false;
    }
    host.dataset.sessionId = sessionId;
  }

  return true;
}

function estimatePayloadBytes(value) {
  if (value == null) {
    return 0;
  }

  try {
    const serialized = JSON.stringify(value);
    if (typeof serialized !== "string") {
      return 0;
    }
    return new TextEncoder().encode(serialized).length;
  } catch (_error) {
    return 0;
  }
}

function resolveArtifactId(candidate) {
  if (typeof candidate?.artifact_id === "string" && candidate.artifact_id.trim()) {
    return candidate.artifact_id.trim();
  }

  if (typeof candidate?.artifact?.artifact_id === "string" && candidate.artifact.artifact_id.trim()) {
    return candidate.artifact.artifact_id.trim();
  }

  return null;
}

function resolveStreamFrameKey(frame) {
  if (typeof frame?.id !== "string" || !frame.id) {
    return null;
  }

  const eventName = typeof frame?.event === "string" && frame.event
    ? frame.event
    : "message";
  return `${eventName}:${frame.id}`;
}

function collectWarnings(artifactCandidate) {
  if (!Array.isArray(artifactCandidate?.warnings)) {
    return [];
  }

  return artifactCandidate.warnings
    .filter((warning) => typeof warning === "string" && warning.trim())
    .slice(0, 8);
}

function isFailureStatus(status) {
  return status === "validation_error"
    || status === "render_error"
    || status === "unsupported"
    || status === "reference_error";
}

function isTerminalStreamStatus(status) {
  return status === "rendered"
    || status === "updated"
    || status === "empty"
    || status === "deferred_data"
    || status === "deferred"
    || status === "loading_reference";
}

function recordCompatibilityTelemetry(renderer, artifactCandidate, result) {
  renderer?.telemetry?.record?.("visualization.render", {
    artifactId: artifactCandidate?.artifact_id || null,
    chartType: artifactCandidate?.chart_type || null,
    renderer: artifactCandidate?.renderer || null,
    specVersion: artifactCandidate?.spec_version || null,
    status: "unsupported",
    errorCode: result?.code || "unsupported_client_chart_type",
  });
}

function buildBlockedHandle(host, artifactCandidate, result) {
  const shell = mountChartScaffold(host, {
    title: artifactCandidate?.title || "Visualization",
    description: artifactCandidate?.description || "",
  });
  renderChartError(shell, result?.message || "This visualization is not supported in the current frontend build.");
  const error = new Error(result?.message || "Visualization is not supported.");
  error.code = result?.code || "unsupported_client_chart_type";
  return {
    artifact: artifactCandidate,
    shell,
    status: "unsupported",
    error,
    chart: null,
    resize: () => null,
    dispose: () => false,
  };
}

export function resolveChatVisualizationConfig(source = null) {
  const configSource = resolveConfigSource(source);

  return {
    maxArtifactsPerResponse: parsePositiveInt(
      configSource.visualizationMaxArtifacts,
      DEFAULT_CHAT_VISUALIZATION_CONFIG.maxArtifactsPerResponse
    ),
    maxRowsInline: parsePositiveInt(
      configSource.visualizationMaxRowsInline,
      DEFAULT_CHAT_VISUALIZATION_CONFIG.maxRowsInline
    ),
    maxSeries: parsePositiveInt(
      configSource.visualizationMaxSeries,
      DEFAULT_CHAT_VISUALIZATION_CONFIG.maxSeries
    ),
    maxCategories: parsePositiveInt(
      configSource.visualizationMaxCategories,
      DEFAULT_CHAT_VISUALIZATION_CONFIG.maxCategories
    ),
  };
}

export function createChatVisualizationController({ renderer = null, config = null, visualizationState = null } = {}) {
  const resolvedRenderer = renderer || new ChartRenderer();
  const resolvedConfig = {
    ...DEFAULT_CHAT_VISUALIZATION_CONFIG,
    ...(config || resolveChatVisualizationConfig()),
  };
  const streamStates = new Map();
  const lazyRenders = new Map();

  function cancelLazyKey(key) {
    const entry = lazyRenders.get(key);
    if (!entry) {
      return false;
    }

    entry.observer?.disconnect?.();
    lazyRenders.delete(key);
    return true;
  }

  function cancelLazyBy(predicate) {
    const matchingKeys = Array.from(lazyRenders.entries())
      .filter(([, entry]) => predicate(entry))
      .map(([key]) => key);
    matchingKeys.forEach((key) => cancelLazyKey(key));
    return matchingKeys.length;
  }

  function buildLazyKey(messageId, artifactId) {
    return `${messageId || "message"}::${artifactId}`;
  }

  function renderArtifact(host, artifactCandidate, { sessionId = null, messageId = null, lazy = true } = {}) {
    const compatibility = evaluateVisualizationArtifactCompatibility(artifactCandidate, visualizationState);
    if (!compatibility.allowed) {
      recordCompatibilityTelemetry(resolvedRenderer, artifactCandidate, compatibility);
      return buildBlockedHandle(host, artifactCandidate, compatibility);
    }

    const limits = buildRenderLimits(resolvedConfig);
    const artifactId = resolveArtifactId(artifactCandidate) || `${messageId || "message"}-artifact`;

    const renderNow = () => {
      cancelLazyKey(buildLazyKey(messageId, artifactId));
      return resolvedRenderer.render(host, artifactCandidate, {
        sessionId,
        messageId,
        limits,
      });
    };

    if (!lazy || typeof globalThis.IntersectionObserver !== "function") {
      return renderNow();
    }

    const shell = mountChartScaffold(host, {
      title: artifactCandidate?.title || "Visualization",
      description: artifactCandidate?.description || "",
    });
    renderChartLoading(shell, "Visualization will render when visible.");

    const lazyKey = buildLazyKey(messageId, artifactId);
    const observer = new globalThis.IntersectionObserver((entries) => {
      if (!Array.isArray(entries) || !entries.some((entry) => entry?.isIntersecting)) {
        return;
      }
      renderNow();
    }, { rootMargin: "160px 0px" });
    observer.observe(host);

    lazyRenders.set(lazyKey, {
      key: lazyKey,
      observer,
      messageId,
      sessionId,
    });

    return {
      artifact: artifactCandidate,
      shell,
      status: "deferred",
      dispose: () => cancelLazyKey(lazyKey),
    };
  }

  function resolveMessageKey(card, messageId = null) {
    return messageId || resolveMessageId(card);
  }

  function ensureStreamState(card, { messageId = null, sessionId = null } = {}) {
    const resolvedMessageId = resolveMessageKey(card, messageId);
    if (!resolvedMessageId) {
      return null;
    }

    let state = streamStates.get(resolvedMessageId);
    if (!state) {
      state = {
        messageId: resolvedMessageId,
        card: null,
        sessionId: null,
        artifacts: new Map(),
        seenFrameKeys: new Set(),
        bufferedEvents: [],
        bufferedBytes: 0,
      };
      streamStates.set(resolvedMessageId, state);
    }

    if (card && typeof card === "object") {
      state.card = card;
    }

    const resolvedSessionId = sessionId
      || (typeof card?.dataset?.sessionId === "string" && card.dataset.sessionId ? card.dataset.sessionId : null)
      || state.sessionId
      || null;

    if (resolvedSessionId && state.card && !setCardSessionId(state.card, resolvedSessionId)) {
      return null;
    }
    state.sessionId = resolvedSessionId;

    return state;
  }

  function ensureStreamArtifact(state, artifactId) {
    let artifactState = state.artifacts.get(artifactId);
    if (artifactState) {
      setArtifactHostContext(artifactState.host, {
        messageId: state.messageId,
        sessionId: state.sessionId,
      });
      return artifactState;
    }

    if (!state.card) {
      return null;
    }

    const region = ensureArtifactRegion(state.card);
    const item = createArtifactItem();
    const host = createArtifactHost({
      artifactId,
      messageId: state.messageId,
      sessionId: state.sessionId,
    });
    item.append(host);
    region.append(item);
    applyArtifactLayout(region, state.artifacts.size + 1);
    syncArtifactToggle(state.card, state.artifacts.size + 1, false);

    artifactState = {
      artifactId,
      item,
      host,
      shell: null,
      stage: "pending",
      handle: null,
    };
    state.artifacts.set(artifactId, artifactState);
    return artifactState;
  }

  function renderStreamPlaceholder(artifactState, message = "Visualization is streaming...") {
    const shell = mountChartScaffold(artifactState.host, {
      title: "Visualization",
      description: "",
    });
    renderChartLoading(shell, message);
    artifactState.shell = shell;
    artifactState.stage = "started";
    return shell;
  }

  function renderStreamFailure(artifactState, message) {
    const shell = artifactState.shell || mountChartScaffold(artifactState.host, {
      title: "Visualization",
      description: "",
    });
    renderChartError(shell, message || "Chart could not be displayed.");
    artifactState.shell = shell;
    artifactState.stage = "failed";
    return shell;
  }

  function bufferStreamFrame(state, frame, sessionId) {
    const size = estimatePayloadBytes(frame?.data);
    if (size > DEFAULT_STREAM_ARTIFACT_LIMITS.maxBufferedPayloadBytes) {
      return false;
    }

    while (
      state.bufferedEvents.length >= DEFAULT_STREAM_ARTIFACT_LIMITS.maxBufferedEvents
      || state.bufferedBytes + size > DEFAULT_STREAM_ARTIFACT_LIMITS.maxBufferedPayloadBytes
    ) {
      const dropped = state.bufferedEvents.shift();
      state.bufferedBytes -= dropped?.size || 0;
    }

    state.bufferedEvents.push({ frame, sessionId, size });
    state.bufferedBytes += size;
    return true;
  }

  function applyStreamFrame(state, frame, { sessionId = null } = {}) {
    if (!state) {
      return false;
    }

    if (sessionId) {
      state.sessionId = sessionId;
      if (state.card && !setCardSessionId(state.card, sessionId)) {
        return false;
      }
    }

    if (!state.card) {
      return bufferStreamFrame(state, frame, sessionId);
    }

    const frameKey = resolveStreamFrameKey(frame);
    if (frameKey) {
      if (state.seenFrameKeys.has(frameKey)) {
        return true;
      }
      state.seenFrameKeys.add(frameKey);
    }

    if (frame.event === "artifact.started") {
      const artifactId = resolveArtifactId(frame.data);
      if (!artifactId) {
        return false;
      }

      const artifactState = ensureStreamArtifact(state, artifactId);
      if (!artifactState || artifactState.stage === "completed") {
        return true;
      }

      if (artifactState.stage !== "started") {
        renderStreamPlaceholder(artifactState);
      }
      return true;
    }

    if (frame.event === "artifact.completed") {
      const artifact = frame.data?.artifact;
      const artifactId = resolveArtifactId(artifact);
      if (!artifact || typeof artifact !== "object" || !artifactId) {
        return false;
      }

      const artifactState = ensureStreamArtifact(state, artifactId);
      if (!artifactState || artifactState.stage === "completed") {
        return true;
      }

      if (!setArtifactHostContext(artifactState.host, {
        messageId: state.messageId,
        sessionId: state.sessionId,
      })) {
        return false;
      }
      const handle = renderArtifact(artifactState.host, artifact, {
        sessionId: state.sessionId,
        messageId: state.messageId,
      });
      artifactState.handle = handle;
      artifactState.shell = handle.shell || artifactState.shell;
      artifactState.stage = isTerminalStreamStatus(handle.status) ? "completed" : "failed";
      return true;
    }

    if (frame.event === "artifact.failed") {
      const artifactId = resolveArtifactId(frame.data);
      if (!artifactId) {
        return false;
      }

      const artifactState = ensureStreamArtifact(state, artifactId);
      if (!artifactState || artifactState.stage === "completed") {
        return true;
      }

      const message = frame.data?.error?.message || "The chart artifact could not be delivered.";
      renderStreamFailure(artifactState, message);
      return true;
    }

    return false;
  }

  function flushBufferedFrames(state) {
    if (!state?.card || !state.bufferedEvents.length) {
      return 0;
    }

    const pending = state.bufferedEvents.slice();
    state.bufferedEvents = [];
    state.bufferedBytes = 0;
    pending.forEach((entry) => applyStreamFrame(state, entry.frame, { sessionId: entry.sessionId }));
    return pending.length;
  }

  function deleteStreamState(messageId) {
    streamStates.delete(messageId);
  }

  return {
    config: resolvedConfig,
    beginStreamingMessage(card, { sessionId = null } = {}) {
      const state = ensureStreamState(card, { sessionId });
      flushBufferedFrames(state);
      return state?.messageId || null;
    },
    handleStreamingArtifact(card, frame, { messageId = null, sessionId = null } = {}) {
      const state = ensureStreamState(card, { messageId, sessionId });
      return applyStreamFrame(state, frame, { sessionId });
    },
    finalizeStreamingMessage(card, { reason = "completed" } = {}) {
      const messageId = resolveMessageKey(card);
      if (!messageId) {
        return 0;
      }

      const state = streamStates.get(messageId);
      if (!state) {
        return 0;
      }

      let finalizedCount = 0;
      state.bufferedEvents = [];
      state.bufferedBytes = 0;

      state.artifacts.forEach((artifactState) => {
        if (artifactState.stage !== "started") {
          return;
        }

        const message = reason === "aborted"
          ? "Visualization generation was canceled before completion."
          : reason === "error"
            ? "Visualization could not be completed because the stream failed."
            : "Visualization did not finish before the stream ended.";
        renderStreamFailure(artifactState, message);
        finalizedCount += 1;
      });

      return finalizedCount;
    },
    renderArtifacts(card, artifacts, { sessionId = null } = {}) {
      if (!card || typeof card !== "object") {
        return [];
      }

      const messageId = resolveMessageId(card);
      if (!messageId) {
        return [];
      }

      if (typeof artifacts === "undefined") {
        if (sessionId) {
          setCardSessionId(card, sessionId);
        }
        return [];
      }

      deleteStreamState(messageId);
      cancelLazyBy((entry) => entry.messageId === messageId);
      resolvedRenderer.disposeByMessage(messageId);

      const candidates = Array.isArray(artifacts) ? artifacts.filter(Boolean) : [];
      if (!candidates.length) {
        removeArtifactRegion(card);
        return [];
      }

      if (sessionId && !setCardSessionId(card, sessionId)) {
        return [];
      }

      const limitedArtifacts = candidates.slice(0, resolvedConfig.maxArtifactsPerResponse);
      const region = ensureArtifactRegion(card);
      const handles = [];

      limitedArtifacts.forEach((artifactCandidate, index) => {
        const artifactId = typeof artifactCandidate?.artifact_id === "string" && artifactCandidate.artifact_id
          ? artifactCandidate.artifact_id
          : `artifact-${index + 1}`;
        const item = createArtifactItem();
        const host = createArtifactHost({ artifactId, messageId, sessionId });
        item.append(host);

        const handle = renderArtifact(host, artifactCandidate, {
          sessionId,
          messageId,
        });
        handles.push(handle);

        if (isFailureStatus(handle.status)) {
          item.append(createArtifactNotice(handle.error?.message || "Chart could not be displayed.", "error"));
        }

        const warnings = collectWarnings(artifactCandidate);
        if (warnings.length && !["rendered", "updated", "loading_reference", "deferred"].includes(handle.status)) {
          item.append(createArtifactNotice(`Warning: ${warnings.join(" ")}`, "warning"));
        }

        region.append(item);
      });

      applyArtifactLayout(region, limitedArtifacts.length);
      syncArtifactToggle(card, limitedArtifacts.length, false);

      if (candidates.length > limitedArtifacts.length) {
        region.append(
          createArtifactNotice(
            `Only the first ${limitedArtifacts.length} of ${candidates.length} visualizations were rendered for this response.`,
            "warning"
          )
        );
      }

      return handles;
    },
    renderHistoryArtifacts(card, { artifacts = [], artifactCount = 0, replayStatus = null, sessionId = null } = {}) {
      const candidates = Array.isArray(artifacts) ? artifacts.filter(Boolean) : [];
      const resolvedArtifactCount = normalizeArtifactCount(artifactCount || candidates.length);
      const resolvedReplayStatus = normalizeReplayStatus(replayStatus);

      if (!candidates.length) {
        if (!resolvedArtifactCount || !card || typeof card !== "object") {
          removeArtifactRegion(card);
          return [];
        }

        if (sessionId) {
          setCardSessionId(card, sessionId);
        }

        const region = ensureArtifactRegion(card);
        applyArtifactLayout(region, 1);
        region.append(
          createArtifactNotice(
            buildUnavailableHistoryArtifactNotice(resolvedArtifactCount, resolvedReplayStatus),
            "warning"
          )
        );
        syncArtifactToggle(card, 0, false);
        return [];
      }

      const handles = this.renderArtifacts(card, candidates, { sessionId });
      const unavailableCount = Math.max(resolvedArtifactCount - candidates.length, 0);
      if (unavailableCount > 0) {
        findArtifactRegion(card)?.append(
          createArtifactNotice(
            buildPartialHistoryArtifactNotice(unavailableCount),
            "warning"
          )
        );
      }
      return handles;
    },
    disposeMessage(target) {
      const messageId = typeof target === "string" ? target : resolveMessageId(target);
      if (messageId) {
        cancelLazyBy((entry) => entry.messageId === messageId);
        resolvedRenderer.disposeByMessage(messageId);
        deleteStreamState(messageId);
      }
      if (target && typeof target === "object") {
        removeArtifactRegion(target);
      }
    },
    disposeSession(sessionId) {
      if (!sessionId) {
        return 0;
      }
      Array.from(streamStates.values()).forEach((state) => {
        if (state.sessionId === sessionId || state.card?.dataset?.sessionId === sessionId) {
          deleteStreamState(state.messageId);
        }
      });
      cancelLazyBy((entry) => entry.sessionId === sessionId);
      return resolvedRenderer.disposeBySession(sessionId);
    },
    disposeAll() {
      streamStates.clear();
      cancelLazyBy(() => true);
      return typeof resolvedRenderer.disposeAll === "function"
        ? resolvedRenderer.disposeAll()
        : typeof resolvedRenderer.instanceStore?.disposeAll === "function"
          ? resolvedRenderer.instanceStore.disposeAll()
          : 0;
    },
  };
}