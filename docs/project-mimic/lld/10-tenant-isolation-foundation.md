# LLD 10: Tenant Isolation Foundation

## Feature

Needed + Missed #3: Add organization and tenant model with strict data isolation.

## Scope

This increment adds tenant-aware session ownership and API-level tenant enforcement.

- Session records include `tenant_id` ownership.
- API middleware resolves caller tenant from key mapping/header.
- Session operations are allowed only for matching tenant.
- Session list results are filtered by caller tenant.

Organization hierarchy, billing plans, and cross-tenant admin tooling are out-of-scope.

## Configuration

- `API_AUTH_TENANT_MAP`: comma-separated `key:tenant` pairs.
- `API_TENANT_ENFORCEMENT`: `true|false` toggle.
- `API_DEFAULT_TENANT`: fallback tenant id (default: `default`).

## Data Model

### SessionRecord

Add `tenant_id: str` to every session record.

### SessionRegistry API updates

- `create(..., tenant_id: str = "default")`
- `get(..., tenant_id: str | None = None)`
- `get_record(..., tenant_id: str | None = None)`
- `reset(..., tenant_id: str | None = None)`
- `rollback_to_checkpoint(..., tenant_id: str | None = None)`
- `resume_from_checkpoint(..., tenant_id: str | None = None)`
- `mark_completed(..., tenant_id: str | None = None)`
- `mark_failed(..., tenant_id: str | None = None)`
- `pause(..., tenant_id: str | None = None)`
- `resume(..., tenant_id: str | None = None)`
- `list_sessions(..., tenant_id: str | None = None)`

## API Flow

1. Authenticate key and role as implemented in Features 1 and 2.
2. Resolve caller tenant:
   - mapped tenant from key (if configured)
   - header `X-Tenant-ID` (optional)
   - default tenant fallback
3. If mapped tenant and header tenant conflict, return 403.
4. Store `request.state.tenant_id`.
5. Pass tenant id to all session and list operations.

## Error Behavior

- Cross-tenant access returns `403 FORBIDDEN` with structured error contract.

## Test Plan

1. Tenant A creates a session; Tenant B cannot read that session state.
2. Tenant A list endpoint only returns Tenant A sessions.
3. Existing non-auth local behavior remains functional.

## Rollout

1. Enable tenant enforcement in staging using key-to-tenant mapping.
2. Backfill tenant metadata in persistent stores in later storage feature.
3. Add org-level RBAC and scoped admin operations in future features.
