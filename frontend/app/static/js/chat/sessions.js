import { setText } from "../common/dom.js";
import { formatDate as formatDateValue } from "../common/formatters.js";
import { setStatePill } from "../common/status.js";
import { showToast } from "../common/toast.js";
import { deleteJson, getJson, postJson } from "../services/api-client.js";
import { clearActiveSession, setActiveSessionId, setSelectedUsecase } from "../services/session-store.js";
import { resolveHistoryArtifactReplay } from "./artifacts.js";
import { appendMessage, clearConversation, scrollConversationToBottom, setConversationLoading } from "./conversation.js";
import { renderInspector, updateStreamingMode, updateStatusBar } from "./inspector.js";
import { announceChatStatus, resetInspector, setPending, truncateLabel } from "./runtime-state.js";

const DEFAULT_SESSION_LIMIT = 20;
const DEFAULT_HISTORY_LIMIT = 50;
const formatDate = (value) => formatDateValue(value, "Timestamp unavailable");

function clearSessionVisualization(refs, sessionId) {
  if (!sessionId) {
    return;
  }

  refs.chatVisualization?.disposeSession?.(sessionId);
}

function findSessionSummary(runtimeState, sessionId = runtimeState.activeSessionId) {
  if (!sessionId) {
    return null;
  }

  return runtimeState.sessions.find((session) => session.session_id === sessionId) ?? null;
}

function requestConfirmation(refs, { title, body, confirmLabel }) {
  if (!(refs.confirmDialog instanceof HTMLDialogElement) || typeof refs.confirmDialog.showModal !== "function") {
    return Promise.resolve(window.confirm(`${title}\n\n${body}`));
  }

  setText(refs.confirmDialogTitle, title);
  setText(refs.confirmDialogBody, body);
  setText(refs.confirmDialogConfirm, confirmLabel);
  refs.confirmDialog.returnValue = "cancel";

  return new Promise((resolve) => {
    const handleClose = () => {
      resolve(refs.confirmDialog?.returnValue === "confirm");
    };

    refs.confirmDialog.addEventListener("close", handleClose, { once: true });
    refs.confirmDialog.showModal();
    window.requestAnimationFrame(() => {
      refs.confirmDialogCancel?.focus();
    });
  });
}

async function deleteSession(runtimeState, refs, sessionId, { updateActionButtons } = {}) {
  if (!sessionId || !runtimeState.deleteEnabled) {
    return false;
  }

  const confirmed = await requestConfirmation(refs, {
    title: runtimeState.activeSessionId === sessionId ? "Delete the active session?" : "Delete this session?",
    body: `Delete session ${sessionId}. This cannot be undone and removes the saved history from the backend session list.`,
    confirmLabel: "Delete session",
  });
  if (!confirmed) {
    return false;
  }

  setPending(runtimeState, refs, true, "Deleting session", { updateActionButtons });
  try {
    await deleteJson(`/sessions/${encodeURIComponent(sessionId)}`);
    if (runtimeState.activeSessionId === sessionId) {
      clearSessionVisualization(refs, sessionId);
      runtimeState.activeSessionId = null;
      clearActiveSession();
      clearConversation(refs);
      resetInspector(runtimeState);
      renderInspector(runtimeState, refs, { renderSessionContext });
      setText(refs.sessionNote, "The active session was deleted. Start a new chat or choose another session.");
    }
    announceChatStatus(refs, `Session ${sessionId} deleted.`);
    showToast(`Session ${sessionId} deleted.`, { tone: "info" });
    await loadSessions(runtimeState, refs, { updateActionButtons });
    return true;
  } catch (error) {
    announceChatStatus(refs, error.message || "Could not delete session.");
    showToast(error.message || "Could not delete session.", { tone: "error" });
    return false;
  } finally {
    setPending(runtimeState, refs, false, runtimeState.activeSessionId ? "Session ready" : "New chat ready", { updateActionButtons });
  }
}

