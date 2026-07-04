import { setBannerState } from "../common/banner.js";
import { setText } from "../common/dom.js";
import { setStatePill } from "../common/status.js";
import { createCatalogItem, formatJson, renderList, syncText } from "./rendering.js";

function collectSubsystemItems(health) {
  return [
    ["Backend", health.backend?.configured ? health.status : "unknown", [health.backend?.service, health.backend?.environment].filter(Boolean).join(" · ") || null],
    ["API", health.api?.configured ? "ok" : "unknown", [health.api?.docs_enabled ? "docs enabled" : "docs hidden", health.api?.streaming_enabled ? "streaming" : null].filter(Boolean).join(" · ") || null],
    ["Workflow state", health.workflow_state?.status, [health.workflow_state?.provider, health.workflow_state?.schema_initialized ? "schema ready" : null].filter(Boolean).join(" · ") || null],
    ["Trace store", health.trace?.status, [health.trace?.provider, health.trace?.retention_enabled ? "retention on" : null].filter(Boolean).join(" · ") || null],
    ["Memory", health.memory?.status, [health.memory?.provider, health.memory?.search_available ? "search ready" : null].filter(Boolean).join(" · ") || null],
    ["LLM", health.llm?.status, [health.llm?.default_profile, health.llm?.profiles_configured ? "profiles ready" : null].filter(Boolean).join(" · ") || null],
    ["MCP", health.mcp?.status, [health.mcp?.transport, health.mcp?.adapter_reachable ? "adapter reachable" : "adapter unavailable"].filter(Boolean).join(" · ") || null],
    ["Orchestration", health.orchestration?.status, [health.orchestration?.default_strategy, health.orchestration?.enabled ? "enabled" : "disabled"].filter(Boolean).join(" · ") || null],
    ["Checks", health.checks?.status, [health.checks?.healthy_count != null ? `${health.checks.healthy_count} healthy` : null, health.checks?.unhealthy_count != null ? `${health.checks.unhealthy_count} unhealthy` : null].filter(Boolean).join(" · ") || null],
  ];
}

export function renderHealth(runtimeState, refs) {
  const shellState = runtimeState.shellState;
  const health = shellState.healthPayload ?? {};
  const overallStatus = String(health.status ?? shellState.backendStatus ?? "unknown");
  const overallLabel = overallStatus.charAt(0).toUpperCase() + overallStatus.slice(1);

  setStatePill(refs.healthPill, `Health: ${overallLabel}`, shellState.backendStatus);
  setText(refs.overallStatus, overallLabel);
  syncText([refs.serviceName, refs.serviceNameDetail], health.service ?? health.backend?.service ?? "Unavailable");
  syncText([refs.serviceVersion, refs.serviceVersionDetail], health.version ?? health.backend?.version ?? "Unavailable");
  syncText([refs.serviceEnvironment, refs.serviceEnvironmentDetail], health.environment ?? health.backend?.environment ?? "Unavailable");
  setText(refs.healthJson, formatJson(health));

  renderList(
    refs.subsystems,
    collectSubsystemItems(health),
    ([label, status, detail]) => createCatalogItem(label, `${String(status ?? "unknown")}${detail ? ` · ${detail}` : ""}`)
  );

  if (shellState.backendStatus === "online") {
    setBannerState(refs.healthBanner, refs.healthBannerTitle, refs.healthBannerBody, { hidden: true });
    return;
  }

  const tone = shellState.backendStatus === "offline" ? "error" : "warning";
  const title = shellState.backendStatus === "degraded" ? "Backend health is degraded." : "Backend health is unavailable.";
  const body = shellState.backendStatus === "unknown"
    ? "The frontend could not confidently map the health payload, so the admin shell stays in a cautious summary state."
    : shellState.backendStatus === "degraded"
      ? "Some backend subsystems are degraded. Capability cards remain available, but operational actions should stay conservative."
      : "The backend health route could not be reached. Admin data remains in placeholder mode until connectivity returns.";

  setBannerState(refs.healthBanner, refs.healthBannerTitle, refs.healthBannerBody, {
    hidden: false,
    tone,
    title,
    body,
  });
}