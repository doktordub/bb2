import assert from "node:assert/strict";
import test from "node:test";

import { BackendApiError, deleteJson, getJson, postJson, requestJson } from "../../app/static/js/services/api-client.js";

test.beforeEach(() => {
  global.document = {
    body: {
      dataset: {
        uiApiBase: "/ui-api",
      },
    },
  };
});

test.afterEach(() => {
  delete global.document;
  delete global.fetch;
});

test("getJson resolves relative UI API paths and returns parsed JSON", async () => {
  const calls = [];
  global.fetch = async (url, options) => {
    calls.push({ url, options });
    return new Response(JSON.stringify({ status: "ok" }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };

  const payload = await getJson("/backend/health");

  assert.deepEqual(payload, { status: "ok" });
  assert.equal(calls[0].url, "/ui-api/backend/health");
  assert.equal(calls[0].options.method, "GET");
  assert.equal(calls[0].options.credentials, "same-origin");
  assert.equal(calls[0].options.headers.Accept, "application/json");
});

test("postJson serializes the request body and preserves the backend validation message", async () => {
  const calls = [];
  global.fetch = async (url, options) => {
    calls.push({ url, options });
    return new Response(
      JSON.stringify({
        error: {
          message: "Backend validation failed.",
        },
      }),
      {
        status: 422,
        headers: { "content-type": "application/json" },
      }
    );
  };

  await assert.rejects(
    postJson("/chat", { message: "hello fallback" }),
    (error) => {
      assert.ok(error instanceof BackendApiError);
      assert.equal(error.status, 422);
      assert.equal(error.message, "Backend validation failed.");
      return true;
    }
  );

  assert.equal(calls[0].url, "/ui-api/chat");
  assert.equal(calls[0].options.method, "POST");
  assert.equal(calls[0].options.body, JSON.stringify({ message: "hello fallback" }));
  assert.equal(calls[0].options.headers["Content-Type"], "application/json");
});

test("deleteJson uses the DELETE method", async () => {
  const calls = [];
  global.fetch = async (url, options) => {
    calls.push({ url, options });
    return new Response(JSON.stringify({ deleted: true }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };

  const payload = await deleteJson("/sessions/session-123");

  assert.deepEqual(payload, { deleted: true });
  assert.equal(calls[0].url, "/ui-api/sessions/session-123");
  assert.equal(calls[0].options.method, "DELETE");
});

test("requestJson surfaces network timeout failures from fetch", async () => {
  const timeoutError = new Error("Network timeout");
  timeoutError.name = "TimeoutError";

  global.fetch = async () => {
    throw timeoutError;
  };

  await assert.rejects(requestJson("/chat"), timeoutError);
});