export function renderSessionContext(runtimeState, refs) {
  if (!refs.sessionContext) {
    return;
  }

  const session = findSessionSummary(runtimeState);
  const hasSession = Boolean(session);
  refs.sessionContext.hidden = !hasSession;

  if (!hasSession) {
    return;
  }

  const updatedLabel = formatDate(session.last_activity_at || session.updated_at || session.created_at);
  setText(refs.sessionContextTitle, truncateLabel(session.session_id, 34));
  setText(refs.sessionContextUsecase, session.usecase || runtimeState.selectedUsecase || "No use case");
  setStatePill(refs.sessionContextStatus, "Active", "available");
  setText(refs.sessionContextCount, `${session.message_count ?? 0} msgs`);
  setText(refs.sessionContextUpdated, `Updated ${updatedLabel}`);
}

export function renderSessionList(runtimeState, refs, sessions, limit, hasMore, { updateActionButtons } = {}) {
  runtimeState.sessions = sessions;
  if (!refs.sessionList) {
    return;
  }

  refs.sessionList.replaceChildren();
  const hasSessions = Array.isArray(sessions) && sessions.length > 0;
  if (refs.sessionEmptyState) {
    refs.sessionEmptyState.hidden = hasSessions;
  }
  if (refs.sessionListShell) {
    refs.sessionListShell.hidden = !hasSessions;
  }

  if (!hasSessions) {
    setStatePill(refs.sessionListStatus, runtimeState.listEnabled ? "Empty" : "Disabled", runtimeState.listEnabled ? "info" : "disabled");
    setText(refs.sessionSummaryCopy, runtimeState.listEnabled ? "No sessions returned by the backend." : "Session listing is disabled.");
    renderSessionContext(runtimeState, refs);
    if (typeof updateActionButtons === "function") {
      updateActionButtons();
    }
    return;
  }

  sessions.forEach((session) => {
    const item = document.createElement("li");
    item.className = "session-list-item";

    const rowWrap = document.createElement("div");
    rowWrap.className = "session-row-wrap";

    const button = document.createElement("button");
    button.className = "session-row btn";
    button.type = "button";
    button.dataset.sessionId = session.session_id;
    const isActive = session.session_id === runtimeState.activeSessionId;
    button.classList.toggle("is-active", isActive);
    const showInlineDelete = runtimeState.deleteEnabled;
    button.classList.toggle("session-row--with-action", showInlineDelete);
    if (isActive) {
      button.setAttribute("aria-current", "true");
    }

    const top = document.createElement("div");
    top.className = "session-row__top";
    const titleBlock = document.createElement("div");
    titleBlock.className = "session-row__identity";
    const title = document.createElement("p");
    title.className = "session-row__title";
    title.textContent = truncateLabel(session.session_id, 36);
    const subtitle = document.createElement("p");
    subtitle.className = "session-row__subtitle";
    subtitle.textContent = session.usecase || "No use case";
    titleBlock.append(title, subtitle);
    top.append(titleBlock);

    const bottom = document.createElement("div");
    bottom.className = "session-row__identity";
    const updated = document.createElement("p");
    updated.className = "session-row__subtitle";
    const updatedLabel = formatDate(session.last_activity_at || session.updated_at || session.created_at);
    updated.textContent = `Updated ${updatedLabel}`;
    const count = document.createElement("p");
    count.className = "session-row__subtitle";
    count.textContent = `${session.message_count ?? 0} msgs`;
    bottom.append(updated, count);

    button.setAttribute(
      "aria-label",
      `Open session ${session.session_id}. Use case ${session.usecase || "not set"}. Status ${session.status || "unknown"}. Updated ${updatedLabel}. ${session.message_count ?? 0} messages.`
    );
    button.append(top, bottom);
    rowWrap.append(button);

    if (showInlineDelete) {
      const deleteButton = document.createElement("button");
      deleteButton.className = "btn btn-shell btn-shell--compact session-row__delete";
      deleteButton.type = "button";
      deleteButton.dataset.sessionDeleteId = session.session_id;
      deleteButton.setAttribute("aria-label", `Delete session ${session.session_id}`);
      deleteButton.textContent = "Delete";
      rowWrap.append(deleteButton);
    }

    item.append(rowWrap);
    refs.sessionList.append(item);
  });

  const moreLabel = hasMore ? `Showing ${sessions.length} of ${limit}+ sessions.` : `Showing ${sessions.length} session${sessions.length === 1 ? "" : "s"}.`;
  setText(refs.sessionSummaryCopy, moreLabel);
  setStatePill(refs.sessionListStatus, hasMore ? "Partial" : "Loaded", hasMore ? "info" : "available");
  renderSessionContext(runtimeState, refs);
  if (typeof updateActionButtons === "function") {
    updateActionButtons();
  }
}

