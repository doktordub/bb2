import { setBannerState } from "../common/banner.js";
import { setText } from "../common/dom.js";
import { boolLabel, formatDuration as formatDurationValue } from "../common/formatters.js";
import { setStatePill } from "../common/status.js";
import { setSelectedUsecase } from "../services/session-store.js";
import { pluralize, toPositiveInteger, truncateLabel } from "./runtime-state.js";

const formatDuration = (value) => formatDurationValue(value, "Duration unavailable");

function renderInspectorLines(container, { lines = [], items = [] } = {}) {
  if (!container) {
    return;
  }

  container.replaceChildren();

  lines.filter(Boolean).forEach((line) => {
    const paragraph = document.createElement("p");
    paragraph.textContent = line;
    container.append(paragraph);
  });

  if (items.length > 0) {
    const list = document.createElement("ul");
    list.className = "inspector-list";
    items.filter(Boolean).forEach((item) => {
      const listItem = document.createElement("li");
      listItem.textContent = item;
      list.append(listItem);
    });
    container.append(list);
  }
}

function summarizeToolCall(item, index) {
  if (!item || typeof item !== "object") {
    return `Tool ${index + 1}`;
  }

  const name = item.name || item.tool_name || item.logical_name || `Tool ${index + 1}`;
  const status = item.status || item.outcome || item.result || null;
  const duration = Number.isFinite(Number(item.duration_ms)) ? formatDuration(item.duration_ms) : null;
  const parts = [status, duration].filter(Boolean);
  return parts.length > 0 ? `${name} (${parts.join(" · ")})` : name;
}

function summarizeMemoryUpdate(item, index) {
  if (!item || typeof item !== "object") {
    return `Memory update ${index + 1}`;
  }

  const action = item.operation || item.kind || item.type || item.action || `Memory update ${index + 1}`;
  const target = item.namespace || item.store || item.key || item.document_id || item.id || null;
  return target ? `${action}: ${target}` : action;
}

function renderUsecases(usecases, runtimeState, refs) {
  if (!refs.usecaseSelect) {
    return;
  }

  const previousValue = runtimeState.selectedUsecase || refs.usecaseSelect.value || "";
  refs.usecaseSelect.innerHTML = "";
  if (!Array.isArray(usecases) || usecases.length === 0) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "No use cases available";
    refs.usecaseSelect.append(option);
    refs.usecaseSelect.disabled = true;
    runtimeState.selectedUsecase = null;
    runtimeState.inspector.usecase = null;
    setSelectedUsecase(null);
    return;
  }

  usecases.forEach((usecase, index) => {
    const option = document.createElement("option");
    option.value = usecase.name || "";
    option.textContent = usecase.display_name || usecase.name || `Use case ${index + 1}`;
    option.dataset.streamingSupported = usecase.streaming_supported ? "true" : "false";
    refs.usecaseSelect.append(option);
  });

  const matchingOption = Array.from(refs.usecaseSelect.options).find((option) => option.value === previousValue);
  const resolvedValue = matchingOption?.value || refs.usecaseSelect.options[0]?.value || "";
  refs.usecaseSelect.value = resolvedValue;
  runtimeState.selectedUsecase = resolvedValue || null;
  runtimeState.inspector.usecase = runtimeState.selectedUsecase;
  setSelectedUsecase(runtimeState.selectedUsecase);
  updateStatusBar(runtimeState, refs);
}

export function updateStatusBar(runtimeState, refs) {
  const inspector = runtimeState.inspector;
  setText(refs.sessionLabel, inspector.sessionId ? truncateLabel(inspector.sessionId, 28) : "Awaiting session");
  setText(refs.usecaseLabel, inspector.usecase || runtimeState.selectedUsecase || "Not selected");
  setText(refs.traceLabel, inspector.traceId ? truncateLabel(inspector.traceId, 18) : "Pending");
  setText(refs.agentLabel, inspector.agentName || "Pending");
  setText(refs.strategyLabel, inspector.strategyName || "Pending");
}

