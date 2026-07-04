const SESSION_STORAGE_KEY = "pluggable-agentic-ai.chat-session-state";

function safeStorage(action, fallback) {
	try {
		return action();
	} catch (_error) {
		return fallback;
	}
}

function defaultState() {
	return {
		activeSessionId: null,
		selectedUsecase: null,
		panelState: {
			sessionsCollapsed: false,
			inspectorCollapsed: false,
		},
		layoutState: {
			composerPinned: true,
		},
	};
}

function normalizeState(value) {
	const state = defaultState();
	if (!value || typeof value !== "object") {
		return state;
	}

	if (typeof value.activeSessionId === "string" && value.activeSessionId.trim()) {
		state.activeSessionId = value.activeSessionId.trim();
	}
	if (typeof value.selectedUsecase === "string" && value.selectedUsecase.trim()) {
		state.selectedUsecase = value.selectedUsecase.trim();
	}
	if (value.panelState && typeof value.panelState === "object") {
		state.panelState.sessionsCollapsed = Boolean(value.panelState.sessionsCollapsed);
		state.panelState.inspectorCollapsed = Boolean(value.panelState.inspectorCollapsed);
	}
	if (value.layoutState && typeof value.layoutState === "object") {
		state.layoutState.composerPinned = value.layoutState.composerPinned !== false;
	}

	return state;
}

function readState() {
	const stored = safeStorage(() => window.localStorage.getItem(SESSION_STORAGE_KEY), null);
	if (!stored) {
		return defaultState();
	}

	try {
		return normalizeState(JSON.parse(stored));
	} catch (_error) {
		return defaultState();
	}
}

function writeState(state) {
	safeStorage(() => {
		window.localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(state));
		return null;
	}, null);
}

let currentState = readState();

export function getSessionState() {
	return {
		...currentState,
		panelState: {
			...currentState.panelState,
		},
		layoutState: {
			...currentState.layoutState,
		},
	};
}

export function updateSessionState(patch) {
	currentState = normalizeState({
		...currentState,
		...patch,
		panelState: {
			...currentState.panelState,
			...(patch?.panelState ?? {}),
		},
		layoutState: {
			...currentState.layoutState,
			...(patch?.layoutState ?? {}),
		},
	});
	writeState(currentState);
	return getSessionState();
}

export function setActiveSessionId(sessionId) {
	return updateSessionState({
		activeSessionId: typeof sessionId === "string" && sessionId.trim() ? sessionId.trim() : null,
	});
}

export function setSelectedUsecase(usecase) {
	return updateSessionState({
		selectedUsecase: typeof usecase === "string" && usecase.trim() ? usecase.trim() : null,
	});
}

export function clearActiveSession() {
	return updateSessionState({ activeSessionId: null });
}

export function setPanelCollapsed(panelName, collapsed) {
	if (!["sessionsCollapsed", "inspectorCollapsed"].includes(panelName)) {
		return getSessionState();
	}

	return updateSessionState({
		panelState: {
			[panelName]: Boolean(collapsed),
		},
	});
}

export function setComposerPinned(pinned) {
	return updateSessionState({
		layoutState: {
			composerPinned: Boolean(pinned),
		},
	});
}