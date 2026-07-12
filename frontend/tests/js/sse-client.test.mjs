import assert from "node:assert/strict";
import test from "node:test";

import { resolveEventText, streamSseRequest } from "../../app/static/js/services/sse-client.js";

function createStreamResponse(chunks, { status = 200, contentType = "text/event-stream" } = {}) {
  const encoder = new TextEncoder();
  const body = new ReadableStream({
    start(controller) {
      chunks.forEach((chunk) => controller.enqueue(encoder.encode(chunk)));
      controller.close();
    },
  });

  return new Response(body, {
    status,
    headers: { "content-type": contentType },
  });
}

test.afterEach(() => {
  delete global.fetch;
});

test("streamSseRequest normalizes named events and parses JSON payloads", async () => {
  global.fetch = async () =>
    createStreamResponse([
      'event: message_started\ndata: {"trace_id":"trace-1"}\n\n',
      'event: agent_summary\ndata: {"agent_name":"planner"}\n\n',
      'event: message_completed\ndata: {"finish_reason":"stop"}\n\n',
    ]);

  const frames = [];
  const result = await streamSseRequest("/ui-api/chat/stream", {
    body: { message: "hello" },
    onEvent: (frame) => frames.push(frame),
  });

  assert.equal(result.mode, "stream");
  assert.deepEqual(
    frames.map((frame) => frame.event),
    ["response.started", "agent_summary", "response.completed"]
  );
  assert.equal(frames[0].data.trace_id, "trace-1");
  assert.equal(frames[1].data.agent_name, "planner");
  assert.equal(frames[2].data.finish_reason, "stop");
});

test("streamSseRequest combines multi-line data and ignores unknown events", async () => {
  global.fetch = async () =>
    createStreamResponse([
      "event: mystery\ndata: should be ignored\n\n",
      "event: content_delta\ndata: hello\ndata: world\n\n",
    ]);

  const frames = [];
  await streamSseRequest("/ui-api/chat/stream", {
    body: { message: "hello" },
    onEvent: (frame) => frames.push(frame),
  });

  assert.equal(frames.length, 1);
  assert.equal(frames[0].event, "response.delta");
  assert.equal(resolveEventText(frames[0]), "hello\nworld");
});

test("streamSseRequest preserves leading whitespace in plain-text deltas", async () => {
  global.fetch = async () =>
    createStreamResponse([
      "event: content_delta\ndata:  hello\n\n",
      "event: content_delta\ndata:  world\n\n",
    ]);

  const frames = [];
  await streamSseRequest("/ui-api/chat/stream", {
    body: { message: "hello" },
    onEvent: (frame) => frames.push(frame),
  });

  assert.deepEqual(
    frames.map((frame) => resolveEventText(frame)),
    [" hello", " world"]
  );
});

test("streamSseRequest maps plain-text error events into the standard error payload", async () => {
  global.fetch = async () => createStreamResponse(["event: error\ndata: stream exploded\n\n"]);

  const frames = [];
  await streamSseRequest("/ui-api/chat/stream", {
    body: { message: "hello" },
    onEvent: (frame) => frames.push(frame),
  });

  assert.equal(frames[0].event, "response.error");
  assert.equal(frames[0].data.error.message, "stream exploded");
});

test("streamSseRequest preserves additive visualization artifact lifecycle frames", async () => {
  global.fetch = async () =>
    createStreamResponse([
      'event: artifact.started\ndata: {"artifact_id":"chart-1","type":"chart"}\n\n',
      'event: artifact.completed\ndata: {"artifact":{"artifact_id":"chart-1","type":"chart"}}\n\n',
      'event: artifact.failed\ndata: {"artifact_id":"chart-2","error":{"message":"Delivery failed."}}\n\n',
    ]);

  const frames = [];
  await streamSseRequest("/ui-api/chat/stream", {
    body: { message: "hello" },
    onEvent: (frame) => frames.push(frame),
  });

  assert.equal(frames.length, 3);
  assert.equal(frames[0].event, "artifact.started");
  assert.equal(frames[0].data.artifact_id, "chart-1");
  assert.equal(frames[1].event, "artifact.completed");
  assert.equal(frames[1].data.artifact.artifact_id, "chart-1");
  assert.equal(frames[2].event, "artifact.failed");
  assert.equal(frames[2].data.error.message, "Delivery failed.");
});

test("streamSseRequest falls back to JSON mode when the backend returns application/json", async () => {
  global.fetch = async () =>
    new Response(
      JSON.stringify({
        trace_id: "trace-json",
        session_id: "session-json",
        data: { answer: "fallback response" },
      }),
      {
        status: 200,
        headers: { "content-type": "application/json" },
      }
    );

  const result = await streamSseRequest("/ui-api/chat/stream", {
    body: { message: "hello" },
    onEvent: () => {
      throw new Error("JSON fallback should not emit SSE events");
    },
  });

  assert.equal(result.mode, "json");
  assert.equal(result.payload.data.answer, "fallback response");
});