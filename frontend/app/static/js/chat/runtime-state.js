import { setText } from "../common/dom.js";
import { getSessionState } from "../services/session-store.js";

let liveAnnouncementTimer = 0;

export function announceChatStatus(refs, message) {
  if (!refs.liveRegion || !message) {
    return;
  }

  window.clearTimeout(liveAnnouncementTimer);
  refs.liveRegion.textContent = "";
  liveAnnouncementTimer = window.setTimeout(() => {
    if (refs.liveRegion) {
      refs.liveRegion.textContent = message;
    }
  }, 32);
}

export function toPositiveInteger(value) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return null;
  }

  return parsed;
}

export function pluralize(noun, count) {
  return `${count} ${noun}${count === 1 ? "" : "s"}`;
}

export function truncateLabel(value, length = 48) {
  if (typeof value !== "string") {
    return "Unavailable";
  }
  if (value.length <= length) {
    return value;
  }
  return `${value.slice(0, length - 1)}…`;
}

export function buildUiApiPath(path) {
  const base = document.body?.dataset.uiApiBase || "/ui-api";
  const normalized = path.startsWith("/") ? path : `/${path}`;
  return `${base}${normalized}`;
}

export function withTransport(requestBody, transport) {
  return {
    ...requestBody,
    metadata: {
      ...(requestBody.metadata ?? {}),
      transport,
    },
  };
}

export function buildChatRequest({ message, sessionId, usecase }) {
  return {
    message,
    session_id: sessionId || null,
    usecase: usecase || null,
    metadata: {
      client: "frontend",
      ui: "flask-bootstrap",
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
      transport: "non_streaming",
    },
  };
}

export function createInspectorState(sessionId, usecase) {
  return {
    traceId: null,
    sessionId: sessionId || null,
    agentName: null,
    strategyName: null,
    llmProfile: null,
    usecase: usecase || null,
    transport: "request/response",
    finishReason: null,
    durationMs: null,
    toolCalls: [],
    memoryUpdates: [],
    toolCallCount: 0,
    memoryResultCount: 0,
    traceSummary: null,
    lastError: null,
  };
}

export function createRuntimeState(shellState) {
  const stored = getSessionState();
  return {
    shellState,
    capabilities: shellState.capabilities,
    sessions: [],
    activeSessionId: stored.activeSessionId,
    selectedUsecase: stored.selectedUsecase,
    lastTraceId: null,
    lastAssistantAnswer: "",
    lastRequestBody: null,
    pending: false,
    conversationLoading: true,
    lastFailure: null,
    composerPinned: stored.layoutState?.composerPinned !== false,
    listEnabled: false,
    historyEnabled: false,
    resetEnabled: false,
    deleteEnabled: false,
    streamingEnabled: false,
    activeAbortController: null,
    inspector: createInspectorState(stored.activeSessionId, stored.selectedUsecase),
  };
}

export function resetInspector(runtimeState) {
  runtimeState.inspector = createInspectorState(
    runtimeState.activeSessionId,
    runtimeState.selectedUsecase
  );
  runtimeState.lastTraceId = null;
  runtimeState.lastAssistantAnswer = "";
}

export function syncBusyState(runtimeState, refs) {
  const busy = Boolean(runtimeState.pending || runtimeState.conversationLoading);
  if (refs.composer) {
    refs.composer.setAttribute("aria-busy", String(busy));
  }
  if (refs.conversationShell) {
    refs.conversationShell.setAttribute("aria-busy", String(busy));
  }
}

export function updateActionButtons(runtimeState, refs, { refreshCounter } = {}) {
  const backendOnline = runtimeState.shellState.backendStatus !== "offline";
  const chatCapabilities = runtimeState.capabilities?.chat ?? {};
  const debugEnabled = Boolean(runtimeState.shellState.frontendFlags.debugTracesEnabled)
    && Boolean(runtimeState.capabilities?.debug?.trace_routes_enabled);
  const usecaseReady = Boolean(runtimeState.selectedUsecase);
  const chatEnabled = Boolean(chatCapabilities.enabled);
  const hasActiveSession = Boolean(runtimeState.activeSessionId);
  const busy = runtimeState.pending || runtimeState.conversationLoading;

  if (refs.input) {
    refs.input.disabled = busy || !backendOnline || !chatEnabled;
    refs.input.placeholder = runtimeState.conversationLoading
      ? "Loading conversation..."
      : chatEnabled
        ? "Compose a message. Enter sends and Shift+Enter inserts a newline."
        : "Chat is disabled by backend capability.";
  }
  if (refs.usecaseSelect) {
    refs.usecaseSelect.disabled = busy || !chatEnabled || refs.usecaseSelect.options.length === 0;
  }

  if (refs.sendButton) {
    const message = refs.input?.value?.trim() ?? "";
    refs.sendButton.disabled = busy || !backendOnline || !chatEnabled || !usecaseReady || !message;
  }
  if (refs.stopButton) {
    refs.stopButton.disabled = !runtimeState.activeAbortController;
  }
  if (refs.sessionRefresh) {
    refs.sessionRefresh.disabled = busy || !runtimeState.listEnabled;
  }
  if (refs.sessionReset) {
    refs.sessionReset.disabled = busy || !runtimeState.resetEnabled || !hasActiveSession;
  }
  if (refs.sessionDelete) {
    refs.sessionDelete.disabled = busy || !runtimeState.deleteEnabled || !hasActiveSession;
  }
  if (refs.sessionNewChat) {
    refs.sessionNewChat.disabled = busy;
  }
  if (refs.copyLastMessageButton) {
    refs.copyLastMessageButton.disabled = !runtimeState.lastAssistantAnswer;
  }
  if (refs.copyTraceButton) {
    refs.copyTraceButton.disabled = !runtimeState.lastTraceId;
  }
  if (refs.openTraceButton) {
    refs.openTraceButton.disabled = !runtimeState.lastTraceId || !debugEnabled;
  }
  if (refs.retryButton) {
    refs.retryButton.disabled = busy || !runtimeState.lastFailure || !runtimeState.lastRequestBody;
  }

  if (refs.sessionList) {
    refs.sessionList
      .querySelectorAll("[data-session-id], [data-session-delete-id]")
      .forEach((button) => {
        if (button instanceof HTMLButtonElement) {
          button.disabled = busy;
        }
      });
  }

  if (typeof refreshCounter === "function") {
    refreshCounter();
  }
}

export function setPending(runtimeState, refs, pending, statusText, { updateActionButtons: refreshControls } = {}) {
  runtimeState.pending = pending;
  if (statusText) {
    setText(refs.panelStatus, statusText);
  }
  syncBusyState(runtimeState, refs);
  if (typeof refreshControls === "function") {
    refreshControls();
  }
}