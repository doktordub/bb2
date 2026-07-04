const DEFAULT_HEADERS = {
	Accept: "application/json",
};

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

function buildUrl(path) {
	if (path.startsWith("http://") || path.startsWith("https://")) {
		return path;
	}

	const normalizedPath = path.startsWith("/") ? path : `/${path}`;
	return `${resolveUiApiBase()}${normalizedPath}`;
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

export async function requestJson(path, { method = "GET", body, headers = {}, signal } = {}) {
	const response = await fetch(buildUrl(path), {
		method,
		headers: {
			...DEFAULT_HEADERS,
			...(body === undefined ? {} : { "Content-Type": "application/json" }),
			...headers,
		},
		body: body === undefined ? undefined : JSON.stringify(body),
		credentials: "same-origin",
		signal,
	});

	const payload = await parseResponse(response);
	if (!response.ok) {
		throw new BackendApiError(resolveErrorMessage(payload, response.status), response.status, payload);
	}

	return payload;
}

export function getJson(path, options) {
	return requestJson(path, { ...options, method: "GET" });
}

export function postJson(path, body, options) {
	return requestJson(path, { ...options, method: "POST", body });
}

export function deleteJson(path, options) {
	return requestJson(path, { ...options, method: "DELETE" });
}