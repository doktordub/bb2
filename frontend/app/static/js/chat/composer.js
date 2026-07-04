import { copyText } from "../common/clipboard.js";
import { showToast } from "../common/toast.js";
import { setComposerPinned, setSelectedUsecase } from "../services/session-store.js";
import { scrollConversationToBottom } from "./conversation.js";
import { renderInspector, updateStreamingMode } from "./inspector.js";
import { runChatRequest } from "./requests.js";
import { announceChatStatus, buildChatRequest, toPositiveInteger, updateActionButtons } from "./runtime-state.js";

const CHAT_CLIPBOARD_OPTIONS = { errorTone: "warning" };

export function applyComposerPinState(runtimeState, refs) {
  const pinned = Boolean(runtimeState.composerPinned);
  refs.chatWorkspace?.classList.toggle("chat-workspace-shell--composer-pinned", pinned);
  refs.chatWorkspace?.setAttribute("data-composer-pinned", String(pinned));

  if (refs.composerPinToggle) {
    refs.composerPinToggle.setAttribute("aria-pressed", String(pinned));
    refs.composerPinToggle.textContent = pinned ? "Composer pinned" : "Pin composer";
    refs.composerPinToggle.title = pinned
      ? "Pinned: the conversation panel scrolls while the composer stays in view."
      : "Unpinned: the full page scrolls normally.";
  }

  if (pinned) {
    scrollConversationToBottom(refs, { force: true });
  }
}

function validateMessage(runtimeState, refs) {
  const message = refs.input?.value?.trim() ?? "";
  if (!message) {
    showToast("Enter a message before sending.", { tone: "warning" });
    return null;
  }

  const maxChars = toPositiveInteger(runtimeState.capabilities?.chat?.max_message_chars);
  if (maxChars && message.length > maxChars) {
    showToast(`Message exceeds the ${maxChars} character limit.`, { tone: "warning" });
    return null;
  }

  return message;
}

export function bindComposerShell(runtimeState, refs, { renderSessionContext, refreshCounter } = {}) {
  if (!refs.composer || !refs.input) {
    return;
  }

  const refreshControls = () => updateActionButtons(runtimeState, refs, { refreshCounter });

  refs.input.addEventListener("input", () => {
    refreshControls();
  });

  refs.input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      refs.composer.requestSubmit();
    }
  });

  refs.usecaseSelect?.addEventListener("change", () => {
    runtimeState.selectedUsecase = refs.usecaseSelect.value || null;
    runtimeState.inspector.usecase = runtimeState.selectedUsecase;
    setSelectedUsecase(runtimeState.selectedUsecase);
    updateStreamingMode(runtimeState, Boolean(runtimeState.capabilities?.chat?.streaming_enabled), refs);
    renderInspector(runtimeState, refs, { renderSessionContext });
    refreshControls();
  });

  refs.composer.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (runtimeState.pending || runtimeState.conversationLoading) {
      return;
    }
    const message = validateMessage(runtimeState, refs);
    if (!message) {
      return;
    }

    const requestBody = buildChatRequest({
      message,
      sessionId: runtimeState.activeSessionId,
      usecase: runtimeState.selectedUsecase || refs.usecaseSelect?.value || null,
    });
    await runChatRequest(runtimeState, refs, requestBody, {
      renderSessionContext,
      updateActionButtons: refreshControls,
    });
  });
}

export function bindLayoutActions(runtimeState, refs) {
  refs.composerPinToggle?.addEventListener("click", () => {
    runtimeState.composerPinned = !runtimeState.composerPinned;
    setComposerPinned(runtimeState.composerPinned);
    applyComposerPinState(runtimeState, refs);
    announceChatStatus(
      refs,
      runtimeState.composerPinned
        ? "Composer pinned. Conversation messages now scroll inside the chat panel."
        : "Composer unpinned. The full page now scrolls normally."
    );
  });
}

export function bindConversationActions(runtimeState, refs, { renderSessionContext, refreshCounter } = {}) {
  const refreshControls = () => updateActionButtons(runtimeState, refs, { refreshCounter });

  refs.copyLastMessageButton?.addEventListener("click", async () => {
    await copyText(
      runtimeState.lastAssistantAnswer,
      "Assistant reply copied.",
      "Could not copy the assistant reply.",
      CHAT_CLIPBOARD_OPTIONS
    );
  });

  refs.copyTraceButton?.addEventListener("click", async () => {
    await copyText(runtimeState.lastTraceId, "Trace ID copied.", "Could not copy the trace ID.", CHAT_CLIPBOARD_OPTIONS);
  });

  refs.openTraceButton?.addEventListener("click", () => {
    if (!runtimeState.lastTraceId) {
      return;
    }

    const url = new URL(`${window.location.origin}/admin`);
    url.searchParams.set("trace_id", runtimeState.lastTraceId);
    url.hash = "trace-access";
    window.location.assign(url.toString());
  });

  refs.retryButton?.addEventListener("click", async () => {
    if (!runtimeState.lastRequestBody) {
      return;
    }
    await runChatRequest(runtimeState, refs, runtimeState.lastRequestBody, {
      renderSessionContext,
      updateActionButtons: refreshControls,
    });
  });

  refs.stopButton?.addEventListener("click", () => {
    runtimeState.activeAbortController?.abort();
  });
}