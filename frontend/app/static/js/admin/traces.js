import { copyText } from "../common/clipboard.js";
import { setText } from "../common/dom.js";
import { showToast } from "../common/toast.js";
import { getJson } from "../services/api-client.js";
import { createCatalogItem, formatDate, formatDuration, formatJson, renderList } from "./rendering.js";

function createTraceResultItem(summary, activeTraceId) {
  const item = document.createElement("li");
  item.className = "admin-list__item admin-trace-result";
  if (summary.trace_id === activeTraceId) {
    item.classList.add("is-active");
  }

  const button = document.createElement("button");
  button.type = "button";
  button.className = "admin-trace-result__button";
  button.dataset.adminTraceSelect = summary.trace_id;
  button.setAttribute("aria-label", `Open trace ${summary.trace_id}`);

  const title = document.createElement("span");
  title.className = "admin-list__title";
  title.textContent = summary.trace_id;

  const meta = document.createElement("span");
  meta.className = "admin-list__meta";
  const metaBits = [
    summary.status || "unknown",
    summary.event_count != null ? `${summary.event_count} events` : null,
    summary.error_count != null ? `${summary.error_count} errors` : null,
    summary.usecase || null,
    summary.event_name || null,
    formatDate(summary.last_event_at || summary.completed_at || summary.started_at),
  ].filter(Boolean);
  meta.textContent = metaBits.join(" · ");

  button.append(title, meta);
  item.append(button);
  return item;
}

function createTraceEventItem(event) {
  const title = `${event.sequence_no || "?"}. ${event.event_name || "event"}`;
  const metaBits = [
    event.event_type || null,
    event.component || null,
    event.status || null,
    event.severity || null,
    event.duration_ms != null ? formatDuration(event.duration_ms) : null,
    formatDate(event.created_at),
  ].filter(Boolean);
  return createCatalogItem(title, metaBits.join(" · "));
}

function buildTraceQuery(refs) {
  const params = new URLSearchParams();
  const entries = [
    ["status", refs.traceStatusInput?.value],
    ["usecase", refs.traceUsecaseInput?.value],
    ["event_name", refs.traceEventNameInput?.value],
    ["event_type", refs.traceEventTypeInput?.value],
  ];

  entries.forEach(([key, value]) => {
    const normalized = value?.trim();
    if (normalized) {
      params.set(key, normalized);
    }
  });

  const limit = refs.traceLimitInput?.value?.trim();
  if (limit) {
    params.set("limit", limit);
  }

  if (refs.traceErrorsOnlyInput?.checked) {
    params.set("errors_only", "true");
  }

  return params;
}

function setTracePending(refs, pending) {
  if (refs.traceSubmit) {
    refs.traceSubmit.disabled = pending;
  }
  if (refs.traceButton) {
    refs.traceButton.disabled = pending;
  }
}

export function renderTraceResults(runtimeState, refs) {
  renderList(
    refs.traceResults,
    runtimeState.traceSearchResults,
    (summary) => createTraceResultItem(summary, runtimeState.activeTraceId),
    runtimeState.debugEnabled ? "No traces matched the current filter set." : "Trace routes are disabled."
  );
}

export function renderTraceDetail(runtimeState, refs) {
  const payload = runtimeState.traceDetailPayload;
  if (!payload) {
    setText(refs.traceDetailSummary, runtimeState.debugEnabled
      ? "Choose a trace result or paste a trace ID to inspect the event timeline."
      : "Trace detail stays unavailable while debug trace routes are disabled.");
    setText(refs.detailTraceId, "Unavailable");
    setText(refs.detailStatus, "Unavailable");
    setText(refs.detailDuration, "Unavailable");
    setText(refs.detailEvents, "Unavailable");
    setText(refs.detailUsecase, "Unavailable");
    setText(refs.traceJson, "Trace detail JSON will appear here.");
    renderList(refs.traceEvents, [], createTraceEventItem, "Trace events will load here.");
    if (refs.traceDetailCopy) {
      refs.traceDetailCopy.disabled = true;
    }
    return;
  }

  const summary = payload.data?.summary ?? {};
  const events = Array.isArray(payload.data?.events) ? payload.data.events : [];
  const metadata = payload.metadata ?? {};

  setText(refs.traceDetailSummary, metadata.truncated
    ? `Showing ${metadata.returned_events ?? events.length} of ${metadata.total_events ?? events.length} events.`
    : `Showing ${events.length} events from the selected trace.`);
  setText(refs.detailTraceId, summary.trace_id || "Unavailable");
  setText(refs.detailStatus, summary.status || "Unavailable");
  setText(refs.detailDuration, formatDuration(summary.duration_ms));
  setText(refs.detailEvents, summary.event_count != null ? String(summary.event_count) : String(events.length));
  setText(refs.detailUsecase, summary.usecase || "Unavailable");
  setText(refs.traceJson, formatJson(payload));
  renderList(refs.traceEvents, events, createTraceEventItem, "No events were returned for this trace.");
  if (refs.traceDetailCopy) {
    refs.traceDetailCopy.disabled = false;
  }
}

