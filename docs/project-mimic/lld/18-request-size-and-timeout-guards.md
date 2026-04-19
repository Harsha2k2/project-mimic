# LLD 18: Request Size and Timeout Guards for Public APIs

## Feature

Needed + Missed #11: Add strict request size limits and timeout guards on public APIs.

## Scope

This increment adds request size checks and soft timeout guards in FastAPI middleware.

- Reject requests larger than configured maximum body size.
- Reject requests that exceed configured wall-clock budget.
- Keep behavior opt-in via environment variables.

Reverse proxy hard limits and websocket streaming are out-of-scope.

## Configuration

- `API_MAX_REQUEST_BODY_BYTES`: default `0` (disabled).
- `API_REQUEST_TIMEOUT_SECONDS`: default `0` (disabled).

## Enforcement Flow

1. Middleware inspects `Content-Length` header when present.
2. Middleware reads body bytes and rejects if payload exceeds limit.
3. Middleware records request start time.
4. After downstream handler completes, if elapsed time exceeds timeout budget, return 504.

## Error Behavior

- Oversized request:
  - status 413
  - code `REQUEST_TOO_LARGE`
  - message `request body exceeds maximum allowed size`
- Timeout:
  - status 504
  - code `REQUEST_TIMEOUT`
  - message `request exceeded timeout budget`

## Test Plan

1. Oversized payload returns 413.
2. Slow request path returns 504 when timeout budget is small.
3. Existing endpoints remain unaffected when limits are disabled.

## Rollout

1. Start in staging with conservative limits.
2. Tune body size and timeout thresholds by endpoint class.
3. Move to edge proxy enforcement for high-volume routes later.
