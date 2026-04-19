# LLD 44: Tenant Usage Metering Tied to Billable Dimensions

## Feature

Needed + Partial #37: Add tenant usage metering tied to billable dimensions.

## Scope

Add a tenant-scoped usage metering service and API inspection endpoints for billable dimensions.

- Persist per-tenant usage counters by day and dimension.
- Track billable dimensions from control-plane workflows.
- Expose admin APIs to query usage records and summarized totals.
- Support memory and file-backed persistence modes.

This increment provides usage evidence for billing readiness and limit governance; it does not yet implement billing plans or invoice generation.

## API Contract

- `GET /api/v1/usage/metering/records`
- `GET /api/v1/usage/metering/summary`

Legacy routes mirror under unversioned paths.

## Billable Dimensions

This increment records these dimensions:

- `api_request`
- `session_create`
- `session_step`
- `async_job_submit`
- `review_queue_submit`
- `policy_decision_evaluate`
- `feature_flag_evaluate`

## Data Model

Usage records are aggregated by:

- `tenant_id`
- `dimension`
- `day_bucket` (epoch day)

Each record stores cumulative `units`, `created_at`, and `updated_at`.

## Workflow Design

1. API and workflow handlers emit usage events for billable dimensions.
2. Metering service increments per-tenant/day counters.
3. Admin endpoints return raw records or summary totals for reporting.
4. Tenant filtering prevents accidental cross-tenant usage exposure.

## Failure Policy

- Empty tenant or dimension values are rejected by metering service.
- Invalid store configuration in file mode fails fast on startup.
- Metering writes are best-effort and do not block primary request paths.

## Rollout

1. Deploy with in-memory store in dev.
2. Enable file-backed store where restart durability is required.
3. Use summary API outputs as input for billing primitives in next increment.
