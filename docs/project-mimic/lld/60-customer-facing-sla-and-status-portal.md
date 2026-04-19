# LLD 60: Customer-Facing SLA and Status Portal

## Feature

Strategic Improvements #53: Add customer-facing SLA and status portal.

## Scope

Introduce a status portal service and API for publishing service health and SLA compliance.

- Add service status management for customer-visible service components.
- Add SLA target management for each service.
- Add SLA evaluation endpoint comparing live status against targets.
- Support in-memory and JSON-file store modes.
- Expose versioned and legacy API routes with RBAC, audit hooks, usage metering, and realtime status events.

This increment focuses on structured API-driven status publishing; external CDN-hosted status pages are out of scope.

## Data and Control Design

- Service status fields:
  - `service_id`
  - `display_name`
  - `status` (`operational`, `degraded`, `partial_outage`, `major_outage`, `maintenance`)
  - `availability_percent`
  - `latency_p95_ms`
  - `error_rate_percent`
  - `components{component->status}`
  - `message`
  - `created_at`, `updated_at`
- SLA target fields:
  - `service_id`
  - `availability_target_percent`
  - `latency_p95_target_ms`
  - `error_rate_target_percent`
  - `window_days`
  - `created_at`, `updated_at`
- SLA evaluation fields:
  - `service_id`
  - `meets_sla`
  - `availability_ok`
  - `latency_ok`
  - `error_rate_ok`
  - `violations[]`
  - embedded `status` and `target`
  - `evaluated_at`

## Workflow Design

1. Admin upserts service health payload for customer-facing services.
2. Admin upserts SLA targets for each service.
3. Viewer/operator reads service and SLA target snapshots.
4. Operator evaluates SLA compliance for a service.
5. API emits audit, metering, and realtime events for status/SLA updates and evaluations.

## Failure Policy

- Empty IDs/names are rejected.
- Invalid status values are rejected.
- Availability/error percentages must be within [0, 100].
- Latency targets must be positive.
- Missing service status or SLA target returns not found for evaluation.

## Rollout

1. Seed baseline service statuses and targets in staging.
2. Validate SLA evaluation output against synthetic monitoring metrics.
3. Expose read endpoints to customer-facing UI clients.
4. Expand with incident timeline and subscription notifications in follow-up increments.
