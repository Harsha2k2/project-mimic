# LLD 59: Privacy-Preserving Analytics Layer for Tenant Reporting

## Feature

Strategic Improvements #52: Add privacy-preserving analytics layer for tenant reporting.

## Scope

Introduce a tenant-scoped analytics service that supports privacy-aware reporting with configurable suppression and deterministic noise.

- Add privacy analytics policy management per tenant.
- Ingest analytics events with metric names, values, and dimensions.
- Generate privacy-preserving reports with:
  - minimum group-size suppression,
  - deterministic noise scaled by epsilon,
  - optional redaction for sensitive dimension keys.
- Persist policies/events/reports using in-memory or JSON-file stores.
- Expose versioned and legacy API routes with RBAC, audit, metering, and realtime event hooks.

This increment focuses on privacy-safe aggregation and report generation, not external BI pipelines.

## Data and Control Design

- Policy fields:
  - `tenant_id`
  - `epsilon`
  - `min_group_size`
  - `max_groups`
  - `redact_dimension_keys[]`
  - `noise_seed`
  - `created_at`, `updated_at`
- Event fields:
  - `event_id`
  - `tenant_id`
  - `metric_name`
  - `value`
  - `dimensions{key->value}`
  - `observed_at`
- Report fields:
  - `report_id`
  - `tenant_id`
  - `metric_name` (optional filter)
  - `start_time`, `end_time` (optional)
  - `group_by[]`
  - `total_events`
  - `visible_groups`
  - `suppressed_groups`
  - `epsilon`
  - `min_group_size`
  - `groups[{group,count,true_sum,noisy_sum,average,noisy_average,noise}]`
  - `generated_at`

## Workflow Design

1. Admin upserts a tenant privacy analytics policy.
2. Operator ingests tenant analytics events.
3. Operator requests report generation with optional filters/grouping.
4. Service aggregates events, suppresses low-count groups, applies deterministic noise, and persists the report.
5. Operator lists/fetches generated reports for tenant-safe analytics consumption.

## Failure Policy

- Empty tenant IDs or metric names are rejected.
- `epsilon` must be greater than zero.
- `min_group_size` and `max_groups` must be positive integers.
- Tenant override attempts outside caller scope are rejected.
- Missing reports return not found.

## Rollout

1. Deploy with in-memory store and conservative policy defaults.
2. Enable file-backed store where report history persistence is required.
3. Validate suppression and redaction behavior with representative tenant datasets.
4. Integrate report outputs into tenant-facing analytics views in follow-up increments.
