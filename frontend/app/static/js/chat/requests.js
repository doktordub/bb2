import { setText } from "../common/dom.js";
import { showToast } from "../common/toast.js";
import { setActiveSessionId } from "../services/session-store.js";
import { resolveEventText, streamSseRequest } from "../services/sse-client.js";
import { postJson } from "../services/api-client.js";
import { appendMessage, buildMessageMeta, replaceMessageContent, updateMessageMeta } from "./conversation.js";
import { renderInspector, updateInspectorFromResponse, updateInspectorFromStreamFrame } from "./inspector.js";
import { loadSessions, renderSessionContext } from "./sessions.js";
import { announceChatStatus, buildUiApiPath, resetInspector, setPending, withTransport } from "./runtime-state.js";

function beginChatRequest(runtimeState, refs, requestBody, { renderSessionContext, updateActionButtons } = {}) {
  runtimeState.lastRequestBody = requestBody;
  runtimeState.lastFailure = null;
  resetInspector(runtimeState);
  renderInspector(runtimeState, refs, { renderSessionContext });
  if (typeof updateActionButtons === "function") {
    updateActionButtons();
  }

  appendMessage(refs, {
    role: "user",
    content: requestBody.message,
    createdAt: new Date().toISOString(),
    metadata: {
      message_chars: requestBody.message.length,
      mode: requestBody.usecase || runtimeState.selectedUsecase || "default",
      transport: runtimeState.streamingEnabled ? "streaming" : "request/response",
    },
  });
  return appendMessage(refs, {
    role: "assistant",
    content: "",
    createdAt: new Date().toISOString(),
    metadata: {},
    isLoading: true,
  });
}

async function finalizeSuccessfulChat(
  runtimeState,
  refs,
  assistantCard,
  answer,
  { statusText, transport, syncFromPayload = null, renderSessionContext, updateActionButtons } = {}
) {
  replaceMessageContent(refs, assistantCard, answer, { streaming: false });
  runtimeState.lastAssistantAnswer = answer;

  if (typeof syncFromPayload === "function") {
    syncFromPayload();
  }

  const resolvedSessionId = runtimeState.inspector.sessionId || runtimeState.activeSessionId;
  if (resolvedSessionId) {
    runtimeState.activeSessionId = resolvedSessionId;
    setActiveSessionId(resolvedSessionId);
    setText(refs.sessionNote, `Active session: ${resolvedSessionId}`);
  }

  runtimeState.inspector.transport = transport;
  runtimeState.inspector.lastError = null;
  updateMessageMeta(assistantCard, buildMessageMeta({
    createdAt: new Date().toISOString(),
    metadata: {
      message_chars: answer.length,
      mode: runtimeState.inspector.usecase,
      transport,
    },
    traceId: runtimeState.inspector.traceId,
  }));
  renderInspector(runtimeState, refs, { renderSessionContext });

  if (refs.input) {
    refs.input.value = "";
    refs.input.focus();
  }
  setPending(runtimeState, refs, false, statusText, { updateActionButtons });
  await loadSessions(runtimeState, refs, { updateActionButtons });
}

async function runNonStreamingRequest(
  runtimeState,
  refs,
  requestBody,
  assistantCard,
  { fallback = false, renderSessionContext, updateActionButtons } = {}
) {
  setPending(runtimeState, refs, true, fallback ? "Falling back to request/response" : "Waiting for assistant response", { updateActionButtons });
  announceChatStatus(
    refs,
    fallback
      ? "Streaming is unavailable. Falling back to request and response."
      : "Waiting for the assistant response."
  );
  try {
    const payload = await postJson("/chat", withTransport(requestBody, "non_streaming"));
    const answer = payload?.data?.answer || "No answer returned.";
    await finalizeSuccessfulChat(runtimeState, refs, assistantCard, answer, {
      statusText: "Response received",
      transport: "request/response",
      renderSessionContext,
      syncFromPayload: () => updateInspectorFromResponse(runtimeState, refs, payload, {
        transport: "request/response",
        renderSessionContext,
        updateActionButtons,
      }),
      updateActionButtons,
    });
    announceChatStatus(refs, "Assistant response received.");
    showToast(fallback ? "Streaming unavailable. Response received through request/response." : "Response received.", { tone: "info" });
    return payload;
  } catch (error) {
    runtimeState.lastFailure = error.message || "Chat request failed.";
    runtimeState.inspector.lastError = runtimeState.lastFailure;
    renderInspector(runtimeState, refs, { renderSessionContext });
    replaceMessageContent(refs, assistantCard, `Request failed.\n\n${runtimeState.lastFailure}`, { streaming: false });
    updateMessageMeta(assistantCard, buildMessageMeta({
      createdAt: new Date().toISOString(),
      metadata: {
        transport: "request/response",
      },
      status: "Request failed",
      traceId: runtimeState.inspector.traceId,
    }));
    setPending(runtimeState, refs, false, "Request failed", { updateActionButtons });
    announceChatStatus(refs, runtimeState.lastFailure);
    showToast(runtimeState.lastFailure, { tone: "error" });
    return null;
  }
}

