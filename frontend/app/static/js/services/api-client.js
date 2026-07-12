const DEFAULT_HEADERS = {
	Accept: "application/json",
};

const DEFAULT_SESSION_HEADER = "X-Session-Id";

export class BackendApiError extends Error {
	constructor(message, status, payload) {
		super(message);
		this.name = "BackendApiError";
		this.status = status;
		this.payload = payload;
	}
}

function resolveUiApiBase() {
	return document.body?.dataset.uiApiBase || "/ui-api";
}

function resolveSessionHeaderName() {
	const configured = document.body?.dataset.sessionIdHeader;
	return typeof configured === "string" && configured.trim()
		? configured.trim()
		: DEFAULT_SESSION_HEADER;
}

function buildUrl(path) {
	if (path.startsWith("http://") || path.startsWith("https://")) {
		return path;
	}

	const normalizedPath = path.startsWith("/") ? path : `/${path}`;
	const base = resolveUiApiBase();
	if (normalizedPath === base || normalizedPath.startsWith(`${base}/`)) {
		return normalizedPath;
	}
	return `${base}${normalizedPath}`;
}

function buildHeaders({ body, headers = {}, sessionId = null } = {}) {
	return {
		...DEFAULT_HEADERS,
		...(body === undefined ? {} : { "Content-Type": "application/json" }),
		...(sessionId ? { [resolveSessionHeaderName()]: sessionId } : {}),
		...headers,
	};
}

async function parseResponse(response) {
	const contentType = response.headers.get("content-type") || "";
	if (contentType.includes("application/json")) {
		return response.json();
	}

	return response.text();
}

function resolveErrorMessage(payload, status) {
	if (payload && typeof payload === "object") {
		const error = payload.error;
		if (error && typeof error === "object" && typeof error.message === "string") {
			return error.message;
		}
	}

	return `Backend request failed with status ${status}.`;
}

export async function requestJsonDetailed(path, { method = "GET", body, headers = {}, signal, sessionId = null } = {}) {
	const response = await fetch(buildUrl(path), {
		method,
		headers: buildHeaders({ body, headers, sessionId }),
		body: body === undefined ? undefined : JSON.stringify(body),
		credentials: "same-origin",
		signal,
	});

	const payload = await parseResponse(response);
	if (!response.ok) {
		throw new BackendApiError(resolveErrorMessage(payload, response.status), response.status, payload);
	}

	return {
		payload,
		response,
	};
}

export async function requestJson(path, options = {}) {
	const { payload } = await requestJsonDetailed(path, options);
	return payload;
}

export function getJson(path, options) {
	return requestJson(path, { ...options, method: "GET" });
}

export function getJsonDetailed(path, options) {
	return requestJsonDetailed(path, { ...options, method: "GET" });
}

export function postJson(path, body, options) {
	return requestJson(path, { ...options, method: "POST", body });
}

export function deleteJson(path, options) {
	return requestJson(path, { ...options, method: "DELETE" });
}