export function renderInspector(runtimeState, refs, { renderSessionContext } = {}) {
  const capabilities = runtimeState.capabilities ?? {};
  const tools = capabilities.tools ?? {};
  const memory = capabilities.memory ?? {};
  const llm = capabilities.llm ?? {};
  const chat = capabilities.chat ?? {};
  const sessions = capabilities.sessions ?? {};
  const visualization = runtimeState.shellState.visualization ?? {};
  const debugEnabled = Boolean(runtimeState.shellState.frontendFlags.debugTracesEnabled)
    && Boolean(capabilities.debug?.trace_routes_enabled);
  const inspector = runtimeState.inspector;

  if (refs.copyTraceButton) {
    refs.copyTraceButton.disabled = !inspector.traceId;
  }
  if (refs.openTraceButton) {
    refs.openTraceButton.disabled = !inspector.traceId || !debugEnabled;
  }

  if (!inspector.traceId) {
    setText(
      refs.tracePlaceholder,
      debugEnabled
        ? "Trace ids appear after the first backend response and can be opened in Admin trace access."
        : "Trace ids appear after the first backend response. Admin trace lookup stays disabled until debug routes are enabled."
    );
  } else {
    const traceParts = [`Latest trace ${inspector.traceId}`];
    if (inspector.traceSummary && typeof inspector.traceSummary === "object") {
      const eventCount = inspector.traceSummary.event_count;
      if (Number.isFinite(Number(eventCount))) {
        traceParts.push(`${pluralize("event", Number(eventCount))} recorded`);
      }
    }
    traceParts.push(debugEnabled ? "Admin trace lookup is available." : "Admin trace lookup is unavailable.");
    setText(refs.tracePlaceholder, traceParts.join(" · "));
  }

  const executionLines = [];
  if (inspector.usecase) {
    executionLines.push(`Use case: ${inspector.usecase}`);
  }
  executionLines.push(`Transport: ${inspector.transport}`);
  if (inspector.llmProfile) {
    executionLines.push(`LLM profile: ${inspector.llmProfile}`);
  }
  if (inspector.finishReason) {
    executionLines.push(`Finish reason: ${inspector.finishReason}`);
  }
  if (Number.isFinite(Number(inspector.durationMs))) {
    executionLines.push(`Duration: ${formatDuration(inspector.durationMs)}`);
  }
  if (inspector.lastError) {
    executionLines.push(`Latest error: ${inspector.lastError}`);
  }
  renderInspectorLines(refs.executionSummary, {
    lines: executionLines.length > 0
      ? executionLines
      : ["Use case, transport, and runtime details will render here after the first connected chat response."],
  });

  const toolTotal = Math.max(inspector.toolCallCount, inspector.toolCalls.length);
  const toolItems = inspector.toolCalls.slice(0, 3).map((item, index) => summarizeToolCall(item, index));
  const extraToolCount = toolTotal - toolItems.length;
  renderInspectorLines(refs.toolSummary, {
    lines: toolTotal > 0 ? [`${pluralize("tool call", toolTotal)} reported.`] : ["No tool calls yet."],
    items: extraToolCount > 0 ? [...toolItems, `+${extraToolCount} more not shown`] : toolItems,
  });

  const memoryTotal = Math.max(inspector.memoryResultCount, inspector.memoryUpdates.length);
  const memoryItems = inspector.memoryUpdates.slice(0, 3).map((item, index) => summarizeMemoryUpdate(item, index));
  const extraMemoryCount = memoryTotal - memoryItems.length;
  renderInspectorLines(refs.memorySummary, {
    lines: memoryTotal > 0 ? [`${pluralize("memory update", memoryTotal)} reported.`] : ["No memory updates yet."],
    items: extraMemoryCount > 0 ? [...memoryItems, `+${extraMemoryCount} more not shown`] : memoryItems,
  });

  renderInspectorLines(refs.capabilitiesSummary, {
    items: [
      `Chat: ${chat.enabled ? "enabled" : "disabled"}; streaming ${chat.streaming_enabled ? "on" : "off"}; max chars ${toPositiveInteger(chat.max_message_chars) ?? "--"}`,
      `Sessions: list ${boolLabel(Boolean(sessions.list_enabled)).toLowerCase()}, history ${boolLabel(Boolean(sessions.history_enabled)).toLowerCase()}, reset ${boolLabel(Boolean(sessions.reset_enabled)).toLowerCase()}, delete ${boolLabel(Boolean(sessions.delete_enabled)).toLowerCase()}`,
      `Tools: ${tools.enabled ? `${tools.total_tools ?? 0} configured` : "disabled"}; approvals ${tools.approval_required_tools ?? 0}`,
      `Memory: ${memory.enabled ? (memory.provider || "configured") : "disabled"}; search ${memory.search_available ? "on" : "off"}; ingest ${memory.ingest_available ? "on" : "off"}`,
      `LLM: ${llm.enabled ? (llm.default_profile || "configured") : "disabled"}; streaming ${llm.streaming_supported ? "on" : "off"}; structured output ${llm.structured_output_supported ? "on" : "off"}`,
      `Visualization: ${visualization.backendEnabled === false ? "disabled" : visualization.backendAdvertised ? `${visualization.intersectedChartTypes?.length ?? 0} renderable types` : "local-only"}; reference mode ${visualization.referenceModeEnabled ? "on" : "off"}`,
    ],
  });

  setText(
    refs.approvalsSummary,
    Number(tools.approval_required_tools || 0) > 0
      ? `${pluralize("tool", Number(tools.approval_required_tools || 0))} require approval. Approval controls stay read-only until the dedicated phase.`
      : "Approvals are not available yet because no advertised tools currently require approval."
  );
  setText(
    refs.futureViewsSummary,
    "Artifacts, plans, and future side views stay read-only until later phases expose dedicated backend endpoints."
  );
  setText(refs.actionQueueSummary, "No queued approvals, exports, or generated artifacts yet.");
  setText(
    refs.retrySummary,
    runtimeState.lastFailure ? `Retry ready for the last failed request: ${runtimeState.lastFailure}` : "No failed requests to retry."
  );

  if (typeof renderSessionContext === "function") {
    renderSessionContext(runtimeState, refs);
  }
  updateStatusBar(runtimeState, refs);
}

