const http = require("node:http");
const { URL } = require("node:url");
const { buildConfig } = require("./config");

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

function createServer({ config = buildConfig() } = {}) {
  const readiness = buildReadiness(config);

  const server = http.createServer((req, res) => {
    const url = new URL(req.url || "/", `http://${req.headers.host || "localhost"}`);

    if (req.method !== "GET") {
      writeJson(res, 405, { error: "method_not_allowed" });
      return;
    }

    if (url.pathname === "/healthz") {
      writeJson(res, 200, { status: "ok" });
      return;
    }

    if (url.pathname === "/readyz") {
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

    if (url.pathname === "/v1/worker/info") {
      writeJson(res, 200, {
        worker_id: config.workerId,
        port: config.port,
        browsers: config.browsers,
        primary_browser: config.primaryBrowser,
        playwright_version: readiness.playwrightVersion,
        triton_endpoint: config.tritonEndpoint,
        proxy_gateway: config.proxyGateway,
        readiness: readiness.ready ? "ready" : "not_ready",
      });
      return;
    }

    writeJson(res, 404, { error: "not_found" });
  });

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
    server.close(() => resolve());
  });
}

module.exports = {
  buildReadiness,
  createServer,
  startServer,
  stopServer,
};
