# LLD 67: Full Cost Observability Dashboard (GPU, Queue, Storage, Egress)

## Feature

Strategic Improvements #60: Add full cost observability dashboard (GPU, queue, storage, egress).

## Scope

Introduce tenant cost observability snapshots and dashboard analytics across major cost dimensions.

- Record per-period cost snapshots for GPU, queue compute, storage, and egress usage.
- Support configurable per-dimension rates for cost normalization.
- Compute per-snapshot cost breakdown and total cost.
- Compute trend deltas against prior snapshots.
- Expose dashboard aggregation view for lookback windows.
- Support in-memory and JSON-file persistence.
- Expose versioned and legacy APIs with RBAC, audit, usage metering, and realtime events.

This increment focuses on control-plane cost intelligence and operational visibility.

## Data Model

- Cost snapshot:
  - `snapshot_id`
  - `tenant_id`
  - `period_start_day`, `period_end_day`
  - `usage{gpu_hours, queue_compute_hours, storage_gb_month, egress_gb}`
  - `rates{...}`
  - `cost_breakdown{...}`
  - `total_cost`
  - `trend_vs_previous{...}`
  - `metadata`
  - `updated_at`
- Dashboard summary:
  - `tenant_id`
  - `snapshot_count`
  - `totals{gpu_cost, queue_cost, storage_cost, egress_cost, total_cost}`
  - `latest_total_cost`
  - `trend_total_cost`
  - `latest_snapshot`

## Computation Model

- For each dimension:
  - `dimension_cost = usage * rate`
- Total cost:
  - sum of dimension costs.
- Trend against previous snapshot:
  - current value minus prior value by dimension and total.
- Dashboard totals:
  - sum over lookback snapshots by dimension and total.

## Workflow

1. Operator records cost snapshot for billing/monitoring period.
2. Service calculates normalized cost breakdown and trend values.
3. Service persists snapshot and emits cost observability event.
4. Operator retrieves dashboard summary and historical snapshots.

## Failure Policy

- Negative usage or rates are rejected.
- Invalid period ranges are rejected.
- Tenant scoping is enforced for snapshot listing and retrieval.
- Missing snapshots produce zeroed dashboard aggregates.

## Rollout

1. Integrate metering pipeline to emit periodic snapshot updates.
2. Connect dashboard outputs to operator console and finance reporting.
3. Set alert thresholds on trend spikes and absolute cost ceilings.
4. Expand to region and model-level breakdowns in follow-up increments.