export async function loadSessions(runtimeState, refs, { updateActionButtons } = {}) {
  if (!runtimeState.listEnabled) {
    return;
  }

  setStatePill(refs.sessionListStatus, "Loading", "checking");
  setText(refs.sessionSummaryCopy, "Loading sessions...");
  try {
    const payload = await getJson(`/sessions?limit=${DEFAULT_SESSION_LIMIT}`);
    const data = payload?.data ?? {};
    renderSessionList(
      runtimeState,
      refs,
      Array.isArray(data.sessions) ? data.sessions : [],
      data.limit ?? DEFAULT_SESSION_LIMIT,
      Boolean(data.has_more),
      { updateActionButtons }
    );

    if (runtimeState.activeSessionId) {
      const stillExists = runtimeState.sessions.some((session) => session.session_id === runtimeState.activeSessionId);
      if (!stillExists) {
        clearSessionVisualization(refs, runtimeState.activeSessionId);
        runtimeState.activeSessionId = null;
        clearActiveSession();
        clearConversation(refs);
        resetInspector(runtimeState);
        renderInspector(runtimeState, refs, { renderSessionContext });
        setText(refs.sessionNote, "The previously selected session no longer exists. Start a new chat or choose another session.");
        announceChatStatus(refs, "The previously selected session is no longer available.");
      }
    }
  } catch (error) {
    setStatePill(refs.sessionListStatus, "Error", "offline");
    setText(refs.sessionSummaryCopy, error.message || "Could not load sessions.");
    showToast(error.message || "Could not load sessions.", { tone: "error" });
  }
}

