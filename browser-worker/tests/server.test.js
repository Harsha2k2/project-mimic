const assert = require("node:assert/strict");
const { after, before, test } = require("node:test");

const http = require("node:http");

const { startServer, stopServer } = require("../src/server");

let server;
let baseUrl;
let sidecarServer;
let sidecarUrl;

async function startSidecarStub() {
  sidecarServer = http.createServer((req, res) => {
    if (req.method === "POST" && req.url === "/v1/mimetic/pointer/plan") {
      const payload = JSON.stringify({
        events: [
          { t_ms: 0, x: 10, y: 10, event_type: "move" },
          { t_ms: 10, x: 10, y: 10, event_type: "down" },
          { t_ms: 20, x: 10, y: 10, event_type: "up" },
        ],
      });
      res.writeHead(200, { "content-type": "application/json" });
      res.end(payload);
      return;
    }

    if (req.method === "POST" && req.url === "/v1/mimetic/keyboard/plan") {
      const payload = JSON.stringify({
        events: [
          { t_ms: 0, key: "h", event_type: "keydown" },
          { t_ms: 10, key: "h", event_type: "keyup" },
        ],
      });
      res.writeHead(200, { "content-type": "application/json" });
      res.end(payload);
      return;
    }

    res.writeHead(404, { "content-type": "application/json" });
    res.end(JSON.stringify({ error: "not_found" }));
  });

  await new Promise((resolve) => sidecarServer.listen(0, resolve));
  const address = sidecarServer.address();
  sidecarUrl = `http://127.0.0.1:${address.port}`;
}

async function stopSidecarStub() {
  if (!sidecarServer) {
    return;
  }
  await new Promise((resolve) => sidecarServer.close(resolve));
}

before(async () => {
  await startSidecarStub();
  const result = await startServer({
    port: 0,
    env: {
      PLAYWRIGHT_BROWSERS: "chromium,firefox",
      PLAYWRIGHT_PRIMARY_BROWSER: "chromium",
      PLAYWRIGHT_EMIT_ENABLED: "false",
      SIDECAR_URL: sidecarUrl,
    },
  });
  server = result.server;
  baseUrl = result.baseUrl;
});

after(async () => {
  await stopServer(server);
  await stopSidecarStub();
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
  assert.equal(payload.emit_enabled, false);
  assert.equal(payload.sidecar_url, sidecarUrl);
  assert.equal(payload.readiness, "ready");
});

test("pointer plan proxies to sidecar", async () => {
  const response = await fetch(`${baseUrl}/v1/mimetic/pointer/plan`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      start: { x: 1, y: 1 },
      target: { x: 2, y: 2 },
      viewport_width: 100,
      viewport_height: 100,
      dwell_ms: 10,
    }),
  });

  assert.equal(response.status, 200);
  const payload = await response.json();
  assert.equal(payload.events.length, 3);
});

test("emit endpoints return disabled when emit is off", async () => {
  const response = await fetch(`${baseUrl}/v1/mimetic/keyboard/emit`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ text: "hi", base_delay_ms: 20 }),
  });

  assert.equal(response.status, 503);
  const payload = await response.json();
  assert.equal(payload.error, "playwright_emit_disabled");
});
