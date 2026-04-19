# LLD 19: Hardened CORS and Edge Security Policy Defaults

## Feature

Needed + Missed #12: Hardened CORS and edge security policy defaults.

## Scope

Add conservative cross-origin defaults and baseline security headers for the public API.

- Default CORS policy should deny cross-origin requests unless explicit allow-list entries are configured.
- Add common browser security headers to API responses.
- Keep the policy configurable via environment variables for local development and trusted frontends.

This does not replace edge proxy or CDN policy configuration.

## Configuration

- `API_CORS_ALLOW_ORIGINS`: comma-separated allow-list, default empty.
- `API_CORS_ALLOW_CREDENTIALS`: default `false`.
- `API_CORS_ALLOW_METHODS`: default `GET,POST,PUT,PATCH,DELETE,OPTIONS`.
- `API_CORS_ALLOW_HEADERS`: default `Authorization,Content-Type,X-API-Key,X-Request-ID,X-Tenant-ID`.

## Response Headers

Every API response should include a baseline set of headers:

- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Referrer-Policy: no-referrer`
- `Permissions-Policy: geolocation=(), microphone=(), camera=()`
- `Cross-Origin-Opener-Policy: same-origin`
- `Cross-Origin-Resource-Policy: same-origin`

## Test Plan

1. Response headers are present on a normal request.
2. CORS preflight succeeds for an explicitly allowed origin.
3. CORS blocks an origin that is not on the allow-list.

## Rollout

1. Start with empty allow-list in production.
2. Add only the known frontend origins.
3. Keep edge/CDN security policy aligned with API defaults.