export async function loadSessionHistory(runtimeState, refs, sessionId, { updateActionButtons } = {}) {
  if (!runtimeState.historyEnabled || !sessionId) {
    return;
  }

  clearSessionVisualization(refs, runtimeState.activeSessionId || sessionId);
  runtimeState.activeSessionId = sessionId;
  runtimeState.inspector.sessionId = sessionId;
  setActiveSessionId(sessionId);
  setConversationLoading(runtimeState, refs, true, "loading...", { updateActionButtons });
  clearConversation(refs);
  renderSessionContext(runtimeState, refs);
  setText(refs.sessionNote, `Loading history for ${sessionId}...`);
  setText(refs.panelStatus, "Loading session history");
  announceChatStatus(refs, `Loading session history for ${sessionId}.`);
  if (typeof updateActionButtons === "function") {
    updateActionButtons();
  }

  try {
    const payload = await getJson(`/sessions/${encodeURIComponent(sessionId)}/history?limit=${DEFAULT_HISTORY_LIMIT}`);
    const data = payload?.data ?? {};
    const messages = Array.isArray(data.messages) ? data.messages : [];
    const sessionSummary = runtimeState.sessions.find((session) => session.session_id === sessionId);
    const fallbackCreatedAt = sessionSummary?.last_activity_at || sessionSummary?.updated_at || sessionSummary?.created_at || null;
    clearConversation(refs);
    messages.forEach((message) => {
      const metadata = message.metadata && typeof message.metadata === "object"
        ? { ...message.metadata }
        : {};
      if (!metadata.usecase && sessionSummary?.usecase) {
        metadata.usecase = sessionSummary.usecase;
      }
      const card = appendMessage(refs, {
        role: message.role,
        content: message.content,
        createdAt: message.created_at || fallbackCreatedAt,
        metadata,
        sessionId,
      }, { scroll: false });
      if (message.role === "assistant") {
        const historyReplay = resolveHistoryArtifactReplay(message);
        refs.chatVisualization?.renderHistoryArtifacts?.(card, {
          artifacts: historyReplay.artifacts,
          artifactCount: historyReplay.artifactCount,
          replayStatus: historyReplay.replayStatus,
          sessionId,
        });
      }
    });
    scrollConversationToBottom(refs, { force: true });
    if (refs.historyTruncatedCard) {
      refs.historyTruncatedCard.hidden = !Boolean(data.truncated);
    }

    if (sessionSummary?.usecase) {
      runtimeState.selectedUsecase = sessionSummary.usecase;
      runtimeState.inspector.usecase = sessionSummary.usecase;
      setSelectedUsecase(sessionSummary.usecase);
      if (refs.usecaseSelect) {
        const option = Array.from(refs.usecaseSelect.options).find((candidate) => candidate.value === sessionSummary.usecase);
        if (option) {
          refs.usecaseSelect.value = sessionSummary.usecase;
        }
      }
    }

    updateStreamingMode(runtimeState, Boolean(runtimeState.capabilities?.chat?.streaming_enabled), refs);
    renderInspector(runtimeState, refs, { renderSessionContext });
    setText(refs.sessionNote, `Active session: ${sessionId}`);
    setText(refs.panelStatus, messages.length > 0 ? "Session history loaded" : "Session ready");
    renderSessionList(runtimeState, refs, runtimeState.sessions, DEFAULT_SESSION_LIMIT, false, { updateActionButtons });
    announceChatStatus(
      refs,
      messages.length > 0 ? `Session ${sessionId} history loaded.` : `Session ${sessionId} is ready.`
    );
  } catch (error) {
    setText(refs.sessionNote, error.message || `Could not load history for ${sessionId}.`);
    setText(refs.panelStatus, "Session history unavailable");
    announceChatStatus(refs, error.message || "Could not load session history.");
    showToast(error.message || "Could not load session history.", { tone: "error" });
  } finally {
    setConversationLoading(runtimeState, refs, false, undefined, { updateActionButtons });
    if (typeof updateActionButtons === "function") {
      updateActionButtons();
    }
  }
}

export async function resetActiveSession(runtimeState, refs, { updateActionButtons } = {}) {
  if (!runtimeState.activeSessionId || !runtimeState.resetEnabled) {
    return;
  }
  const sessionId = runtimeState.activeSessionId;
  const confirmed = await requestConfirmation(refs, {
    title: "Reset the active session?",
    body: `Reset session ${sessionId}. The conversation can continue with the same use case, but the backend session state will be cleared.`,
    confirmLabel: "Reset session",
  });
  if (!confirmed) {
    return;
  }

  setPending(runtimeState, refs, true, "Resetting session", { updateActionButtons });
  try {
    await postJson(`/sessions/${encodeURIComponent(sessionId)}/reset`, { reason: "frontend_reset" });
    clearSessionVisualization(refs, sessionId);
    clearConversation(refs);
    resetInspector(runtimeState);
    renderInspector(runtimeState, refs, { renderSessionContext });
    announceChatStatus(refs, `Session ${sessionId} reset.`);
    showToast(`Session ${sessionId} reset.`, { tone: "info" });
    await loadSessionHistory(runtimeState, refs, sessionId, { updateActionButtons });
    await loadSessions(runtimeState, refs, { updateActionButtons });
  } catch (error) {
    announceChatStatus(refs, error.message || "Could not reset session.");
    showToast(error.message || "Could not reset session.", { tone: "error" });
  } finally {
    setPending(runtimeState, refs, false, "Session ready", { updateActionButtons });
  }
}

