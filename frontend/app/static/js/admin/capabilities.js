import { setBannerState } from "../common/banner.js";
import { setText } from "../common/dom.js";
import { boolLabel } from "../common/formatters.js";
import { setStatePill } from "../common/status.js";
import { createCatalogItem, formatJson, renderList } from "./rendering.js";

export function renderCapabilities(runtimeState, refs) {
  const shellState = runtimeState.shellState;
  const capabilities = shellState.capabilities;
  if (!capabilities) {
    setBannerState(refs.capabilitiesBanner, refs.capabilitiesBannerTitle, refs.capabilitiesBannerBody, {
      hidden: false,
      tone: "warning",
      title: "Capabilities are unavailable.",
      body: "The admin shell could not load backend capabilities, so chat, session, and debug summaries fall back to safe placeholders.",
    });
    setStatePill(refs.debugPill, "Debug traces: Disabled", "disabled");
    setStatePill(refs.restartPill, "Restart: Hidden", "disabled");
    setStatePill(refs.tracePill, "Unavailable", "disabled");
    setText(refs.debugCopy, "Trace routing is unavailable until the capability route can be loaded again.");
    setText(refs.capabilitiesJson, formatJson({}));
    if (refs.restartCard) {
      refs.restartCard.hidden = true;
    }
    return;
  }

  setBannerState(refs.capabilitiesBanner, refs.capabilitiesBannerTitle, refs.capabilitiesBannerBody, { hidden: true });
  setText(refs.capabilitiesJson, formatJson(shellState.capabilitiesPayload));

  const chat = capabilities.chat ?? {};
  const sessions = capabilities.sessions ?? {};
  const usecases = Array.isArray(capabilities.usecases) ? capabilities.usecases : [];
  const agents = Array.isArray(capabilities.agents) ? capabilities.agents : [];
  const debug = capabilities.debug ?? {};
  const tools = capabilities.tools ?? {};
  const memory = capabilities.memory ?? {};
  const llm = capabilities.llm ?? {};

  setText(refs.chatEnabled, boolLabel(Boolean(chat.enabled)));
  setText(refs.chatStreaming, boolLabel(Boolean(chat.streaming_enabled)));
  setText(refs.chatLimit, chat.max_message_chars ? String(chat.max_message_chars) : "Unavailable");

  setText(refs.sessionList, boolLabel(Boolean(sessions.list_enabled)));
  setText(refs.sessionHistory, boolLabel(Boolean(sessions.history_enabled)));
  setText(refs.sessionReset, boolLabel(Boolean(sessions.reset_enabled)));
  setText(refs.sessionDelete, boolLabel(Boolean(sessions.delete_enabled)));

  renderList(refs.usecases, usecases, (usecase) => {
    const title = usecase.display_name || usecase.name || "Unnamed use case";
    const meta = [
      usecase.strategy_type || "strategy unavailable",
      usecase.streaming_supported ? "streaming" : "request/response",
      usecase.memory_enabled ? "memory" : "memory off",
      usecase.tools_enabled ? "tools" : "tools off",
    ].join(" · ");
    return createCatalogItem(title, meta);
  });

  renderList(refs.agents, agents, (agent) => {
    const title = agent.display_name || agent.name || "Unnamed agent";
    const capabilitySummary = Array.isArray(agent.capabilities) && agent.capabilities.length > 0
      ? agent.capabilities.join(", ")
      : "no declared capabilities";
    const meta = `${agent.type || "unknown type"} · ${agent.streaming_supported ? "streaming" : "non-streaming"} · ${capabilitySummary}`;
    return createCatalogItem(title, meta);
  });

  const toolCount = Number.isFinite(Number(tools.total_tools)) ? Number(tools.total_tools) : 0;
  const approvalCount = Number.isFinite(Number(tools.approval_required_tools)) ? Number(tools.approval_required_tools) : 0;
  setText(refs.toolsStatus, tools.enabled ? `${toolCount} advertised` : "Disabled");
  setText(refs.toolsApprovals, approvalCount > 0 ? `${approvalCount} required` : "None");
  setText(refs.memoryStatus, memory.enabled ? `${memory.provider || "configured"}` : "Disabled");
  setText(refs.llmProfile, llm.enabled ? llm.default_profile || "Unavailable" : "Disabled");
  setText(refs.llmStreaming, boolLabel(Boolean(llm.streaming_supported)));

  runtimeState.debugEnabled = Boolean(shellState.frontendFlags.debugTracesEnabled) && Boolean(debug.trace_routes_enabled);
  runtimeState.restartEnabled = Boolean(shellState.frontendFlags.restartEnabled) && Boolean(debug.restart_enabled);

  setStatePill(refs.debugPill, `Debug traces: ${runtimeState.debugEnabled ? "Enabled" : "Disabled"}`, runtimeState.debugEnabled ? "available" : "disabled");
  setStatePill(refs.tracePill, runtimeState.debugEnabled ? "Available" : "Unavailable", runtimeState.debugEnabled ? "available" : "disabled");
  setText(
    refs.debugCopy,
    runtimeState.debugEnabled
      ? "The backend trace routes are available through the proxy. Search summaries or jump straight to a specific trace id."
      : shellState.frontendFlags.debugTracesEnabled
        ? "The backend capability response currently disables trace routes."
        : "Frontend configuration keeps debug trace routes disabled."
  );

  if (refs.traceButton) {
    refs.traceButton.disabled = !runtimeState.debugEnabled;
  }
  if (refs.traceSubmit) {
    refs.traceSubmit.disabled = !runtimeState.debugEnabled;
  }
  if (refs.traceReset) {
    refs.traceReset.disabled = !runtimeState.debugEnabled;
  }

  setStatePill(refs.restartPill, runtimeState.restartEnabled ? "Restart: Available" : "Restart: Hidden", runtimeState.restartEnabled ? "available" : "disabled");
  if (refs.restartCard) {
    refs.restartCard.hidden = !runtimeState.restartEnabled;
  }
  if (runtimeState.restartEnabled) {
    setStatePill(refs.restartCardPill, "Explicit confirmation required", "info");
    setText(refs.restartCopy, "Both frontend configuration and backend capability allow restart. The proxy still requires a confirmation step before posting /ui-api/admin/restart.");
  }
  if (refs.restartButton) {
    refs.restartButton.disabled = !runtimeState.restartEnabled;
  }
}