async function runStreamingRequest(runtimeState, refs, requestBody, assistantCard, { renderSessionContext, updateActionButtons } = {}) {
  const controller = new AbortController();
  runtimeState.activeAbortController = controller;
  const streamState = {
    announcedStart: false,
    receivedFrame: false,
    contentStarted: false,
    completed: false,
    answer: "",
  };

  setPending(runtimeState, refs, true, "Opening stream", { updateActionButtons });
  announceChatStatus(refs, "Opening streaming response.");
  replaceMessageContent(refs, assistantCard, "", { streaming: true, loadingLabel: "Opening streaming response..." });

  try {
    const streamResult = await streamSseRequest(buildUiApiPath("/chat/stream"), {
      body: withTransport(requestBody, "streaming"),
      signal: controller.signal,
      onEvent: (frame) => {
        streamState.receivedFrame = true;
        updateInspectorFromStreamFrame(runtimeState, refs, frame, { renderSessionContext });

        if (frame.event === "response.delta" || frame.event === "message") {
          const delta = resolveEventText(frame);
          if (delta) {
            streamState.contentStarted = true;
            if (!streamState.announcedStart) {
              streamState.announcedStart = true;
              announceChatStatus(refs, "Assistant response is streaming.");
            }
            streamState.answer += delta;
            runtimeState.lastAssistantAnswer = streamState.answer;
            replaceMessageContent(refs, assistantCard, streamState.answer, { streaming: true, loadingLabel: "Streaming reply..." });
          }
          return;
        }

        if (frame.event === "response.started") {
          if (!streamState.announcedStart) {
            streamState.announcedStart = true;
            announceChatStatus(refs, "Assistant response is streaming.");
          }
          replaceMessageContent(refs, assistantCard, streamState.answer, { streaming: true, loadingLabel: "Streaming reply..." });
          setText(refs.panelStatus, "Streaming response");
          return;
        }

        if (frame.event === "response.completed") {
          streamState.completed = true;
          return;
        }

        if (frame.event === "response.error") {
          const error = frame.data?.error && typeof frame.data.error === "object" ? frame.data.error : frame.data;
          const streamError = new Error(error.message || "Streaming request failed.");
          streamError.name = "StreamResponseError";
          throw streamError;
        }
      },
    });

    runtimeState.activeAbortController = null;

    if (streamResult.mode === "json" && streamResult.payload?.data?.answer) {
      const payload = streamResult.payload;
      const answer = payload?.data?.answer || "No answer returned.";
      await finalizeSuccessfulChat(runtimeState, refs, assistantCard, answer, {
        statusText: "Response received",
        transport: "request/response",
        renderSessionContext,
        syncFromPayload: () => updateInspectorFromResponse(runtimeState, refs, payload, {
          transport: "request/response",
          renderSessionContext,
          updateActionButtons,
        }),
        updateActionButtons,
      });
      announceChatStatus(refs, "Assistant response received without incremental streaming frames.");
      showToast("Streaming returned a complete response without incremental frames.", { tone: "info" });
      return payload;
    }

    if (streamResult.mode !== "stream" || !streamState.receivedFrame) {
      announceChatStatus(refs, "Streaming is unavailable for this request. Falling back to request and response.");
      showToast("Streaming is unavailable for this request. Falling back to request/response.", { tone: "warning" });
      return runNonStreamingRequest(runtimeState, refs, requestBody, assistantCard, {
        fallback: true,
        renderSessionContext,
        updateActionButtons,
      });
    }

    if (!streamState.completed && !streamState.contentStarted) {
      announceChatStatus(refs, "The stream ended before content arrived. Falling back to request and response.");
      showToast("The stream ended before content arrived. Falling back to request/response.", { tone: "warning" });
      return runNonStreamingRequest(runtimeState, refs, requestBody, assistantCard, {
        fallback: true,
        renderSessionContext,
        updateActionButtons,
      });
    }

    await finalizeSuccessfulChat(runtimeState, refs, assistantCard, streamState.answer || "No answer returned.", {
      statusText: streamState.completed ? "Streaming complete" : "Streaming stopped",
      transport: "streaming",
      renderSessionContext,
      updateActionButtons,
    });
    announceChatStatus(
      refs,
      streamState.completed ? "Streaming response completed." : "Streaming response captured."
    );
    showToast(streamState.completed ? "Streaming response completed." : "Streaming response captured.", { tone: "info" });
    return {
      trace_id: runtimeState.inspector.traceId,
      session_id: runtimeState.inspector.sessionId,
      data: {
        answer: streamState.answer,
      },
    };
  } catch (error) {
    runtimeState.activeAbortController = null;

    if (error.name === "AbortError") {
      runtimeState.inspector.finishReason = "aborted";
      runtimeState.inspector.lastError = null;
      renderInspector(runtimeState, refs, { renderSessionContext });
      replaceMessageContent(
        refs,
        assistantCard,
        streamState.answer || "Streaming stopped before the assistant returned any content.",
        { streaming: false }
      );
      updateMessageMeta(assistantCard, buildMessageMeta({
        createdAt: new Date().toISOString(),
        metadata: {
          message_chars: streamState.answer.length,
          mode: runtimeState.inspector.usecase,
          transport: "streaming",
        },
        status: "Stopped",
        traceId: runtimeState.inspector.traceId,
      }));
      if (runtimeState.inspector.sessionId) {
        runtimeState.activeSessionId = runtimeState.inspector.sessionId;
        setActiveSessionId(runtimeState.activeSessionId);
      }
      setPending(runtimeState, refs, false, "Streaming stopped", { updateActionButtons });
      announceChatStatus(refs, "Streaming stopped.");
      showToast("Streaming stopped.", { tone: "info" });
      return null;
    }

    if (!streamState.contentStarted) {
      announceChatStatus(refs, "Streaming failed before content started. Falling back to request and response.");
      showToast("Streaming failed before content started. Falling back to request/response.", { tone: "warning" });
      return runNonStreamingRequest(runtimeState, refs, requestBody, assistantCard, {
        fallback: true,
        renderSessionContext,
        updateActionButtons,
      });
    }

    runtimeState.lastFailure = error.message || "Streaming request failed.";
    runtimeState.inspector.lastError = runtimeState.lastFailure;
    renderInspector(runtimeState, refs, { renderSessionContext });
    replaceMessageContent(
      refs,
      assistantCard,
      `${streamState.answer}\n\nStream error.\n\n${runtimeState.lastFailure}`,
      { streaming: false }
    );
    updateMessageMeta(assistantCard, buildMessageMeta({
      createdAt: new Date().toISOString(),
      metadata: {
        message_chars: streamState.answer.length,
        mode: runtimeState.inspector.usecase,
        transport: "streaming",
      },
      status: "Stream failed",
      traceId: runtimeState.inspector.traceId,
    }));
    setPending(runtimeState, refs, false, "Stream failed", { updateActionButtons });
    announceChatStatus(refs, runtimeState.lastFailure);
    showToast(runtimeState.lastFailure, { tone: "error" });
    return null;
  }
}

export async function runChatRequest(runtimeState, refs, requestBody, { renderSessionContext, updateActionButtons } = {}) {
  const assistantCard = beginChatRequest(runtimeState, refs, requestBody, { renderSessionContext, updateActionButtons });

  if (runtimeState.streamingEnabled) {
    return runStreamingRequest(runtimeState, refs, requestBody, assistantCard, { renderSessionContext, updateActionButtons });
  }

  return runNonStreamingRequest(runtimeState, refs, requestBody, assistantCard, { renderSessionContext, updateActionButtons });
}