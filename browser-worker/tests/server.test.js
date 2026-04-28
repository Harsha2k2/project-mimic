const assert = require("node:assert/strict");
const { after, before, test } = require("node:test");

const { startServer, stopServer } = require("../src/server");

let server;
let baseUrl;

before(async () => {
  const result = await startServer({
    port: 0,
    env: {
      PLAYWRIGHT_BROWSERS: "chromium,firefox",
      PLAYWRIGHT_PRIMARY_BROWSER: "chromium",
    },
  });
  server = result.server;
  baseUrl = result.baseUrl;
});

after(async () => {
  await stopServer(server);
});

test("healthz returns ok", async () => {
  const response = await fetch(`${baseUrl}/healthz`);
  assert.equal(response.status, 200);
  const payload = await response.json();
  assert.equal(payload.status, "ok");
});

test("readyz returns readiness payload", async () => {
  const response = await fetch(`${baseUrl}/readyz`);
  assert.equal(response.status, 200);
  const payload = await response.json();
  assert.equal(payload.status, "ready");
  assert.equal(payload.primary_browser, "chromium");
  assert.deepEqual(payload.browsers, ["chromium", "firefox"]);
});

test("worker info returns configuration", async () => {
  const response = await fetch(`${baseUrl}/v1/worker/info`);
  assert.equal(response.status, 200);
  const payload = await response.json();
  assert.equal(payload.primary_browser, "chromium");
  assert.ok(payload.worker_id);
  assert.equal(payload.readiness, "ready");
});
