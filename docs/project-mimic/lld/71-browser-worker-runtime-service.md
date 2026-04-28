# LLD 71: Browser Worker Runtime Service

## Feature

Introduce a minimal Node.js browser worker runtime that boots Playwright dependencies, exposes health endpoints, and reports configuration for downstream control-plane coordination.

## Scope

- Create a standalone Node.js service for the browser worker runtime.
- Configure Playwright as a runtime dependency.
- Provide a container image with Playwright browsers installed.
- Expose health and readiness endpoints for Kubernetes probes.

## Runtime Endpoints

### Health

`GET /healthz`

- Returns `{ "status": "ok" }`.

### Readiness

`GET /readyz`

- Validates Playwright is available and the requested browser engines are supported.
- Returns `{ "status": "ready" | "not_ready" }` plus engine metadata.

### Worker Info

`GET /v1/worker/info`

- Returns worker configuration and Playwright version for diagnostics.

## Configuration

- `PORT` (default: 7000)
- `PLAYWRIGHT_BROWSERS` (comma-separated engine list, default: `chromium`)
- `PLAYWRIGHT_PRIMARY_BROWSER` (default: first engine)
- `WORKER_ID` (optional)
- `TRITON_ENDPOINT` (optional)
- `PROXY_GATEWAY` (optional)

## Container Build

- Base image: `mcr.microsoft.com/playwright` with browser binaries baked in.
- Installs only runtime dependencies (`npm install --omit=dev`).

## Kubernetes Integration

- Liveness probe: `GET /healthz` on port 7000.
- Readiness probe: `GET /readyz` on port 7000.
- Engine config provided via `PLAYWRIGHT_BROWSERS` and `PLAYWRIGHT_PRIMARY_BROWSER` env vars.

## Test Plan

- Node unit tests validate `/healthz`, `/readyz`, and `/v1/worker/info` responses.
- Deployment manifests include probe configuration and worker port wiring.