export async function deleteActiveSession(runtimeState, refs, { updateActionButtons } = {}) {
  if (!runtimeState.activeSessionId || !runtimeState.deleteEnabled) {
    return;
  }

  await deleteSession(runtimeState, refs, runtimeState.activeSessionId, { updateActionButtons });
}

export function startNewChat(runtimeState, refs, { updateActionButtons } = {}) {
  clearSessionVisualization(refs, runtimeState.activeSessionId);
  runtimeState.activeSessionId = null;
  clearActiveSession();
  clearConversation(refs);
  resetInspector(runtimeState);
  renderInspector(runtimeState, refs, { renderSessionContext });
  if (refs.historyTruncatedCard) {
    refs.historyTruncatedCard.hidden = true;
  }
  setConversationLoading(runtimeState, refs, false, undefined, { updateActionButtons });
  setText(refs.panelStatus, "New chat ready");
  setText(refs.sessionNote, runtimeState.selectedUsecase ? `New chat ready with use case ${runtimeState.selectedUsecase}.` : "New chat ready. Select a use case and send a message.");
  announceChatStatus(refs, "New chat ready.");
  renderSessionList(runtimeState, refs, runtimeState.sessions, DEFAULT_SESSION_LIMIT, false, { updateActionButtons });
  updateStatusBar(runtimeState, refs);
  if (typeof updateActionButtons === "function") {
    updateActionButtons();
  }
}

export function bindSessionActions(runtimeState, refs, { updateActionButtons } = {}) {
  refs.sessionRefresh?.addEventListener("click", async () => {
    await loadSessions(runtimeState, refs, { updateActionButtons });
  });

  refs.sessionNewChat?.addEventListener("click", () => {
    startNewChat(runtimeState, refs, { updateActionButtons });
  });

  refs.sessionReset?.addEventListener("click", async () => {
    await resetActiveSession(runtimeState, refs, { updateActionButtons });
  });

  refs.sessionDelete?.addEventListener("click", async () => {
    await deleteActiveSession(runtimeState, refs, { updateActionButtons });
  });

  refs.sessionList?.addEventListener("keydown", (event) => {
    const currentButton = event.target instanceof Element ? event.target.closest("[data-session-id]") : null;
    if (!(currentButton instanceof HTMLButtonElement)) {
      return;
    }

    const buttons = Array.from(refs.sessionList.querySelectorAll("[data-session-id]"));
    const currentIndex = buttons.indexOf(currentButton);
    if (currentIndex === -1) {
      return;
    }

    let nextIndex = currentIndex;
    if (event.key === "ArrowDown") {
      nextIndex = Math.min(buttons.length - 1, currentIndex + 1);
    } else if (event.key === "ArrowUp") {
      nextIndex = Math.max(0, currentIndex - 1);
    } else if (event.key === "Home") {
      nextIndex = 0;
    } else if (event.key === "End") {
      nextIndex = buttons.length - 1;
    } else {
      return;
    }

    event.preventDefault();
    buttons[nextIndex]?.focus();
  });

  refs.sessionList?.addEventListener("click", async (event) => {
    const deleteButton = event.target instanceof Element ? event.target.closest("[data-session-delete-id]") : null;
    if (deleteButton instanceof HTMLButtonElement) {
      const sessionId = deleteButton.dataset.sessionDeleteId;
      if (!sessionId || !runtimeState.deleteEnabled) {
        return;
      }
      event.preventDefault();
      event.stopPropagation();
      await deleteSession(runtimeState, refs, sessionId, { updateActionButtons });
      return;
    }

    const button = event.target instanceof Element ? event.target.closest("[data-session-id]") : null;
    if (!(button instanceof HTMLButtonElement)) {
      return;
    }
    const sessionId = button.dataset.sessionId;
    if (!sessionId) {
      return;
    }
    await loadSessionHistory(runtimeState, refs, sessionId, { updateActionButtons });
  });
}