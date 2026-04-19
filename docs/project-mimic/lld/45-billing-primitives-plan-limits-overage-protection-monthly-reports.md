# LLD 45: Billing Primitives - Plan Limits, Overage Protection, Monthly Reports

## Feature

Needed + Partial #38: Add billing primitives (plan limits, overage protection, monthly reports).

## Scope

Add billing control-plane primitives that consume tenant usage metering for plan-aware governance.

- Manage billing plans with per-dimension included units and optional overage buffers.
- Assign subscriptions to tenants with overage protection toggle.
- Compute overage status per tenant and month from metered usage.
- Produce monthly billing reports with usage, limits, and overage breakdown.
- Optionally enforce overage protection in request middleware.

This increment provides billing foundations and guardrails; it does not include invoicing, payment processing, or external billing integrations.

## API Contract

- `POST /api/v1/billing/plans`
- `GET /api/v1/billing/plans`
- `GET /api/v1/billing/plans/{plan_id}`
- `POST /api/v1/billing/subscriptions/{tenant_id}`
- `GET /api/v1/billing/subscriptions/{tenant_id}`
- `GET /api/v1/billing/overage/{tenant_id}`
- `GET /api/v1/billing/reports/{tenant_id}`

Legacy routes mirror under unversioned paths.

## Data Model

- Plan:
  - `plan_id`, `description`
  - `included_units` by billable dimension
  - `hard_limits` and `overage_buffer_units`
- Subscription:
  - `tenant_id`, `plan_id`, `overage_protection`
- Overage status/report:
  - tenant usage, plan limits, exceeded dimensions, blocked dimensions, and status flags

## Workflow Design

1. Admin creates or updates plans with billable-dimension limits.
2. Admin assigns plan subscriptions to tenants.
3. Usage metering aggregates monthly tenant usage.
4. Billing APIs compute overage status and monthly reports from usage + plan data.
5. Optional middleware enforcement blocks requests when protected tenants exceed hard limits.

## Failure Policy

- Unknown plans/subscriptions return 404.
- Invalid month format is rejected (`YYYY-MM` expected).
- Invalid plan dimensions (negative units) are rejected.
- Billing enforcement is fail-open if metering/report calculation encounters internal errors.

## Rollout

1. Start with billing APIs and reporting while enforcement is disabled.
2. Enable enforcement in selected environments via `BILLING_ENFORCEMENT_ENABLED=true`.
3. Use monthly reports as input to upcoming billing and invoice automation work.
