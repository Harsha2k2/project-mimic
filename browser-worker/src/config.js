const DEFAULT_PORT = 7000;

function parseList(value, fallback) {
  if (!value) {
    return fallback;
  }
  const items = value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  return items.length ? items : fallback;
}

function normalizeBrowsers(items) {
  return items.map((item) => item.toLowerCase());
}

function buildConfig(env = process.env) {
  const browsers = normalizeBrowsers(parseList(env.PLAYWRIGHT_BROWSERS, ["chromium"]));
  const primaryRaw = (env.PLAYWRIGHT_PRIMARY_BROWSER || browsers[0] || "chromium").toLowerCase();
  const primaryBrowser = browsers.includes(primaryRaw) ? primaryRaw : browsers[0] || primaryRaw;
  const portValue = Number.parseInt(env.PORT || `${DEFAULT_PORT}`, 10);
  const port = Number.isNaN(portValue) ? DEFAULT_PORT : portValue;
  const workerId = env.WORKER_ID && env.WORKER_ID.trim() ? env.WORKER_ID.trim() : `worker-${process.pid}`;

  return {
    port,
    workerId,
    browsers,
    primaryBrowser,
    tritonEndpoint: env.TRITON_ENDPOINT || "",
    proxyGateway: env.PROXY_GATEWAY || "",
  };
}

module.exports = {
  DEFAULT_PORT,
  buildConfig,
};
