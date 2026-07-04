import { setText } from "../common/dom.js";
import { setStatePill } from "../common/status.js";
import { showToast } from "../common/toast.js";
import { postJson } from "../services/api-client.js";
import { formatDate, formatJson } from "./rendering.js";

function showRestartDialog(runtimeState, refs) {
  if (!runtimeState.restartEnabled || !(refs.restartDialog instanceof HTMLDialogElement)) {
    return;
  }
  refs.restartDialog.showModal();
}

async function requestRestart(runtimeState, refs) {
  if (!runtimeState.restartEnabled || runtimeState.restartPending) {
    return;
  }

  runtimeState.restartPending = true;
  if (refs.restartButton) {
    refs.restartButton.disabled = true;
  }
  setText(refs.restartReceipt, "Submitting restart request...");

  try {
    const payload = await postJson("/admin/restart", {});
    setText(refs.restartJson, formatJson(payload));
    const requestId = payload.data?.request_id || "unknown-request";
    const requestedAt = payload.data?.requested_at ? formatDate(payload.data.requested_at) : "just now";
    setText(refs.restartReceipt, `Restart request ${requestId} accepted at ${requestedAt}.`);
    setStatePill(refs.restartCardPill, "Restart requested", "available");
    showToast("Restart request accepted.", { tone: "info" });
  } catch (error) {
    setText(refs.restartReceipt, error instanceof Error ? error.message : "Restart request failed.");
    showToast("Restart request failed.", { tone: "error" });
  } finally {
    runtimeState.restartPending = false;
    if (refs.restartButton) {
      refs.restartButton.disabled = !runtimeState.restartEnabled;
    }
  }
}

export function bindRestartActions(runtimeState, refs) {
  refs.restartButton?.addEventListener("click", () => {
    showRestartDialog(runtimeState, refs);
  });

  refs.restartDialog?.addEventListener("close", async () => {
    if (refs.restartDialog?.returnValue === "confirm") {
      await requestRestart(runtimeState, refs);
    }
  });
}