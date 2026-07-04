import { setText } from "../common/dom.js";
import { formatDate as formatDateValue } from "../common/formatters.js";
import { renderMarkdownLite } from "./markdown.js";
import { syncBusyState, toPositiveInteger, truncateLabel } from "./runtime-state.js";

const formatDate = (value) => formatDateValue(value, "Timestamp unavailable");

function syncMessageCharCount(card, content) {
  if (!card) {
    return;
  }

  const length = typeof content === "string" ? content.length : 0;
  card.dataset.messageChars = String(length);
}

function getConversationCharCount(refs) {
  if (!refs.conversationThread) {
    return 0;
  }

  return Array.from(refs.conversationThread.querySelectorAll(".chat-message")).reduce((total, card) => {
    const count = Number(card.dataset.messageChars ?? "0");
    return Number.isFinite(count) && count > 0 ? total + count : total;
  }, 0);
}

function setThreadVisible(refs, visible) {
  const loading = Boolean(refs.loadingChatCard && !refs.loadingChatCard.hidden);
  if (refs.conversationThread) {
    refs.conversationThread.hidden = !visible;
  }
  if (refs.emptyChatCard) {
    refs.emptyChatCard.hidden = loading || visible;
  }
}

function createMessageCard({ role, content, createdAt, metadata = {}, isLoading = false }) {
  const article = document.createElement("article");
  article.className = `chat-message ${role === "user" ? "chat-message--user" : "chat-message--assistant"}`;
  syncMessageCharCount(article, content);

  const bubble = document.createElement("div");
  bubble.className = "chat-message__bubble";

  const body = document.createElement("div");
  body.className = "chat-message__body";
  if (isLoading) {
    const loading = document.createElement("p");
    loading.className = "assistant-loading";
    loading.textContent = "Waiting for backend response...";
    body.append(loading);
  } else {
    body.innerHTML = renderMarkdownLite(content);
  }

  bubble.append(body);

  const meta = document.createElement("div");
  meta.className = "chat-message__meta";
  const metaItems = buildMessageMeta({
    createdAt,
    metadata,
    status: isLoading ? "Pending" : null,
    traceId: metadata.trace_id,
    transport: metadata.transport,
  });
  metaItems.forEach((item, index) => {
    const line = document.createElement("span");
    line.className = index === metaItems.length - 1 && isLoading
      ? "chat-message__meta-item chat-message__meta-item--status"
      : "chat-message__meta-item";
    line.textContent = item;
    meta.append(line);
  });

  article.append(bubble, meta);
  return article;
}

export function scrollConversationToBottom(refs, { force = false } = {}) {
  const viewport = refs.conversationViewport;
  if (!(viewport instanceof HTMLElement)) {
    return;
  }

  const distanceFromBottom = viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight;
  if (!force && distanceFromBottom > 48) {
    return;
  }

  window.requestAnimationFrame(() => {
    viewport.scrollTop = viewport.scrollHeight;
  });
}

export function updateCounter(refs, limit) {
  if (!refs.input || !refs.charCounter) {
    return;
  }

  const currentLength = refs.input.disabled ? 0 : refs.input.value.length;
  const threadLength = getConversationCharCount(refs);
  const totalLength = threadLength + currentLength;
  refs.charCounter.textContent = limit
    ? `${totalLength} total · ${currentLength} / ${limit}`
    : `${totalLength} total · ${currentLength} / --`;
}

export function refreshCounter(refs) {
  updateCounter(refs, toPositiveInteger(refs.input?.getAttribute("maxLength")));
}