export function applyHealthState(runtimeState, refs) {
  const healthStatus = runtimeState.shellState.backendStatus;
  const healthLabel = healthStatus.charAt(0).toUpperCase() + healthStatus.slice(1);
  setStatePill(refs.healthPill, `Health: ${healthLabel}`, healthStatus);

  if (healthStatus === "online") {
    setBannerState(refs.healthBanner, refs.healthBannerTitle, refs.healthBannerBody, { hidden: true });
    if (refs.offlineCard) {
      refs.offlineCard.hidden = true;
    }
    return;
  }

  const tone = healthStatus === "offline" ? "error" : "warning";
  const title = healthStatus === "degraded" ? "Backend is degraded." : "Backend is unavailable.";
  const body = healthStatus === "unknown"
    ? "The frontend could not confidently map the health payload. The workspace stays in a safe placeholder state."
    : healthStatus === "degraded"
      ? "The backend responded with a degraded status. Session history and chat may still work, but responses can be partial until the service recovers."
      : "The frontend could not reach the backend health route. Chat sending stays disabled until connectivity returns.";

  setBannerState(refs.healthBanner, refs.healthBannerTitle, refs.healthBannerBody, {
    hidden: false,
    tone,
    title,
    body,
  });

  if (refs.offlineCard) {
    refs.offlineCard.hidden = false;
  }
  setText(refs.offlineCopy, body);
}

export function updateStreamingMode(runtimeState, globalStreamingEnabled, refs) {
  const selectedOption = refs.usecaseSelect?.selectedOptions?.[0] ?? null;
  const selectedStreamingSupported = selectedOption?.dataset.streamingSupported === "true";
  const streamingEnabled = Boolean(globalStreamingEnabled) && selectedStreamingSupported;
  const modeLabel = streamingEnabled ? "Mode: Streaming" : "Mode: Request/response";
  const tone = streamingEnabled ? "available" : "info";

  runtimeState.streamingEnabled = streamingEnabled;

  setStatePill(refs.modePill, modeLabel, tone);
  setStatePill(refs.streamingBadge, modeLabel, tone);

  return streamingEnabled;
}

