# LLD 09: API Authorization RBAC

## Feature

Needed + Missed #2: Add authorization layer with role-based permissions.

## Scope

This increment adds lightweight role-based authorization for HTTP API requests.

- Enforcement location: API middleware.
- Role source: API key to role mapping from environment.
- Role levels: `viewer`, `operator`, `admin`.
- Authorization model:
  - Read-only requests (`GET`) require `viewer` or higher.
  - Mutating requests (`POST`, `PUT`, `PATCH`, `DELETE`) require `operator` or higher.

Fine-grained per-resource policy and tenant-aware permissions are out of scope.

## Configuration

- `API_AUTH_ROLE_MAP`: comma-separated `key:role` pairs.
  - Example: `alpha-key:admin,beta-key:operator,gamma-key:viewer`
- `API_AUTH_DEFAULT_ROLE`: role used when key has no explicit mapping.
  - Default: `operator`

## Request Flow

1. API key authentication validates `X-API-Key`.
2. Middleware resolves caller role from `API_AUTH_ROLE_MAP` or default role.
3. Middleware computes required role from HTTP method.
4. If caller role rank < required rank, return structured 403 response.
5. Otherwise proceed to endpoint handler.

## Error Behavior

- HTTP status: `403`.
- Structured code: `FORBIDDEN`.
- Message: `role does not permit this operation`.

## Test Plan

1. Viewer key blocked on mutating request (`POST /api/v1/sessions`) with 403.
2. Viewer key allowed on read-only request (`GET /api/v1/sessions/{id}/state`).
3. Operator key allowed on mutating requests.
4. Existing tests stay green when auth env vars are not configured.

## Rollout

1. Start with read-vs-mutate split in staging.
2. Add endpoint-level permission map in next increment.
3. Add org/tenant-aware authorization in later feature.
