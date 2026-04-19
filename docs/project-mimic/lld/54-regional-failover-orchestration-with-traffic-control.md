# LLD 54: Regional Failover Orchestration with Traffic Control

## Feature

Needed + Partial #47: Add regional failover orchestration with traffic control.

## Scope

Introduce a regional failover orchestrator that manages traffic-control policies across control-plane regions and executes deterministic failover/recovery operations.

- Add policy definitions with primary/secondary region intent.
- Add read-traffic distribution and write-region controls.
- Add policy apply action that writes distribution into control-plane region topology.
- Add failover execute action to shift read/write traffic to a target region.
- Add recovery action to restore prior topology snapshot and optional auto-failback policy apply.
- Add failover status endpoint for operator visibility.
- Preserve legacy unversioned routes with deprecation headers.

This increment focuses on orchestration behavior and API contracts, not service-mesh or DNS-level routing implementation.

## Data and Control Design

- Failover policy fields:
  - `policy_id`
  - `primary_region`
  - `secondary_region`
  - `read_traffic_percent{region->percent}`
  - `write_region`
  - `auto_failback`
  - `last_applied_at`
- Failover status fields:
  - `policy_id`
  - `active`
  - `target_region`
  - `reason`
  - `initiated_by`
  - `recovered_by`
  - `started_at`
  - `resolved_at`
- Recovery behavior:
  - Restore captured pre-failover topology snapshot.
  - Re-apply policy if `auto_failback=true`.

## Workflow Design

1. Admin defines or updates failover policy.
2. Admin applies policy to enforce baseline read/write routing.
3. During incident, admin executes failover to target region.
4. Operator checks failover status while incident is active.
5. Admin recovers failover; orchestrator restores prior topology and applies failback behavior.

## Failure Policy

- Unknown control-plane regions in policy are rejected.
- Invalid or empty traffic distributions are rejected.
- Concurrent failover execution on same policy is rejected.
- Recovery without an active failover is rejected.

## Rollout

1. Seed policies for each multi-region tenant/control-plane profile.
2. Apply policies and verify region topology and route behavior.
3. Exercise execute/recover in staging incidents.
4. Enable operator runbooks against status endpoint.
