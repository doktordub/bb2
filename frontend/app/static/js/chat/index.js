import { waitForShellReady } from "../core/app-shell.js";
import { bindConversationActions, bindComposerShell, bindLayoutActions, applyComposerPinState } from "./composer.js";
import { refreshCounter, setConversationLoading, updateCounter } from "./conversation.js";
import { bindDrawers } from "./drawers.js";
import { applyCapabilities, applyHealthState, renderInspector } from "./inspector.js";
import { initializeRefs } from "./refs.js";
import { createRuntimeState, updateActionButtons } from "./runtime-state.js";
import { bindSessionActions, loadSessionHistory, loadSessions, renderSessionContext, startNewChat } from "./sessions.js";

export async function initializeChatPage() {
	if (document.body?.dataset.page !== "chat") {
		return;
	}

	const refs = initializeRefs();
	bindDrawers(refs);
	if (refs.composer) {
		refs.composer.setAttribute("aria-busy", "true");
	}
	if (refs.conversationShell) {
		refs.conversationShell.setAttribute("aria-busy", "true");
	}

	const shellState = await waitForShellReady();
	const runtimeState = createRuntimeState(shellState);
	const refreshControls = () => updateActionButtons(runtimeState, refs, {
		refreshCounter: () => refreshCounter(refs),
	});

	applyComposerPinState(runtimeState, refs);
	setConversationLoading(runtimeState, refs, true, "loading...", { updateActionButtons: refreshControls });
	applyHealthState(runtimeState, refs);
	applyCapabilities(runtimeState, refs, {
		renderSessionContext,
		updateActionButtons: refreshControls,
		updateCounter: (limit) => updateCounter(refs, limit),
	});
	renderInspector(runtimeState, refs, { renderSessionContext });
	bindComposerShell(runtimeState, refs, {
		renderSessionContext,
		refreshCounter: () => refreshCounter(refs),
	});
	bindLayoutActions(runtimeState, refs);
	bindConversationActions(runtimeState, refs, {
		renderSessionContext,
		refreshCounter: () => refreshCounter(refs),
	});
	bindSessionActions(runtimeState, refs, { updateActionButtons: refreshControls });

	if (runtimeState.listEnabled) {
		await loadSessions(runtimeState, refs, { updateActionButtons: refreshControls });
	}
	if (runtimeState.activeSessionId && runtimeState.historyEnabled) {
		await loadSessionHistory(runtimeState, refs, runtimeState.activeSessionId, { updateActionButtons: refreshControls });
	} else {
		startNewChat(runtimeState, refs, { updateActionButtons: refreshControls });
	}
	refreshControls();
}

if (typeof document !== "undefined") {
	void initializeChatPage();
}