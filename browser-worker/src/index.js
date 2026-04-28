const { startServer, stopServer } = require("./server");

async function main() {
  const { server, baseUrl, config } = await startServer();
  console.log(`[browser-worker] listening on ${baseUrl}`);
  console.log(`[browser-worker] primary browser: ${config.primaryBrowser}`);

  const shutdown = async (signal) => {
    console.log(`[browser-worker] received ${signal}, shutting down`);
    await stopServer(server);
    process.exit(0);
  };

  process.on("SIGINT", () => shutdown("SIGINT"));
  process.on("SIGTERM", () => shutdown("SIGTERM"));
}

main().catch((err) => {
  console.error(`[browser-worker] failed to start: ${err instanceof Error ? err.message : err}`);
  process.exit(1);
});