export function applyCapabilities(
  runtimeState,
  refs,
  { renderSessionContext, updateActionButtons, updateCounter } = {}
) {
  const capabilities = runtimeState.shellState.capabilities;
  runtimeState.capabilities = capabilities;
  if (!capabilities) {
    setBannerState(refs.capabilitiesBanner, refs.capabilitiesBannerTitle, refs.capabilitiesBannerBody, {
      hidden: false,
      tone: "warning",
      title: "Capabilities are unavailable.",
      body: "The workspace fell back to safe defaults because the backend capability route could not be loaded.",
    });
    setStatePill(refs.capabilityPill, "Composer: Disabled", "disabled");
    setStatePill(refs.modePill, "Mode: Request/response", "info");
    setStatePill(refs.streamingBadge, "Mode: Request/response", "info");
    setText(refs.panelStatus, "Capabilities unavailable");
    setText(refs.composerHint, "Capabilities could not be loaded. The composer stays disabled until the backend contract is available again.");
    setText(refs.sessionEmptyCopy, "Session capability data is unavailable, so the rail remains in a placeholder state.");
    setText(refs.sessionNote, "History, reset, and delete wiring is unavailable until a valid capability response returns.");
    renderInspector(runtimeState, refs, { renderSessionContext });
    if (typeof updateActionButtons === "function") {
      updateActionButtons();
    }
    return;
  }

  setBannerState(refs.capabilitiesBanner, refs.capabilitiesBannerTitle, refs.capabilitiesBannerBody, { hidden: true });

  const chatCapabilities = capabilities.chat ?? {};
  const sessionCapabilities = capabilities.sessions ?? {};
  const usecases = Array.isArray(capabilities.usecases) ? capabilities.usecases : [];

  runtimeState.listEnabled = Boolean(sessionCapabilities.list_enabled);
  runtimeState.historyEnabled = Boolean(sessionCapabilities.history_enabled);
  runtimeState.resetEnabled = Boolean(sessionCapabilities.reset_enabled);
  runtimeState.deleteEnabled = Boolean(sessionCapabilities.delete_enabled);

  const chatEnabled = Boolean(chatCapabilities.enabled);
  const messageLimit = toPositiveInteger(chatCapabilities.max_message_chars);
  renderUsecases(usecases, runtimeState, refs);

  if (refs.input) {
    refs.input.disabled = !chatEnabled;
    refs.input.placeholder = chatEnabled
      ? "Compose a message. Enter sends and Shift+Enter inserts a newline."
      : "Chat is disabled by backend capability.";
    if (messageLimit) {
      refs.input.maxLength = String(messageLimit);
    } else {
      refs.input.removeAttribute("maxLength");
    }
  }
  if (refs.usecaseSelect) {
    refs.usecaseSelect.disabled = !chatEnabled || usecases.length === 0;
  }

  const streamingEnabled = updateStreamingMode(runtimeState, Boolean(chatCapabilities.streaming_enabled), refs);
  setStatePill(refs.capabilityPill, `Composer: ${chatEnabled ? "Enabled" : "Disabled"}`, chatEnabled ? "available" : "disabled");
  setText(refs.panelStatus, chatEnabled ? "Chat ready" : "Composer disabled");
  setText(
    refs.composerHint,
    chatEnabled
      ? streamingEnabled
        ? "Enter sends. Shift+Enter inserts a newline. Streaming is preferred when the selected use case supports it, with request-response fallback if needed."
        : "Enter sends. Shift+Enter inserts a newline. Non-streaming chat is active through the frontend proxy."
      : "Chat is disabled by the backend capability response."
  );
  setText(
    refs.emptyChatCopy,
    usecases.length > 0
      ? `Select ${"one of " + usecases.length + " use cases" || "a use case"} and send a message to start or resume a backend session.`
      : "No backend use cases are currently available, so the chat shell remains read-only."
  );

  if (typeof updateCounter === "function") {
    updateCounter(messageLimit);
  }

  setStatePill(refs.sessionListPill, `List: ${boolLabel(runtimeState.listEnabled)}`, runtimeState.listEnabled ? "available" : "disabled");
  setStatePill(refs.sessionHistoryPill, `History: ${boolLabel(runtimeState.historyEnabled)}`, runtimeState.historyEnabled ? "available" : "disabled");

  if (refs.sessionRefresh) {
    refs.sessionRefresh.hidden = !runtimeState.listEnabled;
  }
  if (refs.sessionReset) {
    refs.sessionReset.hidden = !runtimeState.resetEnabled;
  }
  if (refs.sessionDelete) {
    refs.sessionDelete.hidden = !runtimeState.deleteEnabled;
  }

  setText(
    refs.sessionEmptyCopy,
    runtimeState.listEnabled
      ? "No sessions yet. Start a new conversation and it will appear here after the first response."
      : "Session listing is currently disabled by backend capability."
  );
  setText(
    refs.sessionNote,
    runtimeState.historyEnabled
      ? runtimeState.activeSessionId
        ? `Active session: ${runtimeState.activeSessionId}`
        : "Select a session to reload prior messages, or start a new chat with the current use case."
      : "Session history is currently disabled by backend capability."
  );

  renderInspector(runtimeState, refs, { renderSessionContext });
  if (typeof updateActionButtons === "function") {
    updateActionButtons();
  }
}