export async function runTraceSearch(runtimeState, refs) {
  if (!runtimeState.debugEnabled) {
    return;
  }

  runtimeState.traceSearchPending = true;
  setTracePending(refs, true);
  setText(refs.traceSummary, "Loading trace summaries...");

  try {
    const params = buildTraceQuery(refs);
    const query = params.toString();
    const payload = await getJson(`/debug/traces${query ? `?${query}` : ""}`);
    runtimeState.traceSearchResults = Array.isArray(payload.data?.traces) ? payload.data.traces : [];
    setText(refs.traceSummary, `${payload.metadata?.result_count ?? runtimeState.traceSearchResults.length} trace summaries returned.`);
    renderTraceResults(runtimeState, refs);

    const requestedTraceId = refs.traceIdInput?.value?.trim();
    if (requestedTraceId) {
      await loadTraceDetail(runtimeState, refs, requestedTraceId);
    }
  } catch (error) {
    runtimeState.traceSearchResults = [];
    renderTraceResults(runtimeState, refs);
    setText(refs.traceSummary, error instanceof Error ? error.message : "Trace search failed.");
    showToast("Trace search failed.", { tone: "error" });
  } finally {
    runtimeState.traceSearchPending = false;
    setTracePending(refs, false);
  }
}

export async function loadTraceDetail(runtimeState, refs, traceId) {
  if (!runtimeState.debugEnabled || !traceId) {
    return;
  }

  runtimeState.traceDetailPending = true;
  runtimeState.activeTraceId = traceId;
  renderTraceResults(runtimeState, refs);
  setText(refs.traceDetailSummary, `Loading ${traceId}...`);

  const params = new URLSearchParams();
  const limit = refs.traceLimitInput?.value?.trim();
  if (limit) {
    params.set("limit", limit);
  }

  try {
    const query = params.toString();
    const payload = await getJson(`/debug/traces/${encodeURIComponent(traceId)}${query ? `?${query}` : ""}`);
    runtimeState.traceDetailPayload = payload;
    if (refs.traceIdInput) {
      refs.traceIdInput.value = traceId;
    }
    renderTraceDetail(runtimeState, refs);
  } catch (error) {
    runtimeState.traceDetailPayload = null;
    renderTraceDetail(runtimeState, refs);
    setText(refs.traceDetailSummary, error instanceof Error ? error.message : `Trace ${traceId} could not be loaded.`);
    showToast(`Trace ${traceId} could not be loaded.`, { tone: "error" });
  } finally {
    runtimeState.traceDetailPending = false;
  }
}

export function resetTraceFilters(refs) {
  refs.traceForm?.reset();
  if (refs.traceLimitInput) {
    refs.traceLimitInput.value = "10";
  }
}

export function bindTraceActions(runtimeState, refs) {
  refs.traceButton?.addEventListener("click", async () => {
    await runTraceSearch(runtimeState, refs);
  });

  refs.traceForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const traceId = refs.traceIdInput?.value?.trim();
    if (traceId) {
      await loadTraceDetail(runtimeState, refs, traceId);
      return;
    }
    await runTraceSearch(runtimeState, refs);
  });

  refs.traceReset?.addEventListener("click", () => {
    resetTraceFilters(refs);
    runtimeState.traceSearchResults = [];
    runtimeState.traceDetailPayload = null;
    runtimeState.activeTraceId = null;
    renderTraceResults(runtimeState, refs);
    renderTraceDetail(runtimeState, refs);
    setText(refs.traceSummary, "Search headings are cleared. Load recent traces when ready.");
  });

  refs.traceResults?.addEventListener("click", async (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) {
      return;
    }
    const button = target.closest("[data-admin-trace-select]");
    if (!(button instanceof HTMLElement)) {
      return;
    }

    const traceId = button.dataset.adminTraceSelect;
    if (traceId) {
      await loadTraceDetail(runtimeState, refs, traceId);
    }
  });

  refs.traceDetailCopy?.addEventListener("click", async () => {
    await copyText(refs.traceJson?.textContent || "", "Trace JSON copied.", "Could not copy trace JSON.");
  });
}