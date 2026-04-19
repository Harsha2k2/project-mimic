# LLD 53: Multi-Region Active-Active Control Plane Architecture

## Feature

Needed + Partial #46: Add multi-region active-active control plane architecture.

## Scope

Introduce a control-plane topology service and API that models multiple regions, tracks health, and performs deterministic active-active routing for read/write operations.

- Add region registration and topology persistence with in-memory and JSON file stores.
- Add per-region health updates for live availability state.
- Add active-active route selection that honors preferred region when healthy.
- Add deterministic weighted fallback routing across healthy regions.
- Add topology snapshot endpoint for operator visibility and readiness checks.
- Preserve legacy unversioned routes with deprecation headers.

This increment establishes active-active architecture primitives in control-plane logic and APIs.

## Data and Control Design

- Region topology fields:
  - `region_id`
  - `endpoint`
  - `traffic_weight`
  - `write_enabled`
  - `read_enabled`
  - `priority`
  - `healthy`
  - `health_reason`
  - `last_heartbeat_at`
  - `created_at`, `updated_at`
- Topology snapshot fields:
  - `mode`
  - `total_regions`
  - `healthy_regions[]`
  - `writable_regions[]`
  - `readable_regions[]`
  - `active_active_ready`
  - `primary_region`
- Routing fields:
  - `tenant_id`
  - `operation` (`read` or `write`)
  - `preferred_region`
  - `selected_region`
  - `endpoint`
  - `reason`

## Workflow Design

1. Admin registers regions and endpoint metadata.
2. Admin updates region health during incidents or recovery.
3. Operator requests topology snapshot to validate readiness.
4. Operator requests route selection for read/write operation.
5. Service selects preferred region if healthy; otherwise falls back to deterministic weighted active-active routing.

## Failure Policy

- Empty region IDs or endpoints are rejected.
- Non-positive traffic weights are rejected.
- Invalid operations are rejected.
- Tenant override in route request must match caller tenant scope.
- Routing fails with explicit error when no healthy eligible regions exist.

## Rollout

1. Register at least two healthy read/write regions.
2. Confirm `active_active_ready=true` from topology endpoint.
3. Route traffic via operator endpoint and monitor selection reasons.
4. Exercise health flips to validate failover behavior.
