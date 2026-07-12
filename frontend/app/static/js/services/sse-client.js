function normalizeEventName(name) {
	if (typeof name !== "string") {
		return "message";
	}

	const normalized = name.trim();
	if (!normalized) {
		return "message";
	}

	const legacyMap = {
		message_started: "response.started",
		content_delta: "response.delta",
		tool_call_summary: "tool_call_summary",
		agent_summary: "agent_summary",
		trace_summary: "trace_summary",
		message_completed: "response.completed",
		error: "response.error",
	};

	return legacyMap[normalized] || normalized;
}

function appendDataLine(lines, value) {
	if (typeof value !== "string") {
		return;
	}

	lines.push(value.startsWith(" ") ? value.slice(1) : value);
}

function parseEventPayload(eventName, dataBlock) {
	if (typeof dataBlock !== "string") {
		return { raw: "", text: "" };
	}

	const trimmed = dataBlock.trim();
	if (!trimmed) {
		return { raw: "", text: "" };
	}

	try {
		return JSON.parse(trimmed);
	} catch (_error) {
		if (eventName === "response.error") {
			return {
				error: {
					code: "stream_error",
					message: trimmed,
					retryable: true,
				},
			};
		}

		return {
			raw: dataBlock,
			text: dataBlock,
		};
	}
}

function parseFrame(frameText) {
	const lines = frameText.replace(/\r\n/g, "\n").split("\n");
	let eventName = "message";
	let eventId = null;
	const dataLines = [];

	lines.forEach((line) => {
		if (!line || line.startsWith(":")) {
			return;
		}

		const separatorIndex = line.indexOf(":");
		if (separatorIndex === -1) {
			dataLines.push(line);
			return;
		}

		const field = line.slice(0, separatorIndex).trim();
		const value = line.slice(separatorIndex + 1);
		if (field === "event") {
			eventName = normalizeEventName(value);
			return;
		}
		if (field === "data") {
			appendDataLine(dataLines, value);
			return;
		}
		if (field === "id") {
			eventId = value.trim() || null;
		}
	});

	const dataBlock = dataLines.join("\n");
	return {
		event: eventName,
		id: eventId,
		data: parseEventPayload(eventName, dataBlock),
		raw: dataBlock,
	};
}

function isRecognizedEvent(eventName) {
	return new Set([
		"response.started",
		"response.delta",
		"artifact.started",
		"artifact.completed",
		"artifact.failed",
		"response.artifact",
		"response.metadata",
		"response.completed",
		"response.error",
		"heartbeat",
		"tool_call_summary",
		"agent_summary",
		"trace_summary",
		"message",
	]).has(eventName);
}

async function pumpStream(reader, onEvent) {
	const decoder = new TextDecoder();
	let buffer = "";

	while (true) {
		const { value, done } = await reader.read();
		if (done) {
			break;
		}

		buffer += decoder.decode(value, { stream: true });
		const frames = buffer.split(/\n\n/);
		buffer = frames.pop() || "";

		frames.forEach((frameText) => {
			const frame = parseFrame(frameText);
			if (!isRecognizedEvent(frame.event)) {
				return;
			}
			onEvent(frame);
		});
	}

	const trailing = decoder.decode();
	if (trailing) {
		buffer += trailing;
	}

	const finalFrame = buffer.trim();
	if (finalFrame) {
		const frame = parseFrame(finalFrame);
		if (isRecognizedEvent(frame.event)) {
			onEvent(frame);
			return;
		}

		onEvent({
			event: "response.delta",
			id: null,
			data: {
				text: finalFrame,
				raw: finalFrame,
			},
			raw: finalFrame,
		});
	}
}

export async function streamSseRequest(path, { body, signal, headers = {}, onEvent }) {
	const response = await fetch(path, {
		method: "POST",
		headers: {
			Accept: "text/event-stream, application/json",
			"Content-Type": "application/json",
			...headers,
		},
		body: JSON.stringify(body),
		credentials: "same-origin",
		signal,
	});

	const contentType = response.headers.get("content-type") || "";
	if (!response.ok || contentType.includes("application/json")) {
		let payload = null;
		try {
			payload = await response.json();
		} catch (_error) {
			payload = null;
		}
		return {
			ok: response.ok,
			mode: "json",
			status: response.status,
			payload,
			response,
		};
	}

	if (!response.body) {
		return {
			ok: false,
			mode: "unsupported",
			status: response.status,
			payload: null,
			response,
		};
	}

	const reader = response.body.getReader();
	await pumpStream(reader, onEvent);
	return {
		ok: true,
		mode: "stream",
		status: response.status,
		payload: null,
		response,
	};
}

export function resolveEventText(frame) {
	const payload = frame?.data;
	if (typeof payload === "string") {
		return payload;
	}
	if (payload && typeof payload === "object") {
		const candidates = [payload.text, payload.delta, payload.answer, payload.message, payload.raw];
		for (const candidate of candidates) {
			if (typeof candidate === "string" && candidate.length > 0) {
				return candidate;
			}
		}
	}
	if (typeof frame?.raw === "string" && frame.raw.length > 0) {
		return frame.raw;
	}
	return "";
}