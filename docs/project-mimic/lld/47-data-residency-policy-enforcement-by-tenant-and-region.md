# LLD 47: Data Residency Policy Enforcement by Tenant and Region

## Feature

Needed + Partial #40: Add data residency policy enforcement by tenant and region.

## Scope

Introduce tenant-scoped region policies and enforce request-region constraints in the API middleware.

- Add a data residency policy service with in-memory and JSON file persistence.
- Add admin policy management endpoints (upsert, list, get).
- Add operator/admin validation endpoint for tenant-region checks.
- Enforce residency policy in request middleware behind an environment toggle.
- Preserve legacy unversioned routes with deprecation headers.

This increment focuses on region governance and safe tenant isolation controls.

## Data and Control Design

- Data residency policy fields per tenant:
  - `tenant_id`
  - `allowed_regions[]`
  - `default_region`
  - `created_at`
  - `updated_at`
- Service behaviors:
  - Normalize regions to lowercase.
  - Deduplicate and sort allowed regions.
  - Validate default region membership in allowed regions.
- Middleware behavior:
  - Resolve region from `X-Region` header.
  - Optionally enforce policy when `DATA_RESIDENCY_ENFORCEMENT_ENABLED=true`.
  - Return `403 FORBIDDEN` when region is not permitted.

## Workflow Design

1. Admin creates or updates a tenant data residency policy.
2. Requests carry tenant scope from API key and optional `X-Region` header.
3. Middleware validates tenant-region pair before route execution.
4. Disallowed regions are blocked with structured error details.
5. Operators can call validation endpoint to inspect allow/deny decisions.

## Failure Policy

- Empty tenant IDs are rejected.
- Empty allowed region sets are rejected.
- Default region outside allowed regions is rejected.
- Unknown tenant policy in validation is treated as allowed with reason `no_residency_policy`.
- Enforcement can be disabled for staged rollout.

## Rollout

1. Deploy with enforcement disabled and seed tenant policies.
2. Use validation endpoint to verify expected outcomes by tenant/region.
3. Enable middleware enforcement incrementally by environment.
4. Monitor denied-request rates and tune region policies.