export function updateInspectorFromResponse(
  runtimeState,
  refs,
  payload,
  { transport = "request/response", renderSessionContext, updateActionButtons } = {}
) {
  const data = payload?.data ?? {};
  runtimeState.lastTraceId = payload?.trace_id || runtimeState.lastTraceId || null;
  runtimeState.lastAssistantAnswer = data.answer || runtimeState.lastAssistantAnswer || "";
  runtimeState.inspector.traceId = runtimeState.lastTraceId;
  runtimeState.inspector.sessionId = payload?.session_id || runtimeState.activeSessionId || runtimeState.inspector.sessionId;
  runtimeState.inspector.agentName = data.agent_name || null;
  runtimeState.inspector.strategyName = data.strategy_name || null;
  runtimeState.inspector.llmProfile = data.llm_profile || null;
  runtimeState.inspector.usecase = data.usecase || runtimeState.selectedUsecase || runtimeState.inspector.usecase;
  runtimeState.inspector.transport = transport;
  runtimeState.inspector.lastError = null;
  runtimeState.inspector.finishReason = data.finish_reason || runtimeState.inspector.finishReason;
  runtimeState.inspector.durationMs = data.duration_ms ?? runtimeState.inspector.durationMs;
  runtimeState.inspector.toolCalls = Array.isArray(data.tool_calls) ? data.tool_calls.slice(0, 8) : [];
  runtimeState.inspector.toolCallCount = Array.isArray(data.tool_calls) ? data.tool_calls.length : 0;
  runtimeState.inspector.memoryUpdates = Array.isArray(data.memory_updates) ? data.memory_updates.slice(0, 8) : [];
  runtimeState.inspector.memoryResultCount = Array.isArray(data.memory_updates) ? data.memory_updates.length : 0;
  runtimeState.inspector.traceSummary = data.trace_summary && typeof data.trace_summary === "object"
    ? data.trace_summary
    : null;

  renderInspector(runtimeState, refs, { renderSessionContext });
  if (typeof updateActionButtons === "function") {
    updateActionButtons();
  }
}

export function updateInspectorFromStreamFrame(runtimeState, refs, frame, { renderSessionContext } = {}) {
  const payload = frame?.data && typeof frame.data === "object" ? frame.data : {};
  const inspector = runtimeState.inspector;

  if (typeof payload.trace_id === "string" && payload.trace_id) {
    inspector.traceId = payload.trace_id;
    runtimeState.lastTraceId = payload.trace_id;
  }
  if (typeof payload.session_id === "string" && payload.session_id) {
    inspector.sessionId = payload.session_id;
  }

  if (frame.event === "response.started") {
    inspector.transport = "streaming";
    inspector.lastError = null;
  }

  if (frame.event === "response.metadata" || frame.event === "agent_summary") {
    if (typeof payload.agent_name === "string" && payload.agent_name) {
      inspector.agentName = payload.agent_name;
    }
    if (typeof payload.strategy_name === "string" && payload.strategy_name) {
      inspector.strategyName = payload.strategy_name;
    }
    if (typeof payload.llm_profile === "string" && payload.llm_profile) {
      inspector.llmProfile = payload.llm_profile;
    }
    if (typeof payload.usecase === "string" && payload.usecase) {
      inspector.usecase = payload.usecase;
    }
    if (Number.isFinite(Number(payload.tool_call_count))) {
      inspector.toolCallCount = Number(payload.tool_call_count);
    }
    if (Number.isFinite(Number(payload.memory_result_count))) {
      inspector.memoryResultCount = Number(payload.memory_result_count);
    }
  }

  if (frame.event === "tool_call_summary") {
    inspector.toolCalls = [...inspector.toolCalls, payload].slice(0, 8);
    inspector.toolCallCount = Math.max(inspector.toolCallCount, inspector.toolCalls.length);
  }

  if (frame.event === "trace_summary") {
    inspector.traceSummary = payload;
  }

  if (frame.event === "response.completed") {
    if (typeof payload.finish_reason === "string" && payload.finish_reason) {
      inspector.finishReason = payload.finish_reason;
    }
    if (Number.isFinite(Number(payload.duration_ms))) {
      inspector.durationMs = Number(payload.duration_ms);
    }
  }

  if (frame.event === "response.error") {
    const error = payload.error && typeof payload.error === "object" ? payload.error : payload;
    inspector.lastError = error.message || "The request failed.";
  }

  renderInspector(runtimeState, refs, { renderSessionContext });
}