export function buildMessageMeta({ createdAt, metadata = {}, status = null, traceId = null, transport = null }) {
  const meta = [];
  if (typeof createdAt === "string" && createdAt) {
    meta.push(formatDate(createdAt));
  }

  if (typeof metadata.message_chars === "number") {
    meta.push(`${metadata.message_chars} chars`);
  }

  const resolvedUsecase = typeof metadata.mode === "string" && metadata.mode
    ? metadata.mode
    : typeof metadata.usecase === "string" && metadata.usecase
      ? metadata.usecase
      : null;
  if (resolvedUsecase) {
    meta.push(resolvedUsecase);
  }

  const resolvedTransport = typeof transport === "string" && transport
    ? transport
    : typeof metadata.transport === "string" && metadata.transport
      ? metadata.transport
      : null;
  if (resolvedTransport) {
    meta.push(resolvedTransport);
  }

  const resolvedTraceId = typeof traceId === "string" && traceId
    ? traceId
    : typeof metadata.trace_id === "string" && metadata.trace_id
      ? metadata.trace_id
      : null;
  if (typeof metadata.trace_fragment === "string" && metadata.trace_fragment) {
    meta.push(`trace ${metadata.trace_fragment}`);
  } else if (resolvedTraceId) {
    meta.push(`trace ${truncateLabel(resolvedTraceId, 18)}`);
  }

  if (typeof status === "string" && status) {
    meta.push(status);
  }

  return meta;
}

export function setConversationLoading(runtimeState, refs, loading, message = "loading...", { updateActionButtons } = {}) {
  runtimeState.conversationLoading = loading;
  if (refs.loadingChatCard) {
    refs.loadingChatCard.hidden = !loading;
  }
  if (loading) {
    setText(refs.loadingChatCopy, message);
    if (refs.emptyChatCard) {
      refs.emptyChatCard.hidden = true;
    }
    if (refs.conversationThread) {
      refs.conversationThread.hidden = true;
    }
    if (refs.historyTruncatedCard) {
      refs.historyTruncatedCard.hidden = true;
    }
  } else {
    const hasMessages = Boolean(refs.conversationThread?.childElementCount);
    if (refs.conversationThread) {
      refs.conversationThread.hidden = !hasMessages;
    }
    if (refs.emptyChatCard) {
      refs.emptyChatCard.hidden = hasMessages;
    }
  }
  syncBusyState(runtimeState, refs);
  if (typeof updateActionButtons === "function") {
    updateActionButtons();
  }
}

export function clearConversation(refs) {
  if (refs.conversationThread) {
    refs.conversationThread.replaceChildren();
  }
  setThreadVisible(refs, false);
  if (refs.historyTruncatedCard) {
    refs.historyTruncatedCard.hidden = true;
  }
  refreshCounter(refs);
}

export function appendMessage(refs, message, { scroll = true } = {}) {
  if (!refs.conversationThread) {
    return null;
  }
  setThreadVisible(refs, true);
  const card = createMessageCard(message);
  refs.conversationThread.append(card);
  refreshCounter(refs);
  if (scroll) {
    scrollConversationToBottom(refs, { force: true });
  }
  return card;
}

export function replaceMessageContent(refs, card, content, { streaming = false, loadingLabel = "Waiting for backend response..." } = {}) {
  const body = card?.querySelector(".chat-message__body");
  if (!body) {
    return;
  }

  syncMessageCharCount(card, content);
  body.classList.toggle("is-streaming", streaming);
  if (streaming && !content) {
    const loading = document.createElement("p");
    loading.className = "assistant-loading";
    loading.textContent = loadingLabel;
    body.replaceChildren(loading);
    refreshCounter(refs);
    return;
  }

  body.innerHTML = renderMarkdownLite(content || "");
  refreshCounter(refs);
  scrollConversationToBottom(refs, { force: true });
}

export function updateMessageMeta(card, entries) {
  const meta = card?.querySelector(".chat-message__meta");
  if (!meta) {
    return;
  }

  meta.replaceChildren();
  entries.filter(Boolean).forEach((entry) => {
    const line = document.createElement("span");
    line.className = "chat-message__meta-item";
    line.textContent = entry;
    meta.append(line);
  });
}