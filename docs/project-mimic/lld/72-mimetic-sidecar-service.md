# LLD 72: Mimetic Sidecar Service

## Feature

Create a Rust-based sidecar service that generates low-level pointer and keyboard event plans for the browser worker to emit via Playwright/CDP.

## Scope

- Add a Rust sidecar binary (`mimetic-sidecar`).
- Expose HTTP endpoints to request pointer and keystroke plans.
- Package the sidecar in a lightweight container image.
- Expose the sidecar port via Kubernetes manifests.

## API Contract

### Health

`GET /healthz`

- Returns `{ "status": "ok" }`.

### Readiness

`GET /readyz`

- Returns `{ "status": "ready", "version": "<crate version>" }`.

### Pointer Plan

`POST /v1/mimetic/pointer/plan`

Request:

- `start: { x: f64, y: f64 }`
- `target: { x: f64, y: f64 }`
- `viewport_width: u32`
- `viewport_height: u32`
- `dwell_ms: u32`
- `steps: usize | null`

Response:

- `events: [{ t_ms, x, y, event_type }]`

### Keystroke Plan

`POST /v1/mimetic/keyboard/plan`

Request:

- `text: string`
- `base_delay_ms: u32`

Response:

- `events: [{ t_ms, key, event_type }]`

## Configuration

- `SIDECAR_PORT` (default: 7200)

## Container Build

- Multi-stage Rust build with a slim runtime image.

## Kubernetes Integration

- Sidecar container exposes port 7200 and sets `SIDECAR_PORT`.

## Test Plan

- Unit tests validate pointer and keystroke plan generation.
