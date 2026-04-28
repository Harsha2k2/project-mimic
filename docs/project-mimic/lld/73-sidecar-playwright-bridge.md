# LLD 73: Sidecar-to-Playwright Bridge

## Feature

Wire the browser worker to the mimetic sidecar so the worker can request event plans and optionally emit them through Playwright.

## Scope

- Add a sidecar HTTP client inside the browser worker runtime.
- Proxy pointer and keystroke planning requests to the sidecar.
- Optionally emit planned events through Playwright when enabled.
- Expose the sidecar URL via worker configuration and Kubernetes manifests.

## API Contract (Browser Worker)

### Plan Pointer Events

`POST /v1/mimetic/pointer/plan`

- Proxies payload to the sidecar `/v1/mimetic/pointer/plan` endpoint.
- Returns sidecar event plan.

### Plan Keystrokes

`POST /v1/mimetic/keyboard/plan`

- Proxies payload to the sidecar `/v1/mimetic/keyboard/plan` endpoint.
- Returns sidecar event plan.

### Emit Pointer Events

`POST /v1/mimetic/pointer/emit`

- Requests a pointer plan from the sidecar and emits the events via Playwright when enabled.
- Returns `{ status: "emitted", event_count }`.

### Emit Keystrokes

`POST /v1/mimetic/keyboard/emit`

- Requests a keystroke plan from the sidecar and emits the events via Playwright when enabled.
- Returns `{ status: "emitted", event_count }`.

## Configuration

- `SIDECAR_URL` (default: `http://127.0.0.1:7200`)
- `SIDECAR_PORT` (default: 7200)
- `PLAYWRIGHT_EMIT_ENABLED` (default: false)

## Failure Policy

- Invalid JSON payloads return 400.
- Sidecar request failures return 502.
- Emission endpoints return 503 when `PLAYWRIGHT_EMIT_ENABLED` is false.

## Test Plan

- Worker unit tests validate proxying to the sidecar stub.
- Emit endpoints return a disabled response when emission is off.
