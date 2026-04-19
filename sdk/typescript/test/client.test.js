const assert = require("node:assert/strict");
const test = require("node:test");

const { ProjectMimicClient } = require("../dist/client.js");

test("createSession sends expected payload and headers", async () => {
  let capturedUrl = "";
  let capturedOptions = {};

  global.fetch = async (url, options) => {
    capturedUrl = String(url);
    capturedOptions = options;
    return new Response(JSON.stringify({ session_id: "session-1" }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };

  const client = new ProjectMimicClient({
    baseUrl: "http://localhost:8000",
    apiKey: "sdk-key",
    tenantId: "tenant-a",
  });

  const response = await client.createSession({ goal: "sdk-goal", maxSteps: 3 });

  assert.equal(response.session_id, "session-1");
  assert.equal(capturedUrl, "http://localhost:8000/api/v1/sessions");
  assert.equal(capturedOptions.method, "POST");
  assert.equal(capturedOptions.headers["X-API-Key"], "sdk-key");
  assert.equal(capturedOptions.headers["X-Tenant-ID"], "tenant-a");
  assert.deepEqual(JSON.parse(capturedOptions.body), { goal: "sdk-goal", max_steps: 3 });
});

test("rollbackSession throws on non-2xx", async () => {
  global.fetch = async () =>
    new Response(JSON.stringify({ detail: "forbidden" }), {
      status: 403,
      headers: { "content-type": "application/json" },
    });

  const client = new ProjectMimicClient({ baseUrl: "http://localhost:8000" });

  await assert.rejects(
    async () => {
      await client.rollbackSession("session-2");
    },
    /status 403/,
  );
});
