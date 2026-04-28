const http = require("node:http");
const { URL } = require("node:url");
const { buildConfig } = require("./config");
const { SidecarClient } = require("./sidecar-client");
const { PlaywrightEmitter } = require("./playwright-emitter");

function loadPlaywrightVersion() {
  try {
    const metadata = require("playwright/package.json");
    return metadata.version || "unknown";
  } catch (err) {
    return "unknown";
  }
}

function buildReadiness(config) {
  let error = null;
  let missing = [];
  try {
    const playwright = require("playwright");
    missing = config.browsers.filter((name) => !(name in playwright));
  } catch (err) {
    error = err instanceof Error ? err.message : String(err);
    missing = [...config.browsers];
  }

  return {
    ready: !error && missing.length === 0,
    missingBrowsers: missing,
    error,
    playwrightVersion: loadPlaywrightVersion(),
  };
}

function writeJson(res, statusCode, payload) {
  const body = JSON.stringify(payload);
  res.writeHead(statusCode, {
    "content-type": "application/json",
    "content-length": Buffer.byteLength(body),
  });
  res.end(body);
}

function writeError(res, statusCode, message) {
  writeJson(res, statusCode, { error: message });
}

function readJsonBody(req) {
  return new Promise((resolve, reject) => {
    let body = "";
    req.on("data", (chunk) => {
      body += chunk;
    });
    req.on("end", () => {
      if (!body) {
        resolve({});
        return;
      }
      try {
        resolve(JSON.parse(body));
      } catch (err) {
        reject(new Error("invalid_json"));
      }
    });
    req.on("error", () => reject(new Error("invalid_body")));
  });
}

function createServer({ config = buildConfig() } = {}) {
  const readiness = buildReadiness(config);
  const sidecarClient = new SidecarClient(config.sidecarUrl);
  const emitter = new PlaywrightEmitter({ browserName: config.primaryBrowser });

  const server = http.createServer(async (req, res) => {
    const url = new URL(req.url || "/", `http://${req.headers.host || "localhost"}`);

    if (req.method === "GET" && url.pathname === "/healthz") {
      writeJson(res, 200, { status: "ok" });
      return;
    }

    if (req.method === "GET" && url.pathname === "/readyz") {
      const statusCode = readiness.ready ? 200 : 503;
      writeJson(res, statusCode, {
        status: readiness.ready ? "ready" : "not_ready",
        primary_browser: config.primaryBrowser,
        browsers: config.browsers,
        missing_browsers: readiness.missingBrowsers,
        error: readiness.error,
        playwright_version: readiness.playwrightVersion,
      });
      return;
    }

    if (req.method === "GET" && url.pathname === "/v1/worker/info") {
      writeJson(res, 200, {
        worker_id: config.workerId,
        port: config.port,
        browsers: config.browsers,
        primary_browser: config.primaryBrowser,
        playwright_version: readiness.playwrightVersion,
        triton_endpoint: config.tritonEndpoint,
        proxy_gateway: config.proxyGateway,
        sidecar_url: config.sidecarUrl,
        emit_enabled: config.emitEnabled,
        readiness: readiness.ready ? "ready" : "not_ready",
      });
      return;
    }

    if (req.method === "POST" && url.pathname === "/v1/mimetic/pointer/plan") {
      try {
        const payload = await readJsonBody(req);
        const response = await sidecarClient.planPointer(payload);
        writeJson(res, 200, response);
      } catch (err) {
        if (err instanceof Error && err.message === "invalid_json") {
          writeError(res, 400, "invalid_json");
        } else {
          writeError(res, 502, err instanceof Error ? err.message : "sidecar_unavailable");
        }
      }
      return;
    }

    if (req.method === "POST" && url.pathname === "/v1/mimetic/keyboard/plan") {
      try {
        const payload = await readJsonBody(req);
        const response = await sidecarClient.planKeystrokes(payload);
        writeJson(res, 200, response);
      } catch (err) {
        if (err instanceof Error && err.message === "invalid_json") {
          writeError(res, 400, "invalid_json");
        } else {
          writeError(res, 502, err instanceof Error ? err.message : "sidecar_unavailable");
        }
      }
      return;
    }

    if (req.method === "POST" && url.pathname === "/v1/mimetic/pointer/emit") {
      if (!config.emitEnabled) {
        writeError(res, 503, "playwright_emit_disabled");
        return;
      }
      try {
        const payload = await readJsonBody(req);
        const response = await sidecarClient.planPointer(payload);
        await emitter.emitPointer(response.events || []);
        writeJson(res, 200, { status: "emitted", event_count: (response.events || []).length });
      } catch (err) {
        if (err instanceof Error && err.message === "invalid_json") {
          writeError(res, 400, "invalid_json");
        } else {
          writeError(res, 502, err instanceof Error ? err.message : "emit_failed");
        }
      }
      return;
    }

    if (req.method === "POST" && url.pathname === "/v1/mimetic/keyboard/emit") {
      if (!config.emitEnabled) {
        writeError(res, 503, "playwright_emit_disabled");
        return;
      }
      try {
        const payload = await readJsonBody(req);
        const response = await sidecarClient.planKeystrokes(payload);
        await emitter.emitKeystrokes(response.events || []);
        writeJson(res, 200, { status: "emitted", event_count: (response.events || []).length });
      } catch (err) {
        if (err instanceof Error && err.message === "invalid_json") {
          writeError(res, 400, "invalid_json");
        } else {
          writeError(res, 502, err instanceof Error ? err.message : "emit_failed");
        }
      }
      return;
    }

    if (req.method !== "GET" && req.method !== "POST") {
      writeError(res, 405, "method_not_allowed");
      return;
    }

    writeError(res, 404, "not_found");
  });

  server._emitter = emitter;
  return { server, config, readiness };
}

function startServer({ port, env } = {}) {
  const config = buildConfig(env);
  if (port !== undefined && port !== null) {
    config.port = port;
  }
  const { server, readiness } = createServer({ config });

  return new Promise((resolve, reject) => {
    server.on("error", reject);
    server.listen(config.port, () => {
      const address = server.address();
      const host = "127.0.0.1";
      const baseUrl = typeof address === "string" ? address : `http://${host}:${address.port}`;
      resolve({ server, config, readiness, baseUrl });
    });
  });
}

function stopServer(server) {
  return new Promise((resolve) => {
    const emitter = server._emitter;
    const finalize = () => server.close(() => resolve());

    if (emitter && typeof emitter.stop === "function") {
      emitter.stop().then(finalize).catch(finalize);
      return;
    }

    finalize();
  });
}

module.exports = {
  buildReadiness,
  createServer,
  startServer,
  stopServer,
};
