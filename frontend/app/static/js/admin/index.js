import { waitForShellReady } from "../core/app-shell.js";
import { renderCapabilities } from "./capabilities.js";
import { renderHealth } from "./health.js";
import { initializeRefs } from "./refs.js";
import { bindRestartActions } from "./restart.js";
import { bindTabs, hydrateFromQuery, setActiveTab } from "./tabs.js";
import { bindTraceActions, loadTraceDetail, renderTraceDetail, renderTraceResults, runTraceSearch } from "./traces.js";

function createRuntimeState(shellState) {
	return {
		shellState,
		activeTab: "health",
		debugEnabled: false,
		restartEnabled: false,
		traceSearchResults: [],
		activeTraceId: null,
		traceDetailPayload: null,
		traceSearchPending: false,
		traceDetailPending: false,
		restartPending: false,
	};
}

export async function initializeAdminPage() {
	if (document.body?.dataset.page !== "admin") {
		return;
	}

	const refs = initializeRefs();
	const shellState = await waitForShellReady();
	const runtimeState = createRuntimeState(shellState);
	hydrateFromQuery(runtimeState, refs);
	bindTabs(runtimeState, refs);
	setActiveTab(runtimeState, refs, runtimeState.activeTab);
	renderHealth(runtimeState, refs);
	renderCapabilities(runtimeState, refs);
	renderTraceResults(runtimeState, refs);
	renderTraceDetail(runtimeState, refs);
	bindTraceActions(runtimeState, refs);
	bindRestartActions(runtimeState, refs);

	if (runtimeState.debugEnabled && runtimeState.activeTraceId) {
		await loadTraceDetail(runtimeState, refs, runtimeState.activeTraceId);
	} else if (runtimeState.debugEnabled) {
		await runTraceSearch(runtimeState, refs);
	}
}

if (typeof document !== "undefined") {
	void initializeAdminPage();
}