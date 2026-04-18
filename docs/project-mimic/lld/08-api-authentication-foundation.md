# LLD 08: API Authentication Foundation

## Feature

Needed + Missed #1: Add real API authentication for all endpoints (API keys or JWT).

## Scope

This increment implements API key authentication for FastAPI endpoints.

- Authentication source: static API key allowlist from environment variable.
- Auth header: `X-API-Key`.
- Enforcement: all API endpoints except documentation and OpenAPI schema routes.
- Error contract: use existing structured error envelope with machine code.

JWT, RBAC, tenant scoping, and key lifecycle APIs are out-of-scope for this increment and remain separate features.

## Design

### Configuration

- `API_AUTH_KEYS`: comma-separated list of allowed API keys.
- If no keys are configured, authentication is disabled for local/dev compatibility.
- If keys are configured, requests must include matching `X-API-Key`.

### Request Flow

1. Middleware creates `request_id` and stores it in request state.
2. Middleware checks whether path is auth-exempt:
   - `/openapi.json`
   - `/docs`
   - `/docs/oauth2-redirect`
   - `/redoc`
3. If auth is enabled and path is not exempt:
   - Read `X-API-Key`.
   - Validate against configured allowlist.
   - On failure return 401 with structured error code.
4. Continue normal handler processing for authorized requests.

### Error Behavior

- HTTP status: `401`.
- Structured code: `UNAUTHORIZED`.
- Message: `missing or invalid api key`.
- Include correlation/request ID in response as today.

## Test Plan

1. No configured keys -> existing API behavior unchanged.
2. Configured keys + missing header -> 401 with machine code `UNAUTHORIZED`.
3. Configured keys + invalid header -> 401.
4. Configured keys + valid header -> protected endpoints succeed.
5. Configured keys + OpenAPI/docs routes remain accessible.

## Rollout

1. Enable in staging with one key and rotate to per-client keys later.
2. Add metrics for unauthorized attempts in follow-up feature.
3. Migrate to JWT + RBAC in next access-control feature.
